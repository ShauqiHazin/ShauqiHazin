# Petrobras Initiation Tool (Simple)

Command line version of `PG_Petrobras_Initiation` with Streamlit, wxPython and
pyautogui removed. The engineering logic (base model build, static step
optimisation, post-processing) is the same; the UI is replaced by two files:

| File              | Replaces                                                        |
|-------------------|-----------------------------------------------------------------|
| `input_data.json` | "General Input" pages (same JSON format as the old "Save Data") |
| `settings.json`   | vessel / draught selection, "Static Steps" page, criteria tab   |

**Documentation:** [docs/User_Guide.pdf](docs/User_Guide.pdf) (explanation, guideline and
flowcharts) - source text in [docs/GUIDE.md](docs/GUIDE.md), flowcharts in
`docs/flowchart_overview.*` and `docs/flowchart_optimisation.*` (PNG / SVG / PDF).

## Setup

Requires a full, licensed OrcaFlex installation. The OrcaFlex **Demo** does not
ship `OrcFxAPI.dll`, so Python scripting (and this tool) cannot run on it.

```
run.bat info
```

The first run of `run.bat` creates `venv` and installs `requirements.txt`.
You can also call `python run.py <command>` directly.

## Workflow

1. Edit `input_data.json` (or copy an `output_data_*.json` saved by the old tool).
2. Set `vessel`, `draught` and `analysis_folder` in `settings.json`.
3. Run the commands:

| Command                               | What it does                                                                                 |
|---------------------------------------|----------------------------------------------------------------------------------------------|
| `run.bat info`                        | Lists vessels, draughts, ramp pin angles and payout options                                  |
| `run.bat build`                       | Computes PLET / buoyancy hydrodynamics, saves `output_data_<date>.json` and the base `.dat` |
| `run.bat full`                        | Full static sequence → `Statics_StepNNN_current-<dir>.dat`                                  |
| `run.bat critical`                    | Critical step screening in parallel → `critical_*.dat`                                       |
| `run.bat lcm`                         | Writes the critical step load case matrix to `lcm.csv`                                       |
| `run.bat results`                     | Lay table + engineering results → `Statics_Results_<dir>.xlsx`                               |
| `run.bat results --critical`          | Same for the `critical_*.dat` files                                                          |
| `run.bat results file1.dat file2.dat` | Post-process specific files                                                                  |
| `run.bat snapshots`                   | Combines step files into `Steps/snapshots.dat` / `.sim`                                      |

Remember to optimise element lengths in the base model before running statics
(`full` / `critical` use the newest `*_Base_Rev*.dat` in the analysis folder, or
`base_model` if set).

`results` / `snapshots` without file arguments use every `Statics_Step*.dat` in
the analysis folder except `_NoBuoy`, `_unstable` and the `_ramp-` upfront check files.

## settings.json

| Key                                            | Meaning                                                                   |
|------------------------------------------------|---------------------------------------------------------------------------|
| `input_file`                                   | Project input JSON (relative to settings.json)                            |
| `analysis_folder`                              | Output folder (created if missing)                                        |
| `vessel`                                       | `7Vega`, `7Oceans` or `7Navica`                                           |
| `draught`                                      | RAO type name, see `run.bat info` (null = first)                          |
| `base_model`                                   | Base model for statics (null = newest built one)                          |
| `orcaflex_dll`                                 | Full path to `OrcFxAPI.dll` if OrcaFlex isn't found automatically (null = use registry) |
| `debug`                                        | Save intermediate optimisation models (`opti_*.dat`, `inspect_*.csv`)     |
| `statics.contents_density`                     | Te/m3, null = value in the model                                          |
| `statics.include_current`                      | Also run in-line and against-lay current                                  |
| `statics.brake_mode`                           | 7Vega only: 1 deg ramp increments / non-standard landing angle            |
| `statics.use_rollerbox`                        | Add the vessel rollerbox to the model (not 7Navica)                       |
| `statics.rollerbox_openings_mm`                | Opening(s). Full sequence uses the first, critical step uses all          |
| `full_sequence.landing_ramp_angle`             | Ramp angle at landing. Must be a standard pin unless `brake_mode`         |
| `full_sequence.max_payout_m`                   | Max payout when jacking down (null = smallest, see PG-ENG-ST-007)         |
| `full_sequence.upfront_ramp_check`             | Solve and check the landing step before the full sequence                 |
| `full_sequence.auto_select_ramp_angle`         | If the check fails, try the other pins automatically (not in brake mode)  |
| `critical_step.ramp_angle_range`               | `[min, max]` ramp angles to screen                                        |
| `critical_step.clearance_target_m`             | PLET to receptacle clearance target                                       |
| `critical_step.buoyancy_tolerance_te`          | ± buoyancy uplift sensitivity (0 = off)                                   |
| `critical_step.wire_length_tolerance_m`        | ± initiation wire length sensitivity (0 = off)                            |
| `critical_step.cores`                          | Parallel worker processes                                                 |
| `criteria`                                     | Acceptance criteria. `null` turns a criterion off                          |

## Differences from the Streamlit version

- `build` always recalculates PLET hydrodynamics, buoyancy module volume /
  hydrodynamics and fitting volumes from the geometry (what "Save Data" did).
- The ramp angle check no longer asks "manual / automatic": set
  `auto_select_ramp_angle` instead.
- Critical step cases are distributed with a process pool (one case per task)
  instead of fixed chunks per worker.
- Fixed from the original: auto ramp selection did not pass the payout range;
  the payout-less-than-fixed branch passed `(10,)` as a target (infinite retry);
  worker errors wrote an exception object instead of text; catenary estimate failed
  with numpy >= 2.
- Tabular stress-strain line types must include their `stressStrain` data
  (the old default X65 curve was only a Google Sheet).

## Missing assets (Google Sheets in the original folder)

These were stored as Google Sheets (`.gsheet`) so they could not be copied as files.
Export them from Google Drive if you need them:

| Needed for                  | Export as                                                        |
|-----------------------------|------------------------------------------------------------------|
| 7Vega rollerbox             | `assets/vessel_database/vega/_Vega_RB_DB.csv`                    |
| Company lay table format    | `assets/PetrobrasInitiation_Laytable_Template.xlsx` (optional)   |

(7Oceans rollerbox coordinates are calculated, no database needed.)

Without the template, results are written to a plain workbook with the same
three sheets plus a "Job Data" sheet.
