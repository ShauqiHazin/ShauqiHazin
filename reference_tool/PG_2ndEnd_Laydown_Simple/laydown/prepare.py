"""Load, check and prepare the laydown project JSON.

Replaces what the old PyQt GUI did before calling the engine ("Save Data"):
derived values (ID from OD/WT, stress-joint OD, wings-up weights, ramp object name,
ramp-angle list, buoy numbering, ...) are recalculated and the inputs are checked
against the vessel database. The project file format is unchanged, so JSON files
saved by the GUI (e.g. examples/Yoke.json) can be used directly.

This module does not import OrcFxAPI (usable without an OrcaFlex licence).
"""
import copy
import json
import os

from .constants import VESSEL_DB_DIR

VESSELS = {"Seven Vega": "vega", "Seven Oceans": "oceans", "Seven Navica": "navica"}
CURRENT_OPTIONS = {
    "none": ("No Current", "noCurrent"),
    "inline": ("Current In Lay Dir. (0deg)", "InLineCurrent"),
    "against": ("Current Against Lay Dir. (180deg)", "AgainstCurrent"),
}
PLET_OPTIONS = ("Frame only", "Frame & Mudmat (No Wings)", "Frame & Mudmat (With Wings)")
DUAL_MODE = "Dual Mode (A&R Beam)"


class InputError(ValueError):
    """Raised when the project JSON cannot be used."""


def load(path):
    with open(path) as f:
        return json.load(f)


def vessel_coords(vessel_selected):
    """Vessel database entry for 'Seven Vega' / 'Seven Oceans' / 'Seven Navica'."""
    short = VESSELS[vessel_selected]
    with open(os.path.join(VESSEL_DB_DIR, short, f"{short}_coords.json")) as f:
        return json.load(f)


def _merge(base, overrides):
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _f(value, name):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise InputError(f"{name} must be a number (got {value!r})")


