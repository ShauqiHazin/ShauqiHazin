"""Static step generation for the Petrobras Initiation Tool (OrcFxAPI).

Two analysis modes:
- Full sequence   : step-by-step lay table from vertical payout to PLET landing and TDP.
- Critical step   : parallel sensitivity of the "PLET close to seabed" step over buoyancy,
                    wire length, ramp angle, rollerbox opening and current direction.

The engineering logic is ported from the Streamlit tool's ofx_static.py. UI state
(st.session_state) is replaced by a `StaticsContext` object and progress messages go
to the console.
"""
import itertools
import math
import os
import re
import shutil
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from random import uniform

import numpy as np
import pandas as pd
import OrcFxAPI as of
from scipy import optimize

from . import vessels
from .catenary import find_catenary_starting_shape
from .postprocess import post_process, get_criteria


def log(msg):
    print(msg, flush=True)


class StaticsError(Exception):
    """Raised when the analysis cannot continue (replaces the Streamlit warning dialogs)."""


CURRENT_LABELS = {0: "inLine", 180: "against", -1: "None"}


###########################################################################
#############   CONTEXT (replaces st.session_state)   #####################
###########################################################################

@dataclass
class StaticsContext:
    model_path: str
    analysis_folder: str
    vessel: str
    vessel_data: dict
    water_depth: float
    total_pipe_length: float
    buoyancy_wiw: float
    nom_wire_length: float
    contents_density: float
    include_current: bool = False
    rollerbox: bool = False
    roller_openings: list = field(default_factory=lambda: [0])
    criteria: dict = field(default_factory=dict)
    debug: bool = False

    @property
    def ramp_name(self):
        return self.vessel_data["Ramp"]

    @property
    def pin_locations(self):
        return [pin for pin in self.vessel_data["Pin Locations"] if pin < 90]

    @property
    def current_directions(self):
        return [0, -1, 180] if self.include_current else [-1]


def _vessel_from_comments(comments):
    match = re.search(r"Vessel:\s*7(\w+)", comments)
    if match:
        return match.group(1)
    return re.findall(r"7\w+\S", comments)[0][1:]


def load_context(base_model, analysis_folder, contents_density=None, include_current=False,
                 rollerbox=False, roller_openings=None, criteria=None, debug=False):
    """Reads key parameters from the base model and copies it into the analysis folder."""
    os.makedirs(analysis_folder, exist_ok=True)
    model = of.Model(str(base_model))
    rho = model["Environment"].Density
    buoy = model["PLET_Buoy"]
    vessel = vessels.vessel_name(_vessel_from_comments(model["General"].Comments))
    if vessel == "Navica" and rollerbox:
        raise StaticsError("7Navica has no rollerbox model.")

    model_path = str(Path(analysis_folder) / Path(base_model).name)
    if Path(model_path).resolve() != Path(base_model).resolve():
        model.SaveData(model_path)

    ctx = StaticsContext(
        model_path=model_path,
        analysis_folder=str(analysis_folder),
        vessel=vessel,
        vessel_data=vessels.vessel_coords(vessel),
        water_depth=model["Environment"].WaterDepth,
        total_pipe_length=model["RigidPipe"].CumulativeLength[-1],
        buoyancy_wiw=buoy.Mass - buoy.Volume * rho,
        nom_wire_length=model["Initiation"].CumulativeLength[-1],
        contents_density=model["RigidPipe"].ContentsDensity if contents_density is None else contents_density,
        include_current=include_current,
        rollerbox=rollerbox,
        roller_openings=list(roller_openings) if (rollerbox and roller_openings) else [0],
        criteria=criteria or {},
        debug=debug,
    )
    return ctx


###########################################################################
#############   HELPER FUNCTIONS                ###########################
###########################################################################

def check_line_structure(model, pipe):
    """Returns a DataFrame of the pipe sections (line type, variable OD, length, segment, pre-bend)."""
    no_rows = pipe.NumberofSections
    section_lt, var_type, length, segment_length, bend_type, curvature = [], [], [], [], [], []
    for rowi in range(no_rows):
        lt_name = pipe.LineType[rowi]
        var_check = False if type(model[lt_name].OD) is float else True
        if pipe.PreBendSpecifiedBy == "Curvature":
            bend_type.append("curvature")
            curvature.append(pipe.PreBendCurvaturey[rowi])
        else:
            bend_type.append("bend angle")
            curvature.append((
                pipe.PreBendBendAngle[rowi],
                pipe.PreBendBendRadius[rowi],
                pipe.PreBendBendAxisDirection[rowi]
            ))
        section_lt.append(lt_name)
        var_type.append(var_check)
        length.append(pipe.Length[rowi])
        segment_length.append(pipe.TargetSegmentLength[rowi])
    df = pd.DataFrame({
        "sectionLineType": section_lt,
        "variableOD": var_type,
        "length": length,
        "segmentLength": segment_length,
        "bendType": bend_type,
        "curvature": curvature
    })
    df["cumulativeLength"] = df.loc[::-1, "length"].cumsum()
    return df


def get_section_index(df, catenary_length):
    """Pipe sections (from the PLET end) needed to make up `catenary_length`."""
    if df.iloc[-1]["cumulativeLength"] > catenary_length:
        idx_start = len(df) - 1
    else:
        idx_match = df[df["cumulativeLength"] < catenary_length].index
        idx_start = idx_match[0]
        if idx_match[0] > 0:
            idx_start = idx_match[0] - 1
    return df[idx_start:].reset_index()


def reassign_pipe_sections(pipe, df_catenary):
    """Rebuilds the pipe sections from the DataFrame."""
    pipe.NumberofSections = len(df_catenary)
    for idx, row in df_catenary.iterrows():
        pipe.LineType[idx] = row["sectionLineType"]
        if not row["variableOD"]:
            pipe.Length[idx] = row["length"]
        pipe.TargetSegmentLength[idx] = row["segmentLength"]
        if row["bendType"] == "curvature":
            pipe.PreBendCurvaturey[idx] = row["curvature"]
        else:
            pipe.PreBendBendAngle[row["curvature"][0]]
            try:
                pipe.PreBendBendRadius[row["curvature"][1]]
                pipe.PreBendBendAxisDirection[row["curvature"][2]]
            except Exception:
                pass


def simplify_pipe_sections(pipe, df_line, water_depth, mode="clearance"):
    """Simplifies the pipe into 4 equal sections of the longest section's line type."""
    main_lt_row = df_line[df_line["length"] == max(df_line["length"])]
    main_lt = main_lt_row.iloc[0]["sectionLineType"]
    total_length = df_line["cumulativeLength"][0]
    pipe.NumberOfSections = 4
    segment_length = math.ceil(water_depth / 200)
    for irow in range(4):
        pipe.LineType[irow] = main_lt
        pipe.Length[irow] = total_length / 4
        pipe.TargetSegmentLength[irow] = segment_length


def set_pipe_length(pipe, target_length, df_catenary, mode="full"):
    df_catenary["cumulativeLength"] = df_catenary.loc[::-1, "length"].cumsum()
    delta = df_catenary.iloc[0]["cumulativeLength"] - target_length
    new_len = max(df_catenary.loc[0, "length"] - delta, 1)
    df_catenary.at[0, "length"] = new_len
    if mode == "full":
        pipe.Length[0] = math.ceil(new_len)
    else:
        pipe.Length[0] = new_len


def check_length(ctx, angles):
    """Raises if the estimated catenary for any ramp angle is longer than the pipe in the model."""
    for angle in angles:
        _, catenary_length = find_catenary_starting_shape(ctx.water_depth, -angle)
        if catenary_length * 0.95 > ctx.total_pipe_length:
            raise StaticsError(
                f"Required catenary length ({catenary_length}m at {angle}deg) is greater than the total pipe "
                f"length in the model ({ctx.total_pipe_length:.1f}m). Please update your model and try again."
            )


def _find_vessel(model):
    for obj in model.objects:
        if obj.type == of.otVessel:
            return obj


def _anchor_pipe_end_b_x(pipe):
    """Global X of the pipe End B (temporarily anchoring it to read the value)."""
    pipe_connection = pipe.EndBConnection
    pipe.EndBConnection = "Anchored"
    end_b_x = pipe.EndBX
    pipe.EndBConnection = pipe_connection
    return end_b_x


def _use_calculated_positions(model, set_lines):
    try:
        model.UseCalculatedPositions(SetLinesToUserSpecifiedStartingShape=set_lines)
    except Exception:
        model.UseCalculatedPositions(setLinesToUserSpecifiedStartingShape=set_lines)


def check_clearance(model, analysis_folder):
    """True if main trunnion to receptacle clearance is between 8 and 10m."""
    trunnion = model["TrunnionMain"]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    buoy = model["PLET_Buoy"]
    receptacle_height = receptacle.SizeZ
    while True:
        try:
            model.CalculateStatics()
            seabed_result = min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle_height
            break
        except Exception as e:
            with open(f"{analysis_folder}//position_error.log", "a+") as f:
                f.write(str(e))
                f.write(traceback.format_exc())
            log("Calculation not converged when checking clearance. Retrying...")
            model["General"].StaticsMaxIterations = 2000
            model["General"].StaticsMinDamping = uniform(3, 15)
            model["General"].StaticsMaxDamping = uniform(20, 30)
            buoy.InitialZ = model["PLET_Buoy"].InitialZ + 2.5
    return 8 < seabed_result < 10


