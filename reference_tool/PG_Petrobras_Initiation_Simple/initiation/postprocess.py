"""Post-processing of static step models: lay table, engineering results and snapshots."""
import re
from pathlib import Path
from random import uniform

import numpy as np
import pandas as pd
import OrcFxAPI as of

from .vessels import ASSETS

LAYTABLE_COLS = [
    'Pipe Payout',
    'Total Pipe Paid Out',
    'Horizontal Projected Length',
    'Vertical Projected Length',
    'Vessel Move',
    'Vessel Position',
    'Total Layback',
    'Total Catenary Length',
    'Receptacle Clearance',
    'plet Depth',
    'plet Angle Relative to Horizontal',
    'Top Tension',
    'Horizontal Top Tension',
    'Wire Tension',
    'Ramp Angle',
    'Max Von Mises Stress',
]
ENG_COLS = [
    "LCC Hang Off",
    "LCC Sagbend",
    "LCC Achor Flange",
    "Strain",
    "Top Tension",
    "Top Moment",
    "Horizontal Top Tension",
    "Wire Tension",
    "Targetbox Utilisation",
    "Front Stopper Contact Force",
    "Back Stopper Contact Force",
    "Rollerbox Load"
]

# Default acceptance criteria. None = criterion turned off.
DEFAULT_CRITERIA = {
    # Pipe capacities
    "Hang-Off LCC": 0.7,
    "Sag Bend LCC": 0.7,
    "Structure Interface LCC": 0.7,
    "Strain (%)": 0.15,
    # Vessel capacities
    "Top Tension (Te)": 600.0,
    "Bollard Pull (Te)": 50.0,
    "Rollerbox Load (Te)": None,
    "Layback (m)": 1200.0,
    # Initiation system
    "Target Box Static Utilisation (%)": 70.0,
    "Wire Tension (Te)": 150.0,
}

TEMPLATE = ASSETS / "PetrobrasInitiation_Laytable_Template.xlsx"


def get_criteria(criteria=None):
    """Limits aligned with the full-results and engineering-results columns ('-' = not checked)."""
    c = {**DEFAULT_CRITERIA, **(criteria or {})}
    lim = {k: ("-" if v is None else v) for k, v in c.items()}
    full_lim = ["-", "-", "-", "-", "-", "-", lim["Layback (m)"], "-", "-", "-", "-",
                lim["Top Tension (Te)"], lim["Bollard Pull (Te)"], lim["Wire Tension (Te)"], "-", "-",
                lim["Hang-Off LCC"], lim["Sag Bend LCC"], lim["Structure Interface LCC"], lim["Strain (%)"], "-",
                lim["Target Box Static Utilisation (%)"], "-", "-", lim["Rollerbox Load (Te)"]]
    eng_lim = [lim["Hang-Off LCC"], lim["Sag Bend LCC"], lim["Structure Interface LCC"], lim["Strain (%)"],
               lim["Top Tension (Te)"], "-", lim["Bollard Pull (Te)"], lim["Wire Tension (Te)"],
               lim["Target Box Static Utilisation (%)"], "-", "-", lim["Rollerbox Load (Te)"]]
    return full_lim, eng_lim


