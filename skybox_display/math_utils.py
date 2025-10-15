import math
from enum import StrEnum, auto


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on Earth.

    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates

    Returns:
        Distance in kilometers
    """
    R = 6371.0  # Earth radius in kilometers

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the bearing from point 1 to point 2.

    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates

    Returns:
        Bearing in degrees (0-360)
    """
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlon = lon2_rad - lon1_rad

    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)

    bearing = math.atan2(y, x)
    bearing = math.degrees(bearing)
    bearing = (bearing + 360) % 360

    return bearing


class ScaleMode(StrEnum):
    LINEAR = auto()
    LOG5 = auto()
    LOG10 = auto()


def range_scale(d: float, dmax: float, scale_mode: ScaleMode) -> float:
    """Convert distance using selected scale mode."""
    dmax = max(dmax, 1e-3)
    ratio = min(max(d / dmax, 0.0), 1.0)

    if scale_mode == ScaleMode.LOG5:
        f = math.log(1.0 + 4.0 * ratio, 5.0)
    elif scale_mode == ScaleMode.LOG10:
        f = math.log(1.0 + 9.0 * ratio, 10.0)
    else:  # linear
        f = ratio

    return min(max(f, 0.0), 1.0)

def quantise_range(dist: float, max_dist: float, inc: float) -> float:
    """Clip/quantise distance to specified increments and cap by max dist."""
    return max(inc, min(max_dist, math.ceil(dist / inc) * inc))


def pt_for_brg(cx: float, cy: float, r: float, brg_deg: float) -> tuple[float, float]:
    """Compute a point at a given bearing and distance from a center.

    The bearing convention matches aviation/radar displays:
    - 0 degrees points up (towards negative Y, i.e., North)
    - 90 degrees points right (positive X, i.e., East)

    Args:
        cx: Center X coordinate in pixels
        cy: Center Y coordinate in pixels
        r: Radial distance in pixels
        brg_deg: Bearing in degrees (0 = up/North, 90 = right/East)

    Returns:
        A tuple (x, y) of screen coordinates.
    """
    a = math.radians(brg_deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)
