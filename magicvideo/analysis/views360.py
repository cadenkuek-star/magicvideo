"""360° helpers shared by analysis and render: v360 filter strings and angle math."""
from __future__ import annotations

import math


def vfov_for(hfov: float, width: int, height: int) -> float:
    """Vertical FOV of a rectilinear view with the given horizontal FOV and aspect."""
    return math.degrees(2 * math.atan(math.tan(math.radians(hfov) / 2) * height / width))


def _input_opts(projection: str, fisheye_fov: float) -> str:
    if projection == "dual_fisheye":
        return f"input=dfisheye:ih_fov={fisheye_fov:g}:iv_fov={fisheye_fov:g}"
    return "input=e"


def analysis_view_filter(projection: str, yaw: float, hfov: float, size: tuple[int, int],
                         fisheye_fov: float = 200.0, pitch: float = 0.0) -> str:
    w, h = size
    return (f"v360={_input_opts(projection, fisheye_fov)}:output=flat:h_fov={hfov:g}:"
            f"v_fov={vfov_for(hfov, w, h):.3f}:yaw={yaw:g}:pitch={pitch:g}:w={w}:h={h}")


def multi_view_filter(projection: str, yaws: list[float], hfov: float, view_size: tuple[int, int],
                      fisheye_fov: float = 200.0) -> str:
    """One decode, N flat views side by side (hstack)."""
    n = len(yaws)
    if n == 1:
        return analysis_view_filter(projection, yaws[0], hfov, view_size, fisheye_fov)
    parts = [f"split={n}" + "".join(f"[i{k}]" for k in range(n))]
    for k, yaw in enumerate(yaws):
        parts.append(f"[i{k}]" + analysis_view_filter(projection, yaw, hfov, view_size, fisheye_fov) + f"[v{k}]")
    parts.append("".join(f"[v{k}]" for k in range(n)) + f"hstack=inputs={n}")
    return ";".join(parts)


def view_yaws(n: int) -> list[float]:
    """Evenly spaced view yaws within v360's [-180, 180] range: 0, 60, 120, 180, -120, -60 for n=6."""
    return [wrap180(round((360.0 / n) * k, 3)) for k in range(n)]


def yaw_of(view_yaw: float, cx: float, hfov: float) -> float:
    """Absolute yaw (deg) of a point at normalized x position cx in a rectilinear view."""
    off = math.degrees(math.atan((cx - 0.5) * 2 * math.tan(math.radians(hfov) / 2)))
    return wrap180(view_yaw + off)


def pitch_of(cy: float, vfov: float) -> float:
    return -math.degrees(math.atan((cy - 0.5) * 2 * math.tan(math.radians(vfov) / 2)))


def wrap180(a: float) -> float:
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def angle_diff(a: float, b: float) -> float:
    """Signed smallest difference a - b in degrees, within [-180, 180]."""
    return wrap180(a - b)


def circular_mean(angles: list[float]) -> float:
    if not angles:
        return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    return wrap180(math.degrees(math.atan2(s, c)))


def circular_spread(angles: list[float]) -> float:
    """Max pairwise angular distance (deg)."""
    best = 0.0
    for i in range(len(angles)):
        for j in range(i + 1, len(angles)):
            best = max(best, abs(angle_diff(angles[i], angles[j])))
    return best


def min_hfov_for_width(width: int, policy_min: dict) -> float:
    return float(policy_min["at_least_8k"] if width >= 7680 else policy_min["below_8k"])
