# PG Petrobras Initiation Tool (Simple) - User Guide

Command-line version of the PG Petrobras Initiation Tool. It automates the OrcaFlex
static analysis of a **1st-end PLET initiation** onto a suction pile (SIP) receptacle:
the PLET is lowered with a buoyancy module on a yoke, connected to the SIP with an
initiation (bungee) wire, and landed in the receptacle while the vessel jacks the ramp
down to the normal-lay angle.

The tool does three things:

1. **Build** an OrcaFlex base model from a project JSON file.
2. **Generate static steps**, either the full installation sequence (lay table) or a
   critical-step sensitivity study.
3. **Post-process** the step models into a lay table and engineering results workbook.

There is no user interface: all inputs live in two JSON files and each stage is one command.

## 1. How the tool works

The flowchart on the next page shows the complete flow. In short:

| Stage | Command | What happens | Main output |
|---|---|---|---|
| Build | `run.bat build` | Reads and checks `input_data.json`, calculates PLET and buoyancy-module hydrodynamics, builds the OrcaFlex model on the selected vessel template | `<Project>_<Pipe>_<Vessel>_Base_RevX.dat` |
| Full sequence | `run.bat full` | Optional landing check at the chosen ramp angle, then every installation step from vertical payout to the pipe on the seabed | `Statics_StepNNN_current-X.dat` |
| Critical step | `run.bat critical` | Solves the "PLET close to the receptacle" step for every combination of buoyancy, wire length, ramp angle, rollerbox opening and current, in parallel | `critical_*.dat` |
| Results | `run.bat results` | Re-runs statics on each step file and extracts lay table and code-check results, compared with the acceptance criteria | `Statics_Results_<current>.xlsx` |
| Snapshots | `run.bat snapshots` | Combines all step models into one model for visual review | `Steps/snapshots.sim` |

Between **build** and **statics**, open the base model in OrcaFlex, check it and optimise
the element (segment) lengths. The statics commands use the newest
`*_Base_Rev*.dat` in the analysis folder unless `base_model` is set in `settings.json`.

<!-- figure: flowchart_overview.pdf | Figure 1 - Tool flowchart (also in docs/flowchart_overview.png / .svg) -->

## 2. Quick start

1. Install a **full, licensed OrcaFlex** on the PC. The OrcaFlex Demo cannot be driven
   from Python because it does not include `OrcFxAPI.dll`.
2. Copy or open the tool folder and run `run.bat info`. The first run creates a Python
   virtual environment (`venv`) and installs `requirements.txt`.
3. Put the project data in `input_data.json` (same format as the "Save Data" file of the
   old Streamlit tool, so old project files can be reused).
4. Edit `settings.json`: vessel, draught, analysis folder, statics options and criteria.
5. Run `run.bat build`, then open the base model in OrcaFlex and optimise the segment lengths.
6. Run `run.bat full` (lay table) or `run.bat critical` (sensitivity).
7. Run `run.bat results` (or `run.bat results --critical`) and review the Excel workbook.
8. Optionally run `run.bat snapshots` and open `Steps/snapshots.sim` to review all steps.

Every command prints its progress in the console. Optimisation logs
(`stepNNN_optimization.log`) and error logs (`*error.log`) are written to the analysis folder.

## 3. Inputs

### input_data.json (project data)

| Section | Content |
|---|---|
| `general` | Client, project, pipeline, revision, job name, comments (written into the model comments) |
| `environment` | Water depth or seabed profile, seawater density, current profile, seabed stiffness |
| `lineTypes`, `variableOD` | Pipe line types (OD/WT/coatings, stress-strain: linear, Ramberg-Osgood or tabular) and variable-OD profiles |
| `lineData` | Pipe sections from the vessel to the PLET (line type, length) |
| `wireType`, `variableStiffness` | Initiation (bungee) wire, axial stiffness profile, rigging fittings and make-up |
| `structureData`, `sipData` | PLET weight, envelope, CoG, trunnions, perforation, connection points; SIP pile and receptacle geometry |
| `buoyancyData` | Yoke and buoyancy module (weights, dimensions, rigging length and stiffness) |
| `codeChecksData` | DNV-ST-F101 load factors, line-type factors, material and CRA properties |

The PLET hydrodynamics, buoyancy-module volume and hydrodynamics, fitting volumes and
line totals are recalculated from the geometry on every `build`.

### settings.json (run options)

| Key | Meaning |
|---|---|
| `vessel`, `draught` | `7Vega`, `7Oceans` or `7Navica`; RAO/draught name (`run.bat info` lists them) |
| `analysis_folder` | Where all outputs are written |
| `statics.contents_density`, `include_current` | Pipe contents (null = value in model); also run in-line and against-lay current |
| `statics.brake_mode` | 7Vega only: 1 deg ramp increments / non-standard landing angle |
| `statics.use_rollerbox`, `rollerbox_openings_mm` | Add the vessel rollerbox model and its opening(s) |
| `full_sequence.*` | Landing ramp angle, maximum payout per jack-down, upfront ramp check, automatic ramp selection |
| `critical_step.*` | Ramp-angle range, clearance target, buoyancy and wire-length tolerances, number of cores |
| `criteria` | Acceptance limits (null = not checked): LCC at hang-off / sagbend / structure, strain, top tension, bollard pull, rollerbox load, layback, target-box utilisation, wire tension |