def post_process(model, step=12345, prev_vals=(None, None)):
    """Extracts lay table and engineering results from one static step model.

    Returns ((df_full, df_lay, df_eng), (pipe_length, vessel_x)).
    """
    step = f"{step:03d}" if type(step) != str else step
    if model is None:
        laytable_vals = [None] * len(LAYTABLE_COLS)
        eng_vals = [None] * len(ENG_COLS)
        pipe_length = None
        vessel_x = None
    else:
        line = model["RigidPipe"]
        wire = model["Initiation"]
        plet = model["PLET_Properties"]
        trunnion = model["TrunnionMain"]
        trunnion_sec = model["TrunnionSecondary"]
        trunnion_lt = model["trunnionLT"]
        for obj in model.objects:
            if "Ramp" in obj.name:
                ramp = obj
        target = model["SIP_Pile"]
        receptacle = model["SIP_Receptacle_Bottom_Solid#1"]
        front_wall = model["SIP_Receptacle_FrontWall#1"]
        back_wall = model["SIP_Receptacle_BackWall#1"]
        rigging_plet = model["rigging_plet"]
        rigging_sip = model["rigging_SIP"]
        code_checks = model["Code checks"]
        rollerbox = None
        for obj in model.objects:
            if obj.type == of.otVessel:
                vessel = obj
            if obj.type == of.ot6DBuoy and "_RB" in obj.Name:
                rollerbox = obj

        # --- Run static analysis ---
        while True:
            try:
                model.CalculateStatics()
                break
            except Exception:
                model["General"].StaticsMaxIterations = 2000
                model["General"].StaticsMinDamping = uniform(3, 15)
                model["General"].StaticsMaxDamping = uniform(20, 30)

        prev_pipe_length, prev_vessel_x = prev_vals
        pipe_length = line.CumulativeLength[-1]
        pipe_payout = pipe_length - prev_pipe_length if prev_pipe_length is not None else pipe_length

        # --- Vessel position & ramp angle ---
        vessel_x = ramp.StaticResult("X") - target.StaticResult("X")
        ramp_angle = abs(round(ramp.InitialRotation2, 1))
        vessel_move = vessel_x - prev_vessel_x if prev_vessel_x is not None else 0

        # --- Projected length ---
        pipe_x = line.StaticResult("X", of.oeEndA) - line.StaticResult("X", of.oeEndB)
        pipe_z = line.StaticResult("Z", of.oeEndA) - line.StaticResult("Z", of.oeEndB)

        # --- Layback and catenary length ---
        wire_axial_strain = wire.RangeGraph("Total Mean Axial Strain", of.pnStaticState).Mean
        wire_nodes = wire.RangeGraph("X", of.pnStaticState).X
        wire_element_length = wire_nodes[1:] - wire_nodes[:-1]
        wire_stretch = np.sum(np.asarray([l * (1 + s / 100) for l, s in zip(wire_element_length, wire_axial_strain)]))

        INVALID = 3e+307  # OrcaFlex sentinel for unavailable values
        touchdown_pipe = line.StaticResult("X", of.oeTouchdown)
        touchdown_wire = wire.StaticResult("X", of.oeTouchdown)
        if rigging_plet.EndAConnection == "PLET_Properties":
            if touchdown_pipe < INVALID:
                touchdown_value = touchdown_pipe
                catenary = line.StaticResult("Arc Length", of.oeTouchdown)
            elif touchdown_wire < INVALID:
                touchdown_value = touchdown_wire
                catenary = wire.StaticResult("Arc Length", of.oeTouchdown) + line.StaticResult("Arc Length", of.oeEndB)
            else:
                catenary = wire_stretch + line.CumulativeLength[-1] + rigging_plet.UnstretchedLength + rigging_sip.UnstretchedLength
                touchdown_value = None
            if touchdown_value is not None:
                layback = line.StaticResult("X", of.oeEndA) - touchdown_value
            else:
                layback = line.StaticResult("X", of.oeEndA) - rigging_sip.StaticResult("End B X")
        else:
            catenary = 0
            layback = 0

        # --- PLET clearance, depth, angle ---
        plet_depth = round(abs(trunnion.StaticResult("Z", of.oeEndA)) + trunnion_lt.OuterContactDiameter / 2, 0)
        clearance = round(abs(receptacle.StaticResult("Z")) - receptacle.SizeZ - plet_depth, 0)
        declination = round(plet.StaticResult("Declination"))

        # --- Tension, stress and strain ---
        top_tension = line.StaticResult("Effective Tension", of.oeEndA) / 9.81  # Te
        top_moment = line.StaticResult("Bend Moment", of.oeEndA)
        top_horizontal_tension = abs(vessel.StaticResult("Connections Gx force")) / 9.81  # Te
        wire_tension = wire.RangeGraph("Effective Tension").Mean.max() / 9.81  # Te
        wire_tension = wire_tension if wire_tension < 500 else 0
        vm_stress = line.RangeGraph("Max Bending Stress").Mean.max() / 1000  # MPa
        strain = max(line.RangeGraph("Max Bending Strain", of.pnStaticState).Mean, key=abs)

        # --- DNV-ST-F101 load controlled condition, worst of case A and case B ---
        sagbend_range = of.arSpecifiedArclengths(1.0, line.CumulativeLength[-1])
        model.CalculateStatics()
        lcc_hang_off, lcc_sagbend, lcc_anchor_flange = [], [], []
        for gamma_f, gamma_e in ((1.2, 0.7), (1.1, 1.3)):
            code_checks.DNVSTF101GammaF = gamma_f
            code_checks.DNVSTF101GammaE = gamma_e
            lcc_hang_off.append(line.StaticResult("DNV ST F101 load controlled", of.oeEndA))
            lcc_sagbend.append(line.RangeGraph("DNV ST F101 load controlled", of.pnStaticState, arclengthRange=sagbend_range).Mean.max())
            lcc_anchor_flange.append(line.StaticResult("DNV ST F101 load controlled", of.oeEndB))
        lcc_hang_off = max(lcc_hang_off)
        lcc_sagbend = max(lcc_sagbend)
        lcc_anchor_flange = max(lcc_anchor_flange)

        # --- Target box utilisation: trunnion clearance to stoppers over 50% of receptacle size ---
        if clearance == 0:
            main_trunnion_x = trunnion.StaticResult("X", of.oeEndA)
            sec_trunnion_x = trunnion_sec.StaticResult("X", of.oeEndA)
            front_wall_x = front_wall.StaticResult("X")
            back_wall_x = back_wall.StaticResult("X")
            box_size = abs(front_wall_x - back_wall_x)
            front_clr = abs((main_trunnion_x - trunnion_lt.OuterContactDiameter / 2) - front_wall_x)
            back_clr = abs(back_wall_x - (sec_trunnion_x + trunnion_lt.OuterContactDiameter / 2))
            targetbox_util = (1 - min(front_clr / (box_size / 2), back_clr / (box_size / 2))) * 100
        else:
            targetbox_util = None

        force_front_wall = front_wall.StaticResult("Contact Force") / 9.81
        force_back_wall = back_wall.StaticResult("Contact Force") / 9.81
        force_rollerbox = rollerbox.StaticResult("Supports Force") / 9.81 if rollerbox is not None else 0.0

        laytable_vals = [pipe_payout, pipe_length, pipe_x, pipe_z, vessel_move, vessel_x, layback, catenary,
                         clearance, plet_depth, declination, top_tension, top_horizontal_tension, wire_tension,
                         ramp_angle, vm_stress]
        eng_vals = [lcc_hang_off, lcc_sagbend, lcc_anchor_flange, strain, top_tension, top_moment,
                    top_horizontal_tension, wire_tension, targetbox_util, force_front_wall, force_back_wall,
                    force_rollerbox]

    df_lay = pd.DataFrame([laytable_vals], columns=LAYTABLE_COLS, index=[step])
    df_eng = pd.DataFrame([eng_vals], columns=ENG_COLS, index=[step])
    common_cols = list(set(LAYTABLE_COLS) & set(ENG_COLS))
    df_full = df_lay.merge(df_eng.drop(columns=common_cols), how="left", left_index=True, right_index=True)
    return (df_full, df_lay, df_eng), (pipe_length, vessel_x)


