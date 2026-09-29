"""Hydrodynamic properties of the PLET and the buoyancy module (DNVGL-RP-N103).

`plate_hydro` is the part of buoy6d.hydrodynamic_properties_rectangular_plate that
the initiation tool actually uses (volume, drag areas, deep-water Cd, adjusted Ca
and mass moments of inertia). Splash-zone / rotational outputs have been dropped.
"""
import math
import numpy as np

# Table A-2 Analytical added mass coefficient for three-dimensional bodies in infinite fluid
_LW_RATIO = [1, 1.2, 1.25, 1.33, 1.5, 1.59, 2, 2.5, 3, 3.17, 4, 5, 6.25, 8, 10, 1e3]
_CA = [0.579, 0.63, 0.642, 0.66, 0.690, 0.704, 0.757, 0.801, 0.830, 0.840, 0.872, 0.897, 0.917, 0.934, 0.947, 1.000]
# Table B-2 Drag coefficient, rectangular plate normal to flow direction
_LH_RATIO = [1, 5, 10, 11, 100, 1000, 10000]
_CDS_RECT = [1.16, 1.20, 1.50, 1.90, 1.90, 1.90, 1.90]
# Prism
_LW_RATIO_CD = [1, 1.5, 2, 2.5, 3, 4, 5]
_CDS_PRISM = [1.15, 0.97, 0.87, 0.9, 0.93, 0.95, 0.95]


def _perforation_factor(perf):
    """Reduction of added mass due to perforation."""
    if perf <= 0.05:
        return 1
    elif perf < 0.34:
        return 0.7 + 0.3 * math.cos(math.pi * (perf * 100 - 5) / 34)
    elif perf <= 0.50:
        return math.exp((10 - perf * 100) / 28)
    return 0.25


def _added_mass(a, b, c, roW, perf):
    ca_struct = np.interp(b / a, _LW_RATIO, _CA)
    # lambda factor to account for the "wall" effect
    lambda_fact = math.sqrt(a * b) / (c + math.sqrt(a * b))
    vol_ref = (math.pi / 4) * (a ** 2) * b
    added_mass = vol_ref * ca_struct * roW * (1 + math.sqrt((1 - lambda_fact ** 2) / (2 * (1 + lambda_fact ** 2))))
    return added_mass * _perforation_factor(perf)


def plate_hydro(length, width, height, wia, wiw, perf_x, perf_y, perf_z, roW, cog_x, cog_y, cog_z):
    """Hydrodynamic properties of a rectangular plate-like structure (the PLET envelope).

    Perforations are ratios (0 to 1). Returns a dict with the keys used by the base model.
    """
    volume = (wia - wiw) / roW

    # X direction
    a, b, c = min(width, height), max(width, height), length
    ca_x = _added_mass(a, b, c, roW, perf_x) / (roW * volume)
    drag_area_x = width * height * (1 - perf_x)
    if c / math.sqrt(a * b) < 1:
        cd_x = np.interp(c / math.sqrt(a * b), _LH_RATIO, _CDS_RECT)
    else:
        cd_x = np.interp(c / a, _LW_RATIO_CD, _CDS_PRISM)

    # Y direction
    a, b, c = min(length, height), max(length, height), width
    ca_y = _added_mass(a, b, c, roW, perf_y) / (roW * volume)
    drag_area_y = length * height * (1 - perf_y)
    if c / math.sqrt(a * b) < 1:
        cd_y = np.interp(b / a, _LH_RATIO, _CDS_RECT)
    else:
        cd_y = np.interp(b / a, _LW_RATIO_CD, _CDS_PRISM)

    # Z direction
    a, b, c = min(width, length), max(width, length), height
    ca_z = _added_mass(a, b, c, roW, perf_z) / (roW * volume)
    drag_area_z = width * length * (1 - perf_z)
    if c / math.sqrt(a * b) < 1:
        cd_z = np.interp(b / a, _LH_RATIO, _CDS_RECT)
    else:
        cd_z = np.interp(b / a, _LW_RATIO_CD, _CDS_PRISM)

    # Mass moment of inertia including parallel axis theorem
    ix = (wia / 12) * (width ** 2 + height ** 2) + wia * (cog_y ** 2 + cog_z ** 2)
    iy = (wia / 12) * (length ** 2 + height ** 2) + wia * (cog_x ** 2 + cog_z ** 2)
    iz = (wia / 12) * (length ** 2 + width ** 2) + wia * (cog_x ** 2 + cog_y ** 2)

    return {
        "volume": volume,
        "Ix": ix, "Iy": iy, "Iz": iz,
        "dragAreaX": drag_area_x, "dragAreaY": drag_area_y, "dragAreaZ": drag_area_z,
        "cdX": float(cd_x), "cdY": float(cd_y), "cdZ": float(cd_z),
        "caX": ca_x, "caY": ca_y, "caZ": ca_z,
    }


def buoyancy_module_hydro(length, width, height):
    """Hydrodynamic properties of the PLET buoyancy module."""
    # Table B-2 rectangular plate normal to flow direction
    b_to_h_plate_drag = [1, 5, 10, 10000]
    cds_plate = [1.16, 1.20, 1.50, 1.90]
    # Prism
    l_to_d_rod = [1, 1.5, 2, 2.5, 3, 4, 5]
    cds_rod = [1.15, 0.97, 0.87, 0.9, 0.93, 0.95, 0.95]
    # Table A-2
    b_to_a_flat = [1.000, 1.250, 1.500, 1.590, 2.000, 2.500, 3.000, 3.170, 4.000, 5.000, 6.250, 8.000, 10.000, 1000]
    ca_flat = [0.579, 0.642, 0.690, 0.704, 0.757, 0.801, 0.830, 0.840, 0.872, 0.897, 0.917, 0.934, 0.947, 1.000]
    b_to_a_prism = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 10.0]
    ca_prism = [0.68, 0.36, 0.24, 0.19, 0.15, 0.13, 0.11, 0.08]

    return {
        "dragAreaX": height * length,
        "dragAreaY": height * width,
        "dragAreaZ": length * width,
        "cdX": float(np.interp(height / length, b_to_h_plate_drag, cds_plate)),
        "cdY": float(np.interp(height / width, b_to_h_plate_drag, cds_plate)),
        "cdZ": float(max(np.interp(height / length, l_to_d_rod, cds_rod), np.interp(height / width, l_to_d_rod, cds_rod))),
        "caX": float(np.interp(height / length, b_to_a_flat, ca_flat)),
        "caY": float(np.interp(height / width, b_to_a_flat, ca_flat)),
        "caZ": float(max(np.interp(height / length, b_to_a_prism, ca_prism), np.interp(height / width, b_to_a_prism, ca_prism))),
    }