def check_hangoff_moment(model, analysis_folder):
    """True if |hang-off in-plane bend moment| < 12.5% of the plastic moment capacity."""
    pipe = model["RigidPipe"]
    buoy = model["PLET_Buoy"]
    mp = check_Mp(model)
    while True:
        try:
            model.CalculateStatics()
            bend_moment = pipe.StaticResult('In Plane Bend Moment', of.oeEndA)
            break
        except Exception as e:
            with open(f"{analysis_folder}//position_error.log", "a+") as f:
                f.write(str(e))
                f.write(traceback.format_exc())
            log("Calculation not converged when checking hang-off moment. Retrying...")
            model["General"].StaticsMaxIterations = 2000
            model["General"].StaticsMinDamping = uniform(3, 15)
            model["General"].StaticsMaxDamping = uniform(20, 30)
            buoy.InitialZ = model["PLET_Buoy"].InitialZ + 2.5
    return abs(bend_moment) < 0.125 * mp


def write_log(step_no, pipe_length, vessel_x, seabed_result, bendMoment, target, mode, iteration=None, analysis_folder="temp"):
    """Appends one optimisation iteration to step<no>_optimization.log."""
    if str(step_no).isdigit():
        step_no = f"{step_no:03d}"
    else:
        step_no = f"_{step_no}"
    log_file = f"{analysis_folder}//step{step_no}_optimization.log"
    if not os.path.exists(log_file):
        with open(log_file, "w") as f:
            f.write(f"iteration, pipe length, vessel x, {mode}, bend moment, target\n")
    else:
        if iteration is None:
            with open(log_file, "r") as f:
                prev_data = f.readlines()
            last_iter = prev_data[-1].split(",")[0]
            iteration = [int(last_iter) + 1] if str(last_iter[:]).isdigit() else [1]
        with open(log_file, "+a") as f:
            f.write(f"{iteration[0]}, {pipe_length}, {vessel_x}, {seabed_result}, {bendMoment}, {target}\n")


def rename_log(step_from, step_to, analysis_folder):
    src = f"{analysis_folder}//step{step_from:03d}_optimization.log"
    dst = f"{analysis_folder}//step{step_to:03d}_optimization.log"
    try:
        os.rename(src, dst)
    except Exception:
        _move_to_trash(src, analysis_folder)


def _move_to_trash(file, analysis_folder):
    """Moves a file to <analysis>/Trash instead of deleting it."""
    trash = Path(analysis_folder) / "Trash"
    trash.mkdir(exist_ok=True)
    try:
        shutil.move(file, trash / Path(file).name)
    except Exception:
        pass


def check_Mp(model):
    """Plastic moment capacity of the pipe (DNV-ST-F101)."""
    lt_obj = model[model["RigidPipe"].LineType[0]]
    fy = lt_obj.DNVSTF101Fy  # kPa
    outer_diameter = lt_obj.OD  # m
    wall_thickness = (outer_diameter - lt_obj.ID) / 2
    return fy * (outer_diameter - wall_thickness) ** 2 * wall_thickness


###########################################################################
#############   ROLLERBOX                       ###########################
###########################################################################

def create_rollerbox_model(ctx, model):
    """Clones the vessel rollerbox (6D buoy + support types) into a copy of `model`. Returns the new path."""
    rollerbox_model = of.Model(str(vessels.rollerbox_model_file(ctx.vessel)))
    rb_obj = rollerbox_model[f"{ctx.vessel}_RB"]
    supports = [obj for obj in rollerbox_model.objects if obj.type == of.otSupportType and "_RB" in obj.name]
    base_model = of.Model(model)
    for support in supports:
        support.CreateClone(name=support.name, model=base_model)
    rb_obj.CreateClone(name=f"{ctx.vessel}_RB", model=base_model)
    out_name = f"{model[:-4]}_RB.dat"
    base_model.SaveData(out_name)
    return out_name


def get_rb_settings(ctx, base_model):
    """Returns (model path to analyse, {opening: support coordinate DataFrame})."""
    rb_settings = {}
    if ctx.rollerbox:
        model_name = create_rollerbox_model(ctx, base_model)
        for opening in ctx.roller_openings:
            rb_settings[opening] = vessels.roller_coordinates(ctx.vessel, opening)
    else:
        model_name = base_model
    return model_name, rb_settings


def model_roller_openings(rb_opening, rb_settings, model):
    """Applies the rollerbox support coordinates for `rb_opening` to the rollerbox 6D buoy."""
    if rb_opening > 0:
        rb_setting = rb_settings[rb_opening]
        for obj in model.objects:
            if obj.type == of.ot6DBuoy and "_RB" in obj.Name:
                rb_obj = obj
            if obj.type == of.otVessel:
                vessel_name = obj.Name
        rb_obj.NumberOfSupportedLines = 0
        if "Vega" in vessel_name:
            for i in range(rb_obj.NumberOfSupportsCoordinateSystems):
                rb_obj.SupportCoordinateSystemName[i] = rb_setting.loc[i, "Name"]
                rb_obj.SupportCoordinateSystemPosX[i] = rb_setting.loc[i, "X"]
                rb_obj.SupportCoordinateSystemPosY[i] = rb_setting.loc[i, "Y"]
                rb_obj.SupportCoordinateSystemPosZ[i] = rb_setting.loc[i, "Z"]
                rb_obj.SupportCoordinateSystemAzimuth[i] = rb_setting.loc[i, "Azimuth"]
                rb_obj.SupportCoordinateSystemDeclination[i] = rb_setting.loc[i, "Declination"]
                rb_obj.SupportCoordinateSystemGamma[i] = rb_setting.loc[i, "Gamma"]
        elif "Oceans" in vessel_name:
            for i in range(rb_obj.NumberOfSupports):
                rb_obj.SupportCoordinateSystem[i] = rb_setting.loc[i, "Name"]
                rb_obj.SupportPositionX[i] = rb_setting.loc[i, "X"]
                rb_obj.SupportPositionY[i] = rb_setting.loc[i, "Y"]
                rb_obj.SupportPositionZ[i] = rb_setting.loc[i, "Z"]
                rb_obj.SupportAzimuth[i] = rb_setting.loc[i, "Azimuth"]
                rb_obj.SupportDeclination[i] = rb_setting.loc[i, "Declination"]
                rb_obj.SupportGamma[i] = rb_setting.loc[i, "Gamma"]


def _support_pipe_on_rollerbox(model):
    pipe = model["RigidPipe"]
    for obj in model.objects:
        if obj.type == of.ot6DBuoy and "_RB" in obj.Name:
            obj.NumberOfSupportedLines = 1
            obj.SupportedLine[0] = pipe.Name


###########################################################################
#############   OPTIMISATION                     ##########################
###########################################################################

