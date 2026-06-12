"""
Parametric Study Runner
=======================
Runs multiple OrcaFlex riser installation analyses with
varying parameters (e.g., water depth, top tension, current speed)
to find critical conditions and sensitivity.

Usage:
    python parametric_study.py
    python parametric_study.py --param water_depth --values 300 400 500 600
    python parametric_study.py --param top_tension --values 200 250 300 350 400
"""

import os
import sys
import copy
import logging
import argparse
import json
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from riser_installation_analysis import load_config, run_analysis
from utils.orcaflex_helpers import setup_logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Parameter Definitions
# ─────────────────────────────────────────────────────────────

PARAMETER_MAP = {
    "water_depth": {
        "path": ["environment", "water_depth"],
        "unit": "m",
        "description": "Water depth",
        "default_values": [300.0, 400.0, 500.0, 600.0, 750.0],
    },
    "top_tension": {
        "path": ["installation_stages", "*", "top_tension"],
        "unit": "kN",
        "description": "Top tension (all stages scaled)",
        "default_values": [200.0, 250.0, 300.0, 350.0, 400.0],
        "scale_mode": True,  # Scale relative to base value
    },
    "current_speed": {
        "path": ["environment", "current_profile", 0, "speed"],
        "unit": "m/s",
        "description": "Surface current speed",
        "default_values": [0.3, 0.5, 0.7, 1.0, 1.2],
    },
    "seabed_stiffness": {
        "path": ["seabed", "stiffness"],
        "unit": "kN/m/m2",
        "description": "Seabed normal stiffness",
        "default_values": [50.0, 100.0, 200.0, 500.0, 1000.0],
    },
    "stinger_angle": {
        "path": ["vessel", "stinger_angle"],
        "unit": "deg",
        "description": "Stinger angle",
        "default_values": [30.0, 35.0, 40.0, 45.0, 50.0],
    },
    "wall_thickness": {
        "path": ["riser", "wall_thickness"],
        "unit": "m",
        "description": "Pipe wall thickness",
        "default_values": [0.0191, 0.0222, 0.0254, 0.0286, 0.0318],
    },
}


# ─────────────────────────────────────────────────────────────
# Config Modifier
# ─────────────────────────────────────────────────────────────

def set_nested_value(config: dict, path: list, value) -> dict:
    """Set a value in a nested dict/list using a path list."""
    cfg = copy.deepcopy(config)
    obj = cfg
    for i, key in enumerate(path[:-1]):
        if key == "*":
            # Apply to all list items
            remaining_path = path[i + 1:]
            if isinstance(obj, list):
                for item in obj:
                    set_nested_value_inplace(item, remaining_path, value)
            return cfg
        elif isinstance(obj, list):
            obj = obj[int(key)]
        else:
            obj = obj[key]
    last_key = path[-1]
    if isinstance(obj, list):
        obj[int(last_key)] = value
    else:
        obj[last_key] = value
    return cfg


def set_nested_value_inplace(obj, path: list, value) -> None:
    """Set value in nested structure in-place."""
    for key in path[:-1]:
        if isinstance(obj, list):
            obj = obj[int(key)]
        else:
            obj = obj.get(key, {})
    last_key = path[-1]
    if isinstance(obj, dict):
        obj[last_key] = value
    elif isinstance(obj, list):
        obj[int(last_key)] = value


def get_nested_value(config: dict, path: list):
    """Get a value from a nested dict/list using a path list."""
    obj = config
    for key in path:
        if key == "*":
            return None
        if isinstance(obj, list):
            obj = obj[int(key)]
        else:
            obj = obj.get(key)
        if obj is None:
            return None
    return obj


# ─────────────────────────────────────────────────────────────
# Parametric Study Runner
# ─────────────────────────────────────────────────────────────

