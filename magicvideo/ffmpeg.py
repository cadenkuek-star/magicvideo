"""ffmpeg / ffprobe wrappers. Argument lists only (no shell), Windows-safe."""
from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Iterator

import numpy as np

from .util import log


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    return os.environ.get("MAGICVIDEO_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.environ.get("MAGICVIDEO_FFPROBE") or shutil.which("ffprobe") or "ffprobe"


def run(args: list[str], cwd: Path | None = None, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", *[str(a) for a in args]]
    log.debug("ffmpeg %s", " ".join(cmd[1:]))
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=capture, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        tail = (proc.stderr or "")[-2000:]
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}): {' '.join(cmd[1:])[:500]}\n{tail}")
    return proc


def probe(path: Path) -> dict:
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path}: {proc.stderr[-500:]}")
    return json.loads(proc.stdout or "{}")


@functools.lru_cache(maxsize=None)
def filters() -> frozenset[str]:
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-filters"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    names = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and len(parts[0]) == 3 and set(parts[0]) <= set("TSC."):
            names.add(parts[1])
    return frozenset(names)


def has_filter(name: str) -> bool:
    return name in filters()


def count_frames(path: Path) -> int:
    """Decoded video frame count (slow path; used when the container lacks nb_frames)."""
    cmd = [ffprobe_bin(), "-v", "error", "-count_frames", "-select_streams", "v:0",
           "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return int(proc.stdout.strip().split(",")[0])
    except ValueError:
        return -1


def parse_rate(rate: str | None) -> Fraction | None:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        f = Fraction(rate)
    except (ValueError, ZeroDivisionError):
        return None
    return f if f > 0 else None


def even(x: float) -> int:
    v = int(round(x))
    return max(2, v - (v % 2))


def scaled_size(width: int, height: int, long_side: int) -> tuple[int, int]:
    if width >= height:
        return even(long_side), even(long_side * height / width)
    return even(long_side * width / height), even(long_side)


def read_frames(path: Path, fps: float, size: tuple[int, int], start: float | None = None,
                duration: float | None = None, gray: bool = False, extra_vf: str | None = None
                ) -> Iterator[tuple[float, np.ndarray]]:
    """Decode frames at `fps`, scaled to `size` (w, h) after autorotation. Yields (t, frame)."""
    w, h = size
    pix = "gray" if gray else "bgr24"
    channels = 1 if gray else 3
    vf = f"fps={fps},scale={w}:{h}:flags=area"
    if extra_vf:
        vf = f"{extra_vf},{vf}"
    args = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(path)]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += ["-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", pix, "-"]
    frame_bytes = w * h * channels
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        i = 0
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            arr = np.frombuffer(buf, dtype=np.uint8)
            frame = arr.reshape((h, w)) if gray else arr.reshape((h, w, 3))
            yield (start or 0.0) + i / fps, frame
            i += 1
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.kill()
        proc.wait()


def extract_audio(path: Path, out: Path, sample_rate: int = 16000, channels: int = 1) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["-y", "-v", "error", "-i", str(path), "-vn", "-ac", str(channels), "-ar", str(sample_rate),
         "-c:a", "pcm_s16le", str(out)])
    return out


def frame_png(path: Path, t: float, out: Path, vf: str | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-y", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1"]
    if vf:
        args += ["-vf", vf]
    run(args + [str(out)])
    return out


def gpu_available() -> bool:
    """True when an NVIDIA GPU is usable (CUDA via torch/onnxruntime, or nvidia-smi present)."""
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return True
    except Exception:
        pass
    try:
        import onnxruntime as ort  # type: ignore
        if "CUDAExecutionProvider" in ort.get_available_providers():
            return True
    except Exception:
        pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            return subprocess.run([smi, "-L"], capture_output=True, timeout=10).returncode == 0
        except Exception:
            return False
    return False