def get_job_data(model, df_full):
    """(operation, pipeline name, water depth, ramp angle range, contents) for the lay table header."""
    comments = model["General"].Comments
    found = re.findall(r"Pipeline:(.*)", comments)
    pipeline_name = found[0].strip() if found else ""
    water_depth = model["Environment"].WaterDepth
    ramp_angles = pd.to_numeric(df_full['Ramp Angle'], errors='coerce').dropna()
    ramp_angles = f"{min(ramp_angles)} to {max(ramp_angles)}" if min(ramp_angles) != max(ramp_angles) else ramp_angles.iloc[0]
    contents_density = "Empty" if model["RigidPipe"].ContentsDensity == 0 else "Flooded"
    return ("1st End PLET Initiation", pipeline_name, water_depth, ramp_angles, contents_density)


def _step_number(path):
    return int(re.findall(r'\d+', Path(path).name)[0])


def extract_results(files, out_folder, criteria=None):
    """Extracts results from static step files and writes one results workbook per current direction.

    Files are grouped by current direction ('inLine', 'None', 'against' in the file name).
    Full sequence files are sorted by step number; missing leading steps are left blank.
    Returns the list of written files.
    """
    files = [str(f) for f in files]
    if not files:
        raise ValueError("No static step files to post-process.")
    mode = "critical" if "critical" in Path(files[0]).name else "full"
    written = []
    for key in ("against", "None", "inLine"):
        static_files = [f for f in files if key in Path(f).name]
        if not static_files:
            continue
        if mode == "full":
            static_files = sorted(static_files, key=_step_number)
        print(f"Extracting results for current direction: {key}", flush=True)
        first_step = _step_number(static_files[0]) if mode == "full" else 1
        prev_info = (None, None)
        df_full, df_lay, df_eng = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        for i in range(1, first_step):
            dfs, prev_info = post_process(None, i)
            df_full = pd.concat([df_full, dfs[0]])
            df_lay = pd.concat([df_lay, dfs[1]])
            df_eng = pd.concat([df_eng, dfs[2]])

        for file in static_files:
            step = _step_number(file) if mode == "full" else Path(file).stem
            print(f"  step {step}...", flush=True)
            model = of.Model(file)
            dfs, prev_info = post_process(model, step, prev_info)
            df_full = pd.concat([df_full, dfs[0]])
            df_lay = pd.concat([df_lay, dfs[1]])
            df_eng = pd.concat([df_eng, dfs[2]])

        full_lim, eng_lim = get_criteria(criteria)
        df_full = pd.concat([pd.DataFrame([full_lim], columns=df_full.columns, index=["limit"]), df_full])
        df_eng = pd.concat([pd.DataFrame([eng_lim], columns=df_eng.columns, index=["limit"]), df_eng])
        job_data = get_job_data(model, df_full)
        written.append(_write_results(out_folder, key, df_full, df_lay, df_eng, job_data))
    return written


