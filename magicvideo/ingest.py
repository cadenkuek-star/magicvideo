"""Inventory: probe every source file, detect camera / projection / capture time, group 360 files.

docs/IMPLEMENTATION_BRIEF.md §6.1
"""
from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import ffmpeg
from .util import log, sha1_hex, sha256_file

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".3gp", ".webm", ".insv", ".lrv"}
SKIP_DIR_NAMES = {"$recycle.bin", "system volume information", "output", "work", "people", "proxies",
                  "analysis", "render", "__pycache__", ".thumbnails", "misc"}

_DJI_RE = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))DJI_(\d{14})_(\d{4})", re.I)
_INSTA_RE = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))(VID|LRV|PRO_VID|PRO_LRV|IMG)_(\d{8})_(\d{6})_(\d{2})_(\d{3})", re.I)
_PIXEL_RE = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))(?:PXL|VID|IMG)_(\d{8})_(\d{6})", re.I)


# --------------------------------------------------------------------------- discovery
def discover(source_dirs: list[Path]) -> list[tuple[Path, Path]]:
    """Return (source_root, file) pairs for all video files, deterministic order."""
    found: list[tuple[Path, Path]] = []
    for root in source_dirs:
        root = Path(root)
        for p in sorted(root.rglob("*")):
            if any(part.lower() in SKIP_DIR_NAMES or part.startswith(".") for part in p.relative_to(root).parts[:-1]):
                continue
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not p.name.startswith("._"):
                found.append((root, p))
    return found


