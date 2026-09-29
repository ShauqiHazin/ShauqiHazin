# PG 2nd End Laydown Tool (Simple)

Command line version of `PG_2ndEnd_Laydown` with the PyQt6 GUI removed. The OrcaFlex
engine (base models, static laydown sequence, result extraction) is the same code as
the GUI tool; only confirmed defects were fixed (see below). Full guide:
[docs/User_Guide.pdf](docs/User_Guide.pdf) / [docs/GUIDE.md](docs/GUIDE.md).

| File              | Replaces                                                                  |
|-------------------|---------------------------------------------------------------------------|
| `input_data.json` | All GUI tabs. Same JSON format as the GUI "Save Current Data" file        |
| `settings.json`   | Current option, job folder, file dialogs                                   |

## Setup

Requires a full, licensed OrcaFlex (the Demo has no `OrcFxAPI.dll`).

```
run.bat info
```

The first `run.bat` creates `venv` and installs `requirements.txt`
(`python run.py <command>` also works).

## Commands

| Command                   | What it does                                                                         |
|---------------------------|--------------------------------------------------------------------------------------|
| `run.bat info`            | Vessels: RAO types / draughts, ramp pins, pipe hang-offs, A&R sheaves                |
| `run.bat check`           | Checks `input_data.json`, recalculates derived values, prints a summary (no OrcaFlex)|
| `run.bat base`            | Base models + steps 00-03 + buoy deployment steps + results (was "Generate Basefile Only") |
| `run.bat full`            | Complete static laydown sequence (was "Generate Static Laydown Sequence")            |
| `run.bat results [folder]`| Re-extract results from the step files (was "Rerun Results Extraction")              |

Outputs go to `analysis_folder/<noCurrent|InLineCurrent|AgainstCurrent>/`: `Stage_1_PLET.dat`
(+ `Stage_2_PLET.dat` with wings), step files `NN_LD_<ramp>_Stage_<n>.dat`, the job JSON,
`<job>_StaticResults.xlsx`, a log file, and `<job>_Laytable.xlsx` when the template exists.

## settings.json

| Key               | Meaning                                                                                  |
|-------------------|------------------------------------------------------------------------------------------|
| `input_file`      | Project JSON (GUI format). Examples: `examples/Yoke.json`, `examples/Bridle.json`         |
| `analysis_folder` | Job folder                                                                               |
| `current_options` | Any of `"none"`, `"inline"`, `"against"`; one run per entry (the GUI ran one per click)   |
| `orcaflex_dll`    | Full path to `OrcFxAPI.dll` if OrcaFlex is not found automatically (null = registry)       |
| `overrides`       | Optional values merged into the project JSON, e.g. `{"vesselGeneral": {"SelectedRampAngle": "76.1"}}` |

## Fixes compared with the GUI tool

- Vessel files had no `A&R Wire ID`, `AR Winch Limit` and `Bollard Pull Limit` keys, so every run
  stopped with a KeyError. Added from the legacy code / old GUI values (Vega 600 / 100 te,
  Oceans 500 / 120 te, Navica 250 / 102 te), with code fallbacks.
- Dual Mode never built its wires (builder checked "Dual Mode", the GUI saves "Dual Mode (A&R Beam)").
- "PLET touched seabed, vessel stationary" branch passed the result-extraction arguments in the wrong order.
- Log file path broke with Windows paths; `Static-Failed.dat` was written to the working directory;
  result re-extraction changed the working directory permanently.
- A failed statics solve in steps 00/01 returned a bending moment of 0, which the solver took as converged.
- Step 00/01/02 descriptions were written after the file was saved.
- Step 03 jack-down loop had no exit when no lower ramp pin was left.
- Catenary estimate failed with numpy >= 2 (`math.cosh` on arrays).
- Missing `Laytable_Template.xlsx` (Google Sheet in the original) no longer stops the run.

## Company lay table template

`Laytable_Template` is a Google Sheet in the original folder. Export it as
`assets/Laytable_Template.xlsx` (sheet `LaydownLaytable`) to get `<job>_Laytable.xlsx`;
without it only `<job>_StaticResults.xlsx` is written.