def _write_results(out_folder, key, df_full, df_lay, df_eng, job_data):
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        base = Path(out_folder) / f"Statics_Results_{key}"
        df_full.to_csv(f"{base}_Full.csv")
        df_lay.to_csv(f"{base}_LayTable.csv")
        df_eng.to_csv(f"{base}_Engineering.csv")
        print("  openpyxl not installed, results written as CSV.", flush=True)
        return f"{base}_*.csv"

    dst = Path(out_folder) / f"Statics_Results_{key}.xlsx"
    if TEMPLATE.exists():
        _write_template(dst, df_full, df_lay, df_eng, job_data)
    else:
        labels = ["Operation", "Pipeline", "Water Depth (m)", "Ramp Angle (deg)", "Contents"]
        with pd.ExcelWriter(dst, engine="openpyxl") as writer:
            pd.DataFrame({"Item": labels, "Value": job_data}).to_excel(writer, sheet_name="Job Data", index=False)
            df_full.to_excel(writer, sheet_name="Full Results")
            df_lay.to_excel(writer, sheet_name="InitiationLayTable")
            df_eng.to_excel(writer, sheet_name="Engineering Results")
    return str(dst)


def _write_template(dst, df_full, df_lay, df_eng, job_data):
    """Fills the company lay table template (same layout as the original tool)."""
    import shutil
    from openpyxl.styles import Border, Side, Alignment

    shutil.copyfile(TEMPLATE, dst)
    writer = pd.ExcelWriter(dst, mode="a", engine="openpyxl", if_sheet_exists="overlay")
    df_full.to_excel(writer, sheet_name="Full Results", startrow=4, startcol=0, index=True, header=False)
    df_lay.to_excel(writer, sheet_name="InitiationLayTable", startrow=11, startcol=0, index=True, header=False)
    df_eng.to_excel(writer, sheet_name="Engineering Results", startrow=4, startcol=0, index=True, header=False)
    wb = writer.book
    thin = Side(style='thin')
    thick = Side(style='thick')
    white = Side(style='thick', color="FFFFFF")
    border_fmt = Border(left=thin, right=thin, top=thin, bottom=thin)
    border_first = Border(left=thick, right=white, top=thick, bottom=thick)
    border_intermediate = Border(left=white, right=white, top=thick, bottom=thick)
    border_last = Border(left=white, right=thick, top=thick, bottom=thick)
    for df, sheet_name in zip([df_full, df_lay, df_eng], ["Full Results", "InitiationLayTable", "Engineering Results"]):
        sheet = wb[sheet_name]
        start_row = 12 if sheet_name == "InitiationLayTable" else 5
        if sheet_name == "InitiationLayTable":
            for r, value in enumerate(job_data, start=1):
                sheet.cell(row=r, column=3).value = value
        n_cols = len(df.columns) + 1
        for i in range(start_row, start_row + len(df)):
            for j in range(1, n_cols + 1):
                sheet.cell(row=i, column=j).border = border_fmt
        # Notes row
        i = start_row + len(df)
        for j in range(1, n_cols + 1):
            cell = sheet.cell(row=i, column=j)
            if j == 1:
                cell.value = "Put your notes here"
                cell.border = border_first
                cell.alignment = Alignment(horizontal='left')
            elif j == n_cols:
                cell.border = border_last
            else:
                cell.border = border_intermediate
    writer.close()