def optimize_configuration(
        model,
        df_line,
        target_seabed,
        tol,
        trunnion_name="Main",
        mode="clearance",
        step_no=1,
        analysis_folder="temp",
        multithread=False,
        debug=False
):
    """Optimises vessel X-position and pipe length for a target seabed interaction.

    Two-stage loop: `fsolve` on vessel X for ~zero hang-off bend moment (tolerance 2.5% Mp),
    then bounded `minimize_scalar` on pipe length for the target seabed interaction:
      - "clearance": main/secondary trunnion clearance above the receptacle (m)
      - "contact"  : trunnion solid contact force (kN/m), with pipe kept off seabed
      - "touchdown": length of pipe on seabed (m)
    Each iteration is logged to step<no>_optimization.log.
    """
    clr_holder = []
    bm_holder = []
    iteration = [0]
    clr_tol = [target_seabed - tol, target_seabed + tol]
    pipe_mp = check_Mp(model)
    bm_tol = [-pipe_mp * 0.025, pipe_mp * 0.025]
    max_iterations = 30 if multithread else 15

    def find_length(length, pipe, model, trunnion, target_seabed, plet, mode, step_no,
                    analysis_folder=analysis_folder, multithread=False):
        """Objective for the pipe length search: |target - seabed result|."""
        converged = False
        try:
            length = length[0]
        except Exception:
            pass
        log(f'Trying Length of {length}')
        delta = pipe.CumulativeLength[-1] - length
        new_len = pipe.Length[0] - delta
        env = model["Environment"]
        buoy = model["PLET_Buoy"]
        while new_len < 0:
            pipe.Length.DeleteRow(0)
            delta = pipe.CumulativeLength[-1] - length
            new_len = pipe.Length[0] - delta
        pipe.Length[0] = new_len
        trunnion_od = model[trunnion.LineType[0]].OuterContactDiameter
        receptacle_height = receptacle.SizeZ
        pipe_length = pipe.CumulativeLength[-1]
        # Set initial plet position to avoid jacobian error
        target_z = -env.WaterDepth + receptacle_height + trunnion_od / 2
        init_connection = trunnion.EndAConnection
        trunnion.EndAConnection = "Free"
        init_z = trunnion.EndAZ
        trunnion.EndAConnection = init_connection
        final_z = plet.InitialZ - (init_z - target_z)
        plet.InitialZ = final_z
        plet.InitialY = 0
        plet.InitialX = receptacle.OriginX + receptacle.SizeX * 0.6
        plet.InitialRotation1 = 0
        plet.InitialRotation2 = 0
        plet.InitialRotation3 = 0
        if debug:
            model.SaveData(f'{analysis_folder}//opti_len_{step_no}.dat')
        model["General"].StaticsMinDamping = 3
        model["General"].StaticsMaxDamping = 14
        while not converged:
            try:
                if mode == "clearance":
                    model.CalculateStatics()
                    seabed_result = min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle_height
                elif mode == "contact":
                    penalty = 5
                    model.CalculateStatics()
                    seabed_result = max(trunnion.RangeGraph('solid contact force').Mean)
                    if seabed_result == 0:
                        seabed_result = -(min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle_height) * penalty
                    rg_contact = pipe.RangeGraph('seabed normal resistance')
                    seabed_contact = rg_contact.Mean[rg_contact.Mean > 0]
                    if len(seabed_contact) > 0:
                        arc_len = rg_contact.X[rg_contact.Mean > 0]
                        seabed_result = (arc_len[-1] - arc_len[0]) * (penalty ** 2)
                elif mode == "touchdown":
                    penalty = 5
                    model.CalculateStatics()
                    seabed_result = -(min(pipe.RangeGraph('seabed clearance', arclengthRange=of.arSpecifiedArclengths(0, pipe_length - 10)).Mean))
                    if seabed_result >= 0:
                        rg_contact = pipe.RangeGraph('seabed normal resistance')
                        arc_len = rg_contact.X[rg_contact.Mean > 0]
                        seabed_result = arc_len[-1] - arc_len[0]
                    else:
                        seabed_result = seabed_result * penalty
                bendMoment = pipe.StaticResult('In Plane Bend Moment', of.oeEndA)
                target = abs(target_seabed - seabed_result)
                clr_holder.append(seabed_result)
                bm_holder.append(bendMoment)
                iteration[0] += 1
                if not multithread:
                    log(f"  hang-off bend moment {bendMoment:.2f}kNm (target 0), receptacle {mode} {seabed_result:.2f}")
                write_log(step_no, pipe_length, vessel.InitialX, seabed_result, bendMoment, target, mode,
                          iteration, analysis_folder=analysis_folder)
                converged = True
            except Exception as e:
                target = target_seabed * 10
                with open(f"{analysis_folder}//length_error.log", "a+") as f:
                    f.write(str(e))
                    f.write(traceback.format_exc())
                log("Calculation not converged during length finding step.. retrying...")
                model["General"].StaticsMaxIterations = 2000
                model["General"].StaticsMinDamping = uniform(3, 15)
                model["General"].StaticsMaxDamping = uniform(20, 30)
                plet.InitialX = (receptacle.OriginX + receptacle.SizeX * 0.5) - uniform(0.1, 0.5)
                plet.InitialZ = final_z + uniform(0.3, 0.8)
                buoy.InitialZ = buoy.InitialZ - buoy.InitialZ * uniform(0.1, 0.2)
        return target

    def estimate_length(model, receptacle, plet, trunnion, mode):
        """Initial pipe length change estimate so the optimisation starts with positive clearance."""
        env = model["Environment"]
        buoy = model["PLET_Buoy"]
        wd = env.WaterDepth
        plet_height = plet.VertexZ[3] - plet.VertexZ[4]
        trunnion_od = model[trunnion.LineType[0]].OuterContactDiameter
        receptacle_height = receptacle.sizeZ
        converged = False
        model["General"].StaticsMinDamping = 2
        model["General"].StaticsMaxDamping = 12
        i = 0
        while not converged:
            try:
                if mode == "clearance":
                    model.CalculateStatics()
                    plet_clearance = min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle_height
                    delta = plet_clearance - target_seabed
                    if plet_clearance < 1:
                        delta = -wd * 0.005
                else:
                    delta = 0
                converged = True
            except Exception:
                model["General"].StaticsMaxIterations = 2000
                model["General"].StaticsMinDamping = uniform(3, 15)
                model["General"].StaticsMaxDamping = uniform(20, 30)
                plet.InitialX = (receptacle.OriginX + receptacle.SizeX * 0.5) - uniform(0.1, 0.5)
                plet.InitialZ = (-env.WaterDepth + receptacle_height + plet_height / 2 + trunnion_od) + uniform(0.1, 0.5)
                buoy.InitialZ = model["PLET_Buoy"].InitialZ + 2.5
            i += 1
            if i == 10:
                delta = 0
                converged = True
        return delta

    def find_position(position, pipe, model, trunnion, receptacle, target_seabed, plet, mode, step_no,
                      analysis_folder=analysis_folder, multithread=False):
        """Objective for the vessel X search: hang-off bend moment (0 when inside tolerance)."""
        converged = False
        bendMoment = 10
        model["General"].StaticsMinDamping = 2
        model["General"].StaticsMaxDamping = 12
        while not converged:
            try:
                log(f'Trying Vessel Position {position[0]}')
                vessel.InitialX = position[0]
                receptacle_height = receptacle.SizeZ
                plet_height = plet.VertexZ[3] - plet.VertexZ[4]
                trunnion_od = model[trunnion.LineType[0]].OuterContactDiameter
                env = model["Environment"]
                buoy = model["PLET_Buoy"]
                pipe_length = pipe.CumulativeLength[-1]
                plet.InitialZ = -env.WaterDepth + receptacle_height + plet_height / 2 + trunnion_od * 1.0
                plet.InitialY = 0
                plet.InitialX = receptacle.OriginX + receptacle.SizeX * 0.5
                plet.InitialRotation1 = 0
                plet.InitialRotation2 = 0
                plet.InitialRotation3 = 0
                if debug:
                    model.SaveData(f'{analysis_folder}//opti_pos_{step_no}.dat')
                if mode == "clearance":
                    model.CalculateStatics()
                    seabed_result = min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle_height
                elif mode == "contact":
                    model.CalculateStatics()
                    seabed_result = max(trunnion.RangeGraph('solid contact force').Mean)
                    if seabed_result == 0:
                        seabed_result = -(min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle_height)
                elif mode == "touchdown":
                    model.CalculateStatics()
                    seabed_result = -(min(pipe.RangeGraph('seabed clearance', arclengthRange=of.arSpecifiedArclengths(0, pipe_length - 10)).Mean))
                    if seabed_result >= 0:
                        rg_contact = pipe.RangeGraph('seabed normal resistance')
                        arc_len = rg_contact.X[rg_contact.Mean > 0]
                        seabed_result = arc_len[-1] - arc_len[0]
                bendMoment = pipe.StaticResult('In Plane Bend Moment', of.oeEndA)
                endBendStrain = pipe.StaticResult('Max Bending Strain', of.oeEndA)
                target = bendMoment if endBendStrain < 0.1 else bendMoment * endBendStrain * 100
                bm_holder.append(bendMoment)
                clr_holder.append(seabed_result)
                iteration[0] += 1
                if not multithread:
                    log(f"  hang-off bend moment {bendMoment:.2f}kNm (target 0), seabed {mode} {seabed_result:.2f}")
                if bm_tol[0] < target < bm_tol[1]:
                    target = 0
                write_log(step_no, pipe_length, vessel.InitialX, seabed_result, bendMoment, target, mode,
                          iteration, analysis_folder=analysis_folder)
                converged = True
            except Exception as e:
                target = bendMoment * 10
                with open(f"{analysis_folder}//error.log", "a+") as f:
                    f.write(str(e))
                    f.write(traceback.format_exc())
                log("Calculation not converged during position finding step.. retrying...")
                model["General"].StaticsMaxIterations = 2000
                model["General"].StaticsMinDamping = uniform(3, 15)
                model["General"].StaticsMaxDamping = uniform(20, 30)
                buoy.InitialZ = buoy.InitialZ - buoy.InitialZ * uniform(0.1, 0.2)
                plet.InitialX = (receptacle.OriginX + receptacle.SizeX * 0.5) - uniform(0.1, 0.4)
                plet.InitialZ = (-env.WaterDepth + receptacle_height + plet_height / 2 + trunnion_od) + uniform(0.2, 6.0)
        return target

    # Start optimisation loop
    pipe = model["RigidPipe"]
    trunnion = model[f"Trunnion{trunnion_name}"]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    plet = model["PLET_Properties"]
    check = False
    vessel = _find_vessel(model)
    i = 1
    # Optimise on the simplified line, reassign the actual sections afterwards.
    estimate_length(model, receptacle, plet, trunnion, mode)
    while not check:
        try:
            log(f"Solving iteration {i}")
            # introduce randomness so the calcs are not stuck.
            initial_location = vessel.InitialX * uniform(0.95, 1.05)
            # Stage 1: vessel position for 0 hang-off BM
            opt_solved = False
            while not opt_solved:
                opt_obj = optimize.fsolve(
                    find_position,
                    initial_location,
                    args=(pipe, model, trunnion, receptacle, target_seabed, plet, mode, step_no, analysis_folder, multithread),
                    maxfev=50,
                    full_output=True
                )
                if opt_obj[-1] == "The solution converged.":
                    opt_solved = True
                else:
                    initial_location = initial_location * uniform(0.6, 1.2)
            pipe_length = pipe.CumulativeLength[-1]
            if mode == "clearance":
                result_seabed = min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle.SizeZ
            elif mode == "contact":
                # Penalty if no seabed contact is observed to get stronger response
                penalty = 5
                result_seabed = max(trunnion.RangeGraph('solid contact force').Mean)
                if result_seabed == 0:
                    result_seabed = -(min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle.SizeZ) * penalty
                rg_contact = pipe.RangeGraph('seabed normal resistance')
                seabed_contact = rg_contact.Mean[rg_contact.Mean > 0]
            elif mode == "touchdown":
                result_seabed = -(min(pipe.RangeGraph('seabed clearance', arclengthRange=of.arSpecifiedArclengths(0, pipe_length - 10)).Mean))
                if result_seabed >= 0:
                    rg_contact = pipe.RangeGraph('seabed normal resistance')
                    arc_len = rg_contact.X[rg_contact.Mean > 0]
                    result_seabed = arc_len[-1] - arc_len[0]
            bend_moment = pipe.StaticResult('Bend Moment', of.oeEndA)
            _use_calculated_positions(model, False)
            model["PLET_Buoy"].InitialZ = model["PLET_Buoy"].InitialZ + 50
            if mode == "contact":
                if (result_seabed > 0) and (result_seabed < clr_tol[1]) and (seabed_contact.size == 0):
                    check = True
                elif ((result_seabed > 0) and (result_seabed < clr_tol[1]) and (seabed_contact.size != 0)) or i == 9:
                    # Stuck at an incorrect local minimum. Nudge the model to try again.
                    vessel.InitialX = vessel.InitialX * uniform(0.9, 1.2)
            else:
                if clr_tol[0] < result_seabed < clr_tol[1]:
                    write_log(step_no, pipe_length, vessel.InitialX, result_seabed, bend_moment, clr_tol[0],
                              mode, iteration, analysis_folder=analysis_folder)
                    check = True
            if not check:
                if mode != "clearance":
                    model.Reset()
                    model["General"].BuoysIncludedInStatics = "Individually Specified"
                    model['PLET_Properties'].DegreesOfFreedomInStatics = "All"
                # Stage 2: pipe length for the seabed target
                optimize.minimize_scalar(
                    find_length,
                    bracket=(pipe_length * 0.7, pipe_length * 0.9, pipe_length * 1.1),
                    bounds=(pipe_length * 0.7, pipe_length * 1.1),
                    method="bounded",
                    args=(pipe, model, trunnion, target_seabed, plet, mode, step_no, analysis_folder, multithread),
                    tol=1.0
                )
                pipe_length = pipe.CumulativeLength[-1]
                if mode == "clearance":
                    result_seabed = min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle.SizeZ
                elif mode == "contact":
                    result_seabed = max(trunnion.RangeGraph('solid contact force').Mean)
                    if result_seabed == 0:
                        result_seabed = -(min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle.SizeZ)
                    rg_contact = pipe.RangeGraph('seabed normal resistance')
                    seabed_contact = rg_contact.Mean[rg_contact.Mean > 0]
                elif mode == "touchdown":
                    result_seabed = -(min(pipe.RangeGraph('seabed clearance', arclengthRange=of.arSpecifiedArclengths(0, pipe_length - 10)).Mean))
                    if result_seabed >= 0:
                        rg_contact = pipe.RangeGraph('seabed normal resistance')
                        arc_len = rg_contact.X[rg_contact.Mean > 0]
                        result_seabed = arc_len[-1] - arc_len[0]
                bend_moment = pipe.StaticResult('Bend Moment', of.oeEndA)
                _use_calculated_positions(model, False)
                model["PLET_Buoy"].InitialZ = model["PLET_Buoy"].InitialZ + 50
                if mode == "contact":
                    # Extra care given here, to ensure PLET has landed.
                    if (bm_tol[0] < bend_moment < bm_tol[1]) and (seabed_contact.size == 0):
                        if 0 < result_seabed < clr_tol[1]:
                            check = True
                else:
                    if bm_tol[0] < bend_moment < bm_tol[1]:
                        check = True
            if not multithread:
                log(f"  hang-off bend moment {bend_moment:.2f}kNm, seabed {mode} {result_seabed:.2f}")
            i += 1
            if i == max_iterations:
                log("Iteration not progressing.. please do this step manually.")
                check = True
        except Exception as e:
            log("Model failed to converge.")
            with open(f"{analysis_folder}//error.log", "a+") as f:
                f.write(str(e))
                f.write(traceback.format_exc())
            break

    # Reassign pipe sections
    solved_length = pipe.CumulativeLength[-1]
    df_solved = get_section_index(df_line, solved_length)
    reassign_pipe_sections(pipe, df_solved)
    set_pipe_length(pipe, solved_length, df_solved)
    log("Calculation done...")
    return model


