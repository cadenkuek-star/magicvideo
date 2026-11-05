"""ffmpeg filter construction per render piece (brief §6.8). All file arguments are relative names."""
from __future__ import annotations

from ..analysis.views360 import vfov_for
from ..ffmpeg import has_filter

CUT_DEG = 60.0


def rotate_filters(rotate: int) -> list[str]:
    r = rotate % 360
    if r == 90:
        return ["transpose=1"]
    if r == 270:
        return ["transpose=2"]
    if r == 180:
        return ["hflip", "vflip"]
    return []


def stabilize_filters(trf_name: str, zoom: float, detect: bool) -> list[str]:
    """vidstab when available (two passes), else deshake + zoom crop (one pass)."""
    if has_filter("vidstabdetect") and has_filter("vidstabtransform"):
        if detect:
            return [f"vidstabdetect=shakiness=6:accuracy=12:result={trf_name}"]
        return [f"vidstabtransform=input={trf_name}:smoothing=20:zoom={zoom * 100:.1f}:optzoom=0",
                "unsharp=5:5:0.5:3:3:0.2"]
    keep = 1.0 - zoom
    return ["deshake=edge=clamp", f"crop=w='trunc(iw*{keep:.4f}/2)*2':h='trunc(ih*{keep:.4f}/2)*2'"]


def stabilize_backend() -> str:
    return "vidstab" if has_filter("vidstabdetect") and has_filter("vidstabtransform") else "deshake"


def reframe_filters(spec: dict, W: int, H: int) -> list[str]:
    mode = spec.get("mode", "fill")
    cx, cy = float(spec.get("cx", 0.5)), float(spec.get("cy", 0.5))
    if mode == "fill":
        return [f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos",
                f"crop={W}:{H}:x='max(0,min(iw-ow,{cx:.4f}*iw-ow/2))':y='max(0,min(ih-oh,{cy:.4f}*ih-oh/2))'"]
    if mode == "crop":
        if W >= H:  # portrait source into landscape master
            crop = f"crop=w=iw:h='trunc(iw*{H}/{W}/2)*2':x=0:y='max(0,min(ih-oh,{cy:.4f}*ih-oh/2))'"
        else:       # landscape source into portrait master
            crop = f"crop=w='trunc(ih*{W}/{H}/2)*2':h=ih:x='max(0,min(iw-ow,{cx:.4f}*iw-ow/2))':y=0"
        return [crop, f"scale={W}:{H}:flags=lanczos"]
    if mode == "static_bg":
        return [f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos"]
    raise ValueError(f"unknown reframe mode {mode}")


def v360_filter(spec: dict, W: int, H: int, cmd_name: str | None, fisheye_fov: float, start: list[float]) -> list[str]:
    proj = spec.get("projection", "equirect")
    inp = f"input=dfisheye:ih_fov={fisheye_fov:g}:iv_fov={fisheye_fov:g}" if proj == "dual_fisheye" else "input=e"
    _, yaw, pitch, hfov = start
    f = (f"v360={inp}:output=flat:h_fov={hfov:g}:v_fov={vfov_for(hfov, W, H):.3f}:yaw={yaw:g}:pitch={pitch:g}"
         f":w={W}:h={H}:interp=cubic")
    return ([f"sendcmd=f={cmd_name}"] if cmd_name else []) + [f]


def path_for_piece(path: list[list[float]], offset: int, frames: int) -> list[list[float]]:
    """Keyframes of a segment path re-based to a piece starting `offset` frames into the segment."""
    if not path:
        return [[0, 0.0, 0.0, 90.0]]
    before = [k for k in path if k[0] <= offset]
    start = list(before[-1]) if before else list(path[0])
    start[0] = 0
    out = [start]
    for k in path:
        if offset < k[0] < offset + frames:
            out.append([k[0] - offset, k[1], k[2], k[3]])
    return out


def per_frame_commands(path: list[list[float]], frames: int, fps: float, W: int, H: int) -> list[str]:
    """sendcmd lines with linear interpolation between keyframes (no interpolation across cuts)."""
    if len(path) <= 1:
        return []
    lines = []
    last = None
    for f in range(frames):
        prev = max((k for k in path if k[0] <= f), key=lambda k: k[0])
        nxt = [k for k in path if k[0] > f]
        yaw, pitch, hfov = prev[1], prev[2], prev[3]
        if nxt:
            n = min(nxt, key=lambda k: k[0])
            jump = abs(((n[1] - prev[1]) + 180) % 360 - 180)
            if jump <= CUT_DEG and n[0] > prev[0]:
                a = (f - prev[0]) / (n[0] - prev[0])
                d = ((n[1] - prev[1]) + 180) % 360 - 180
                yaw = ((prev[1] + a * d) + 180) % 360 - 180
                pitch = prev[2] + a * (n[2] - prev[2])
                hfov = prev[3] + a * (n[3] - prev[3])
        cur = (round(yaw, 2), round(pitch, 2), round(hfov, 2))
        if cur != last:
            t = f / fps
            parts = [f"v360 yaw {cur[0]:g}", f"v360 pitch {cur[1]:g}"]
            if last is None or cur[2] != last[2]:
                parts += [f"v360 h_fov {cur[2]:g}", f"v360 v_fov {vfov_for(cur[2], W, H):.3f}"]
            lines.append(f"{t:.4f} " + ", ".join(parts) + ";")
            last = cur
    return lines
