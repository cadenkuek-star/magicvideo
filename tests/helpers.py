"""Test helpers: synthetic clips and analysis that stand in for the model backends."""
from __future__ import annotations

import numpy as np

from magicvideo.analysis.quality import QualityTrack
from magicvideo.plan.data import ClipData, build_turns
from magicvideo.policy import Policy


def policy(**over) -> Policy:
    p = Policy.load()
    return p.with_overrides(over) if over else p


def clip(cid="c_1", duration=60.0, start="2026-04-19T12:00:00", w=1920, h=1080, fps=30.0, **kw) -> dict:
    d = {"clip_id": cid, "path": f"/x/{cid}.mp4", "rel_path": f"{cid}.mp4", "duration": duration,
         "capture_start": start, "display_w": w, "display_h": h, "width": w, "height": h, "fps": fps,
         "projection": "flat", "render_projection": "flat", "camera": {"make": "DJI", "model": None, "kind": "unknown"},
         "has_audio": True, "render_path": f"/x/{cid}.mp4", "analysis_path": f"/x/{cid}.mp4"}
    d.update(kw)
    return d


def words(spec: list[tuple[float, float, str]]) -> list[dict]:
    """[(t0, t1, text)] -> transcript words."""
    return [{"t0": a, "t1": b, "w": t, "p": 0.9} for a, b, t in spec]


def clipdata(c: dict, word_spec=(), speakers=None, quality=None, tags=None, desc_seed=0) -> ClipData:
    ws = words(list(word_spec))
    windows = [{"t0": w["t0"], "t1": w["t1"], "w0": i, "w1": i + 1} for i, w in enumerate(ws)]
    labels = list(speakers) if speakers else ["UNKNOWN"] * len(ws)
    cd = ClipData(clip=c, words=ws, asr_done=True)
    cd.turns = build_turns(ws, windows, labels, 6.0)
    if quality is None:
        n = int(c["duration"] * 10)
        rng = np.random.default_rng(desc_seed)
        desc = rng.normal(size=(int(c["duration"]) + 1, 176)).astype(np.float32)
        desc /= np.linalg.norm(desc, axis=1, keepdims=True)
        quality = QualityTrack({"fps": 10, "t": [i / 10 for i in range(n)], "sharp": [0.6] * n, "luma": [0.45] * n,
                                "white": [0.0] * n, "black": [0.0] * n, "jitter": [0.001] * n,
                                "desc_t": [float(i) for i in range(int(c["duration"]) + 1)]}, desc)
    cd.quality = quality
    cd.tags = tags or []
    return cd
