"""Load, validate and prepare the project input JSON.

The JSON format is the same one the Streamlit tool saved ("Save Data"), so existing
project files can be reused. `prepare` does the calculations the old "Save Data"
button did (PLET / buoyancy module hydrodynamics, fitting volumes, line totals).
"""
import copy
import json
from datetime import datetime
from pathlib import Path

from .catenary import find_catenary_starting_shape
from .hydro import plate_hydro, buoyancy_module_hydro
from .vessels import ASSETS

# Seawater densities used by the original tool for derived quantities
RHO_STRUCTURE = 1.027
RHO_BUOYANCY = 1.025

DEFAULT_CODE_CHECKS = {
    "lineTypeFactor": {"gamma_sc_lb": 1.04, "gamma_m": 1.15, "alpha_fab": 1.0, "alpha_gw": 1.0, "alpha_pm": 1.0},
    "lineTypeProperties": {"pMin": "~", "t2": "~", "fy": 450e3, "fu": 530e3, "E": 207000000,
                           "alpha_h": 0.93, "f0": 0.015, "simplifiedStrainLimit": 0.305},
    "craProperties": {"tCRA": 0.00, "fyCRA": 430e3, "fuCRA": 500e3},
}


def load_input(path):
    """Read and schema-validate the input JSON."""
    with open(path) as f:
        data = json.load(f)
    validate(data)
    return data


def validate(data):
    try:
        from jsonschema import validate as js_validate
    except ImportError:
        print("WARNING: jsonschema not installed, input file not validated.")
        return
    with open(ASSETS / "schema.json") as f:
        schema = json.load(f)
    js_validate(instance=data, schema=schema)


def prepare(data, ramp_estimate=85.6):
    """Compute derived input quantities. Returns (prepared data, list of warnings)."""
    data = copy.deepcopy(data)
    warnings = []

    # --- Line: fixed lengths for variable OD sections, totals ---
    line_types = {lt["lineTypeName"]: lt for lt in data["lineTypes"]}
    od_profiles = {p["profileName"]: p["profile"] for p in data["variableOD"]}
    for idx, seg in enumerate(data["lineData"]["lineSegments"]):
        lt = line_types.get(seg["sectionLineType"])
        if lt is None:
            raise ValueError(f"Line section {idx + 1} uses unknown line type '{seg['sectionLineType']}'")
        if isinstance(lt["outerDiameter"], str):
            fixed_len = max(od_profiles[lt["outerDiameter"]]["arcLength"])
            if seg["sectionLength"] != fixed_len:
                warnings.append(
                    f"Section {idx + 1} ({lt['lineTypeName']}) has variable OD, length fixed to {fixed_len}m"
                )
                seg["sectionLength"] = fixed_len
    data["lineData"]["numberOfLineSegments"] = len(data["lineData"]["lineSegments"])
    data["lineData"]["totalLength"] = sum(seg["sectionLength"] for seg in data["lineData"]["lineSegments"])

    # --- Wire axial stiffness from the named profile ---
    wire = data["wireType"]
    for profile in data["variableStiffness"]:
        if profile["profileName"] == wire["wireAxialStiffnessName"]:
            wire["wireAxialStiffness"] = copy.deepcopy(profile["profile"])
    for fitting in wire["fittings"]:
        fitting["volume"] = (fitting["mass"] - fitting["wiw"]) / RHO_BUOYANCY

    # --- PLET hydrodynamics ---
    s = data["structureData"]
    s["hydrodynamics"] = plate_hydro(
        s["length"], s["width"], s["height"],
        s["weightInAir"], s["weightInWater"],
        s["perforation"]["x"] / 100, s["perforation"]["y"] / 100, s["perforation"]["z"] / 100,
        RHO_STRUCTURE, s["cogX"], s["cogY"], s["cogZ"],
    )

    # --- Buoyancy module ---
    m = data["buoyancyData"]["moduleData"]
    m["moduleVolume"] = (m["moduleWIA"] - m["moduleWIW"]) / RHO_BUOYANCY
    m["hydrodynamics"] = buoyancy_module_hydro(m["moduleLength"], m["moduleWidth"], m["moduleHeight"])

    # --- Code check entries for every line type (defaults if missing) ---
    f101 = data["codeChecksData"]["f101"]
    for key, defaults in DEFAULT_CODE_CHECKS.items():
        names = [item["name"] for item in f101[key]]
        for lt_name in line_types:
            if lt_name not in names:
                f101[key].append({**defaults, "name": lt_name})
                warnings.append(f"No '{key}' code check data for '{lt_name}', defaults used")

    # --- Pipe length check against an estimated catenary length ---
    _, length_guess = find_catenary_starting_shape(data["environment"]["waterDepth"], -ramp_estimate)
    total = data["lineData"]["totalLength"]
    if total < length_guess:
        warnings.append(
            f"Total pipe length of {total:.1f}m seems short for {data['environment']['waterDepth']}m "
            f"water depth (estimated catenary {length_guess}m at {ramp_estimate}deg). Consider adding pipe length."
        )

    return data, warnings


def save_prepared(data, folder):
    """Write the prepared data to <folder>/output_data_<date>.json (as 'Save Data' did)."""
    iso_date = datetime.now().isoformat(timespec="hours").replace(":", "-")
    path = Path(folder) / f"output_data_{iso_date}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=4, default=float)
    return path
