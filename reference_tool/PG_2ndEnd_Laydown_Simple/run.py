"""PG 2nd End Laydown Tool - command line version (no GUI).

Usage:
    python run.py info               vessels: RAO types / draughts, ramp pins, pipe hang-offs, A&R sheaves
    python run.py check              check the project JSON and show the derived values (no OrcaFlex needed)
    python run.py base               base models + first steps (tensioner, clamp, pallet, PLET at 10 m, buoy steps)
    python run.py full               complete static laydown sequence (landing + wire slackening)
    python run.py results [folder]   re-extract results from the step files of a variant folder
                                     (default: every variant folder in analysis_folder)

Options:
    --settings PATH   settings file (default: settings.json next to this script)

The project data stays in the JSON format saved by the old GUI (input_data.json).
Run options are in settings.json. See README.md and docs/User_Guide.pdf.
"""
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_settings(path):
    path = Path(path).resolve()
    with open(path) as f:
        settings = json.load(f)
    root = path.parent

    def resolve(p):
        return None if p is None else str(p if Path(p).is_absolute() else (root / p).resolve())

    settings["input_file"] = resolve(settings.get("input_file", "input_data.json"))
    settings["analysis_folder"] = resolve(settings.get("analysis_folder", "analysis"))
    settings.setdefault("current_options", ["none"])
    settings.setdefault("overrides", {})
    # Optional explicit OrcFxAPI.dll (when OrcaFlex is not registered as a normal install)
    if settings.get("orcaflex_dll"):
        os.environ["_OrcFxAPIlib"] = settings["orcaflex_dll"]
    return settings


def prepared_cases(settings):
    """Yields (option, variant folder name, prepared data, warnings) for each current option."""
    from laydown import prepare
    data = prepare.load(settings["input_file"])
    for option in settings["current_options"]:
        prepared, warnings = prepare.prepare(data, option, settings["overrides"])
        yield option, prepare.CURRENT_OPTIONS[option][1], prepared, warnings


###########################################################################
#############   COMMANDS                         ##########################
###########################################################################

def cmd_info(settings, args):
    from laydown import prepare
    for vessel in prepare.VESSELS:
        c = prepare.vessel_coords(vessel)
        print(vessel)
        for rao, draughts in c["RAO Types"].items():
            print(f"  RAO '{rao}': draught {draughts}")
        print(f"  ramp pins      : {c['Pin Locations']}")
        print(f"  pipe hang-offs : {list(c['Hang-off Locations'])}")
        print(f"  A&R sheaves    : {list(c['A&R Sheaves'])}" + ("   (+ Dual Mode beam)" if "A&R Dual Mode" in c else ""))


def cmd_check(settings, args):
    stem = Path(settings["input_file"]).stem
    for option, folder, d, warnings in prepared_cases(settings):
        v, s = d["vesselGeneral"], d["sequenceGeneral"]
        print(f"[{folder}] {d['General']['CurrentOption']}")
        print(f"  vessel {v['VesselSelected']} ({v['RAOSelected']} / {v['DraughtSelected']}), "
              f"ramp {v['SelectedRampAngle']} deg, pallet step ramp {s['PalletStepRampAngle']} deg")
        print(f"  WD {d['General']['WD']} m, pipe '{d['pipeGeneral']['LineTypeName']}' ({d['pipeGeneral']['PipeType']}), "
              f"PLET: {d['structureGeneral']['PLETModellingOpt']}, A&R: {v['AR_Mode']} / {d['structureGeneral']['AR_Type']}")
        print(f"  buoyancy: {d['buoyGeneral']['BuoyancyModuleQuantity']} module(s), connection {d['buoyGeneral']['ConnectionType']}; "
              f"sequence: {s['DeploymentSequenceOption']}, max payout {s['MaxPayoutRate']} m")
        print(f"  outputs -> {Path(settings['analysis_folder']) / folder} ({stem}_StaticResults.xlsx)")
        for w in warnings:
            print(f"  WARNING: {w}")
    print("Input OK.")


def _run_sequence(settings, base_only):
    from laydown import a_buildSequence, prepare
    stem = Path(settings["input_file"]).stem
    for option, folder, data, warnings in prepared_cases(settings):
        for w in warnings:
            print(f"WARNING: {w}")
        job_json = prepare.write_job_json(data, Path(settings["analysis_folder"]) / folder / f"{stem}.json")
        start = time.time()
        print(f"=== {data['General']['CurrentOption']} -> {Path(job_json).parent} ===")
        a_buildSequence.main_LD(job_json, settings["analysis_folder"], "YES" if base_only else "NO")
        print(f"=== done in {(time.time() - start) / 60:.1f} min ===")


def cmd_base(settings, args):
    _run_sequence(settings, base_only=True)


def cmd_full(settings, args):
    _run_sequence(settings, base_only=False)


def cmd_results(settings, args):
    from laydown import d_extractFunctions
    if args.folder:
        folders = [Path(args.folder).resolve()]
    else:
        folders = [p for p in sorted(Path(settings["analysis_folder"]).glob("*")) if p.is_dir() and list(p.glob("*.json"))]
    if not folders:
        sys.exit(f"No variant folders with a job JSON in {settings['analysis_folder']}")
    for folder in folders:
        job_json = sorted(folder.glob("*.json"))[0]
        print(f"Re-extracting {folder} ({job_json.name})")
        d_extractFunctions.rerun_extractMain(str(job_json), str(folder))


COMMANDS = {"info": cmd_info, "check": cmd_check, "base": cmd_base, "full": cmd_full, "results": cmd_results}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("folder", nargs="?", help="variant folder for 'results'")
    parser.add_argument("--settings", default=str(HERE / "settings.json"))
    args = parser.parse_args()
    sys.path.insert(0, str(HERE))
    settings = load_settings(args.settings)
    try:
        COMMANDS[args.command](settings, args)
    except Exception as exc:
        from laydown.prepare import InputError
        if isinstance(exc, InputError):
            sys.exit(f"INPUT ERROR: {exc}")
        traceback.print_exc()
        sys.exit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
