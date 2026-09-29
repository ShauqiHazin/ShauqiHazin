"""Petrobras Initiation Tool - command line version (no Streamlit).

Usage:
    python run.py info                       vessels, draughts and ramp pins
    python run.py build                      input JSON -> OrcaFlex base model
    python run.py full                       full static sequence
    python run.py critical                   critical step screening (parallel)
    python run.py lcm                        write the critical step load case matrix (lcm.csv)
    python run.py results [files...]         lay table / engineering results (Excel)
    python run.py results --critical         ... for critical step files
    python run.py snapshots [files...]       combine step files into Steps/snapshots.sim

Options:
    --settings PATH   settings file (default: settings.json next to this script)

All run options are in settings.json. See README.md.
"""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_settings(path):
    path = Path(path).resolve()
    with open(path) as f:
        settings = json.load(f)
    root = path.parent

    def resolve(p):
        return None if p is None else str((root / p).resolve()) if not Path(p).is_absolute() else p

    settings["input_file"] = resolve(settings.get("input_file"))
    settings["analysis_folder"] = resolve(settings.get("analysis_folder", "analysis"))
    settings["base_model"] = resolve(settings.get("base_model"))
    Path(settings["analysis_folder"]).mkdir(parents=True, exist_ok=True)
    # Optional: explicit OrcFxAPI.dll path when OrcaFlex is not registered as a normal install.
    # Set before OrcFxAPI is imported; worker processes inherit it through the environment.
    if settings.get("orcaflex_dll"):
        os.environ["_OrcFxAPIlib"] = settings["orcaflex_dll"]
    return settings


def find_base_model(settings):
    """base_model from settings, else the newest *_Base_Rev*.dat in the analysis folder."""
    if settings.get("base_model"):
        return settings["base_model"]
    candidates = [p for p in Path(settings["analysis_folder"]).glob("*_Base_Rev*.dat") if not p.stem.endswith("_RB")]
    if not candidates:
        sys.exit("No base model found. Run 'python run.py build' first or set 'base_model' in settings.json.")
    return str(max(candidates, key=lambda p: p.stat().st_mtime))


def make_context(settings):
    from initiation import statics
    s = settings["statics"]
    base_model = find_base_model(settings)
    print(f"Base model: {base_model}")
    ctx = statics.load_context(
        base_model,
        settings["analysis_folder"],
        contents_density=s.get("contents_density"),
        include_current=s.get("include_current", False),
        rollerbox=s.get("use_rollerbox", False),
        roller_openings=s.get("rollerbox_openings_mm"),
        criteria=settings.get("criteria"),
        debug=settings.get("debug", False),
    )
    print(f"Vessel: 7{ctx.vessel}, water depth {ctx.water_depth}m, pipe length {ctx.total_pipe_length:.1f}m, "
          f"contents density {ctx.contents_density}")
    return ctx


def write_runtime(folder, start):
    with open(Path(folder) / "runtime.txt", "w") as f:
        f.write(f"Total runtime : {(time.time() - start) / 60:.2f} minutes")


###########################################################################
#############   COMMANDS                         ##########################
###########################################################################

def cmd_info(settings, args):
    from initiation import vessels
    for name in vessels.VESSELS:
        print(f"7{name}")
        print(f"  draughts : {vessels.draughts(name)}")
        print(f"  pins     : {vessels.pin_locations(name)}")
        print(f"  payouts  : {vessels.payout_range(name)}")


def cmd_build(settings, args):
    from initiation import inputs, base_model
    data = inputs.load_input(settings["input_file"])
    data, warnings = inputs.prepare(data, ramp_estimate=settings.get("ramp_estimate_deg", 85.6))
    for w in warnings:
        print(f"WARNING: {w}")
    json_path = inputs.save_prepared(data, settings["analysis_folder"])
    print(f"Prepared input saved: {json_path}")
    model_path = base_model.generate_base_model(data, settings["vessel"], settings.get("draught"), settings["analysis_folder"])
    print(f"Base model saved: {model_path}")
    print("Please remember to optimise your element lengths.")


