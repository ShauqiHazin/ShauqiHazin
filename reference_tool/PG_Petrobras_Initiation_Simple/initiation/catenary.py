import math

import numpy as np
from scipy import optimize


# Following function is taken from NL_Buildstatic.py
def find_catenary_starting_shape(w_depth, ramp_angle):
    """Estimates a catenary shape for an initial static analysis guess.

    Calculates an initial anchor position and total line length for a catenary
    based on water depth and hang-off angle, using a scaled and shifted cosh curve.

    Args:
        w_depth (float): The water depth.
        ramp_angle (float): The hang-off angle at the top of the catenary (in degrees).

    Returns:
        tuple: (anchor position relative to hang-off, total catenary line length)
    """
    ramp_angle = float(ramp_angle)

    # Graph parameters
    if ramp_angle >= 45:
        end_angle = 45
    else:
        end_angle = ramp_angle

    end_angle_rad = math.radians(end_angle)
    graphX_atEnd = math.log(
        (math.sin(end_angle_rad) + 1) / math.cos(end_angle_rad), math.exp(1)
    )
    scale_factor = w_depth / math.cosh(graphX_atEnd)

    if w_depth >= 50:
        stretch_factor = 0.08
    else:
        # Factor to stretch Y values to achieve start shape catenary starting from below seabed level and ending at sea-level
        stretch_factor = 0.50

    xG0 = -0.8  # Starting X for unit graph
    gN = 50  # number of points on graph

    # np.cosh: fsolve passes 1-element arrays (math.cosh fails on those with numpy >= 2)
    def find_graphXo(x):
        """Iterate on x value to set catenary y to zero."""
        yG0 = np.cosh(x)
        yC0 = (yG0 - 1) * scale_factor - w_depth * stretch_factor
        return yC0

    xG0 = optimize.fsolve(find_graphXo, xG0)

    def find_graphXinc_setWD(inc):
        """Iterate on x increment to set final catenary height (yCn) to water depth."""
        yCn = (
            (np.cosh(xG0[0] + (gN - 1) * inc)) - 1
        ) * scale_factor - w_depth * stretch_factor
        return yCn - w_depth

    graph_inc = optimize.fsolve(find_graphXinc_setWD, 0.1)[0]

    def catenary_(n):
        """Creates X.Y points on graph that describes catenary, belly of catenary will be at X=0."""
        xCn = (xG0[0] + n * graph_inc) * scale_factor
        yCn = (
            (math.cosh(xG0[0] + n * graph_inc)) - 1
        ) * scale_factor - w_depth * stretch_factor
        return [xCn, yCn]

    arc_graph = [catenary_(k) for k in range(gN)]

    # Create array of segment lengths
    arc_graph_segLengths = [
        math.sqrt(
            (y[0] - arc_graph[x - 1][0]) ** 2 + (y[1] - arc_graph[x - 1][1]) ** 2
        )
        for x, y in enumerate(arc_graph)
        if x != 0
    ]
    x_sBed_pos = arc_graph[0][0]
    x_sLevel_pos = arc_graph[-1][0]
    total_lineL = int(sum(arc_graph_segLengths))
    # Distance between ends of catenary graph, corresponds to relative position between anchor and hang-off
    anchor_pos = -1 * (x_sLevel_pos - x_sBed_pos)

    return anchor_pos, total_lineL