def generate_snapshots(files, out_folder):
    """Combines all static step files into one model: <out>/Steps/snapshots.dat and .sim."""
    files = [str(f) for f in files]
    if not files:
        raise ValueError("No static step files for snapshots.")
    if "Step" in Path(files[0]).name:
        try:
            files = sorted(files, key=_step_number)
        except Exception:
            pass

    datanames = [
        'EndAConnection', 'EndBConnection', 'Connection',
        'EndAX', 'EndAY', 'EndAZ', 'EndBX', 'EndBY', 'EndBZ',
        'EndAAzimuth', 'EndADeclination', 'EndAGamma',
        'EndBAzimuth', 'EndBDeclination', 'EndBGamma',
        'InitialX', 'InitialY', 'InitialZ',
        'InitialRotation1', 'InitialRotation2', 'InitialRotation3',
        'OriginX', 'OriginY', 'OriginZ', 'Azimuth', 'Declination',
        'InitialAzimuth', 'InitialDeclination', 'InitialGamma'
    ]
    snapshot_folder = Path(out_folder) / "Steps"
    snapshot_folder.mkdir(parents=True, exist_ok=True)
    print(f"Copying {Path(files[0]).name}...", flush=True)
    base = of.Model(files[0])
    base["General"].StaticsMinDamping = 1
    base["General"].StaticsMaxDamping = 10
    base["General"].StaticsTolerance = 0.1

    for i, file in enumerate(files[1:], start=1):
        print(f"Copying {Path(file).name}...", flush=True)
        model = of.Model(file)
        model["General"].StaticsMinDamping = 3
        model["General"].StaticsMaxDamping = 14
        while True:
            try:
                model.CalculateStatics()
                try:
                    model.UseCalculatedPositions(SetLinesToUserSpecifiedStartingShape=True)
                except Exception:
                    model.UseCalculatedPositions(setLinesToUserSpecifiedStartingShape=True)
                break
            except Exception:
                model["General"].StaticsMinDamping = uniform(3, 9)
                model["General"].StaticsMaxDamping = uniform(11, 20)
                model["General"].StaticsMaxIterations = 1500

        # Rename and copy each object into the snapshot model
        step = i + 1
        for obj in model.objects:
            try:
                obj.Name = f'{obj.Name}_Step{step}'
                obj.CreateClone(obj.Name, base)
            except Exception:
                continue
        # Then copy the connection data for each object
        for obj in model.objects:
            for data in datanames:
                try:
                    base[obj.Name].SetData(data, 0, obj.GetData(data, 0))
                except Exception:
                    continue
        base.SaveData(str(snapshot_folder / "snapshots.dat"))

    print("Saving .sim file...", flush=True)
    base.CalculateStatics()
    base.SaveSimulation(str(snapshot_folder / "snapshots.sim"))
    return snapshot_folder / "snapshots.sim"
