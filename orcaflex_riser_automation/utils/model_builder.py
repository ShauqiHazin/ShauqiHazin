"""
OrcaFlex Model Builder
======================
Builds and configures OrcaFlex models for riser installation
static analysis from configuration dictionaries.
"""

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import OrcFxAPI as ofx
    ORCAFLEX_AVAILABLE = True
except ImportError:
    ORCAFLEX_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# Main Model Builder
# ─────────────────────────────────────────────────────────────

class RiserInstallationModelBuilder:
    """
    Builds an OrcaFlex model for riser installation static analysis.

    Usage:
        builder = RiserInstallationModelBuilder(config)
        model = builder.build_model()
        builder.configure_stage(model, stage_config)
    """

    def __init__(self, config: dict):
        """
        Args:
            config: Full configuration dict (loaded from YAML).
        """
        self.config = config
        self.vessel_cfg = config.get("vessel", {})
        self.riser_cfg = config.get("riser", {})
        self.env_cfg = config.get("environment", {})
        self.seabed_cfg = config.get("seabed", {})
        self.analysis_cfg = config.get("analysis", {})

    # ─────────────────────────────────────────────────────────
    # Build Base Model
    # ─────────────────────────────────────────────────────────

    def build_model(self) -> Optional[object]:
        """
        Create and configure a new OrcaFlex model with:
        - General settings
        - Environment (water depth, current, seabed)
        - Vessel
        - Line type (pipe properties)
        - Riser line

        Returns:
            OrcaFlex Model object, or None in simulation mode.
        """
        if not ORCAFLEX_AVAILABLE:
            logger.warning("[SIM MODE] Would build OrcaFlex model from config.")
            return None

        model = ofx.Model()
        logger.info("Building OrcaFlex model...")

        self._configure_general(model)
        self._configure_environment(model)
        self._configure_seabed(model)
        self._add_vessel(model)
        self._add_line_type(model)
        self._add_riser_line(model)

        logger.info("OrcaFlex model built successfully.")
        return model

    # ─────────────────────────────────────────────────────────
    # General Settings
    # ─────────────────────────────────────────────────────────

    def _configure_general(self, model) -> None:
        """Configure general model settings."""
        gen = model.general
        gen.StageDuration[0] = 0.0          # Static only
        gen.ImplicitConstantTimeStep = 0.1
        gen.Gravity = self.analysis_cfg.get("gravity", 9.81)
        logger.debug("General settings configured.")

    # ─────────────────────────────────────────────────────────
    # Environment
    # ─────────────────────────────────────────────────────────

    def _configure_environment(self, model) -> None:
        """Configure water depth, density, and current profile."""
        env = model.environment
        env.WaterDepth = self.env_cfg.get("water_depth", 500.0)
        env.WaterDensity = self.env_cfg.get("seawater_density", 1025.0)
        env.KinematicViscosity = self.env_cfg.get("kinematic_viscosity", 1.35e-6)

        # Current profile
        current_profile = self.env_cfg.get("current_profile", [])
        if current_profile:
            depths = [cp["depth"] for cp in current_profile]
            speeds = [cp["speed"] for cp in current_profile]
            directions = [cp["direction"] for cp in current_profile]
            env.RefCurrentSpeed = speeds
            env.RefCurrentDirection = directions
            env.RefCurrentDepth = depths

        # No waves / wind for static
        env.WaveType = "None"
        logger.debug(f"Environment configured: depth={env.WaterDepth} m")

    # ─────────────────────────────────────────────────────────
    # Seabed
    # ─────────────────────────────────────────────────────────

    def _configure_seabed(self, model) -> None:
        """Configure seabed properties."""
        gen = model.general
        gen.SeabedType = self.seabed_cfg.get("type", "Elastic")
        gen.SeabedNormalStiffness = self.seabed_cfg.get("stiffness", 100.0)
        gen.SeabedShearStiffness = (
            self.seabed_cfg.get("stiffness", 100.0) *
            self.seabed_cfg.get("friction_coefficient", 0.5)
        )
        logger.debug("Seabed configured.")

    # ─────────────────────────────────────────────────────────
    # Vessel
    # ─────────────────────────────────────────────────────────

    def _add_vessel(self, model) -> None:
        """Add and configure the lay vessel."""
        vessel_name = self.vessel_cfg.get("name", "Lay Vessel")
        vessel = model.CreateObject(ofx.ObjectType.Vessel, vessel_name)

        init_pos = self.vessel_cfg.get("initial_position", {})
        vessel.InitialX = init_pos.get("x", 0.0)
        vessel.InitialY = init_pos.get("y", 0.0)
        vessel.InitialZ = init_pos.get("z", 0.0)
        vessel.InitialHeading = self.vessel_cfg.get("heading", 0.0)

        logger.debug(f"Vessel '{vessel_name}' added.")

    # ─────────────────────────────────────────────────────────
    # Line Type (Pipe Properties)
    # ─────────────────────────────────────────────────────────

    def _add_line_type(self, model) -> None:
        """Create a line type with pipe material properties."""
        lt_name = f"{self.riser_cfg.get('name', 'Riser')} Pipe"
        lt = model.CreateObject(ofx.ObjectType.LineType, lt_name)

        OD = self.riser_cfg.get("outer_diameter", 0.3239)
        WT = self.riser_cfg.get("wall_thickness", 0.0254)
        ID = OD - 2 * WT
        E = self.riser_cfg.get("youngs_modulus", 2.07e11)
        nu = self.riser_cfg.get("poissons_ratio", 0.3)
        rho_steel = self.riser_cfg.get("density", 7850.0)

        # Coating
        coating = self.riser_cfg.get("coating", {})
        coat_t = coating.get("thickness", 0.0)
        coat_rho = coating.get("density", 1300.0)
        OD_coated = OD + 2 * coat_t

        # Cross-section areas
        A_steel = math.pi / 4 * (OD**2 - ID**2)
        A_coat = math.pi / 4 * (OD_coated**2 - OD**2)
        A_bore = math.pi / 4 * ID**2

        # Second moment of area
        I = math.pi / 64 * (OD**4 - ID**4)

        # Bending stiffness EI
        EI = E * I

        # Axial stiffness EA
        EA = E * A_steel

        # Mass per unit length
        contents_rho = self.riser_cfg.get("contents", {}).get("density", 1025.0)
        mass_per_m = (rho_steel * A_steel + coat_rho * A_coat +
                      contents_rho * A_bore)

        lt.OD = OD_coated
        lt.ID = ID
        lt.MassPerUnitLength = mass_per_m
        lt.BendingStiffness = EI
        lt.AxialStiffness = EA
        lt.TorsionalStiffness = EI / (2 * (1 + nu))  # GJ approx
        lt.NormalDragCoefficient = 1.2
        lt.AxialDragCoefficient = 0.008
        lt.NormalAddedMassCoefficient = 1.0

        logger.debug(f"Line type '{lt_name}' created: OD={OD_coated:.4f}m, EI={EI:.3e} N·m²")

    # ─────────────────────────────────────────────────────────
    # Riser Line
    # ─────────────────────────────────────────────────────────

    def _add_riser_line(self, model) -> None:
        """Add the riser line to the model."""
        riser_name = self.riser_cfg.get("name", "Production Riser")
        lt_name = f"{riser_name} Pipe"
        vessel_name = self.vessel_cfg.get("name", "Lay Vessel")
        water_depth = self.env_cfg.get("water_depth", 500.0)

        line = model.CreateObject(ofx.ObjectType.Line, riser_name)

        # Line type assignment
        line.LineType[0] = lt_name

        # Initial length (will be updated per stage)
        line.Length[0] = water_depth * 1.05  # Slightly longer than water depth

        # End A: connected to vessel (top)
        line.EndAConnection = vessel_name
        line.EndAX = 0.0
        line.EndAY = 0.0
        line.EndAZ = -self.vessel_cfg.get("draft", 8.5)

        # End B: free (touchdown on seabed)
        line.EndBConnection = "Anchored"
        line.EndBX = 0.0
        line.EndBY = 0.0
        line.EndBZ = -water_depth

        # Segment discretization
        line.NumberOfSections = 1
        line.TargetSegmentLength[0] = 2.0  # 2 m segments

        logger.debug(f"Riser line '{riser_name}' added.")

    # ─────────────────────────────────────────────────────────
    # Stage Configuration
    # ─────────────────────────────────────────────────────────

    def configure_stage(self, model, stage_config: dict) -> None:
        """
        Update model parameters for a specific installation stage.

        Args:
            model: OrcaFlex model object
            stage_config: dict with stage parameters
        """
        if not ORCAFLEX_AVAILABLE or model is None:
            logger.warning(f"[SIM MODE] Would configure stage: {stage_config.get('name')}")
            return

        vessel_name = self.vessel_cfg.get("name", "Lay Vessel")
        riser_name = self.riser_cfg.get("name", "Production Riser")
        water_depth = self.env_cfg.get("water_depth", 500.0)

        # Update vessel position
        vessel = model[vessel_name]
        vessel.InitialX = stage_config.get("vessel_position", 0.0)
        vessel.InitialY = 0.0
        vessel.InitialZ = 0.0

        # Update riser length
        line = model[riser_name]
        deployed_length = stage_config.get("riser_length_deployed", water_depth)
        line.Length[0] = deployed_length

        # Update layback (End B horizontal position)
        layback = stage_config.get("layback", 0.0)
        line.EndBX = stage_config.get("vessel_position", 0.0) - layback
        line.EndBY = 0.0
        line.EndBZ = -water_depth

        logger.info(f"Stage '{stage_config.get('name')}' configured: "
                    f"vessel_x={stage_config.get('vessel_position')} m, "
                    f"length={deployed_length} m, layback={layback} m")