class ParametricStudy:
    """
    Runs a parametric study varying one or more parameters
    across a range of values.
    """

    def __init__(self, base_config: dict, output_dir: str):
        self.base_config = base_config
        self.output_dir = output_dir
        self.results = []
        os.makedirs(output_dir, exist_ok=True)

    def run_single_parameter(self, param_name: str,
                              values: list = None) -> list:
        """
        Run analysis for a range of values of a single parameter.

        Args:
            param_name: Parameter name (key in PARAMETER_MAP)
            values: List of values to test (uses defaults if None)

        Returns:
            List of result dicts, one per value
        """
        if param_name not in PARAMETER_MAP:
            raise ValueError(f"Unknown parameter: '{param_name}'. "
                             f"Available: {list(PARAMETER_MAP.keys())}")

        param_def = PARAMETER_MAP[param_name]
        if values is None:
            values = param_def["default_values"]

        logger.info(f"\n{'═'*60}")
        logger.info(f"  PARAMETRIC STUDY: {param_def['description']}")
        logger.info(f"  Values: {values} {param_def['unit']}")
        logger.info(f"{'═'*60}")

        study_results = []
        for val in values:
            logger.info(f"\n  ── {param_name} = {val} {param_def['unit']} ──")

            # Modify config
            modified_config = set_nested_value(
                self.base_config, param_def["path"], val
            )
            modified_config["model"]["output_dir"] = os.path.join(
                self.output_dir, f"{param_name}_{val}"
            )

            # Run analysis (all stages)
            try:
                stage_results = run_analysis(
                    modified_config,
                    generate_plots_flag=False  # Skip plots for speed
                )
                study_results.append({
                    "parameter": param_name,
                    "value": val,
                    "unit": param_def["unit"],
                    "stage_results": stage_results,
                    "summary": _summarize_results(stage_results),
                })
            except Exception as e:
                logger.error(f"  Error for {param_name}={val}: {e}")
                study_results.append({
                    "parameter": param_name,
                    "value": val,
                    "unit": param_def["unit"],
                    "error": str(e),
                })

        self.results.extend(study_results)
        return study_results

    def run_multi_parameter(self, param_names: list,
                             value_sets: list) -> list:
        """
        Run analysis for multiple parameter combinations.

        Args:
            param_names: List of parameter names
            value_sets: List of value tuples (one per combination)

        Returns:
            List of result dicts
        """
        logger.info(f"\n{'═'*60}")
        logger.info(f"  MULTI-PARAMETER STUDY: {param_names}")
        logger.info(f"  Combinations: {len(value_sets)}")
        logger.info(f"{'═'*60}")

        study_results = []
        for i, values in enumerate(value_sets):
            label = "_".join(f"{n}={v}" for n, v in zip(param_names, values))
            logger.info(f"\n  ── Combination {i+1}/{len(value_sets)}: {label} ──")

            modified_config = copy.deepcopy(self.base_config)
            for param_name, val in zip(param_names, values):
                param_def = PARAMETER_MAP[param_name]
                modified_config = set_nested_value(
                    modified_config, param_def["path"], val
                )
            modified_config["model"]["output_dir"] = os.path.join(
                self.output_dir, f"combo_{i+1}"
            )

            try:
                stage_results = run_analysis(
                    modified_config, generate_plots_flag=False
                )
                study_results.append({
                    "parameters": dict(zip(param_names, values)),
                    "stage_results": stage_results,
                    "summary": _summarize_results(stage_results),
                })
            except Exception as e:
                logger.error(f"  Error for combination {label}: {e}")
                study_results.append({
                    "parameters": dict(zip(param_names, values)),
                    "error": str(e),
                })

        self.results.extend(study_results)
        return study_results

    def save_study_results(self) -> str:
        """Save all parametric study results to JSON."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = os.path.join(self.output_dir, f"parametric_study_{timestamp}.json")

        # Serialize (strip large result arrays)
        serializable = []
        for r in self.results:
            entry = {k: v for k, v in r.items() if k != "stage_results"}
            serializable.append(entry)

        with open(json_path, "w") as f:
            json.dump(serializable, f, indent=2, default=str)

        logger.info(f"Parametric study results saved: {json_path}")
        return json_path

    def print_sensitivity_table(self, param_name: str,
                                 study_results: list) -> None:
        """Print a sensitivity table for a single-parameter study."""
        param_def = PARAMETER_MAP.get(param_name, {})
        unit = param_def.get("unit", "")

        print(f"\n{'═'*70}")
        print(f"  SENSITIVITY: {param_def.get('description', param_name)}")
        print(f"{'═'*70}")
        print(f"  {'Value':>12} {'Unit':>6} | {'Max T (kN)':>12} {'Min BR (m)':>12} "
              f"{'Max VM (MPa)':>14} {'Status':>8}")
        print(f"  {'─'*12} {'─'*6} | {'─'*12} {'─'*12} {'─'*14} {'─'*8}")

        for r in study_results:
            if "error" in r:
                print(f"  {r['value']:>12} {unit:>6} | ERROR: {r['error']}")
                continue
            s = r.get("summary", {})
            val = r.get("value", "N/A")
            max_t = s.get("max_tension_kN", "N/A")
            min_br = s.get("min_bend_radius_m", "N/A")
            max_vm = s.get("max_von_mises_MPa", "N/A")
            status = "PASS ✓" if s.get("all_pass", True) else "FAIL ✗"

            max_t_s = f"{max_t:.1f}" if isinstance(max_t, float) else str(max_t)
            min_br_s = f"{min_br:.1f}" if isinstance(min_br, float) else str(min_br)
            max_vm_s = f"{max_vm:.1f}" if isinstance(max_vm, float) else str(max_vm)

            print(f"  {val:>12} {unit:>6} | {max_t_s:>12} {min_br_s:>12} "
                  f"{max_vm_s:>14} {status:>8}")

        print(f"{'═'*70}\n")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _summarize_results(stage_results: list) -> dict:
    """Summarize results across all stages."""
    all_pass = True
    max_tensions = []
    min_bend_radii = []
    max_vm_stresses = []

    for sd in stage_results:
        checks = sd.get("code_checks", {})
        if not checks.get("overall", {}).get("pass", True):
            all_pass = False
        t = checks.get("tension", {}).get("max_tension_kN")
        br = checks.get("bend_radius", {}).get("min_bend_radius_m")
        vm = checks.get("von_mises", {}).get("max_von_mises_MPa")
        if t is not None:
            max_tensions.append(t)
        if br is not None:
            min_bend_radii.append(br)
        if vm is not None:
            max_vm_stresses.append(vm)

    return {
        "all_pass": all_pass,
        "max_tension_kN": max(max_tensions) if max_tensions else None,
        "min_bend_radius_m": min(min_bend_radii) if min_bend_radii else None,
        "max_von_mises_MPa": max(max_vm_stresses) if max_vm_stresses else None,
        "n_stages": len(stage_results),
    }


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="OrcaFlex Riser Installation Parametric Study"
    )
    parser.add_argument("--config", "-c",
                        default=str(SCRIPT_DIR / "config" / "installation_config.yaml"))
    parser.add_argument("--param", "-p",
                        default="water_depth",
                        choices=list(PARAMETER_MAP.keys()),
                        help="Parameter to vary")
    parser.add_argument("--values", "-v",
                        nargs="+", type=float, default=None,
                        help="Values to test (space-separated)")
    parser.add_argument("--output-dir", "-o",
                        default=str(SCRIPT_DIR / "output" / "parametric"))
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(str(SCRIPT_DIR / "logs"), "parametric_study")

    config = load_config(args.config)

    study = ParametricStudy(config, args.output_dir)
    results = study.run_single_parameter(args.param, args.values)
    study.print_sensitivity_table(args.param, results)
    study.save_study_results()

    logger.info("Parametric study complete.")


if __name__ == "__main__":
    main()
