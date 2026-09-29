"""
Version
=======
0.1.0, January 20, 2025
=======
General functions used at multiple stages"""

import json
import math
from typing import Dict

from . import constants
import OrcFxAPI


def read_json_file(file_path) -> Dict:
    with open(file_path, "r") as file:
        data = json.load(file)

    return data


def calc_statics_with_damping(model):
    """Calculate system statics, increase system minimum and maximum damping factor to ensure static convergence."""

    for attempt in range(1, 4):
        try:
            model.CalculateStatics()
            return

        except OrcFxAPI.DLLError as e:
            print(
                f"\tNon-convergence error: {e}. Attempt to increase minimum and maximum damping factors."
            )

            # OrcaFlex error code for non-convergence is 27
            if e.status.value == 27:
                attempt += 1
                new_min_damping = math.ceil(
                    model["General"].StaticsMinDamping
                    * constants.DAMPING_CORRECTION_FACTOR
                )
                new_max_damping = math.ceil(
                    model["General"].StaticsMaxDamping
                    * constants.DAMPING_CORRECTION_FACTOR
                )
                print(
                    f"\tChanging whole system static damping to Min:{new_min_damping} Max:{new_max_damping}"
                )
                model["General"].StaticsMinDamping = new_min_damping
                model["General"].StaticsMaxDamping = new_max_damping

            else:
                print(f"Static system does not converge. Error: {e}")
                return

        except Exception as e:
            print(f"Unexpected Error: {e}")
            return

    print(
        f"Static system does not converge after {attempt} attempts of adjusting damping factor."
    )
    return


def adjust_anchor_for_zero_bm(initial_anchor_position, model):
    """Adjust anchor position (pipe.EndBX) to get zero bending moment at the top."""
    pipe = model[constants.PIPE_NAME]
    pipe.EndBX = initial_anchor_position

    model.CalculateStatics()
    pipe_y_bm = pipe.StaticResult("y bend moment", OrcFxAPI.oeEndA)

    return pipe_y_bm
