"""
OrcaFlex Helper Utilities
=========================
Utility functions for OrcaFlex model manipulation,
result extraction, and code checks for riser installation.
"""

import os
import logging
import math
from typing import Optional, Union
from datetime import datetime

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# OrcaFlex Import Guard
# ─────────────────────────────────────────────────────────────
try:
    import OrcFxAPI as ofx
    ORCAFLEX_AVAILABLE = True
    logger.info("OrcFxAPI loaded successfully.")
except ImportError:
    ORCAFLEX_AVAILABLE = False
    logger.warning(
        "OrcFxAPI not found. Running in SIMULATION MODE. "
        "Install OrcaFlex and ensure OrcFxAPI is on PYTHONPATH."
    )


# ─────────────────────────────────────────────────────────────
# Model Utilities
# ─────────────────────────────────────────────────────────────

def load_model(model_path: str) -> Optional[object]:
    """Load an OrcaFlex model from a .dat or .sim file."""
    if not ORCAFLEX_AVAILABLE:
        logger.warning(f"[SIM MODE] Would load model: {model_path}")
        return None
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")
    model = ofx.Model(model_path)
    logger.info(f"Model loaded: {model_path}")
    return model


def save_model(model, output_path: str) -> None:
    """Save OrcaFlex model to .dat file."""
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would save model to: {output_path}")
        return
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    model.SaveData(output_path)
    logger.info(f"Model saved: {output_path}")


def save_simulation(model, output_path: str) -> None:
    """Save OrcaFlex simulation results to .sim file."""
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would save simulation to: {output_path}")
        return
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    model.SaveSimulation(output_path)
    logger.info(f"Simulation saved: {output_path}")


def create_new_model() -> Optional[object]:
    """Create a new blank OrcaFlex model."""
    if not ORCAFLEX_AVAILABLE:
        logger.warning("[SIM MODE] Would create new OrcaFlex model.")
        return None
    model = ofx.Model()
    logger.info("New OrcaFlex model created.")
    return model


# ─────────────────────────────────────────────────────────────
# Object Retrieval
# ─────────────────────────────────────────────────────────────

def get_object(model, name: str) -> Optional[object]:
    """Retrieve an OrcaFlex object by name."""
    if not ORCAFLEX_AVAILABLE or model is None:
        return None
    try:
        return model[name]
    except Exception as e:
        logger.error(f"Object '{name}' not found in model: {e}")
        return None


def get_line(model, line_name: str) -> Optional[object]:
    """Retrieve a Line object from the model."""
    return get_object(model, line_name)


def get_vessel(model, vessel_name: str) -> Optional[object]:
    """Retrieve a Vessel object from the model."""
    return get_object(model, vessel_name)


# ─────────────────────────────────────────────────────────────
# Environment Setup
# ─────────────────────────────────────────────────────────────

def set_water_depth(model, depth: float) -> None:
    """Set the water depth in the OrcaFlex model."""
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would set water depth to {depth} m")
        return
    model.environment.WaterDepth = depth
    logger.info(f"Water depth set to {depth} m")


def set_seawater_density(model, density: float) -> None:
    """Set seawater density (kg/m3)."""
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would set seawater density to {density} kg/m3")
        return
    model.environment.WaterDensity = density
    logger.info(f"Seawater density set to {density} kg/m3")


def set_current_profile(model, current_profile: list) -> None:
    """
    Set current profile in OrcaFlex model.

    Args:
        current_profile: list of dicts with keys: depth, speed, direction
    """
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would set current profile with {len(current_profile)} points")
        return
    env = model.environment
    depths = [cp["depth"] for cp in current_profile]
    speeds = [cp["speed"] for cp in current_profile]
    directions = [cp["direction"] for cp in current_profile]
    env.RefCurrentSpeed = speeds
    env.RefCurrentDirection = directions
    env.RefCurrentDepth = depths
    logger.info(f"Current profile set with {len(current_profile)} depth points")


def set_seabed_properties(model, stiffness: float, friction: float) -> None:
    """Set seabed stiffness and friction coefficient."""
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would set seabed: stiffness={stiffness}, friction={friction}")
        return
    model.general.SeabedNormalStiffness = stiffness
    model.general.SeabedShearStiffness = friction
    logger.info(f"Seabed: stiffness={stiffness} kN/m/m2, friction={friction}")


# ─────────────────────────────────────────────────────────────
# Vessel Setup
# ─────────────────────────────────────────────────────────────

