"""Content-based orientation check: is the picture upright after the metadata rotation? (brief §15)

Phones and action cameras sometimes record sideways or upside-down with no (or wrong) rotation metadata.
A few frames are tried at 0/90/180/270 degrees with the face backend; the rotation with clearly the most
(and largest) faces wins. The result is an *extra* rotation on top of the metadata, stored in orient.json.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import ffmpeg
from ..policy import Policy

ROTATIONS = (0, 90, 180, 270)
MIN_FACE_FRACTION = 0.05   # faces smaller than this share of the frame height are ignored


def rotate_image(bgr: np.ndarray, rot: int) -> np.ndarray:
    """Rotate clockwise by rot degrees (what ffmpeg's transpose would do before reframing)."""
    k = {0: 0, 90: -1, 180: 2, 270: 1}[rot % 360]
    return np.ascontiguousarray(np.rot90(bgr, k))


def face_scores(detect, frames: list[np.ndarray]) -> dict[int, dict]:
    """Per rotation: {"score": sum of det scores of large-enough faces, "faces": count}."""
    out: dict[int, dict] = {}
    for rot in ROTATIONS:
        score, count = 0.0, 0
        for f in frames:
            img = rotate_image(f, rot)
            h = img.shape[0]
            for box, det_score, _ in detect(img):
                if box[3] >= MIN_FACE_FRACTION * h:
                    score += float(det_score)
                    count += 1
        out[rot] = {"score": round(score, 3), "faces": count}
    return out


def pick_rotation(scores: dict[int, dict], min_faces: int, min_ratio: float) -> int:
    """The extra rotation to apply: 0 unless another rotation clearly beats the metadata orientation."""
    base = scores.get(0, {}).get("score", 0.0)
    best_rot, best = 0, base
    for rot in (90, 180, 270):
        s = scores.get(rot, {})
        if s.get("faces", 0) >= min_faces and s.get("score", 0.0) > best:
            best_rot, best = rot, s["score"]
    if best_rot == 0:
        return 0
    if base <= 0 or best >= min_ratio * base:
        return best_rot
    return 0


def analyze(path: Path, clip: dict, policy: Policy, backend) -> dict:
    n = int(policy("orientation.sample_frames"))
    px = int(policy("orientation.frame_px"))
    dur = float(clip.get("duration") or 0.0)
    w, h = ffmpeg.scaled_size(clip["display_w"], clip["display_h"], px)
    frames: list[np.ndarray] = []
    if dur > 0 and n > 0:
        for k in range(n):
            t = dur * (k + 0.5) / n
            for _, f in ffmpeg.read_frames(path, fps=1, size=(w, h), start=t, duration=1.0):
                frames.append(f)
                break
    scores = face_scores(backend.detect, frames) if frames else {r: {"score": 0.0, "faces": 0} for r in ROTATIONS}
    rot = pick_rotation(scores, int(policy("orientation.min_faces")), float(policy("orientation.min_ratio")))
    return {"backend": getattr(backend, "name", "?"), "frames": len(frames), "rotate": rot,
            "scores": {str(r): scores[r] for r in ROTATIONS}}