###########################################################################
#############   FULL SEQUENCE                    ##########################
###########################################################################

def payout_step(length, model, water_depth, target_object, clearance_criteria, pipe, step_no, analysis_folder):
    """Objective for vertical payout steps: |target sea surface clearance - clearance|."""
    converged = False
    vessel = _find_vessel(model)
    plet = model["PLET_Properties"]
    init_x = plet.InitialX
    init_z = plet.InitialZ
    log(f'Paying out pipe... trying length of {length[0]}')
    delta = pipe.CumulativeLength[-1] - length[0]
    new_len = pipe.Length[0] - delta
    while new_len < 0:
        pipe.Length.DeleteRow(0)
        delta = pipe.CumulativeLength[-1] - length[0]
        new_len = pipe.Length[0] - delta
    pipe.Length[0] = new_len
    pipe_length = pipe.CumulativeLength[-1]
    model["General"].StaticsMinDamping = 3
    model["General"].StaticsMaxDamping = 14
    while not converged:
        try:
            model.CalculateStatics()
            if target_object.type == of.otLine:
                obj_od = model[target_object.LineType[0]].OuterContactDiameter
                sb_clearance = min(target_object.RangeGraph("seabed clearance").Mean)
                sea_clearance = water_depth - sb_clearance - obj_od
            elif target_object.type == of.ot3DBuoy:
                sea_clearance = target_object.StaticResult("Sea Surface Clearance")
            target = abs(clearance_criteria[0] - sea_clearance)
            if -clearance_criteria[1] < target < clearance_criteria[1]:
                target = 0
            bendMoment = pipe.StaticResult('Bend Moment', of.oeEndA)
            converged = True
            write_log(step_no, pipe_length, vessel.InitialX, sea_clearance, bendMoment, target,
                      mode="seabed clearance", analysis_folder=analysis_folder)
        except Exception:
            model.SaveData(f"{analysis_folder}//payout_temp.dat")
            model["General"].StaticsMaxIterations = 2000
            model["General"].StaticsMinDamping = uniform(3, 15)
            model["General"].StaticsMaxDamping = uniform(20, 30)
            plet.InitialX = init_x + uniform(-10, 10)
            plet.InitialZ = init_z - uniform(1, 10)
    return target


def vessel_step(vessel_x, model, vessel, criteria_one, criteria_two, pipe, step_no, mode, analysis_folder, debug=False):
    """Objective for the vessel X search.

    mode "bm": hang-off bend moment, "clr": receptacle clearance, "br": min wire bend radius.
    criteria_one = (target, tolerance). criteria_two is unused (kept from the original).
    """
    try:
        vessel_x = vessel_x[0]
    except Exception:
        pass
    converged = False
    log(f'Finding vessel position... trying {abs(vessel_x)}')
    trunnion = model["TrunnionMain"]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    wire = model["Initiation"]
    buoy = model["PLET_Buoy"]
    vessel.InitialX = abs(vessel_x)
    receptacle_height = receptacle.SizeZ
    if debug:
        model.SaveData(f"{analysis_folder}//Vessel_working.dat")
    pipe_length = pipe.CumulativeLength[-1]
    model["General"].StaticsMinDamping = 4
    model["General"].StaticsMaxDamping = 15
    while not converged:
        try:
            model.CalculateStatics()
            bendMoment = pipe.StaticResult("In Plane Bend Moment", of.oeEndA)
            endBendStrain = pipe.StaticResult('Max Bending Strain', of.oeEndA)
            seabed_result = min(trunnion.RangeGraph('seabed clearance').Mean) - receptacle_height
            wire_strain = max(wire.RangeGraph("Total mean axial strain", of.pnStaticState).Mean, key=abs)
            wire_bend_radius = wire.RangeGraph("Bend radius", of.pnStaticState).Mean
            criteria = criteria_one
            if mode == "bm":
                if wire_strain > 10:
                    target = wire_strain * 50
                else:
                    if seabed_result <= 0:
                        target = abs(bendMoment) * 100
                    else:
                        target = abs(bendMoment) if endBendStrain < 0.1 else bendMoment * endBendStrain * 100
            elif mode == "clr":
                target = abs(criteria[0] - seabed_result)
            elif mode == "br":
                target = abs(criteria[0] - min(wire_bend_radius))
            if -criteria[1] < target < criteria[1]:
                target = 0
            write_log(step_no, pipe_length, vessel.InitialX, seabed_result, bendMoment, target,
                      mode="receptacle clearance", analysis_folder=analysis_folder)
            converged = True
        except Exception as e:
            with open(f"{analysis_folder}//position_error.log", "a+") as f:
                f.write(str(e))
                f.write(traceback.format_exc())
            log("Calculation not converged during vessel finding step.. retrying...")
            model["General"].StaticsMaxIterations = 2000
            model["General"].StaticsMinDamping = uniform(3, 15)
            model["General"].StaticsMaxDamping = uniform(20, 30)
            buoy.InitialZ = model["PLET_Buoy"].InitialZ + 2.5
    return target


def prep_base_model(ctx, model, current_direction, rb_opening, rb_settings, mode="clearance"):
    """Variation model for a step: current, contents, rollerbox, simplified pipe.

    Returns (var_model, df_line original sections, df_simplified, pipe).
    """
    log("Preparing base model...")
    var_model = of.Model()
    var_model.NewVariationModel(model.latestFileName)
    var_model.type = of.ModelType.Standard
    env = var_model["Environment"]
    if current_direction != -1:
        env.RefCurrentSpeed = 1.0
        env.RefCurrentDirection = current_direction
    else:
        env.RefCurrentSpeed = 0.0
    pipe = var_model["RigidPipe"]
    pipe.contentsDensity = ctx.contents_density
    model_roller_openings(rb_opening, rb_settings, var_model)
    df_line = check_line_structure(var_model, pipe)
    simplify_pipe_sections(pipe, df_line, env.WaterDepth, mode)
    df_simplified = check_line_structure(var_model, pipe)
    return var_model, df_line, df_simplified, pipe