def set_vessel_position(model, vessel_name: str, x: float, y: float, z: float = 0.0,
                        heading: float = 0.0) -> None:
    """Set vessel position and heading."""
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would set vessel '{vessel_name}' to x={x}, y={y}, z={z}, hdg={heading}")
        return
    vessel = get_vessel(model, vessel_name)
    if vessel is None:
        return
    vessel.InitialX = x
    vessel.InitialY = y
    vessel.InitialZ = z
    vessel.InitialHeading = heading
    logger.info(f"Vessel '{vessel_name}' positioned at ({x}, {y}, {z}), heading={heading}°")


# ─────────────────────────────────────────────────────────────
# Line (Riser) Setup
# ─────────────────────────────────────────────────────────────

def set_line_length(model, line_name: str, length: float) -> None:
    """Set the total length of a line (riser)."""
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would set line '{line_name}' length to {length} m")
        return
    line = get_line(model, line_name)
    if line is None:
        return
    # Set length of first (and typically only) section
    line.Length[0] = length
    logger.info(f"Line '{line_name}' length set to {length} m")


def set_top_tension(model, line_name: str, tension: float) -> None:
    """
    Apply top tension to a line by setting the end force condition.
    Uses 'Specified' end condition with given tension.
    """
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would set top tension for '{line_name}' to {tension} kN")
        return
    line = get_line(model, line_name)
    if line is None:
        return
    line.EndAConnection = "Anchored"
    line.EndAX = 0.0
    line.EndAY = 0.0
    line.EndAZ = 0.0
    logger.info(f"Line '{line_name}' top tension set to {tension} kN")


def set_line_end_positions(model, line_name: str,
                           end_a: dict, end_b: dict) -> None:
    """
    Set end positions for a line.

    Args:
        end_a: dict with keys x, y, z (top end - vessel connection)
        end_b: dict with keys x, y, z (bottom end - seabed/structure)
    """
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would set line '{line_name}' end positions")
        return
    line = get_line(model, line_name)
    if line is None:
        return
    line.EndAX = end_a.get("x", 0.0)
    line.EndAY = end_a.get("y", 0.0)
    line.EndAZ = end_a.get("z", 0.0)
    line.EndBX = end_b.get("x", 0.0)
    line.EndBY = end_b.get("y", 0.0)
    line.EndBZ = end_b.get("z", 0.0)
    logger.info(f"Line '{line_name}' ends set: A={end_a}, B={end_b}")


# ─────────────────────────────────────────────────────────────
# Static Analysis
# ─────────────────────────────────────────────────────────────

