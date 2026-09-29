"""
Version
=======
0.1.0, January 20, 2025
(Simple CLI version: added paths and vessel fallbacks at the end of this file.)
"""
import os

# dnv code checks
STRAIN_HARDENING_FACTOR = 0.93
OUT_OF_ROUNDNESS = 0.03
STRAIN_RESISTANCE_FACTOR = 2.0
GIRTH_WELD_FACTOR = 1.0
PLASTIC_MOMENT_REDUCTION = 1.0
SIMPLIFIED_STRAIN_LIMIT = 0

# initial steps
INITIAL_DEPLOY_PAYOUT = 20

# landing sequence
ORCAFLEX_DEFAULT_WIRE_LEN = 3e300
START_FINAL_APPROACH_DISTANCE = 10
FINAL_APPROACH_PAYOUT = 10
FINAL_PAYOUT = 100
CORRECTION_FACTOR = 1.1
DAMPING_CORRECTION_FACTOR = 1.1
WIRE_PAYOUT_NEAREST_VALUE = 5

# naming
BEAM_NAME = "A&R Spreader Beam"
PIPE_NAME = "Pipe1"
ANR_WIRE_1 = "Wire1"
ANR_WIRE_2 = "Wire2"
ANR_WIRE_3 = "Wire3"
RIGGING_NAME = "Rigging"
ANR_YOKE_NAME = "AR_YOKE"
BUOY_YOKE_NAME = "BUOY_YOKE"

# m/s^2
GRAVITY = 9.81

# density (g/cm^2, g/mL)
STEEL_DENSITY = 7.85
SEAWATER_DENSITY = 1.025

# line end connection orientation
END_A_AZIMUTH = 180
END_A_DECLINATION = 90
END_B_AZIMUTH = 180
END_B_DECLINATION = 90
LAY_AZIMUTH = 0

# remeshing parameters
TOP_SECTION_LEN = 50.0
TDP_SECTION_LEN = 100.0
BOTTOM_SECTION_LEN = 50.0
MIN_SEGMENT_LEN = 1.0
MAX_SEGMENT_LEN = 16
TARGET_NUMBER_OF_SEGMENT_PER_SECTION = 50
INTERVAL = 2

# ---- Simple CLI version additions ---- #
# Tool folder (parent of this package) and vessel database location
TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VESSEL_DB_DIR = os.path.join(TOOL_DIR, "assets", "vessel_database")
# Optional company lay table template (export of the Laytable_Template Google Sheet)
LAYTABLE_TEMPLATE = os.path.join(TOOL_DIR, "assets", "Laytable_Template.xlsx")

# Fallbacks when a vessel coords JSON does not define these keys
# (A&R wire line type names exist inside the vessel base .dat files; limits from the old GUI)
AR_WIRE_IDS = {
    "Vega": "A&R Wire",
    "Navica": "250Te winch wire",
    "Oceans": "119mm A&R wire (500Te winch)",
}
AR_WINCH_LIMITS = {"Vega": 600.0, "Oceans": 500.0, "Navica": 250.0}      # te
BOLLARD_PULL_LIMITS = {"Vega": 100.0, "Oceans": 120.0, "Navica": 102.0}  # te