def disconnect_buoyancy(model):
    """Fixes the buoyancy module and its rigging (buoyancy not yet active)."""
    buoy = model["PLET_Buoy"]
    buoy_rigging = model["Buoyancy_Rigging"]
    buoy.Connection = "Fixed"
    buoy_rigging.EndAConnection = "Fixed"
    buoy_rigging.EndBConnection = "Fixed"
    model["PLET_YokeHinge"].DOFFree[4] = "No"
    buoy.hidden = "Yes"
    buoy_rigging.hidden = "Yes"


def disconnect_sip(model):
    """Disconnects the SIP rigging from the initiation wire."""
    model["rigging_SIP"].EndAConnection = "Fixed"


def connect_sip(model):
    """Connects the SIP rigging to the initiation wire."""
    rigging = model["rigging_SIP"]
    rigging.EndAConnection = "Initiation"
    rigging.EndAzRelativeTo = "End B"
    rigging.EndAZ = 0.0


def plet_helper(model):
    """Places the PLET near the receptacle to improve static convergence."""
    env = model["Environment"]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    trunnion = model["TrunnionMain"]
    plet = model["PLET_Properties"]
    trunnion_od = model[trunnion.LineType[0]].OuterContactDiameter
    target_z = -env.WaterDepth + receptacle.SizeZ + trunnion_od / 2
    init_connection = trunnion.EndAConnection
    trunnion.EndAConnection = "Free"
    init_z = trunnion.EndAZ
    trunnion.EndAConnection = init_connection
    plet.InitialZ = plet.InitialZ - (init_z - target_z)
    plet.InitialX = receptacle.OriginX + receptacle.SizeX * 0.5


def connect_buoyancy(base_model, var_model):
    """Restores the buoyancy module, yoke and rigging connections from the base model."""
    buoy_rigging_base = base_model["Buoyancy_Rigging"]
    buoy_var = var_model["PLET_Buoy"]
    buoy_rigging_var = var_model["Buoyancy_Rigging"]
    buoy_var.Connection = "Free"
    buoy_rigging_var.EndAConnection = buoy_rigging_base.EndAConnection
    buoy_rigging_var.EndAX = buoy_rigging_base.EndAX
    buoy_rigging_var.EndAY = buoy_rigging_base.EndAY
    buoy_rigging_var.EndAZ = buoy_rigging_base.EndAZ
    buoy_rigging_var.EndBConnection = buoy_rigging_base.EndBConnection
    buoy_rigging_var.EndBX = buoy_rigging_base.EndBX
    buoy_rigging_var.EndBY = buoy_rigging_base.EndBY
    buoy_rigging_var.EndBZ = buoy_rigging_base.EndBZ
    var_model["PLET_YokeHinge"].DOFFree[4] = "Yes"
    buoy_var.hidden = "No"
    buoy_rigging_var.hidden = "No"


def guess_config_vertical(model, target_clearance):
    """Initial guess for the vertical payout steps (PLET hanging below the ramp)."""
    plet = model["PLET_Properties"]
    pipe = model["RigidPipe"]
    buoy = model["PLET_Buoy"]
    og_pipe_endA = pipe.EndAConnection
    pipe.EndAConnection = "Free"
    initX = pipe.EndAX
    pipe.EndAConnection = og_pipe_endA
    vessel = _find_vessel(model)
    vessel.InitialX = vessel.InitialX - initX
    pipe.EndAConnection = "Free"
    initX = pipe.EndAX
    pipe.EndAConnection = og_pipe_endA
    plet.InitialX = initX
    plet.InitialZ = -target_clearance
    plet.InitialRotation2 = 270
    buoy.initialX = initX - 25
    buoy.initialZ = 0


def stabilise_model(model, model_name, rb_opening):
    """Recalculates statics until converged and saves the step file. False if unstable after 10 tries."""
    plet = model["PLET_Properties"]
    init_x = plet.InitialX
    init_z = plet.InitialZ
    if rb_opening > 0:
        _support_pipe_on_rollerbox(model)
    counter = 1
    model["General"].StaticsMinDamping = 3
    model["General"].StaticsMaxDamping = 14
    while True:
        try:
            model.CalculateStatics()
            _use_calculated_positions(model, True)
            model["General"].StaticsMinDamping = 3
            model["General"].StaticsMaxDamping = 14
            model.SaveData(model_name)
            return True
        except Exception:
            if counter == 10:
                log(f"Model {model_name} unstable. Please continue manually.")
                model.SaveData(f"{model_name[:-4]}_unstable.dat")
                return False
            model["General"].StaticsMaxIterations = 1000
            model["General"].StaticsMinDamping = uniform(3, 15)
            model["General"].StaticsMaxDamping = uniform(20, 30)
            plet.InitialX = init_x - uniform(0.2, 0.8)
            plet.InitialZ = init_z + uniform(0.1, 0.5)
            counter += 1


def _report(stabilised, step, label=""):
    label = f" {label}" if label else ""
    if stabilised:
        log(f"Step {step}{label} done, check saved file...")
    else:
        log(f"Step {step}{label} unstable, please do this step manually...")


def _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance, angle_offset=0.0, sign=-1):
    """Sets the ramp angle and moves the vessel to the estimated catenary anchor spacing.

    Returns the estimated catenary length.
    """
    anchor_pos, catenary_length = find_catenary_starting_shape(surface_clearance, ramp_angle + angle_offset)
    ramp.InitialRotation2 = ramp_angle
    spacing = vessel.InitialX - _anchor_pipe_end_b_x(pipe)
    vessel.InitialX = vessel.InitialX + (abs(anchor_pos) + sign * spacing)
    return catenary_length


def verify_ramp_angle(ctx, selected_angle):
    """Upfront landing step check for a ramp angle, for every current direction.

    Returns (verified, DataFrame of failed criteria or None).
    """
    for current_direction in ctx.current_directions:
        verified, df_failed = generate_landing_step(ctx, current_direction, selected_angle)
        if not verified:
            return False, df_failed
    return True, None


def optimise_ramp_angle(ctx, selected_angle, pin_locations):
    """Tries the remaining standard pins (highest first) until one passes the landing check.

    Returns the angle found, or None.
    """
    candidates = [pin for pin in pin_locations if pin != selected_angle]
    for check_angle in reversed(candidates):
        try:
            check_length(ctx, [check_angle])
        except StaticsError:
            log(f"No suitable ramp angle identified, not enough pipe length for ramp angle of {check_angle}deg.")
            return None
        verified, df_failed = verify_ramp_angle(ctx, check_angle)
        if verified:
            log(f"Found potential ramp angle of {check_angle}, proceeding analysis...")
            return check_angle
        if df_failed is not None:
            log(f"Ramp angle {check_angle} failed:\n{df_failed.to_string()}")
            if 'Horizontal Top Tension' in df_failed.columns:
                log("No suitable ramp angle identified for standard pins. Non-standard ramp angle might be required.")
                return None
    return None


def generate_full_sequence(ctx, brake_mode, selected_angle, pin_locations, payout_range):
    """Generates all static steps from the landing angle up to vertical, for each current direction."""
    angle_range = pin_locations[pin_locations.index(selected_angle):]
    if len(angle_range) > 1:
        angle_range = angle_range if angle_range[0] != angle_range[1] else angle_range[1:]
    angle_range = angle_range[::-1]
    for current_direction in ctx.current_directions:
        log(f"===== Current: {CURRENT_LABELS[current_direction]} =====")
        generate_static_steps(ctx, current_direction, angle_range, payout_range)
    log("All static steps have been generated. Please check OrcaFlex models.")


def generate_landing_step(ctx, current_direction, selected_angle):
    """Solves the secondary trunnion landing step for a ramp angle and checks it against the criteria.

    Returns (verified, DataFrame of failed criteria or None).
    """
    analysis_folder = ctx.analysis_folder
    current_label = CURRENT_LABELS[current_direction]
    model_name, rb_settings = get_rb_settings(ctx, ctx.model_path)
    rb_opening = ctx.roller_openings[0] if ctx.rollerbox else 0
    model = of.Model(model_name)
    step = 316

    cat_factor = 0.9 + (0.04 if current_direction == 0 else 0.0)
    target_contact = 10  # kN/m
    target_clearance = 0  # m
    tolerance = 10  # kN/m
    var_model, df_line, df_simplified, pipe = prep_base_model(ctx, model, current_direction, rb_opening, rb_settings)
    log(f"Verifying ramp angle of {selected_angle}, solving landing step...")
    water_depth = var_model["Environment"].WaterDepth
    ramp = var_model[ctx.ramp_name]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    vessel = _find_vessel(var_model)
    ramp_angle = -selected_angle
    surface_clearance = water_depth - target_clearance - receptacle.SizeZ
    catenary_length = _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance, angle_offset=-0.5)
    df_catenary = get_section_index(df_simplified, catenary_length * cat_factor)
    reassign_pipe_sections(pipe, df_catenary)
    set_pipe_length(pipe, catenary_length * cat_factor, df_catenary, mode="simplified")
    optimize_configuration(var_model, df_line, target_contact, tolerance, trunnion_name="Secondary",
                           mode="contact", step_no=step, analysis_folder=analysis_folder, debug=ctx.debug)
    solved_length = pipe.CumulativeLength[-1]
    df_solved = get_section_index(df_line, solved_length)
    reassign_pipe_sections(pipe, df_solved)
    set_pipe_length(pipe, solved_length, df_solved)
    var_name = f"{analysis_folder}//Statics_Step{step:03d}_current-{current_label}_ramp-{selected_angle}.dat"
    stabilised = stabilise_model(var_model, var_name, rb_opening)
    if not stabilised:
        log("Unable to verify landing step. Ramp angle is probably too steep or too flat.")
        return False, None

    log(f"Landing step ({step}) with angle {selected_angle} done, checking criteria...")
    results, _ = post_process(var_model, step)
    df_eng = results[-1]
    _, eng_lim = get_criteria(ctx.criteria)
    values = df_eng.iloc[0].tolist()
    failed = [
        col for col, val, lim in zip(df_eng.columns, values, eng_lim)
        if lim != "-" and val is not None and float(val) > float(lim)
    ]
    if ctx.debug:
        df_check = df_eng.copy()
        df_check.loc["limit"] = eng_lim
        df_check.to_csv(f"{analysis_folder}//inspect_{selected_angle}.csv")
    if not failed:
        return True, None
    df_failed = pd.DataFrame(
        [[df_eng.iloc[0][c] for c in failed], [eng_lim[list(df_eng.columns).index(c)] for c in failed]],
        columns=failed, index=["result", "limit"],
    )
    return False, df_failed