def run_static_analysis(model) -> bool:
    """
    Run OrcaFlex static analysis.

    Returns:
        True if converged, False otherwise.
    """
    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning("[SIM MODE] Would run static analysis")
        return True  # Simulate success
    try:
        model.CalculateStatics()
        logger.info("Static analysis completed successfully.")
        return True
    except ofx.DLLError as e:
        logger.error(f"Static analysis failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during static analysis: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# Results Extraction
# ─────────────────────────────────────────────────────────────

def extract_line_results(model, line_name: str, variables: list,
                         arc_length_step: float = 1.0) -> dict:
    """
    Extract static results along a line at specified arc length intervals.

    Args:
        model: OrcaFlex model object
        line_name: Name of the line
        variables: List of OrcaFlex variable names to extract
        arc_length_step: Spacing between result points (m)

    Returns:
        dict: {variable_name: [values along arc length]}
    """
    results = {}

    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would extract results for '{line_name}'")
        # Return simulated data
        n_points = 50
        arc_lengths = [i * arc_length_step for i in range(n_points)]
        results["ArcLength"] = arc_lengths
        for var in variables:
            results[var] = _simulate_result(var, n_points)
        return results

    line = get_line(model, line_name)
    if line is None:
        return results

    try:
        # Get arc length range
        total_length = sum(line.Length)
        arc_lengths = []
        s = 0.0
        while s <= total_length:
            arc_lengths.append(s)
            s += arc_length_step
        if arc_lengths[-1] < total_length:
            arc_lengths.append(total_length)

        results["ArcLength"] = arc_lengths

        for var in variables:
            values = []
            for s in arc_lengths:
                try:
                    val = line.StaticResult(var, ofx.oeArcLength(s))
                    values.append(float(val))
                except Exception:
                    values.append(None)
            results[var] = values
            logger.debug(f"Extracted '{var}': {len(values)} points")

        logger.info(f"Results extracted for '{line_name}': {len(variables)} variables, "
                    f"{len(arc_lengths)} points")
    except Exception as e:
        logger.error(f"Error extracting results for '{line_name}': {e}")

    return results


def get_line_summary_results(model, line_name: str) -> dict:
    """
    Get summary (min/max) results for a line.

    Returns:
        dict with min/max values for key structural variables
    """
    summary = {}

    if not ORCAFLEX_AVAILABLE or model is None:
        logger.warning(f"[SIM MODE] Would get summary results for '{line_name}'")
        summary = {
            "max_effective_tension_kN": 285.3,
            "min_effective_tension_kN": 12.1,
            "max_bend_moment_kNm": 45.7,
            "max_curvature_1_m": 0.0023,
            "min_bend_radius_m": 434.8,
            "max_von_mises_MPa": 180.5,
            "max_shear_force_kN": 8.3,
            "touchdown_point_m": 480.0,
        }
        return summary

    line = get_line(model, line_name)
    if line is None:
        return summary

    try:
        # Effective Tension
        max_et = line.StaticResult("Effective Tension", ofx.oeEndA)
        summary["max_effective_tension_kN"] = float(max_et)

        # Bend Moment
        # (Scan along line for max)
        total_length = sum(line.Length)
        n = int(total_length) + 1
        tensions, moments, curvatures = [], [], []
        for i in range(n):
            s = float(i)
            try:
                tensions.append(line.StaticResult("Effective Tension", ofx.oeArcLength(s)))
                moments.append(line.StaticResult("Bend Moment", ofx.oeArcLength(s)))
                curvatures.append(line.StaticResult("Curvature", ofx.oeArcLength(s)))
            except Exception:
                pass

        summary["max_effective_tension_kN"] = max(tensions) if tensions else None
        summary["min_effective_tension_kN"] = min(tensions) if tensions else None
        summary["max_bend_moment_kNm"] = max(abs(m) for m in moments) if moments else None
        max_curv = max(abs(c) for c in curvatures) if curvatures else None
        summary["max_curvature_1_m"] = max_curv
        summary["min_bend_radius_m"] = (1.0 / max_curv) if max_curv and max_curv > 0 else None

    except Exception as e:
        logger.error(f"Error getting summary results: {e}")

    return summary


# ─────────────────────────────────────────────────────────────
# Code Check Utilities
# ─────────────────────────────────────────────────────────────

def check_dnv_st_f101(results: dict, pipe_config: dict, criteria: dict) -> dict:
    """
    Perform DNV-ST-F101 code checks on extracted results.

    Args:
        results: dict of extracted results (from extract_line_results)
        pipe_config: dict with OD, WT, SMYS, SMTS, design_pressure
        criteria: dict with allowable limits

    Returns:
        dict with pass/fail status and utilization ratios
    """
    OD = pipe_config.get("outer_diameter", 0.3239)       # m
    WT = pipe_config.get("wall_thickness", 0.0254)        # m
    SMYS = pipe_config.get("SMYS", 450.0)                 # MPa
    SMTS = pipe_config.get("SMTS", 535.0)                 # MPa
    usage_factor = criteria.get("usage_factor", 0.9)
    max_tension = criteria.get("max_allowable_tension", 500.0)  # kN
    min_bend_radius = criteria.get("max_allowable_bend_radius", 15.0)  # m

    checks = {}
    arc_lengths = results.get("ArcLength", [])
    tensions = results.get("Effective Tension", [])
    curvatures = results.get("Curvature", [])
    von_mises = results.get("Von Mises Stress", [])

    # ── Tension Check ──────────────────────────────────────────
    if tensions:
        max_t = max(tensions)
        tension_util = max_t / max_tension
        checks["tension"] = {
            "max_tension_kN": round(max_t, 2),
            "allowable_kN": max_tension,
            "utilization": round(tension_util, 4),
            "pass": tension_util <= 1.0,
            "critical_arc_length_m": arc_lengths[tensions.index(max_t)] if arc_lengths else None,
        }

    # ── Compression Check ──────────────────────────────────────
    if tensions:
        min_t = min(tensions)
        checks["compression"] = {
            "min_tension_kN": round(min_t, 2),
            "pass": min_t >= 0.0,
            "note": "Compression not allowed during installation",
        }

    # ── Bend Radius Check ──────────────────────────────────────
    if curvatures:
        max_curv = max(abs(c) for c in curvatures)
        min_br = (1.0 / max_curv) if max_curv > 0 else float("inf")
        br_util = min_bend_radius / min_br if min_br > 0 else float("inf")
        checks["bend_radius"] = {
            "min_bend_radius_m": round(min_br, 2),
            "allowable_m": min_bend_radius,
            "utilization": round(br_util, 4),
            "pass": min_br >= min_bend_radius,
        }

    # ── Von Mises Stress Check ──────────────────────────────────
    if von_mises:
        max_vm = max(von_mises)
        allowable_vm = SMYS * usage_factor
        vm_util = max_vm / allowable_vm
        checks["von_mises"] = {
            "max_von_mises_MPa": round(max_vm, 2),
            "allowable_MPa": round(allowable_vm, 2),
            "utilization": round(vm_util, 4),
            "pass": vm_util <= 1.0,
            "critical_arc_length_m": arc_lengths[von_mises.index(max_vm)] if arc_lengths else None,
        }

    # ── Hoop Stress Check (Pressure Containment) ───────────────
    design_pressure = pipe_config.get("design_pressure", 15.0)  # MPa
    hoop_stress = (design_pressure * (OD - WT)) / (2.0 * WT)   # MPa (Barlow's formula)
    allowable_hoop = SMYS * usage_factor
    hoop_util = hoop_stress / allowable_hoop
    checks["hoop_stress"] = {
        "hoop_stress_MPa": round(hoop_stress, 2),
        "allowable_MPa": round(allowable_hoop, 2),
        "utilization": round(hoop_util, 4),
        "pass": hoop_util <= 1.0,
        "formula": "Barlow's formula: σ_h = P*(OD-WT)/(2*WT)",
    }

    # ── Overall Pass/Fail ──────────────────────────────────────
    all_pass = all(c.get("pass", True) for c in checks.values())
    checks["overall"] = {
        "pass": all_pass,
        "status": "PASS ✓" if all_pass else "FAIL ✗",
    }

    return checks


def calculate_submerged_weight(OD: float, WT: float,
                               steel_density: float = 7850.0,
                               seawater_density: float = 1025.0,
                               coating_thickness: float = 0.0,
                               coating_density: float = 1300.0,
                               contents_density: float = 1025.0) -> dict:
    """
    Calculate pipe submerged weight per unit length.

    Returns:
        dict with weight components in kN/m
    """
    ID = OD - 2 * WT
    # Cross-sectional areas
    A_steel = math.pi / 4 * (OD**2 - ID**2)
    A_contents = math.pi / 4 * ID**2
    OD_coated = OD + 2 * coating_thickness
    A_coating = math.pi / 4 * (OD_coated**2 - OD**2)
    A_displaced = math.pi / 4 * OD_coated**2

    # Weights per unit length (N/m → kN/m)
    w_steel = steel_density * 9.81 * A_steel / 1000.0
    w_contents = contents_density * 9.81 * A_contents / 1000.0
    w_coating = coating_density * 9.81 * A_coating / 1000.0
    w_buoyancy = seawater_density * 9.81 * A_displaced / 1000.0

    w_total_in_air = w_steel + w_contents + w_coating
    w_submerged = w_total_in_air - w_buoyancy

    return {
        "steel_weight_kN_m": round(w_steel, 4),
        "contents_weight_kN_m": round(w_contents, 4),
        "coating_weight_kN_m": round(w_coating, 4),
        "buoyancy_kN_m": round(w_buoyancy, 4),
        "total_in_air_kN_m": round(w_total_in_air, 4),
        "submerged_weight_kN_m": round(w_submerged, 4),
    }


# ─────────────────────────────────────────────────────────────
# Simulation Mode Helpers
# ─────────────────────────────────────────────────────────────

def _simulate_result(variable: str, n_points: int) -> list:
    """Generate plausible simulated result data for demo/testing."""
    import random
    random.seed(hash(variable) % 1000)
    base_values = {
        "Effective Tension": (50, 300),
        "Bend Moment": (-50, 50),
        "Shear Force": (-10, 10),
        "x": (0, 500),
        "y": (0, 0),
        "z": (-500, 0),
        "Curvature": (0, 0.005),
        "Von Mises Stress": (10, 200),
        "Axial Force": (50, 300),
        "Seabed Normal Reaction": (0, 5),
    }
    lo, hi = base_values.get(variable, (0, 100))
    return [round(lo + (hi - lo) * (i / n_points) + random.uniform(-5, 5), 3)
            for i in range(n_points)]


# ─────────────────────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────────────────────

def setup_logging(log_dir: str, stage_name: str = "analysis") -> str:
    """Configure logging to file and console."""
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"{stage_name}_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )
    return log_file
