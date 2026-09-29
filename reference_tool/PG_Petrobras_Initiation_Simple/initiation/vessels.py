"""Vessel database helpers (7Vega, 7Oceans, 7Navica)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ASSETS = Path(__file__).resolve().parent.parent / "assets"
VESSEL_DB = ASSETS / "vessel_database"

VESSELS = ("Vega", "Oceans", "Navica")
BASE_FILES = {
    "Vega": "_vegaBase_3.2.dat",
    "Oceans": "_oceansBase.dat",
    "Navica": "_navicaBase.dat",
}
HANG_OFF_OBJECT = {
    "Oceans": "Tensioner Lower End",
    "Navica": "Tensioner Exit",
    "Vega": "T2",
}


def vessel_name(vessel):
    """Normalise '7Vega', 'Vega', 'vega' -> 'Vega'."""
    name = str(vessel).strip()
    if name.startswith("7"):
        name = name[1:]
    for known in VESSELS:
        if name.lower() == known.lower():
            return known
    raise ValueError(f"Unknown vessel '{vessel}'. Choose one of: {', '.join('7' + v for v in VESSELS)}")


def vessel_folder(vessel):
    return VESSEL_DB / vessel_name(vessel).lower()


def vessel_coords(vessel):
    name = vessel_name(vessel)
    with open(vessel_folder(name) / f"{name.lower()}_coords.json") as f:
        return json.load(f)


def base_model_file(vessel):
    return vessel_folder(vessel) / BASE_FILES[vessel_name(vessel)]


def rollerbox_model_file(vessel):
    name = vessel_name(vessel)
    return vessel_folder(name) / f"_{name.lower()}RollerBox.dat"


def draughts(vessel):
    """Available draught (RAO type) names for the vessel."""
    return list(vessel_coords(vessel)["RAO Types"].keys())


def hang_off(vessel):
    """Returns (ramp object name, x, y, z) of the pipe hang-off on the vessel."""
    coords = vessel_coords(vessel)
    x, y, z = coords["Hang-off Locations"][HANG_OFF_OBJECT[vessel_name(vessel)]]
    return coords["Ramp"], float(x), float(y), float(z)


def pin_locations(vessel):
    """Standard ramp pin angles below vertical."""
    return [pin for pin in vessel_coords(vessel)["Pin Locations"] if pin < 90]


def payout_range(vessel):
    """Allowable payout increments during jack-down (PG-ENG-ST-007)."""
    start_payout = 6 if vessel_name(vessel) == "Vega" else 5
    return [start_payout] + list(range(10, 35, 5))


###########################################################################
#############   ROLLERBOX                        ##########################
###########################################################################

def _roller_db(vessel):
    """Rollerbox database CSV (columns: Roller_Openings, ERB6_Deg, ERB3_Deg).

    NOTE: in the original tool this lives on Google Drive as a Google Sheet
    (_vega_RB_DB.gsheet). Export it as CSV into the vessel folder as
    `_Vega_RB_DB.csv` (or `_Oceans_RB_DB.csv`) to enable the rollerbox.
    """
    name = vessel_name(vessel)
    for candidate in (f"_{name}_RB_DB.csv", f"_{name.lower()}_RB_DB.csv"):
        path = vessel_folder(name) / candidate
        if path.exists():
            return pd.read_csv(path)
    raise FileNotFoundError(
        f"Rollerbox database not found. Export the '_{name.lower()}_RB_DB' Google Sheet "
        f"as CSV to {vessel_folder(name) / f'_{name}_RB_DB.csv'}"
    )


def roller_coordinates(vessel, opening):
    """Rollerbox support coordinates for an opening (mm). None if the vessel has no rollerbox."""
    name = vessel_name(vessel)
    if name == "Vega":
        df_roller = pd.DataFrame(vessel_coords(name)["RollerBox"]).set_index("rollers")
        return _vega_roller_calcs(_roller_db(name), df_roller, opening)
    if name == "Oceans":
        return _oceans_roller_calcs(opening)
    return None


def _oceans_roller_calcs(opening):
    """Oceans roller box coordinates. Based on ref drawing A05-70400-13-308A."""
    roller_width = 0.4
    opening = opening / 1000
    b = 45
    a = 90
    A = np.sin(np.deg2rad(a)) * (1 / 2 * opening + 1 / 2 * roller_width) / np.sin(np.deg2rad(b))
    return pd.DataFrame({
        "Name": ["Coordinate system1", "Coordinate system1"],
        "X": [0, 0],
        "Y": [-A, A],
        "Z": [0.2275, -0.2275],
        "Azimuth": [90, 270],
        "Declination": [90, 90],
        "Gamma": [0, 0],
    })


def _vega_roller_calcs(db_roller, df_roller, opening):
    """Vega roller box coordinates. Based on the existing rollerbox settings excel sheet."""
    erb6_azimuth = np.interp(opening, db_roller["Roller_Openings"], db_roller["ERB6_Deg"])
    erb3_azimuth = np.interp(opening, db_roller["Roller_Openings"], db_roller["ERB3_Deg"])
    erb1_azimuth = -erb6_azimuth
    erb2_azimuth = 0.0
    erb4_azimuth = -erb3_azimuth
    erb5_azimuth = 0.0

    erb6_y = -(opening / 2 + df_roller.loc["top", "diameter"] * 1e3 / 2) / np.sin(np.deg2rad(erb6_azimuth)) / 1000
    erb3_y = (opening / 2 + df_roller.loc["top", "diameter"] * 1e3 / 2) / np.sin(np.deg2rad(erb3_azimuth)) / 1000
    erb2_y = ((opening / 2) + (df_roller.loc["center", "diameter"] * 1e3 / 2)) / 1000
    erb1_y = -erb6_y
    erb4_y = -erb3_y
    erb5_y = -erb2_y

    erb1_z = -0.54
    erb2_z = 0.00
    erb3_z = 0.54
    erb4_z = erb1_y
    erb5_z = erb2_y
    erb6_z = erb3_y

    return pd.DataFrame({
        "Name": ["ER1", "ER2", "ER3", "ER4", "ER5", "ER6"],
        "X": [0] * 6,
        "Y": [erb1_y, erb2_y, erb3_y, erb4_y, erb5_y, erb6_y],
        "Z": [erb1_z, erb2_z, erb3_z, erb4_z, erb5_z, erb6_z],
        "Azimuth": [erb1_azimuth, erb2_azimuth, erb3_azimuth, erb4_azimuth, erb5_azimuth, erb6_azimuth],
        "Declination": [90] * 6,
        "Gamma": [0] * 6,
    })