def generate_static_steps(ctx, current_direction, angle_range, payout_range):
    """Generates the full static sequence for one current direction.

    1. Vertical payout (trunnion 30m below surface, buoyancy 10m below surface, SIP connection)
    2. Jack down through the ramp angles, paying out pipe (max payout from `payout_range`)
    3. No-stop zone: 5m clearance, main trunnion landing, secondary trunnion landing, TDP 5m and 20m
    Each solved step is saved as Statics_StepNNN_current-<label>.dat in the analysis folder.
    """
    analysis_folder = ctx.analysis_folder
    vessel_name = ctx.vessel_data["Name"]
    ramp_name = ctx.ramp_name
    current_cat = 0.04 if current_direction == 0 else 0.0
    current_label = CURRENT_LABELS[current_direction]
    model_name, rb_settings = get_rb_settings(ctx, ctx.model_path)
    rb_opening = ctx.roller_openings[0] if ctx.rollerbox else 0
    model = of.Model(model_name)

    def prep(mode="clearance"):
        return prep_base_model(ctx, model, current_direction, rb_opening, rb_settings, mode=mode)

    def finalise(var_model, pipe, df_line, solved_length):
        df_solved = get_section_index(df_line, solved_length)
        reassign_pipe_sections(pipe, df_solved)
        set_pipe_length(pipe, solved_length, df_solved)

    def step_file(step, suffix=""):
        return f"{analysis_folder}//Statics_Step{step:03d}_current-{current_label}{suffix}.dat"

    ##################### Step 3 - Main trunnion 30m below surface #########################
    step = 3
    target_clearance = 30
    var_model, df_line, df_simplified, pipe = prep()
    log(f"Solving Step {step}...")
    df_catenary = get_section_index(df_simplified, target_clearance)
    reassign_pipe_sections(pipe, df_catenary)
    set_pipe_length(pipe, target_clearance, df_catenary, mode="simplified")
    water_depth = var_model["Environment"].WaterDepth
    main_trunnion = var_model["TrunnionMain"]
    ramp = var_model[ramp_name]
    guess_config_vertical(var_model, target_clearance)
    disconnect_buoyancy(var_model)
    disconnect_sip(var_model)
    ramp.InitialRotation2 = -90.5 if "Vega" in vessel_name else -90
    optimize.fsolve(payout_step, x0=pipe.CumulativeLength[-1],
                    args=(var_model, water_depth, main_trunnion, (target_clearance, 5), pipe, step, analysis_folder))
    solved_length = pipe.CumulativeLength[-1]
    finalise(var_model, pipe, df_line, solved_length)
    _report(stabilise_model(var_model, step_file(step), rb_opening), step)

    ##################### Step 4 - Buoyancy 10m below water surface #########################
    step += 1
    var_model, df_line, df_simplified, pipe = prep()
    log(f"Solving Step {step}...")
    water_depth = var_model["Environment"].WaterDepth
    main_trunnion = var_model["TrunnionMain"]
    buoy_rigging = var_model["Buoyancy_Rigging"]
    ramp = var_model[ramp_name]
    target_clearance = 10 + buoy_rigging.UnstretchedLength
    df_catenary = get_section_index(df_simplified, target_clearance)
    reassign_pipe_sections(pipe, df_catenary)
    set_pipe_length(pipe, target_clearance, df_catenary, mode="simplified")
    guess_config_vertical(var_model, target_clearance)
    disconnect_buoyancy(var_model)
    disconnect_sip(var_model)
    ramp.InitialRotation2 = -90.5 if "Vega" in vessel_name else -90
    optimize.fsolve(payout_step, x0=pipe.CumulativeLength[-1],
                    args=(var_model, water_depth, main_trunnion, (target_clearance, 5), pipe, step, analysis_folder))
    solved_length = pipe.CumulativeLength[-1]
    finalise(var_model, pipe, df_line, solved_length)
    _report(stabilise_model(var_model, step_file(step, "_NoBuoy"), rb_opening), step, "without buoy")
    connect_buoyancy(model, var_model)
    _report(stabilise_model(var_model, step_file(step), rb_opening), step, "with buoy")

    ##################### Vega only: first jackdown to 90deg with 3m payout #########################
    if "Vega" in vessel_name:
        step += 1
        var_model, df_line, df_simplified, pipe = prep()
        log(f"Solving Step {step}...")
        buoy_rigging = var_model["Buoyancy_Rigging"]
        ramp = var_model[ramp_name]
        target_clearance = 15 + buoy_rigging.UnstretchedLength
        target_length = solved_length + 3
        df_catenary = get_section_index(df_simplified, target_clearance)
        reassign_pipe_sections(pipe, df_catenary)
        set_pipe_length(pipe, target_length, df_catenary, mode="simplified")
        guess_config_vertical(var_model, target_clearance)
        disconnect_sip(var_model)
        ramp.InitialRotation2 = -90
        solved_length = pipe.CumulativeLength[-1]
        finalise(var_model, pipe, df_line, solved_length)
        connect_buoyancy(model, var_model)
        _report(stabilise_model(var_model, step_file(step), rb_opening), step, "(jackdown to 90deg)")

    ##################### Step 4c - Payout enough to install TRF (or other fixed length sections) ######
    var_od_row = df_line.loc[(df_line["variableOD"] == True) & (df_line["cumulativeLength"] > 25)]
    for idx, row in var_od_row[::-1].iterrows():
        step += 1
        var_model, df_line, df_simplified, pipe = prep()
        log(f"Solving Step {step}...")
        ramp = var_model[ramp_name]
        vessel = _find_vessel(var_model)
        total_len = row["cumulativeLength"] + 1
        df_catenary = get_section_index(df_simplified, total_len)
        reassign_pipe_sections(pipe, df_catenary)
        set_pipe_length(pipe, total_len, df_catenary, mode="simplified")
        connect_buoyancy(model, var_model)
        ramp.InitialRotation2 = -90
        if total_len <= water_depth - 10:
            guess_config_vertical(var_model, total_len)
            disconnect_sip(var_model)
        else:
            if step < 900:
                step += 900
            ramp_angle = -angle_range[-1]
            end_b_x = _anchor_pipe_end_b_x(pipe)
            ramp.InitialRotation2 = ramp_angle
            anchor_pos, catenary_length = find_catenary_starting_shape(water_depth, ramp_angle)
            spacing = vessel.InitialX - end_b_x
            sb_len = 50
            if total_len > catenary_length:
                sb_len = total_len - catenary_length
            # Set PLET to landing config
            plet_helper(var_model)
            vessel.InitialX = vessel.InitialX + (abs(anchor_pos) - spacing) + sb_len
            df_catenary = get_section_index(df_simplified, total_len)
            reassign_pipe_sections(pipe, df_catenary)
            set_pipe_length(pipe, total_len, df_catenary, mode="simplified")
            pipe_mp = check_Mp(var_model)
            optimize.fsolve(vessel_step, x0=vessel.InitialX,
                            args=(var_model, vessel, (0, pipe_mp * 0.025), 10, pipe, step, "bm", analysis_folder, ctx.debug))
        finalise(var_model, pipe, df_line, total_len)
        _report(stabilise_model(var_model, step_file(step, "_aux"), rb_opening), step)
    step = step - 900 if step > 900 else step

    ##################### Step 5 - Connect to SIP #########################
    step += 1
    var_model, df_line, df_simplified, pipe = prep()
    log(f"Solving Step {step}...")
    water_depth = var_model["Environment"].WaterDepth
    main_trunnion = var_model["TrunnionMain"]
    ramp = var_model[ramp_name]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    vessel = _find_vessel(var_model)
    receptacle_clearance = 10
    target_clearance = water_depth - receptacle_clearance - receptacle.SizeZ
    df_catenary = get_section_index(df_simplified, target_clearance)
    reassign_pipe_sections(pipe, df_catenary)
    set_pipe_length(pipe, target_clearance, df_catenary, mode="simplified")
    guess_config_vertical(var_model, target_clearance)
    connect_buoyancy(model, var_model)
    disconnect_sip(var_model)
    ramp.InitialRotation2 = -90
    optimize.fsolve(payout_step, x0=pipe.CumulativeLength[-1],
                    args=(var_model, water_depth, main_trunnion, (target_clearance, 1), pipe, step, analysis_folder))
    solved_length = pipe.CumulativeLength[-1]
    solved_vessel = vessel.InitialX
    finalise(var_model, pipe, df_line, solved_length)
    connect_sip(var_model)
    _report(stabilise_model(var_model, step_file(step), rb_opening), step)

    ##################### Step 6 - Move vessel to build layback (target wire bend radius) ##########
    step += 1
    log(f"Solving Step {step}...")
    vessel = _find_vessel(var_model)
    optimize.minimize_scalar(
        vessel_step,
        bounds=(solved_vessel, solved_vessel * 1.4),
        method="bounded",
        options={"maxiter": 7},
        args=(var_model, vessel, (100, 10), 10e3, pipe, step, "br", analysis_folder, ctx.debug)
    )
    _report(stabilise_model(var_model, step_file(step), rb_opening), step)

    ##################### Step 7 - Jack down #########################
    # Jack down and move vessel, then check integrity. If exceeded, payout pipe at same angle, then continue
    prev_length = pipe.CumulativeLength[-1]
    cat_factor = 0.85 + current_cat
    target_clearance = 10.0
    tolerance = 1
    ## FIRST ANGLE CHANGE: fixed payout (5m or 6m, PG-ENG-ST-007), then move vessel for zero BM
    step += 1
    var_model, df_line, df_simplified, pipe = prep()
    log(f"Solving Step {step}...")
    water_depth = var_model["Environment"].WaterDepth
    ramp = var_model[ramp_name]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    vessel = _find_vessel(var_model)
    ramp_angle = -angle_range[0]
    surface_clearance = water_depth - target_clearance - receptacle.SizeZ
    seabed_clearance = target_clearance + receptacle.SizeZ
    pipe_mp = check_Mp(var_model)
    target_nom = pipe_mp * 0.2
    target_tol = pipe_mp * 0.025
    ramp.InitialRotation2 = ramp_angle
    end_b_x = _anchor_pipe_end_b_x(pipe)
    anchor_pos, catenary_length = find_catenary_starting_shape(surface_clearance, ramp_angle)
    spacing = vessel.InitialX - end_b_x
    vessel.InitialX = vessel.InitialX + (abs(anchor_pos * 1.2) - spacing) * 0.8
    # Go through the fixed payout range to find the best for this operation
    for fixed_payout in payout_range:
        log(f"trying {fixed_payout}m payout")
        target_length = prev_length + fixed_payout
        df_catenary = get_section_index(df_simplified, target_length)
        reassign_pipe_sections(pipe, df_catenary)
        set_pipe_length(pipe, target_length, df_catenary, mode="simplified")
        optimize.fsolve(vessel_step, x0=vessel.InitialX,
                        args=(var_model, vessel, (target_nom, target_tol), 10, pipe, step, "bm", analysis_folder, ctx.debug))
        # Break loop and continue if configuration is good
        if check_clearance(var_model, analysis_folder):
            break
    solved_length = pipe.CumulativeLength[-1]
    solved_vessel = vessel.InitialX
    prev_length = solved_length
    finalise(var_model, pipe, df_line, solved_length)
    _report(stabilise_model(var_model, step_file(step), rb_opening), step)

    ## REST OF RAMP ANGLES
    for idx, current_angle in enumerate(angle_range[1:], start=1):
        # Solve each angle change whilst maintaining 8 to 10m clearance.
        # If resultant pipe length > fixed payout from previous step, add a payout + vessel move only step.
        step += 1
        var_model, df_line, df_simplified, pipe = prep()
        log(f"Solving Step {step}...")
        water_depth = var_model["Environment"].WaterDepth
        ramp = var_model[ramp_name]
        receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
        vessel = _find_vessel(var_model)
        ramp_angle = -current_angle
        surface_clearance = water_depth - target_clearance - receptacle.SizeZ
        seabed_clearance = target_clearance + receptacle.SizeZ
        catenary_length = _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance)
        df_catenary = get_section_index(df_simplified, catenary_length * cat_factor)
        reassign_pipe_sections(pipe, df_catenary)
        set_pipe_length(pipe, catenary_length * cat_factor, df_catenary, mode="simplified")
        optimize_configuration(var_model, df_line, seabed_clearance, tolerance, mode="clearance",
                               step_no=step, analysis_folder=analysis_folder, debug=ctx.debug)
        solved_length = pipe.CumulativeLength[-1]
        solved_vessel = vessel.InitialX
        finalise(var_model, pipe, df_line, solved_length)
        solved_length = pipe.CumulativeLength[-1]

        step += 1
        step_status = False
        for fixed_payout in payout_range:
            if step_status:
                break
            if round(solved_length, 0) > round(prev_length, 0) + fixed_payout:
                # Jackdown step needs more payout than allowed: save it as step n,
                # then solve an intermediate payout + vessel move step n-1 at the previous angle.
                _report(stabilise_model(var_model, step_file(step), rb_opening), step)
                rename_log(step - 1, step, analysis_folder)
                payout_length = solved_length - fixed_payout
                temp_var_model, df_line, df_simplified, pipe = prep()
                log(f"Payout during jackdown exceeds fixed payout. Solving Step {step - 1}")
                df_catenary = get_section_index(df_simplified, payout_length)
                reassign_pipe_sections(pipe, df_catenary)
                set_pipe_length(pipe, payout_length, df_catenary, mode="simplified")
                ramp = temp_var_model[ramp_name]
                vessel = _find_vessel(temp_var_model)
                ramp.InitialRotation2 = -angle_range[idx - 1] if idx != 0 else -90
                optimize.fsolve(vessel_step, x0=solved_vessel,
                                args=(temp_var_model, vessel, (0, pipe_mp * 0.05), 10, pipe, step - 1, "bm",
                                      analysis_folder, ctx.debug))
                step_status = check_clearance(temp_var_model, analysis_folder)
                log(f"solved length is {solved_length}, prev length is {prev_length}. "
                    f"new length is {payout_length}. Fixed payout is {fixed_payout}")
                if not step_status and fixed_payout != payout_range[-1]:
                    log(f"not enough length for {fixed_payout}")
                    continue
                var_model = temp_var_model
                prev_length = solved_length
                solved_length = pipe.CumulativeLength[-1]
                temp_var_model.CalculateStatics()
                _use_calculated_positions(var_model, False)
                finalise(var_model, pipe, df_line, solved_length)
                solved_length = pipe.CumulativeLength[-1]
                _report(stabilise_model(var_model, step_file(step - 1), rb_opening), step - 1)
            elif round(solved_length, 0) < round(prev_length, 0) + fixed_payout:
                # Jackdown needs less payout than the fixed payout: fix payout, move vessel for 10m clearance.
                temp_var_model, df_line, df_simplified, pipe = prep()
                log(f"Solving Step {step - 1}...")
                water_depth = temp_var_model["Environment"].WaterDepth
                ramp = temp_var_model[ramp_name]
                receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
                vessel = _find_vessel(temp_var_model)
                ramp_angle = -current_angle
                surface_clearance = water_depth - target_clearance - receptacle.SizeZ
                target_length = prev_length + fixed_payout
                _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance)
                df_catenary = get_section_index(df_simplified, target_length)
                reassign_pipe_sections(pipe, df_catenary)
                set_pipe_length(pipe, target_length, df_catenary, mode="simplified")
                optimize.fsolve(vessel_step, x0=vessel.InitialX,
                                args=(temp_var_model, vessel, (10, 1), 10, pipe, step - 1, "clr",
                                      analysis_folder, ctx.debug))
                step_status = check_hangoff_moment(temp_var_model, analysis_folder)
                if not step_status and fixed_payout != payout_range[-1]:
                    continue
                var_model = temp_var_model
                solved_length = pipe.CumulativeLength[-1]
                solved_vessel = vessel.InitialX
                finalise(var_model, pipe, df_line, solved_length)
                _report(stabilise_model(var_model, step_file(step - 1), rb_opening), step - 1)
            else:
                _report(stabilise_model(var_model, step_file(step), rb_opening), step - 1)
                prev_length = solved_length
                step_status = True

    ##################### Step 9 - No stop zone - 5m above seabed #########################
    step += 1
    target_clearance = 5
    tolerance = 0.2
    var_model, df_line, df_simplified, pipe = prep()
    log(f"Solving Step {step}...")
    water_depth = var_model["Environment"].WaterDepth
    ramp = var_model[ramp_name]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    vessel = _find_vessel(var_model)
    ramp_angle = -angle_range[-1]
    surface_clearance = water_depth - target_clearance - receptacle.SizeZ
    seabed_clearance = target_clearance + receptacle.SizeZ
    catenary_length = _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance)
    df_catenary = get_section_index(df_simplified, catenary_length * cat_factor)
    reassign_pipe_sections(pipe, df_catenary)
    set_pipe_length(pipe, catenary_length * cat_factor, df_catenary, mode="simplified")
    optimize_configuration(var_model, df_line, seabed_clearance, tolerance, mode="clearance",
                           step_no=step, analysis_folder=analysis_folder, debug=ctx.debug)
    solved_length = pipe.CumulativeLength[-1]
    finalise(var_model, pipe, df_line, solved_length)
    _report(stabilise_model(var_model, step_file(step), rb_opening), step)

    ##################### Step 10 - No stop zone - Main trunnion on seabed #########################
    step += 1
    target_contact = 2  # kN/m
    target_clearance = 0  # m
    tolerance = 2  # kN/m
    cat_factor = 0.875 + current_cat
    var_model, df_line, df_simplified, pipe = prep()
    log(f"Solving Step {step}...")
    water_depth = var_model["Environment"].WaterDepth
    ramp = var_model[ramp_name]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    vessel = _find_vessel(var_model)
    ramp_angle = -angle_range[-1]
    surface_clearance = water_depth - target_clearance - receptacle.SizeZ
    catenary_length = _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance, angle_offset=0.5)
    df_catenary = get_section_index(df_simplified, catenary_length * cat_factor)
    reassign_pipe_sections(pipe, df_catenary)
    set_pipe_length(pipe, catenary_length * cat_factor, df_catenary, mode="simplified")
    optimize_configuration(var_model, df_line, target_contact, tolerance, mode="contact",
                           step_no=step, analysis_folder=analysis_folder, debug=ctx.debug)
    solved_length_main_trunnion = pipe.CumulativeLength[-1]
    finalise(var_model, pipe, df_line, solved_length_main_trunnion)
    _report(stabilise_model(var_model, step_file(step), rb_opening), step)

    ##################### Step 13 - 5m pipe on seabed #########################
    # Done first to see if the secondary trunnion lands. If it does, a separate landing step is solved.
    step += 1
    target_span = 5.0  # m
    target_clearance = 0  # m
    tolerance = 2  # m
    cat_factor = 0.9 + current_cat
    var_model, df_line, df_simplified, pipe = prep(mode="touchdown")
    log(f"Solving Step {step}...")
    water_depth = var_model["Environment"].WaterDepth
    ramp = var_model[ramp_name]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    vessel = _find_vessel(var_model)
    ramp_angle = -angle_range[-1]
    surface_clearance = water_depth - target_clearance - receptacle.SizeZ
    catenary_length = _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance, sign=1)
    df_catenary = get_section_index(df_simplified, catenary_length * cat_factor)
    reassign_pipe_sections(pipe, df_catenary)
    set_pipe_length(pipe, catenary_length * cat_factor, df_catenary, mode="simplified")
    optimize_configuration(var_model, df_line, target_span, tolerance, mode="touchdown",
                           step_no=step, analysis_folder=analysis_folder, debug=ctx.debug)
    solved_length = pipe.CumulativeLength[-1]
    finalise(var_model, pipe, df_line, solved_length)
    var_model.CalculateStatics()
    rg_contact = var_model["TrunnionSecondary"].RangeGraph("solid contact force")
    solid_contact = rg_contact.Mean[rg_contact.Mean > 0]
    if solid_contact.size == 0:
        _report(stabilise_model(var_model, step_file(step), rb_opening), step)
    else:
        step += 1
        _report(stabilise_model(var_model, step_file(step), rb_opening), step)
        rename_log(step - 1, step, analysis_folder)
        ##################### Step 12 - No stop zone - Second trunnion on seabed #########################
        cat_factor = 0.98 + current_cat
        target_contact = 5  # kN/m
        target_clearance = 0  # m
        tolerance = 4  # kN/m
        var_model, df_line, df_simplified, pipe = prep()
        log(f"Solving Step {step - 1}...")
        water_depth = var_model["Environment"].WaterDepth
        ramp = var_model[ramp_name]
        receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
        vessel = _find_vessel(var_model)
        ramp_angle = -angle_range[-1]
        surface_clearance = water_depth - target_clearance - receptacle.SizeZ
        _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance, angle_offset=0.5)
        catenary_length = solved_length_main_trunnion * 1.1
        df_catenary = get_section_index(df_simplified, catenary_length * cat_factor)
        reassign_pipe_sections(pipe, df_catenary)
        set_pipe_length(pipe, catenary_length * cat_factor, df_catenary, mode="simplified")
        optimize_configuration(var_model, df_line, target_contact, tolerance, trunnion_name="Secondary",
                               mode="contact", step_no=step - 1, analysis_folder=analysis_folder, debug=ctx.debug)
        solved_length = pipe.CumulativeLength[-1]
        finalise(var_model, pipe, df_line, solved_length)
        _report(stabilise_model(var_model, step_file(step - 1), rb_opening), step - 1)

    ##################### Step 14 - 20m on seabed #########################
    step += 1
    target_span = 20.0  # m
    target_clearance = 0  # m
    tolerance = 2  # m
    cat_factor = 0.9 + current_cat
    var_model, df_line, df_simplified, pipe = prep(mode="touchdown")
    log(f"Solving Step {step}...")
    water_depth = var_model["Environment"].WaterDepth
    ramp = var_model[ramp_name]
    receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
    vessel = _find_vessel(var_model)
    ramp_angle = -angle_range[-1]
    surface_clearance = water_depth - target_clearance - receptacle.SizeZ
    catenary_length = _position_vessel_for_catenary(pipe, vessel, ramp, ramp_angle, surface_clearance)
    df_catenary = get_section_index(df_simplified, catenary_length * cat_factor)
    reassign_pipe_sections(pipe, df_catenary)
    set_pipe_length(pipe, catenary_length * cat_factor, df_catenary, mode="simplified")
    optimize_configuration(var_model, df_line, target_span, tolerance, mode="touchdown",
                           step_no=step, analysis_folder=analysis_folder, debug=ctx.debug)
    solved_length = pipe.CumulativeLength[-1]
    finalise(var_model, pipe, df_line, solved_length)
    _report(stabilise_model(var_model, step_file(step), rb_opening), step)