def prepare(data, current_option=None, overrides=None):
    """Returns (prepared copy of the project data, list of warnings). Raises InputError."""
    d = _merge(copy.deepcopy(data), overrides)
    warnings = []
    for block in ("General", "pipeGeneral", "SJGeneral", "vesselGeneral", "structureGeneral", "buoyGeneral", "sequenceGeneral"):
        if block not in d:
            raise InputError(f"Missing block '{block}' in the project JSON")
    gen, pipe, sj, ves = d["General"], d["pipeGeneral"], d["SJGeneral"], d["vesselGeneral"]
    struct, buoy, seq = d["structureGeneral"], d["buoyGeneral"], d["sequenceGeneral"]

    # ---- General / current ----
    if current_option is not None:
        if current_option not in CURRENT_OPTIONS:
            raise InputError(f"current option must be one of {list(CURRENT_OPTIONS)}")
        gen["CurrentOption"] = CURRENT_OPTIONS[current_option][0]
    if gen.get("CurrentOption") not in [v[0] for v in CURRENT_OPTIONS.values()]:
        raise InputError(f"General.CurrentOption '{gen.get('CurrentOption')}' not recognised")
    profile = gen.get("CurrentProfile") or {}
    if len(profile) < 2:
        raise InputError("General.CurrentProfile needs at least 2 levels")
    wd = _f(gen.get("WD"), "General.WD")
    seq["WD_Max"] = wd                   # GUI: WD_Max and pipeGeneral.WD follow General.WD
    pipe["WD"] = wd

    # ---- Pipe line type(s) ----
    for key in ("Pipe1", "Pipe2"):
        name = pipe.get(key)
        if not name or name == "null":
            continue
        lt = d.get(name)
        if not isinstance(lt, dict) or not lt:
            raise InputError(f"pipeGeneral.{key} = '{name}' but there is no '{name}' block")
        if lt.get("WT") not in (None, ""):
            lt["ID"] = round(max(_f(lt["OD"], f"{name}.OD") - 2 * _f(lt["WT"], f"{name}.WT"), 0.0), 3)
            lt["DNV_OD"] = round(_f(lt["OD"], f"{name}.OD"), 3)
            lt["Nominal_Thickness"] = round(_f(lt["WT"], f"{name}.WT"), 3)
        if "E" in lt:
            lt["DNV_E"] = lt["E"]
            lt["StressStrain_E"] = lt["E"]
    if pipe.get("PipeType") == "Pipe-in-Pipe":
        lt1 = d[pipe["Pipe1"]]
        if lt1.get("StressStrainRelationship") != "Linear":
            warnings.append("Pipe-in-Pipe: stress-strain relationship forced to Linear (as the GUI did)")
            lt1["StressStrainRelationship"] = "Linear"
    if pipe.get("Content") == "Empty":
        pipe["ContentDensity"] = 0

    # ---- Stress joint ----
    if sj.get("SJrequired") and sj.get("SJID") not in (None, "") and sj.get("SJWT") not in (None, ""):
        sj["SJOD"] = round(_f(sj["SJID"], "SJGeneral.SJID") + 2 * _f(sj["SJWT"], "SJGeneral.SJWT"), 3)
    if seq.get("Pipe_ClampSJ") and not sj.get("SJrequired"):
        warnings.append("sequenceGeneral.Pipe_ClampSJ ignored: no stress joint (SJrequired = false)")
        seq["Pipe_ClampSJ"] = False

    # ---- Structure ----
    opt = struct.get("PLETModellingOpt")
    if opt not in PLET_OPTIONS:
        raise InputError(f"structureGeneral.PLETModellingOpt must be one of {PLET_OPTIONS}")
    struct["Mudmat_WingsInc"] = opt == "Frame & Mudmat (With Wings)"
    if opt != "Frame only":
        struct["Frame_AirWeight_WingUp"] = round(_f(struct["Frame_AirWeight"], "Frame_AirWeight")
                                                 + _f(struct["Mudmat_AirWeight_WingDown"], "Mudmat_AirWeight_WingDown"), 2)
        struct["Frame_SubWeight_WingUp"] = round(_f(struct["Frame_SubWeight"], "Frame_SubWeight")
                                                 + _f(struct["Mudmat_SubWeight_WingDown"], "Mudmat_SubWeight_WingDown"), 2)
        struct["Mudmat_FrameConnY"] = 0.0
        struct["Mudmat_FrameConnZ"] = -0.5 * _f(struct["Frame_Height"], "Frame_Height") \
            - 0.5 * _f(struct["Mudmat_Height_WingDown"], "Mudmat_Height_WingDown")
    for key in ("Frame_Perfor_X", "Frame_Perfor_Y", "Frame_Perfor_Z"):
        if not 0.0 <= _f(struct.get(key, 0), key) <= 1.0:
            raise InputError(f"structureGeneral.{key} is a ratio (0 to 1)")
    for i, row in enumerate(struct.get("AR_YokeStiffnessTable") or [], start=1):
        row["StiffnessRow"] = i
    struct["AR_YokeStiffnessRows"] = len(struct.get("AR_YokeStiffnessTable") or [])

    # ---- Vessel ----
    vessel = ves.get("VesselSelected")
    if vessel not in VESSELS:
        raise InputError(f"vesselGeneral.VesselSelected must be one of {list(VESSELS)} (got {vessel!r})")
    coords = vessel_coords(vessel)
    ves["VesselRamp"] = coords["Ramp"]
    rao = ves.get("RAOSelected")
    if rao not in coords["RAO Types"]:
        raise InputError(f"RAOSelected '{rao}' not available for {vessel}: {list(coords['RAO Types'])}")
    if ves.get("DraughtSelected") not in coords["RAO Types"][rao]:
        ves["DraughtSelected"] = coords["RAO Types"][rao][0]
        warnings.append(f"DraughtSelected set to '{ves['DraughtSelected']}' (the draught listed for {rao})")
    if ves.get("PipeHangOff") not in coords["Hang-off Locations"]:
        raise InputError(f"PipeHangOff '{ves.get('PipeHangOff')}' not in {list(coords['Hang-off Locations'])}")
    mode = ves.get("AR_Mode", "Single Mode")
    if str(mode).startswith("Dual Mode"):
        if vessel != "Seven Vega":
            raise InputError("Dual Mode (A&R beam) is only available for Seven Vega")
        ves["AR_Mode"] = DUAL_MODE
    elif mode == "Single Mode":
        if ves.get("AR_Hangoff") not in coords["A&R Sheaves"]:
            raise InputError(f"AR_Hangoff '{ves.get('AR_Hangoff')}' not in {list(coords['A&R Sheaves'])}")
    else:
        raise InputError("vesselGeneral.AR_Mode must be 'Single Mode' or 'Dual Mode (A&R Beam)'")

    pins = [float(p) for p in coords["Pin Locations"]]
    if ves["AR_Mode"] == DUAL_MODE:
        pins = [p for p in pins if p >= 59]
    angles = sorted(set(pins) | {float(a) for a in (ves.get("RampAngleRange") or []) if float(a) < 100})
    if not ves.get("CustomRampAngle"):
        angles = pins
    ves["RampAngleRange"] = angles
    selected = _f(ves.get("SelectedRampAngle"), "SelectedRampAngle")
    if selected not in angles:
        raise InputError(f"SelectedRampAngle {selected} is not in the ramp angle list {angles} "
                         "(use a vessel pin, or CustomRampAngle for Seven Vega)")
    if ves.get("UseMinRampAngle"):
        min_ra = _f(ves.get("MinRampAngle"), "MinRampAngle")
        if min_ra > selected:
            raise InputError(f"MinRampAngle {min_ra} is above SelectedRampAngle {selected}")
    if seq.get("SameRampAngleClamped"):
        seq["PalletStepRampAngle"] = ves["SelectedRampAngle"]
    _f(seq.get("PalletStepRampAngle"), "PalletStepRampAngle")

    # ---- Buoyancy ----
    table = buoy.get("BuoyTable") or []
    for i, row in enumerate(table, start=1):
        row["BuoyID"] = i
        for key in ("BuoyUplift", "BuoyWeight", "BuoyLength", "SlingOD", "SlingLength", "SlingMass"):
            row[key] = _f(row.get(key), f"BuoyTable[{i}].{key}")
    buoy["BuoyancyModuleQuantity"] = len(table)
    if buoy.get("UseBuoyancy") and not table:
        raise InputError("buoyGeneral.UseBuoyancy is true but BuoyTable is empty")
    if buoy.get("ConnectionType") not in ("Yoke", "Running Wire"):
        raise InputError("buoyGeneral.ConnectionType must be 'Yoke' or 'Running Wire'")
    for i, row in enumerate(buoy.get("BuoyYokeStiffnessTable") or [], start=1):
        row["StiffnessRow"] = i
    buoy["BuoyYokeStiffnessRows"] = len(buoy.get("BuoyYokeStiffnessTable") or [])

    # ---- Sequence ----
    seq["MaxPayoutRate"] = _f(seq.get("MaxPayoutRate"), "MaxPayoutRate")
    if seq.get("DeploymentSequenceOption") not in ("Fixed Ramp Angle", "Jack Down at Limit(s)"):
        raise InputError("sequenceGeneral.DeploymentSequenceOption must be 'Fixed Ramp Angle' or 'Jack Down at Limit(s)'")
    return d, warnings


def write_job_json(data, path):
    """Writes the prepared project JSON; jobID / jobDirectory follow the file (they name the outputs)."""
    path = os.path.abspath(path)
    data = copy.deepcopy(data)
    data["General"]["jobID"] = os.path.basename(path)
    data["General"]["jobDirectory"] = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    return path
