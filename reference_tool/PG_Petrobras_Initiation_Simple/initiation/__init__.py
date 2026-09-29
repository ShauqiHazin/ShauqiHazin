"""Petrobras Initiation Tool (simplified, no Streamlit).

Modules
-------
inputs       : load / validate / prepare the project input JSON
hydro        : hydrodynamic calculations for the PLET and buoyancy module
vessels      : vessel database helpers (hang-off, draughts, pins, rollerbox)
base_model   : build the OrcaFlex base model from the input JSON
statics      : static step generation (full sequence and critical step screening)
postprocess  : lay table / engineering results extraction and snapshots
catenary     : catenary starting shape estimate
"""