###########################################################################
#############   CRITICAL STEP (parallel)         ##########################
###########################################################################

def critical_ramp_angles(ctx, angle_range, brake_mode=False):
    """Ramp angles to screen: standard pins within the range, or every 1deg in brake mode."""
    lo, hi = min(angle_range), max(angle_range)
    pins = np.array([float(p) for p in (range(70, 90) if brake_mode else ctx.pin_locations)])
    ramp_angles = list(pins[(lo <= pins) & (pins <= hi)])
    if brake_mode and lo != hi:
        ramp_angles = list(range(int(np.ceil(lo)), int(np.floor(hi)) + 1))
    return [float(a) for a in ramp_angles]


def build_lcm(ctx, ramp_angles, buoy_tol=0.0, wire_tol=0.0):
    """Load case matrix: (buoyancy WIW, wire length, ramp angle, rollerbox opening, current direction)."""
    buoy_lcs = [ctx.buoyancy_wiw]
    wire_lcs = [ctx.nom_wire_length]
    if buoy_tol:
        buoy_lcs = [ctx.buoyancy_wiw - buoy_tol, ctx.buoyancy_wiw + buoy_tol, ctx.buoyancy_wiw]
    if wire_tol:
        wire_lcs = [ctx.nom_wire_length - wire_tol, ctx.nom_wire_length + wire_tol, ctx.nom_wire_length]
    roller_openings = ctx.roller_openings if ctx.rollerbox else [0]
    return list(itertools.product(buoy_lcs, wire_lcs, ramp_angles, roller_openings, ctx.current_directions))