# ─────────────────────────────────────────────────────────────
# Simulation Mode Model Builder
# ─────────────────────────────────────────────────────────────

class SimulationModeModelBuilder(RiserInstallationModelBuilder):
    """
    Simulation mode builder — works without OrcaFlex installed.
    Returns None for model but logs all operations.
    """

    def build_model(self):
        logger.info("[SIM MODE] Building simulated model (no OrcaFlex).")
        self._log_config()
        return None

    def _log_config(self):
        logger.info(f"  Vessel: {self.vessel_cfg.get('name')}")
        logger.info(f"  Riser: {self.riser_cfg.get('name')}, "
                    f"OD={self.riser_cfg.get('outer_diameter')} m")
        logger.info(f"  Water depth: {self.env_cfg.get('water_depth')} m")
        logger.info(f"  Seabed stiffness: {self.seabed_cfg.get('stiffness')} kN/m/m2")

    def configure_stage(self, model, stage_config: dict):
        logger.info(f"[SIM MODE] Configuring stage: {stage_config.get('name')}")
        logger.info(f"  Vessel position: {stage_config.get('vessel_position')} m")
        logger.info(f"  Riser length: {stage_config.get('riser_length_deployed')} m")
        logger.info(f"  Top tension: {stage_config.get('top_tension')} kN")
        logger.info(f"  Layback: {stage_config.get('layback')} m")
