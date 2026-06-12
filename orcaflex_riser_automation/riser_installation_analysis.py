"""
╔══════════════════════════════════════════════════════════════════════════╗
║          OrcaFlex Riser Installation Analysis — Automation Box          ║
║                                                                          ║
║  Automates static analysis for all riser installation stages:           ║
║    1. Load configuration                                                 ║
║    2. Build OrcaFlex model                                               ║
║    3. Loop through installation stages                                   ║
║    4. Configure model per stage                                          ║
║    5. Run static analysis                                                ║
║    6. Extract results                                                    ║
║    7. Perform DNV-ST-F101 code checks                                    ║
║    8. Generate Excel + text reports and plots                            ║
╚══════════════════════════════════════════════════════════════════════════╝

Usage:
    python riser_installation_analysis.py
    python riser_installation_analysis.py --config config/installation_config.yaml
    python riser_installation_analysis.py --stage 3          # Run single stage
    python riser_installation_analysis.py --no-plots         # Skip plot generation
    python riser_installation_analysis.py --sim              # Force simulation mode
"""

import os
import sys
import argparse
import logging
import json
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# Path setup — allow running from any directory
# ─────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# ─────────────────────────────────────────────────────────────
# Local imports
# ─────────────────────────────────────────────────────────────
from utils.orcaflex_helpers import (
    setup_logging,
    run_static_analysis,
    extract_line_results,
    get_line_summary_results,
    check_dnv_st_f101,
    calculate_submerged_weight,
    save_model,
    save_simulation,
    ORCAFLEX_AVAILABLE,
)
from utils.model_builder import (
    RiserInstallationModelBuilder,
    SimulationModeModelBuilder,
)
from utils.report_generator import (
    generate_excel_report,
    generate_text_report,
    generate_plots,
    generate_summary_plot,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Configuration Loader
# ─────────────────────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    """Load YAML configuration file."""
    try:
        import yaml
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        logger.info(f"Configuration loaded: {config_path}")
        return config
    except ImportError:
        logger.warning("PyYAML not installed. Using default configuration.")
        return _default_config()
    except FileNotFoundError:
        logger.warning(f"Config file not found: {config_path}. Using defaults.")
        return _default_config()


def _default_config() -> dict:
    """Return a minimal default configuration."""
    return {
        "project": {"name": "Riser Installation Analysis"},
        "model": {"output_dir": "output", "log_dir": "logs",
                  "save_sim_files": True, "save_results_xlsx": True},
        "vessel": {
            "name": "Lay Vessel", "type": "6DOF",
            "initial_position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "heading": 0.0, "draft": 8.5,
            "stinger_angle": 45.0, "stinger_length": 80.0,
        },
        "riser": {
            "name": "Production Riser",
            "outer_diameter": 0.3239, "wall_thickness": 0.0254,
            "inner_diameter": 0.2731, "material": "Steel",
            "youngs_modulus": 2.07e11, "poissons_ratio": 0.3,
            "density": 7850.0,
            "coating": {"type": "FBE", "thickness": 0.0005, "density": 1300.0},
            "contents": {"fluid_type": "Seawater", "density": 1025.0},
            "design_pressure": 15.0, "design_temperature": 80.0,
            "SMYS": 450.0, "SMTS": 535.0,
        },
        "environment": {
            "water_depth": 500.0, "seawater_density": 1025.0,
            "kinematic_viscosity": 1.35e-6,
            "current_profile": [
                {"depth": 0.0, "speed": 0.5, "direction": 0.0},
                {"depth": 500.0, "speed": 0.05, "direction": 30.0},
            ],
        },
        "seabed": {"type": "Elastic", "stiffness": 100.0, "friction_coefficient": 0.5},
        "analysis": {"type": "Static", "convergence_tolerance": 0.001,
                     "max_iterations": 200, "gravity": 9.81},
        "code_check": {
            "standard": "DNV-ST-F101", "usage_factor": 0.9,
            "max_allowable_bend_radius": 15.0,
            "max_allowable_tension": 500.0,
        },
        "results": {
            "extract_variables": [
                "Effective Tension", "Bend Moment", "Shear Force",
                "x", "y", "z", "Curvature", "Von Mises Stress",
                "Axial Force", "Seabed Normal Reaction",
            ],
            "arc_length_step": 1.0,
            "plot_results": True,
        },
        "installation_stages": [
            {"stage_id": 1, "name": "Initiation",
             "description": "First joint lowered from vessel",
             "vessel_position": 0.0, "riser_length_deployed": 12.0,
             "top_tension": 50.0, "layback": 0.0, "enabled": True},
            {"stage_id": 2, "name": "Shallow Water Lay",
             "description": "Laying through shallow water",
             "vessel_position": 100.0, "riser_length_deployed": 150.0,
             "top_tension": 120.0, "layback": 80.0, "enabled": True},
            {"stage_id": 3, "name": "Mid Water Lay",
             "description": "Laying through mid-water section",
             "vessel_position": 300.0, "riser_length_deployed": 350.0,
             "top_tension": 200.0, "layback": 150.0, "enabled": True},
            {"stage_id": 4, "name": "Deep Water Lay",
             "description": "Laying through deep water",
             "vessel_position": 450.0, "riser_length_deployed": 500.0,
             "top_tension": 280.0, "layback": 200.0, "enabled": True},
            {"stage_id": 5, "name": "Touchdown",
             "description": "Riser touches down on seabed",
             "vessel_position": 500.0, "riser_length_deployed": 520.0,
             "top_tension": 300.0, "layback": 220.0, "enabled": True},
            {"stage_id": 6, "name": "Pull-in",
             "description": "Final pull-in to subsea structure",
             "vessel_position": 510.0, "riser_length_deployed": 530.0,
             "top_tension": 350.0, "layback": 230.0, "enabled": True},
        ],
    }


# ─────────────────────────────────────────────────────────────
# Stage Runner
# ─────────────────────────────────────────────────────────────

def run_stage(model, builder, stage_config: dict, config: dict,
              output_dir: str, generate_plots_flag: bool) -> dict:
    """
    Run static analysis for a single installation stage.

    Returns:
        dict with stage_info, results, code_checks, submerged_weight
    """
    stage_id = stage_config.get("stage_id")
    stage_name = stage_config.get("name", f"Stage {stage_id}")

    logger.info("")
    logger.info(f"{'─'*60}")
    logger.info(f"  STAGE {stage_id}: {stage_name.upper()}")
    logger.info(f"  {stage_config.get('description', '')}")
    logger.info(f"{'─'*60}")

    # ── Configure model for this stage ────────────────────────
    builder.configure_stage(model, stage_config)

    # ── Run static analysis ────────────────────────────────────
    logger.info(f"  Running static analysis...")
    converged = run_static_analysis(model)

    if not converged:
        logger.error(f"  Static analysis did NOT converge for Stage {stage_id}!")
    else:
        logger.info(f"  Static analysis converged ✓")

    # ── Save model/sim files ───────────────────────────────────
    model_cfg = config.get("model", {})
    if model_cfg.get("save_sim_files", True):
        sim_path = os.path.join(output_dir, f"stage{stage_id}_{stage_name.replace(' ', '_')}.sim")
        save_simulation(model, sim_path)

    # ── Extract results ────────────────────────────────────────
    riser_name = config.get("riser", {}).get("name", "Production Riser")
    results_cfg = config.get("results", {})
    variables = results_cfg.get("extract_variables", ["Effective Tension", "Bend Moment"])
    arc_step = results_cfg.get("arc_length_step", 1.0)

    logger.info(f"  Extracting results ({len(variables)} variables)...")
    results = extract_line_results(model, riser_name, variables, arc_step)

    # ── Code checks ────────────────────────────────────────────
    riser_cfg = config.get("riser", {})
    code_cfg = config.get("code_check", {})

    pipe_config = {
        "outer_diameter": riser_cfg.get("outer_diameter", 0.3239),
        "wall_thickness": riser_cfg.get("wall_thickness", 0.0254),
        "SMYS": riser_cfg.get("SMYS", 450.0),
        "SMTS": riser_cfg.get("SMTS", 535.0),
        "design_pressure": riser_cfg.get("design_pressure", 15.0),
    }

    logger.info(f"  Running DNV-ST-F101 code checks...")
    code_checks = check_dnv_st_f101(results, pipe_config, code_cfg)

    # ── Submerged weight ───────────────────────────────────────
    coating = riser_cfg.get("coating", {})
    contents = riser_cfg.get("contents", {})
    sw = calculate_submerged_weight(
        OD=riser_cfg.get("outer_diameter", 0.3239),
        WT=riser_cfg.get("wall_thickness", 0.0254),
        steel_density=riser_cfg.get("density", 7850.0),
        seawater_density=config.get("environment", {}).get("seawater_density", 1025.0),
        coating_thickness=coating.get("thickness", 0.0),
        coating_density=coating.get("density", 1300.0),
        contents_density=contents.get("density", 1025.0),
    )

    # ── Log code check summary ─────────────────────────────────
    overall = code_checks.get("overall", {})
    status_str = overall.get("status", "N/A")
    logger.info(f"  Code Check Result: {status_str}")
    for check_name, check_data in code_checks.items():
        if check_name == "overall":
            continue
        pass_str = "PASS ✓" if check_data.get("pass", True) else "FAIL ✗"
        util = check_data.get("utilization", "N/A")
        util_str = f"  (util={util:.3f})" if isinstance(util, float) else ""
        logger.info(f"    {pass_str} {check_name.replace('_', ' ').title()}{util_str}")

    # ── Generate plots ─────────────────────────────────────────
    stage_data = {
        "stage_info": stage_config,
        "results": results,
        "code_checks": code_checks,
        "submerged_weight": sw,
        "converged": converged,
    }

    if generate_plots_flag and results_cfg.get("plot_results", True):
        plots_dir = os.path.join(output_dir, "plots")
        plot_files = generate_plots(stage_data, plots_dir)
        stage_data["plot_files"] = plot_files

    return stage_data


# ─────────────────────────────────────────────────────────────
# Main Analysis Runner
# ─────────────────────────────────────────────────────────────

def run_analysis(config: dict, stage_filter: int = None,
                 generate_plots_flag: bool = True) -> list:
    """
    Run the full riser installation static analysis.

    Args:
        config: Configuration dictionary
        stage_filter: If set, only run this stage ID
        generate_plots_flag: Whether to generate plots

    Returns:
        List of stage result dicts
    """
    project_name = config.get("project", {}).get("name", "Riser Installation")
    model_cfg = config.get("model", {})
    output_dir = os.path.join(SCRIPT_DIR, model_cfg.get("output_dir", "output"))
    os.makedirs(output_dir, exist_ok=True)

    logger.info("")
    logger.info("╔" + "═" * 68 + "╗")
    logger.info(f"║  OrcaFlex Riser Installation Analysis — {project_name:<28}║")
    logger.info("╚" + "═" * 68 + "╝")
    logger.info(f"  OrcaFlex Available : {'YES ✓' if ORCAFLEX_AVAILABLE else 'NO — Running in SIMULATION MODE'}")
    logger.info(f"  Output Directory   : {output_dir}")
    logger.info("")

    # ── Build model ────────────────────────────────────────────
    if ORCAFLEX_AVAILABLE:
        builder = RiserInstallationModelBuilder(config)
    else:
        builder = SimulationModeModelBuilder(config)

    model = builder.build_model()

    # ── Get enabled stages ─────────────────────────────────────
    stages = config.get("installation_stages", [])
    if stage_filter is not None:
        stages = [s for s in stages if s.get("stage_id") == stage_filter]
        if not stages:
            logger.error(f"Stage {stage_filter} not found in configuration.")
            return []
    else:
        stages = [s for s in stages if s.get("enabled", True)]

    logger.info(f"  Stages to run: {len(stages)}")
    for s in stages:
        logger.info(f"    Stage {s['stage_id']}: {s['name']}")
    logger.info("")

    # ── Run each stage ─────────────────────────────────────────
    all_results = []
    for stage_config in stages:
        try:
            stage_data = run_stage(
                model, builder, stage_config, config,
                output_dir, generate_plots_flag
            )
            all_results.append(stage_data)
        except Exception as e:
            logger.error(f"Error in Stage {stage_config.get('stage_id')}: {e}", exc_info=True)

    return all_results


# ─────────────────────────────────────────────────────────────
# Report Generation
# ─────────────────────────────────────────────────────────────

def generate_reports(all_results: list, config: dict) -> dict:
    """Generate all output reports."""
    project_name = config.get("project", {}).get("name", "Riser Installation")
    model_cfg = config.get("model", {})
    output_dir = os.path.join(SCRIPT_DIR, model_cfg.get("output_dir", "output"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_files = {}

    # ── Excel report ───────────────────────────────────────────
    if model_cfg.get("save_results_xlsx", True):
        xlsx_path = os.path.join(output_dir, f"riser_installation_results_{timestamp}.xlsx")
        result = generate_excel_report(all_results, xlsx_path, project_name)
        if result:
            report_files["excel"] = result
            logger.info(f"  Excel report: {xlsx_path}")

    # ── Text report ────────────────────────────────────────────
    txt_path = os.path.join(output_dir, f"riser_installation_results_{timestamp}.txt")
    generate_text_report(all_results, txt_path, project_name)
    report_files["text"] = txt_path
    logger.info(f"  Text report: {txt_path}")

    # ── JSON results dump ──────────────────────────────────────
    json_path = os.path.join(output_dir, f"riser_installation_results_{timestamp}.json")
    _save_json_results(all_results, json_path)
    report_files["json"] = json_path
    logger.info(f"  JSON results: {json_path}")

    # ── Summary plot ───────────────────────────────────────────
    plots_dir = os.path.join(output_dir, "plots")
    summary_plot = generate_summary_plot(all_results, plots_dir)
    if summary_plot:
        report_files["summary_plot"] = summary_plot
        logger.info(f"  Summary plot: {summary_plot}")

    return report_files


def _save_json_results(all_results: list, json_path: str) -> None:
    """Save results to JSON (serializable subset)."""
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    serializable = []
    for sd in all_results:
        entry = {
            "stage_info": sd.get("stage_info", {}),
            "code_checks": sd.get("code_checks", {}),
            "submerged_weight": sd.get("submerged_weight", {}),
            "converged": sd.get("converged", True),
        }
        # Include first/last 5 result points only (keep JSON small)
        results = sd.get("results", {})
        entry["results_sample"] = {
            k: (v[:5] + ["..."] + v[-5:]) if isinstance(v, list) and len(v) > 10 else v
            for k, v in results.items()
        }
        serializable.append(entry)

    with open(json_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)


# ─────────────────────────────────────────────────────────────
# Print Final Summary
# ─────────────────────────────────────────────────────────────

def print_final_summary(all_results: list, report_files: dict) -> None:
    """Print a formatted summary table to console."""
    print()
    print("╔" + "═" * 78 + "╗")
    print("║" + "  RISER INSTALLATION ANALYSIS — FINAL SUMMARY".center(78) + "║")
    print("╠" + "═" * 78 + "╣")
    print(f"║  {'Stage':<30} {'Max T (kN)':<14} {'Min BR (m)':<14} {'Status':<10} ║")
    print("╠" + "─" * 78 + "╣")

    all_pass = True
    for sd in all_results:
        info = sd.get("stage_info", {})
        checks = sd.get("code_checks", {})
        overall = checks.get("overall", {})
        stage_pass = overall.get("pass", True)
        if not stage_pass:
            all_pass = False

        stage_label = f"S{info.get('stage_id')}: {info.get('name', '')}"
        max_t = checks.get("tension", {}).get("max_tension_kN", "N/A")
        min_br = checks.get("bend_radius", {}).get("min_bend_radius_m", "N/A")
        status = "PASS ✓" if stage_pass else "FAIL ✗"

        max_t_str = f"{max_t:.1f}" if isinstance(max_t, float) else str(max_t)
        min_br_str = f"{min_br:.1f}" if isinstance(min_br, float) else str(min_br)

        print(f"║  {stage_label:<30} {max_t_str:<14} {min_br_str:<14} {status:<10} ║")

    print("╠" + "═" * 78 + "╣")
    overall_str = "ALL STAGES PASS ✓" if all_pass else "ONE OR MORE STAGES FAIL ✗"
    print(f"║  OVERALL: {overall_str:<68}║")
    print("╠" + "═" * 78 + "╣")
    print("║  OUTPUT FILES:".ljust(79) + "║")
    for ftype, fpath in report_files.items():
        short = os.path.basename(fpath) if fpath else "N/A"
        print(f"║    {ftype.upper():<12}: {short:<62}║")
    print("╚" + "═" * 78 + "╝")
    print()


# ─────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="OrcaFlex Riser Installation Static Analysis Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python riser_installation_analysis.py
  python riser_installation_analysis.py --config config/my_project.yaml
  python riser_installation_analysis.py --stage 3
  python riser_installation_analysis.py --no-plots
  python riser_installation_analysis.py --sim
        """
    )
    parser.add_argument(
        "--config", "-c",
        default=str(SCRIPT_DIR / "config" / "installation_config.yaml"),
        help="Path to YAML configuration file (default: config/installation_config.yaml)"
    )
    parser.add_argument(
        "--stage", "-s",
        type=int, default=None,
        help="Run only a specific stage ID (default: run all enabled stages)"
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip plot generation"
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Force simulation mode (no OrcaFlex required)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Override output directory"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Setup logging ──────────────────────────────────────────
    log_dir = str(SCRIPT_DIR / "logs")
    log_file = setup_logging(log_dir, "riser_installation")
    logger.info(f"Log file: {log_file}")

    # ── Load config ────────────────────────────────────────────
    config = load_config(args.config)

    # ── Override output dir if specified ───────────────────────
    if args.output_dir:
        config.setdefault("model", {})["output_dir"] = args.output_dir

    # ── Force sim mode ─────────────────────────────────────────
    if args.sim:
        import utils.orcaflex_helpers as helpers
        helpers.ORCAFLEX_AVAILABLE = False
        import utils.model_builder as mb
        mb.ORCAFLEX_AVAILABLE = False
        logger.info("Forced simulation mode.")

    # ── Run analysis ───────────────────────────────────────────
    all_results = run_analysis(
        config,
        stage_filter=args.stage,
        generate_plots_flag=not args.no_plots,
    )

    if not all_results:
        logger.error("No results generated. Check configuration and logs.")
        sys.exit(1)

    # ── Generate reports ───────────────────────────────────────
    logger.info("")
    logger.info("Generating reports...")
    report_files = generate_reports(all_results, config)

    # ── Print summary ──────────────────────────────────────────
    print_final_summary(all_results, report_files)

    logger.info("Analysis complete.")


if __name__ == "__main__":
    main()