def run_critical_case(job, model_name, ramp_name, contents_density, analysis_folder, target_clearance,
                      rb_settings, debug):
    """Solves one critical step case (runs in a worker process). Returns a status string."""
    cat_factors = {0: 0.89, 180: 0.85, -1: 0.82}
    buoy_wiw, wire_length, angle, rb_opening, current_direction = job
    current_label = CURRENT_LABELS[current_direction]
    sens_name = (f"critical_clr-{target_clearance}_buoy-{abs(buoy_wiw):.1f}_wire-{wire_length:.1f}"
                 f"_angle-{angle:.1f}_rb-{int(rb_opening)}_current-{current_label}")
    try:
        cat_factor = cat_factors[current_direction]
        tolerance = 0.5
        model = of.Model(model_name)
        env = model["Environment"]
        water_depth = env.WaterDepth
        if current_direction != -1:
            env.RefCurrentSpeed = 1.0
            env.RefCurrentDirection = current_direction
        else:
            env.RefCurrentSpeed = 0.0
        ramp = model[ramp_name]
        pipe = model["RigidPipe"]
        buoy = model["PLET_Buoy"]
        buoy.Volume = (buoy.Mass - buoy_wiw) / env.Density
        model["Initiation"].Length[0] = wire_length
        pipe.ContentsDensity = contents_density
        vessel = _find_vessel(model)
        model_roller_openings(rb_opening, rb_settings, model)

        # Estimate catenary length for the ramp angle
        anchor_pos, catenary_length = find_catenary_starting_shape(water_depth - 10, -angle)
        spacing = vessel.InitialX - _anchor_pipe_end_b_x(pipe)
        vessel.InitialX = vessel.InitialX + (abs(anchor_pos * 0.6) - spacing)
        ramp.InitialRotation2 = -angle
        # Simplify model to aid with optimisation
        df_line = check_line_structure(model, pipe)
        simplify_pipe_sections(pipe, df_line, water_depth)
        df_simplified = check_line_structure(model, pipe)
        df_catenary = get_section_index(df_simplified, catenary_length * cat_factor)
        reassign_pipe_sections(pipe, df_catenary)
        set_pipe_length(pipe, catenary_length * cat_factor, df_catenary, mode="simplified")
        optimize_configuration(model, df_line, target_clearance, tolerance, mode="clearance", step_no=sens_name,
                               analysis_folder=analysis_folder, multithread=True, debug=debug)
        if rb_opening > 0:
            _support_pipe_on_rollerbox(model)
        model.SaveData(f"{analysis_folder}//{sens_name}.dat")
        return f"{sens_name} done"
    except Exception:
        with open(f"{analysis_folder}//ERROR.txt", "a") as f:
            f.write(f"{sens_name}\n{traceback.format_exc()}\n")
        return f"{sens_name} FAILED (see ERROR.txt)"


def generate_critical_step(ctx, ramp_angles, target_clearance=10.0, buoy_tol=0.0, wire_tol=0.0, cores=4):
    """Runs the critical step load case matrix in parallel worker processes."""
    lcm = build_lcm(ctx, ramp_angles, buoy_tol, wire_tol)
    log(f"Total number of cases to check: {len(lcm)} on {cores} cores")
    model_name, rb_settings = get_rb_settings(ctx, ctx.model_path)
    with ProcessPoolExecutor(max_workers=cores) as pool:
        futures = [
            pool.submit(run_critical_case, job, model_name, ctx.ramp_name, ctx.contents_density,
                        ctx.analysis_folder, target_clearance, rb_settings, ctx.debug)
            for job in lcm
        ]
        for n, future in enumerate(as_completed(futures), start=1):
            log(f"[{n}/{len(lcm)}] {future.result()}")
    return lcm
