"""Sample-exact audio: per-segment PCM, dialogue level matching, master assembly, loudness (brief §6.8)."""
from __future__ import annotations

import json
import math
import re
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np

from .. import ffmpeg
from ..policy import Policy

CH = 2


def sample_bounds(start_frame: int, frames: int, fps: Fraction, sr: int) -> tuple[int, int]:
    a = int(round(start_frame * sr / fps))
    b = int(round((start_frame + frames) * sr / fps))
    return a, b


def extract_segment(src: Path, src_in: float, n: int, sr: int, has_audio: bool, fade_ms: float) -> np.ndarray:
    """float32 (n, 2) samples for one segment, exactly n long."""
    if not has_audio or n <= 0:
        return np.zeros((max(n, 0), CH), np.float32)
    cmd = [ffmpeg.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{src_in:.6f}", "-i", str(src),
           "-vn", "-map", "0:a:0", "-af", f"aresample={sr},aformat=sample_fmts=flt:channel_layouts=stereo,"
           f"apad,atrim=end_sample={n}", "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"]
    proc = subprocess.run(cmd, capture_output=True)
    data = np.frombuffer(proc.stdout, dtype=np.float32)
    data = data[: (len(data) // CH) * CH].reshape(-1, CH)
    if len(data) < n:
        data = np.vstack([data, np.zeros((n - len(data), CH), np.float32)])
    data = data[:n].copy()
    k = min(int(sr * fade_ms / 1000.0), n // 2)
    if k > 0:
        ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
        data[:k] *= ramp
        data[-k:] *= ramp[::-1]
    return data


def speech_level_db(x: np.ndarray, sr: int) -> float | None:
    """Speech-gated level: mean power of the loudest 60% of 50 ms frames above -50 dBFS."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    hop = int(0.05 * sr)
    if len(mono) < hop:
        return None
    frames = mono[: (len(mono) // hop) * hop].reshape(-1, hop)
    p = (frames ** 2).mean(axis=1)
    db = 10 * np.log10(p + 1e-12)
    db = db[db > -50]
    if len(db) < 4:
        return None
    db = np.sort(db)[int(len(db) * 0.4):]
    return float(10 * np.log10(np.mean(10 ** (db / 10))))


def dialogue_gains(levels: dict[str, float], max_db: float) -> dict[str, float]:
    if not levels:
        return {}
    med = float(np.median(list(levels.values())))
    return {k: float(np.clip(med - v, -max_db, max_db)) for k, v in levels.items()}


# --------------------------------------------------------------------------- loudness
_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def measure(raw_or_wav: Path, sr: int, raw: bool, target_i: float, target_tp: float, lra: float = 20.0) -> dict:
    args = ["-v", "info"]
    if raw:
        args += ["-f", "f32le", "-ar", str(sr), "-ac", "2"]
    args += ["-i", str(raw_or_wav), "-af",
             f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:print_format=json", "-f", "null", "-"]
    proc = ffmpeg.run(args)
    m = _JSON_RE.search(proc.stderr or "")
    if not m:
        raise ffmpeg.FFmpegError("loudnorm measurement JSON not found")
    d = json.loads(m.group(0))
    return {"I": float(d["input_i"]), "TP": float(d["input_tp"]), "LRA": float(d["input_lra"]),
            "thresh": float(d["input_thresh"])}


def master_loudness(raw: Path, out_wav: Path, policy: Policy) -> dict:
    """Linear gain to the target; oversampled limiter first when the gain would push TP over the limit."""
    sr = int(policy("audio.sample_rate"))
    target_i = float(policy("audio.integrated_lufs"))
    tp_lim = float(policy("audio.true_peak_dbtp"))
    log: dict = {"target_I": target_i, "target_TP": tp_lim, "linear": True, "limiter": False}
    m1 = measure(raw, sr, True, target_i, tp_lim)
    log["measured"] = m1
    if not math.isfinite(m1["I"]) or m1["I"] < -70:
        log["note"] = "silent master"
        ffmpeg.run(["-y", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", str(raw),
                    "-c:a", "pcm_f32le", str(out_wav)])
        log["gain_db"] = 0.0
        log["output"] = m1
        return log
    gain = target_i - m1["I"]
    chain = []
    src_meas = m1
    if m1["TP"] + gain > tp_lim:
        ceiling_db = tp_lim - gain - 0.7  # margin for inter-sample peaks after AAC
        lin = 10 ** (ceiling_db / 20)
        if lin < 0.0625:  # alimiter floor (-24 dB): cannot get there by limiting alone
            lin = 0.0625
            log["note"] = "limiter at its floor; integrated loudness will land below target"
        chain = [f"aresample={sr * 4}", f"alimiter=limit={lin:.5f}:level=false:attack=2:release=50:asc=1",
                 f"aresample={sr}"]
        limited = out_wav.with_name(out_wav.stem + "_limited.wav")
        ffmpeg.run(["-y", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", str(raw),
                    "-af", ",".join(chain), "-c:a", "pcm_f32le", str(limited)])
        src_meas = measure(limited, sr, False, target_i, tp_lim)
        log["limiter"] = True
        log["limiter_ceiling_db"] = round(20 * math.log10(lin), 2)
        log["after_limiter"] = src_meas
        gain = target_i - src_meas["I"]
        if src_meas["TP"] + gain > tp_lim:
            gain = tp_lim - src_meas["TP"] - 0.1
            log["note"] = "gain reduced to respect the true-peak limit"
        ffmpeg.run(["-y", "-v", "error", "-i", str(limited), "-af", f"volume={gain:.3f}dB",
                    "-c:a", "pcm_f32le", str(out_wav)])
        limited.unlink(missing_ok=True)
    else:
        ffmpeg.run(["-y", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", str(raw),
                    "-af", f"volume={gain:.3f}dB", "-c:a", "pcm_f32le", str(out_wav)])
    log["gain_db"] = round(gain, 3)
    log["output"] = measure(out_wav, sr, False, target_i, tp_lim)
    return log


# --------------------------------------------------------------------------- post-encode true-peak repair
def _spots(x: np.ndarray, sr: int, threshold: float, merge_s: float) -> list[tuple[float, float]]:
    """[(time, amplitude)] of over-threshold samples, nearby ones merged into the largest."""
    a = np.abs(x) if x.ndim == 1 else np.abs(x).max(axis=1)
    idx = np.flatnonzero(a > threshold)
    spots: list[tuple[float, float]] = []
    group: list[int] = []
    for i in idx:
        if group and (i - group[-1]) / sr > merge_s:
            best = max(group, key=lambda j: (a[j], -j))
            spots.append((best / sr, float(a[best])))
            group = []
        group.append(int(i))
    if group:
        best = max(group, key=lambda j: (a[j], -j))
        spots.append((best / sr, float(a[best])))
    return spots


def _merge_spots(spots: list[tuple[float, float]], merge_s: float) -> list[tuple[float, float]]:
    out: list[list[tuple[float, float]]] = []
    for s in sorted(spots):
        if out and s[0] - out[-1][-1][0] <= merge_s:
            out[-1].append(s)
        else:
            out.append([s])
    return [max(g, key=lambda s: (s[1], -s[0])) for g in out]


def overshoot_times(x: np.ndarray, sr: int, threshold: float, merge_s: float = 0.05) -> list[float]:
    """Times of samples above threshold (any channel); spots closer than merge_s keep the largest."""
    return [t for t, _ in _spots(x, sr, threshold, merge_s)]


def apply_dips(x: np.ndarray, sr: int, times: list[float], dip_db: float, win_ms: float) -> None:
    """Multiply x in place by a raised-cosine gain dip (unity at the edges) around each time; minimum where they overlap."""
    n = max(2, 2 * int(round(win_ms / 1000.0 * sr / 2)))
    half = n // 2
    g = 10 ** (-dip_db / 20)
    env = 1.0 - (1.0 - g) * 0.5 * (1.0 + np.cos(2 * np.pi * np.arange(-half, half + 1) / n))
    spans = sorted((int(round(t * sr)) - half, int(round(t * sr)) + half + 1) for t in times)
    clusters: list[list[int]] = []
    for a, b in spans:
        if clusters and a < clusters[-1][1]:
            clusters[-1][1] = max(clusters[-1][1], b)
        else:
            clusters.append([a, b])
    for ca, cb in clusters:
        gain = np.ones(cb - ca, np.float64)
        for a, b in spans:
            if a >= ca and b <= cb:
                gain[a - ca:b - ca] = np.minimum(gain[a - ca:b - ca], env)
        lo, hi = max(ca, 0), min(cb, len(x))
        if hi > lo:
            seg = gain[lo - ca:hi - ca].astype(np.float32)
            x[lo:hi] = x[lo:hi] * (seg[:, None] if x.ndim == 2 else seg)


def scan_true_peaks(path: Path, sr: int, threshold: float, chunk_s: float = 30.0, merge_s: float = 0.05) -> list[float]:
    """Absolute times where the decoded (4x oversampled) file exceeds threshold; decoded in chunks."""
    osr = 4 * sr
    spots: list[tuple[float, float]] = []
    start = 0.0
    while True:
        cmd = [ffmpeg.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.6f}",
               "-t", f"{chunk_s:.6f}", "-i", str(path), "-vn", "-map", "0:a:0", "-f", "f32le", "-ac", "2",
               "-ar", str(osr), "-"]
        data = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, dtype=np.float32)
        data = data[: (len(data) // CH) * CH].reshape(-1, CH)
        if len(data) == 0:
            break
        spots += [(start + t, a) for t, a in _spots(data, osr, threshold, merge_s)]
        if len(data) < chunk_s * osr * 0.999:
            break
        start += chunk_s
    return [t for t, _ in _merge_spots(spots, merge_s)]
