"""Per-sample picture quality and camera jitter (docs/IMPLEMENTATION_BRIEF.md §6.2).

jitter = |camera path - smoothed path| / frame diagonal, so deliberate pans are not penalised.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import ffmpeg
from ..policy import Policy
from .views360 import analysis_view_filter

LAPLACE_K = 50.0     # normalisation constant for Laplacian variance at ~320 px (sharp = v / (v + K))
WHITE_LEVEL = 245    # 8-bit level counted as near-white
DESC_EVERY_S = 1.0   # visual descriptor cadence


def _cv2():
    import cv2  # local import keeps module importable for docs/tests without OpenCV
    return cv2


def global_motion(prev_gray: np.ndarray, gray: np.ndarray) -> tuple[float, float, float, bool]:
    """(dx, dy, dangle, ok) between two frames via sparse optical flow + partial affine fit."""
    cv2 = _cv2()
    pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=200, qualityLevel=0.01, minDistance=8, blockSize=3)
    if pts is None or len(pts) < 8:
        return 0.0, 0.0, 0.0, False
    nxt, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None, winSize=(21, 21), maxLevel=3)
    if nxt is None:
        return 0.0, 0.0, 0.0, False
    good = status.reshape(-1) == 1
    if good.sum() < 8:
        return 0.0, 0.0, 0.0, False
    m, _ = cv2.estimateAffinePartial2D(pts[good], nxt[good], method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if m is None:
        return 0.0, 0.0, 0.0, False
    return float(m[0, 2]), float(m[1, 2]), float(np.arctan2(m[1, 0], m[0, 0])), True


def moving_average(x: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(x) == 0:
        return x.copy()
    window = min(window, len(x) if len(x) % 2 else max(1, len(x) - 1))
    if window % 2 == 0:
        window += 1
    pad = window // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    kernel = np.ones(window) / window
    return np.convolve(xp, kernel, mode="valid")


def jitter_from_motion(dx: np.ndarray, dy: np.ndarray, da: np.ndarray, diag: float, window: int) -> np.ndarray:
    px, py, pa = np.cumsum(dx), np.cumsum(dy), np.cumsum(da)
    rx = px - moving_average(px, window)
    ry = py - moving_average(py, window)
    ra = (pa - moving_average(pa, window)) * diag / 2.0
    return np.sqrt(rx ** 2 + ry ** 2 + ra ** 2) / diag


def descriptor(frame_bgr: np.ndarray) -> np.ndarray:
    """Cheap appearance descriptor for near-duplicate detection and novelty (L2-normalised)."""
    cv2 = _cv2()
    small = cv2.resize(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY), (16, 9), interpolation=cv2.INTER_AREA)
    g = small.astype(np.float32).reshape(-1)
    g = (g - g.mean()) / (g.std() + 1e-6)
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256]).reshape(-1).astype(np.float32)
    hist = hist / (hist.sum() + 1e-6) * 12.0
    v = np.concatenate([g * 0.5, hist])
    return v / (np.linalg.norm(v) + 1e-9)


def analyze(path: Path, clip: dict, policy: Policy) -> tuple[dict, np.ndarray]:
    cv2 = _cv2()
    fps = float(policy("quality.sample_fps"))
    proj = clip.get("analysis_projection", clip.get("projection", "flat"))
    extra_vf = None
    if proj in ("equirect", "dual_fisheye"):
        # judge 360 footage on a forward-looking flat view
        extra_vf = analysis_view_filter(proj, yaw=0.0, hfov=100.0, size=(640, 360),
                                        fisheye_fov=float(policy("insta360.fisheye_fov_deg")))
        w, h = 320, 180
    else:
        w, h = ffmpeg.scaled_size(clip["display_w"], clip["display_h"], int(policy("quality.proxy_px")))
    diag = float(np.hypot(w, h))
    ts, sharp, luma, white, black_flag = [], [], [], [], []
    dx, dy, da, ok = [], [], [], []
    descs, desc_t = [], []
    prev = None
    next_desc = 0.0
    black_max = float(policy("quality.black_luma_max"))
    for t, frame in ffmpeg.read_frames(Path(path), fps=fps, size=(w, h), extra_vf=extra_vf):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        lv = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        ts.append(t)
        sharp.append(lv / (lv + LAPLACE_K))
        m = float(gray.mean()) / 255.0
        luma.append(m)
        white.append(float((gray >= WHITE_LEVEL).mean()))
        black_flag.append(1.0 if m < black_max else 0.0)
        if prev is None:
            dx.append(0.0); dy.append(0.0); da.append(0.0); ok.append(True)
        else:
            a, b, c, good = global_motion(prev, gray)
            dx.append(a); dy.append(b); da.append(c); ok.append(good)
        prev = gray
        if t >= next_desc:
            descs.append(descriptor(frame))
            desc_t.append(t)
            next_desc = t + DESC_EVERY_S
    n = len(ts)
    if n == 0:
        return {"fps": fps, "t": [], "sharp": [], "luma": [], "white": [], "black": [], "motion": [],
                "jitter": [], "desc_t": []}, np.zeros((0, 176), np.float32)
    dxa, dya, daa = np.array(dx), np.array(dy), np.array(da)
    window = max(1, int(round(float(policy("quality.jitter_smooth_s")) * fps)))
    jit = jitter_from_motion(dxa, dya, daa, diag, window)
    # frames where motion estimation failed (e.g. lens covered) count as unstable
    for i, good in enumerate(ok):
        if not good and i > 0:
            jit[i] = max(jit[i], float(policy("quality.jitter.high")))
    motion = np.hypot(dxa, dya) / diag
    data = {
        "fps": fps, "t": ts, "sharp": sharp, "luma": luma, "white": white, "black": black_flag,
        "motion": motion.tolist(), "jitter": jit.tolist(), "desc_t": desc_t, "proxy_size": [w, h],
    }
    return data, np.stack(descs).astype(np.float32)


# --------------------------------------------------------------------------- queries used by the planner
class QualityTrack:
    """Fast lookups over quality.json arrays."""

    def __init__(self, data: dict, desc: np.ndarray | None = None):
        self.fps = float(data.get("fps") or 10.0)
        self.t = np.asarray(data.get("t", []), dtype=float)
        self.sharp = np.asarray(data.get("sharp", []), dtype=float)
        self.luma = np.asarray(data.get("luma", []), dtype=float)
        self.white = np.asarray(data.get("white", []), dtype=float)
        self.black = np.asarray(data.get("black", []), dtype=float)
        self.jitter = np.asarray(data.get("jitter", []), dtype=float)
        # rolling median (~0.5 s) so single-sample spikes do not fragment otherwise steady shots
        k = max(1, int(round(self.fps * 0.5)) | 1)
        if len(self.jitter) >= k > 1:
            pad = np.pad(self.jitter, (k // 2, k // 2), mode="edge")
            self.jitter_s = np.median(np.lib.stride_tricks.sliding_window_view(pad, k), axis=1)
        else:
            self.jitter_s = self.jitter.copy()
        self.desc_t = np.asarray(data.get("desc_t", []), dtype=float)
        self.desc = desc if desc is not None else np.zeros((0, 176), np.float32)

    @property
    def empty(self) -> bool:
        return len(self.t) == 0

    def _idx(self, t0: float, t1: float) -> np.ndarray:
        return np.where((self.t >= t0) & (self.t < t1))[0]

    def bad_mask(self, policy: Policy) -> np.ndarray:
        if self.empty:
            return np.zeros(0, bool)
        return ((self.black > 0.5)
                | (self.white >= float(policy("quality.white_fraction_max")))
                | (self.jitter_s >= float(policy("quality.jitter.high")))
                | (self.sharp < float(policy("quality.blur_min"))))

    def score(self, t0: float, t1: float, policy: Policy) -> float:
        """0..1 technical score of a span (sharpness, exposure, stability)."""
        idx = self._idx(t0, t1)
        if len(idx) == 0:
            return 0.5
        sharp = float(np.clip(self.sharp[idx].mean() / 0.6, 0, 1))
        expo = float(np.clip(1.0 - abs(self.luma[idx].mean() - 0.45) / 0.45, 0, 1))
        jhigh = float(policy("quality.jitter.high"))
        stab = float(np.clip(1.0 - np.percentile(self.jitter_s[idx], 90) / jhigh, 0, 1))
        return (sharp + expo + stab) / 3.0

    def jitter_p90(self, t0: float, t1: float) -> float:
        idx = self._idx(t0, t1)
        return float(np.percentile(self.jitter_s[idx], 90)) if len(idx) else 0.0

    def clean_spans(self, t0: float, t1: float, policy: Policy) -> list[tuple[float, float]]:
        """Sub-spans of [t0,t1) without bad samples."""
        if self.empty:
            return [(t0, t1)]
        idx = self._idx(t0, t1)
        if len(idx) == 0:
            return [(t0, t1)]
        bad = self.bad_mask(policy)[idx]
        dt = 1.0 / self.fps
        spans, start = [], None
        for k, i in enumerate(idx):
            if not bad[k] and start is None:
                start = self.t[i]
            if bad[k] and start is not None:
                spans.append((max(t0, start), self.t[i]))
                start = None
        if start is not None:
            spans.append((max(t0, start), min(t1, self.t[idx[-1]] + dt)))
        return [(a, b) for a, b in spans if b > a]

    def defect_runs(self, t0: float, t1: float, policy: Policy, min_len: float) -> list[tuple[float, float]]:
        idx = self._idx(t0, t1)
        if len(idx) == 0:
            return []
        bad = self.bad_mask(policy)[idx]
        runs, start = [], None
        for k, i in enumerate(idx):
            if bad[k] and start is None:
                start = self.t[i]
            if not bad[k] and start is not None:
                runs.append((start, self.t[i]))
                start = None
        if start is not None:
            runs.append((start, min(t1, self.t[idx[-1]] + 1.0 / self.fps)))
        return [(a, b) for a, b in runs if b - a >= min_len]

    def desc_at(self, t0: float, t1: float) -> np.ndarray | None:
        if len(self.desc_t) == 0 or len(self.desc) == 0:
            return None
        idx = np.where((self.desc_t >= t0) & (self.desc_t < t1))[0]
        if len(idx) == 0:
            idx = np.array([int(np.argmin(np.abs(self.desc_t - (t0 + t1) / 2)))])
        v = self.desc[idx].mean(axis=0)
        return v / (np.linalg.norm(v) + 1e-9)
