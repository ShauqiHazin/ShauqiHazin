"""
Base Riser Model Template Builder
==================================
Creates a base OrcaFlex .dat file template for riser installation.
Run this script once to generate the base model file that the
main analysis script will load and modify per stage.

Usage:
    python templates/base_riser_model_builder.py
    python templates/base_riser_model_builder.py --output my_base_model.dat
"""

import os
import sys
import argparse
import logging
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.model_builder import RiserInstallationModelBuilder, SimulationModeModelBuilder
from utils.orcaflex_helpers import save_model, ORCAFLEX_AVAILABLE
from riser_installation_analysis import load_config

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")


def build_base_model(config_path: str, output_path: str) -> None:
    """Build and save the base OrcaFlex model."""
    config = load_config(config_path)

    if ORCAFLEX_AVAILABLE:
        builder = RiserInstallationModelBuilder(config)
    else:
        builder = SimulationModeModelBuilder(config)
        logger.warning("OrcaFlex not available. Cannot save .dat file in simulation mode.")

    model = builder.build_model()

    if model is not None:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        save_model(model, output_path)
        logger.info(f"Base model saved: {output_path}")
    else:
        logger.info("[SIM MODE] Base model template would be saved to: " + output_path)
        # Create a placeholder file
        with open(output_path.replace(".dat", "_placeholder.txt"), "w") as f:
            f.write("OrcaFlex base model placeholder.\n")
            f.write("Run with OrcaFlex installed to generate actual .dat file.\n")
        logger.info("Placeholder file created.")


def parse_args():
    parser = argparse.ArgumentParser(description="Build base OrcaFlex riser model")
    parser.add_argument("--config", "-c",
                        default=str(SCRIPT_DIR / "config" / "installation_config.yaml"))
    parser.add_argument("--output", "-o",
                        default=str(SCRIPT_DIR / "templates" / "base_riser_model.dat"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_base_model(args.config, args.output)
