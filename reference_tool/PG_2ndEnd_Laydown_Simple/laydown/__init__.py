"""PG 2nd End Laydown Tool (simplified, no GUI).

Engine modules (unchanged logic from the PyQt tool, small fixes marked "Simple CLI"):
    a_buildSequence     main_LD(): base models, steps 00-03, buoy steps, laydown sequence, Excel output
    b_builderFunctions  OrcaFlex object builders (line types, PLET/mudmat, A&R wire/yoke, buoy yoke/bridle, catenary)
    c_sequenceFunctions solvers (zero wire lift, pallet pipe lift), payout logic, jack-down, landing/slackening loops
    d_extractFunctions  static result extraction, formatted lay table, re-extraction
    constants, utils    shared constants / helpers
New:
    prepare             checks the project JSON and recalculates the values the GUI used to derive

Only `prepare` can be imported without OrcaFlex; the engine modules import OrcFxAPI.
"""