<!-- pagebreak -->

## 4. Analysis logic

### Full sequence (`run.bat full`)

| Step | Configuration | How it is solved |
|---|---|---|
| Landing check (316) | Secondary trunnion in the receptacle at the selected ramp angle | `optimize_configuration` in contact mode, results checked against the criteria |
| 3 | Main trunnion 30 m below the surface, ramp vertical | Payout found with `fsolve` for the target depth |
| 4 | Buoyancy module 10 m below the surface (saved with and without buoyancy) | Payout for the target depth |
| Vega only | First jack-down to 90 deg with 3 m payout | Direct |
| Aux | Payout to install variable-OD sections (e.g. TRF) | Payout, vessel moved for zero hang-off moment when the PLET is near the seabed |
| 5 | Trunnion 10 m above the receptacle, SIP rigging connected | Payout for the target depth |
| 6 | Vessel moves to build layback | Vessel X for a 100 m minimum wire bend radius |
| 7+ | Jack down through each ramp angle keeping 8-10 m trunnion clearance | `optimize_configuration`; an extra payout step is inserted when the payout exceeds the allowed maximum |
| No-stop zone | 5 m clearance, main trunnion landing, 5 m pipe on seabed (or secondary trunnion landing), 20 m pipe on seabed | `optimize_configuration` in clearance, contact and touchdown modes |

Each step is solved on a simplified pipe (4 sections) and then re-assigned to the real
pipe make-up before it is stabilised and saved.

### Critical step (`run.bat critical`)

Builds a load-case matrix from buoyancy uplift and wire length (with +/- tolerance), ramp
angles in the chosen range, rollerbox openings and current directions. Each case is solved
in its own process to the target PLET clearance and saved as `critical_...dat`.
`run.bat lcm` writes the matrix to `lcm.csv` without running anything.

### Solving one step

The loop below is used for every jack-down and landing step (Figure 2).

<!-- figure: flowchart_optimisation.pdf | Figure 2 - optimize_configuration(): solving one step -->

<!-- pagebreak -->

## 5. Outputs

| File | Content |
|---|---|
| `output_data_<date>.json` | Input data after the build calculations (traceability) |
| `<Project>_<Pipe>_<Vessel>_Base_RevX.dat` | OrcaFlex base model |
| `Statics_StepNNN_current-<dir>.dat` | Full-sequence step models (`_NoBuoy`, `_aux`, `_unstable` variants) |
| `Statics_StepNNN_..._ramp-<angle>.dat` | Upfront landing check model |
| `critical_clr-..._current-<dir>.dat` | Critical-step case models |
| `stepNNN_optimization.log`, `*error.log`, `runtime.txt` | Solver history, convergence errors, run time |
| `Statics_Results_<dir>.xlsx` | Sheets: Job Data (or template header), Full Results, InitiationLayTable, Engineering Results |
| `Steps/snapshots.dat`, `.sim` | All steps in one model |

## 6. Troubleshooting

| Symptom | Cause / action |
|---|---|
| `Exception: OrcaFlex not found` | No full OrcaFlex install. Install it, or set `orcaflex_dll` to the full path of `OrcFxAPI.dll` |
| `Required catenary length ... greater than the total pipe length` | Add pipe length in `lineData` and rebuild |
| Step saved as `_unstable.dat` | Statics did not converge after 10 retries: open the file, adjust the start position and solve manually |
| "Iteration not progressing" in the console | The optimiser hit its iteration limit: check the step manually |
| Rollerbox error for 7Vega | Export the `_vega_RB_DB` Google Sheet to `assets/vessel_database/vega/_Vega_RB_DB.csv` |
| Results workbook without the company layout | `PetrobrasInitiation_Laytable_Template.xlsx` is not in `assets/` (Google Sheet in the original tool) |

## 7. Code map

| File | Responsibility |
|---|---|
| `run.py` / `run.bat` | Command line entry point, settings handling, command dispatch |
| `initiation/inputs.py` | Load, validate and prepare the input JSON |
| `initiation/hydro.py` | PLET and buoyancy-module hydrodynamics (DNVGL-RP-N103) |
| `initiation/vessels.py` | Vessel database: templates, hang-off points, draughts, pins, rollerbox coordinates |
| `initiation/base_model.py` | OrcaFlex base-model builder |
| `initiation/statics.py` | Full-sequence and critical-step static solvers |
| `initiation/postprocess.py` | Result extraction, criteria, Excel writer, snapshots |
| `initiation/catenary.py` | Catenary starting-shape estimate |
| `assets/` | Input schema and vessel database |