def cmd_full(settings, args):
    from initiation import statics, vessels
    ctx = make_context(settings)
    s = settings["statics"]
    fs = s["full_sequence"]
    brake_mode = s.get("brake_mode", False)
    if brake_mode and ctx.vessel != "Vega":
        sys.exit("Brake mode is only available for 7Vega.")
    angle = fs.get("landing_ramp_angle")

    # Ramp angles to jack down through
    if brake_mode:
        if angle is None or not 45.0 <= angle <= 89.0:
            sys.exit("In brake mode 'landing_ramp_angle' must be between 45 and 89 deg.")
        pin_locations = [angle] + list(range(math.ceil(angle), 91))
    else:
        pin_locations = list(ctx.pin_locations)
        angle = max(pin_locations) if angle is None else angle
        if angle not in pin_locations:
            sys.exit(f"Landing ramp angle {angle} is not a standard pin for 7{ctx.vessel}: {pin_locations}. "
                     f"Use one of these or set brake_mode (7Vega only).")

    # Max payout during jack down
    envelope = vessels.payout_range(ctx.vessel)
    max_payout = fs.get("max_payout_m") or envelope[0]
    if max_payout not in envelope:
        sys.exit(f"max_payout_m must be one of {envelope}")
    payout_range = envelope[:envelope.index(max_payout) + 1]

    start = time.time()
    try:
        statics.check_length(ctx, [angle])
        if fs.get("upfront_ramp_check", True):
            verified, df_failed = statics.verify_ramp_angle(ctx, angle)
            if not verified:
                print(f"\nRamp angle upfront check failed for {angle}deg:")
                if df_failed is not None:
                    print(df_failed.to_string())
                if fs.get("auto_select_ramp_angle") and not brake_mode:
                    angle = statics.optimise_ramp_angle(ctx, angle, pin_locations)
                    if angle is None:
                        sys.exit("No suitable ramp angle found.")
                else:
                    sys.exit("Select a different landing_ramp_angle (or set auto_select_ramp_angle) and try again.")
        statics.generate_full_sequence(ctx, brake_mode, angle, pin_locations, payout_range)
    except statics.StaticsError as e:
        sys.exit(f"ERROR: {e}")
    finally:
        write_runtime(ctx.analysis_folder, start)


def _critical_inputs(settings, ctx):
    from initiation import statics
    s = settings["statics"]
    cs = s["critical_step"]
    brake_mode = s.get("brake_mode", False) and ctx.vessel == "Vega"
    angles = statics.critical_ramp_angles(ctx, cs["ramp_angle_range"], brake_mode)
    if not angles:
        sys.exit(f"No ramp angles in range {cs['ramp_angle_range']}. Pins: {ctx.pin_locations}")
    return cs, angles


def cmd_critical(settings, args):
    from initiation import statics
    ctx = make_context(settings)
    cs, angles = _critical_inputs(settings, ctx)
    print(f"Ramp angles: {angles}")
    start = time.time()
    try:
        statics.check_length(ctx, angles)
        statics.generate_critical_step(
            ctx, angles,
            target_clearance=cs.get("clearance_target_m", 10.0),
            buoy_tol=cs.get("buoyancy_tolerance_te", 0.0),
            wire_tol=cs.get("wire_length_tolerance_m", 0.0),
            cores=cs.get("cores", 4),
        )
    except statics.StaticsError as e:
        sys.exit(f"ERROR: {e}")
    finally:
        write_runtime(ctx.analysis_folder, start)


def cmd_lcm(settings, args):
    import pandas as pd
    from initiation import statics
    ctx = make_context(settings)
    cs, angles = _critical_inputs(settings, ctx)
    lcm = statics.build_lcm(ctx, angles, cs.get("buoyancy_tolerance_te", 0.0), cs.get("wire_length_tolerance_m", 0.0))
    df = pd.DataFrame(lcm, columns=["buoyancy_te", "wire_length_m", "ramp_angle_deg", "rollerbox_opening", "current direction"])
    path = Path(settings["analysis_folder"]) / "lcm.csv"
    df.to_csv(path, index=False)
    print(f"{len(df)} load cases written to {path}")


def _step_files(settings, args):
    if args.files:
        return args.files
    folder = Path(settings["analysis_folder"])
    if args.critical:
        files = sorted(folder.glob("critical_*.dat"))
    else:
        files = [p for p in sorted(folder.glob("Statics_Step*.dat"))
                 if not any(tag in p.name for tag in ("_NoBuoy", "_unstable", "_ramp-"))]
    if not files:
        sys.exit(f"No step files found in {folder}")
    return [str(f) for f in files]


def cmd_results(settings, args):
    from initiation import postprocess
    files = _step_files(settings, args)
    print(f"{len(files)} step files")
    for path in postprocess.extract_results(files, settings["analysis_folder"], settings.get("criteria")):
        print(f"Results written: {path}")


def cmd_snapshots(settings, args):
    from initiation import postprocess
    files = _step_files(settings, args)
    print(f"Snapshots saved: {postprocess.generate_snapshots(files, settings['analysis_folder'])}")


COMMANDS = {
    "info": cmd_info,
    "build": cmd_build,
    "full": cmd_full,
    "critical": cmd_critical,
    "lcm": cmd_lcm,
    "results": cmd_results,
    "snapshots": cmd_snapshots,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("files", nargs="*", help="step files for 'results' / 'snapshots'")
    parser.add_argument("--settings", default=str(HERE / "settings.json"))
    parser.add_argument("--critical", action="store_true", help="use critical_*.dat files for results/snapshots")
    args = parser.parse_args()
    settings = load_settings(args.settings)
    COMMANDS[args.command](settings, args)


# Guard needed on Windows: the critical step runs in worker processes.
if __name__ == "__main__":
    main()