# --------------------------------------------------------------------------- parsing helpers
def filename_time(name: str) -> dt.datetime | None:
    """Camera-local capture time from DJI / Insta360 / Pixel style file names."""
    m = _DJI_RE.search(name)
    if m:
        try:
            return dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    m = _INSTA_RE.search(name)
    if m:
        try:
            return dt.datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    m = _PIXEL_RE.search(name)
    if m:
        try:
            return dt.datetime.strptime(m.group(1) + m.group(2)[:6], "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None


def insta360_key(name: str) -> tuple[str, str] | None:
    """(group key, kind) for Insta360 names; kind in {'vid','lrv'}; lens index in key suffix."""
    m = _INSTA_RE.search(name)
    if not m:
        return None
    prefix = m.group(1).upper()
    kind = "lrv" if "LRV" in prefix else "vid"
    return f"{m.group(2)}_{m.group(3)}_{m.group(5)}", kind


def _all_tags(info: dict) -> dict[str, str]:
    tags: dict[str, str] = {}
    for k, v in (info.get("format", {}).get("tags") or {}).items():
        tags[k.lower()] = str(v)
    for s in info.get("streams", []):
        for k, v in (s.get("tags") or {}).items():
            tags.setdefault(k.lower(), str(v))
    return tags


def parse_qt_date(value: str) -> dt.datetime | None:
    """Parse ISO-like dates, keeping timezone info when present."""
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    v = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", v)  # +0900 -> +09:00
    try:
        return dt.datetime.fromisoformat(v)
    except ValueError:
        return None


_TZ_WARNED: set[str] = set()


def to_local_naive(t: dt.datetime, timezone: str | None) -> dt.datetime:
    if t.tzinfo is None:
        return t
    if timezone:
        try:
            from zoneinfo import ZoneInfo
            return t.astimezone(ZoneInfo(timezone)).replace(tzinfo=None)
        except Exception as e:  # unknown name, or no tz database (Windows needs the `tzdata` package)
            if timezone not in _TZ_WARNED:
                _TZ_WARNED.add(timezone)
                log.warning("timezone %r unavailable (%s); capture times keep the camera's own offset. "
                            "On Windows run: pip install tzdata", timezone, e)
    # no trip timezone: keep the clock time the camera recorded with its own offset
    return t.replace(tzinfo=None)


def detect_camera(name: str, ext: str, tags: dict[str, str]) -> dict:
    blob = " ".join(f"{k}={v}" for k, v in tags.items()).lower()
    make = None
    model = tags.get("com.apple.quicktime.model") or tags.get("model") or tags.get("com.android.model")
    if _DJI_RE.search(name) or "dji" in blob:
        make = "DJI"
    elif ext in (".insv", ".lrv") or _INSTA_RE.search(name) or "insta360" in blob:
        make = "Insta360"
    elif tags.get("com.apple.quicktime.make", "").lower() == "apple" or "iphone" in blob:
        make = "Apple"
    elif "com.android.version" in tags or "android" in blob:
        make = tags.get("com.android.manufacturer") or "Android"
    if make == "DJI" and not model:
        for key in ("encoder", "handler_name", "comment", "com.dji.model"):
            if "dji" in tags.get(key, "").lower():
                model = tags[key]
                break
    m = (model or "").lower()
    if make == "Insta360":
        kind = "360"
    elif make == "DJI" and "pocket" in m:
        kind = "gimbal"
    elif make == "DJI" and ("nano" in m or "action" in m):
        kind = "action"
    elif make in ("Apple", "Android") or (make and "android" in make.lower()):
        kind = "phone"
    else:
        kind = "unknown"
    return {"make": make or "unknown", "model": model, "kind": kind}


def looks_dual_fisheye(frame: np.ndarray) -> bool:
    """Two side-by-side fisheye circles: all eight half-corners dark, centres bright."""
    if frame is None or frame.size == 0:
        return False
    g = frame if frame.ndim == 2 else frame.mean(axis=2)
    h, w = g.shape
    if abs(w - 2 * h) > 0.05 * w:
        return False
    half = w // 2
    k = max(2, h // 20)
    corners = []
    centers = []
    for x0 in (0, half):
        sub = g[:, x0:x0 + half]
        corners += [sub[:k, :k].mean(), sub[:k, -k:].mean(), sub[-k:, :k].mean(), sub[-k:, -k:].mean()]
        centers.append(sub[h // 2 - k:h // 2 + k, half // 2 - k:half // 2 + k].mean())
    return max(corners) < 16 and min(centers) > max(corners) + 20


def _first_frame_gray(path: Path, w: int, h: int, t: float) -> np.ndarray | None:
    size = ffmpeg.scaled_size(w, h, 256)
    for _, frame in ffmpeg.read_frames(path, fps=1, size=size, start=t, duration=1.1, gray=True):
        return frame
    return None


# --------------------------------------------------------------------------- probe one file
def probe_clip(root: Path, path: Path, timezone: str | None = None) -> dict:
    rel = path.relative_to(root).as_posix()
    info = ffmpeg.probe(path)
    streams = info.get("streams", [])
    vstreams = [s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0]
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    tags = _all_tags(info)
    ext = path.suffix.lower()
    clip: dict = {
        "clip_id": "c_" + sha1_hex(f"{root.name}/{rel}")[:10],
        "path": str(path),
        "rel_path": rel,
        "size": path.stat().st_size,
        "duration": float(info.get("format", {}).get("duration") or 0.0),
        "video_streams": len(vstreams),
        "camera": detect_camera(path.name, ext, tags),
        "role": "source",
        "group": None,
        "duplicate_of": None,
        "errors": [],
    }
    if not vstreams:
        clip["errors"].append("no video stream")
        clip.update({"fps": 0.0, "fps_rational": "0/1", "width": 0, "height": 0, "rotation": 0,
                     "display_w": 0, "display_h": 0, "orientation": "landscape", "projection": "flat",
                     "color": {}})
    else:
        v = vstreams[0]
        rate = ffmpeg.parse_rate(v.get("avg_frame_rate")) or ffmpeg.parse_rate(v.get("r_frame_rate"))
        rotation = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rotation = int(round(float(sd["rotation"])))
                except (TypeError, ValueError):
                    pass
        if not rotation and "rotate" in (v.get("tags") or {}):
            try:
                rotation = -int(v["tags"]["rotate"])  # legacy tag is clockwise; side data is counter-clockwise
            except ValueError:
                pass
        rotation %= 360
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        dw, dh = (h, w) if rotation in (90, 270) else (w, h)
        spherical = any("spherical" in str(sd.get("side_data_type", "")).lower()
                        and "equirect" in str(sd.get("projection", "")).lower()
                        for sd in v.get("side_data_list", []) or [])
        transfer = v.get("color_transfer")
        clip.update({
            "fps": float(rate) if rate else 0.0,
            "fps_rational": f"{rate.numerator}/{rate.denominator}" if rate else "0/1",
            "width": w, "height": h, "rotation": rotation,
            "display_w": dw, "display_h": dh,
            "orientation": "portrait" if dh > dw else ("square" if dh == dw else "landscape"),
            "color": {
                "transfer": transfer, "primaries": v.get("color_primaries"), "matrix": v.get("color_space"),
                "log_profile": _log_profile(tags, transfer),
            },
            "codec": v.get("codec_name"),
            "projection": "equirect" if spherical else "flat",
        })
        if not spherical and clip["camera"]["make"] == "Insta360":
            two_to_one = w > 0 and abs(w - 2 * h) <= 0.02 * w
            if ext == ".insv" or len(vstreams) >= 2:
                clip["projection"] = "dual_fisheye"
            elif two_to_one:
                frame = _first_frame_gray(path, w, h, min(1.0, clip["duration"] / 2))
                clip["projection"] = "dual_fisheye" if looks_dual_fisheye(frame) else "equirect"
    clip["has_audio"] = bool(astreams)
    clip["audio_channels"] = int(astreams[0].get("channels") or 0) if astreams else 0
    clip["audio_rate"] = int(astreams[0].get("sample_rate") or 0) if astreams else 0

    # capture time
    t = filename_time(path.name)
    source = "filename"
    if t is None:
        qt = parse_qt_date(tags.get("com.apple.quicktime.creationdate", ""))
        if qt is not None:
            t, source = to_local_naive(qt, timezone), "qt_creationdate"
    if t is None:
        ct = parse_qt_date(tags.get("creation_time", ""))
        if ct is not None:
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=dt.timezone.utc)
            t, source = to_local_naive(ct, timezone), "creation_time"
    if t is None:
        t, source = dt.datetime.fromtimestamp(path.stat().st_mtime), "mtime"
    clip["capture_start"] = t.replace(microsecond=0).isoformat()
    clip["capture_source"] = source
    clip["location"] = _parse_location(tags.get("com.apple.quicktime.location.iso6709") or tags.get("location"))
    clip["analysis_path"] = str(path)
    clip["render_path"] = str(path)
    return clip


def _log_profile(tags: dict[str, str], transfer: str | None) -> str | None:
    blob = " ".join(tags.values()).lower()
    if "d-log m" in blob or "dlogm" in blob or "d-log-m" in blob:
        return "d-log-m"
    if "d-log" in blob or "dlog" in blob:
        return "d-log"
    if transfer == "arib-std-b67":
        return "hlg"
    if transfer == "smpte2084":
        return "pq"
    return None


def _parse_location(value: str | None) -> list[float] | None:
    if not value:
        return None
    m = re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", value)
    if not m:
        return None
    return [float(m.group(1)), float(m.group(2))]


# --------------------------------------------------------------------------- grouping
def group_insta360(clips: list[dict]) -> None:
    """Link Insta360 recordings: .insv (+second lens), .lrv proxy, stitched equirect exports."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in clips:
        key = insta360_key(Path(c["path"]).name)
        if key and c["camera"]["make"] == "Insta360":
            groups[key[0]].append(c)
    for key, members in groups.items():
        members.sort(key=lambda c: c["rel_path"])
        lrvs = [c for c in members if c["path"].lower().endswith(".lrv")]
        insvs = [c for c in members if c["path"].lower().endswith(".insv")]
        exports = [c for c in members if c not in lrvs and c not in insvs and c["projection"] == "equirect"]
        flats = [c for c in members if c not in lrvs and c not in insvs and c["projection"] == "flat"]
        primary = insvs[0] if insvs else (exports[0] if exports else (flats[0] if flats else members[0]))
        for c in members:
            c["group"] = key
            if c is not primary:
                c["role"] = "lrv" if c in lrvs else ("second_lens" if c in insvs else
                                                     ("stitched_export" if c in exports else "companion"))
        if exports and primary is not exports[0]:
            primary["render_path"] = exports[0]["path"]
            primary["render_projection"] = "equirect"
        else:
            primary["render_projection"] = primary["projection"]
        primary["analysis_path"] = lrvs[0]["path"] if lrvs else primary["render_path"]
        primary["analysis_projection"] = (lrvs[0]["projection"] if lrvs else primary["render_projection"])
        # reframed flat exports from the phone app stay independent clips, but are marked
        for f in flats:
            if f is not primary:
                f["role"] = "source"
                f["note"] = f"flat export of 360 recording {key}"


def mark_duplicates(clips: list[dict]) -> None:
    by_size: dict[int, list[dict]] = defaultdict(list)
    for c in clips:
        by_size[c["size"]].append(c)
    for same in by_size.values():
        if len(same) < 2:
            continue
        hashes: dict[str, dict] = {}
        for c in sorted(same, key=lambda c: c["rel_path"]):
            h = sha256_file(Path(c["path"]))
            c["sha256"] = h
            if h in hashes:
                c["duplicate_of"] = hashes[h]["clip_id"]
            else:
                hashes[h] = c


def apply_device_offsets(clips: list[dict], devices: list[dict]) -> None:
    for c in clips:
        for d in devices:
            make_ok = (d.get("make") or "").lower() in ("", c["camera"]["make"].lower())
            model_ok = d.get("model") in (None, "", c["camera"].get("model"))
            if make_ok and model_ok and d.get("offset_s"):
                t = dt.datetime.fromisoformat(c["capture_start"]) + dt.timedelta(seconds=float(d["offset_s"]))
                c["capture_start"] = t.isoformat()
                c["capture_offset_s"] = float(d["offset_s"])
                break


def build_inventory(source_dirs: list[Path], timezone: str | None = None, devices: list[dict] | None = None) -> list[dict]:
    clips = []
    for root, path in discover(source_dirs):
        try:
            clips.append(probe_clip(root, path, timezone))
        except Exception as e:  # corrupt file: keep a record, never crash the whole trip
            log.warning("probe failed for %s: %s", path, e)
            clips.append({"clip_id": "c_" + sha1_hex(f"{root.name}/{path.relative_to(root).as_posix()}")[:10],
                          "path": str(path), "rel_path": path.relative_to(root).as_posix(),
                          "size": path.stat().st_size, "duration": 0.0, "errors": [f"probe failed: {e}"],
                          "role": "corrupt", "camera": {"make": "unknown", "model": None, "kind": "unknown"},
                          "capture_start": dt.datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat(),
                          "capture_source": "mtime", "duplicate_of": None, "group": None})
    group_insta360(clips)
    mark_duplicates([c for c in clips if c.get("role") != "corrupt"])
    apply_device_offsets(clips, devices or [])
    clips.sort(key=lambda c: (c["capture_start"], c["rel_path"]))
    return clips


def plannable(clips: list[dict]) -> list[dict]:
    """Clips that the planner may use (primary sources, not duplicates/corrupt/companions)."""
    return [c for c in clips if c.get("role") == "source" and not c.get("duplicate_of")
            and not c.get("errors") and c.get("duration", 0) > 0]
