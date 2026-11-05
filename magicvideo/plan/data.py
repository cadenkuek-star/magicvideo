"""Load per-clip analysis into planner-friendly objects (no model inference happens here)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..analysis.faces import label_faces
from ..analysis.quality import QualityTrack
from ..analysis.voices import OTHER, PARTNER_A, PARTNER_B, UNKNOWN, build_windows, label_windows
from ..policy import Policy
from ..util import read_json
from .model import Turn, abs_seconds

PARTNERS = (PARTNER_A, PARTNER_B)


@dataclass
class ClipData:
    clip: dict
    words: list[dict] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    face_dets: list[dict] = field(default_factory=list)
    face_labels: list[str | None] = field(default_factory=list)
    face_fps: float = 2.0
    quality: QualityTrack = field(default_factory=lambda: QualityTrack({}))
    tags: list[dict] = field(default_factory=list)
    asr_done: bool = False

    @property
    def id(self) -> str:
        return self.clip["clip_id"]

    @property
    def duration(self) -> float:
        return float(self.clip["duration"])

    @property
    def abs_start(self) -> float:
        return abs_seconds(self.clip["capture_start"])

    @property
    def is360(self) -> bool:
        return self.clip.get("render_projection", self.clip.get("projection")) in ("equirect", "dual_fisheye")

    # ---- speech ------------------------------------------------------------
    def words_in(self, t0: float, t1: float) -> list[int]:
        return [i for i, w in enumerate(self.words) if w["t1"] > t0 and w["t0"] < t1]

    def speech_in(self, t0: float, t1: float) -> bool:
        return bool(self.words_in(t0, t1))

    def word_speaker(self, i: int) -> str:
        for t in self.turns:
            if t.w0 <= i < t.w1:
                return t.speaker
        return UNKNOWN

    # ---- faces -------------------------------------------------------------
    def partners_visible(self, t0: float, t1: float, min_share: float = 0.3) -> list[str]:
        if not self.face_dets:
            return []
        n_samples = max(1, int(round((t1 - t0) * self.face_fps)))
        out = []
        for p in PARTNERS:
            ts = {round(d["t"], 3) for d, lab in zip(self.face_dets, self.face_labels)
                  if lab == p and t0 <= d["t"] < t1}
            if len(ts) / n_samples >= min_share:
                out.append(p)
        return out

    def partner_yaws(self, t0: float, t1: float) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for d, lab in zip(self.face_dets, self.face_labels):
            if lab in PARTNERS and t0 <= d["t"] < t1 and "yaw" in d:
                out.setdefault(lab, []).append(float(d["yaw"]))
        return out

    def face_center(self, t0: float, t1: float) -> tuple[float, float] | None:
        """Mean centre of faces (partners preferred) in normalised flat-frame coordinates."""
        pts = [(d["box"][0] + d["box"][2] / 2, d["box"][1] + d["box"][3] / 2, lab)
               for d, lab in zip(self.face_dets, self.face_labels) if t0 <= d["t"] < t1 and "yaw" not in d]
        if not pts:
            return None
        part = [p for p in pts if p[2] in PARTNERS] or pts
        return float(np.mean([p[0] for p in part])), float(np.mean([p[1] for p in part]))

    # ---- tags --------------------------------------------------------------
    def tags_in(self, t0: float, t1: float, pad: float = 1.5) -> list[dict]:
        return [f for f in self.tags if t0 - pad <= f["t"] < t1 + pad]


def build_turns(words: list[dict], windows: list[dict], labels: list[str], max_gap: float) -> list[Turn]:
    word_label = [UNKNOWN] * len(words)
    for w, lab in zip(windows, labels):
        for i in range(w["w0"], min(w["w1"], len(words))):
            word_label[i] = lab
    turns: list[Turn] = []
    for i, w in enumerate(words):
        lab = word_label[i]
        if turns and turns[-1].speaker == lab and w["t0"] - words[i - 1]["t1"] <= max_gap:
            turns[-1].t1 = w["t1"]
            turns[-1].w1 = i + 1
        else:
            turns.append(Turn(w["t0"], w["t1"], lab, i, i + 1))
    return turns


def load_clip(project, clip: dict, refs: dict | None, policy: Policy) -> ClipData:
    adir: Path = project.analysis_dir(clip["clip_id"])
    status = project.step_status(clip["clip_id"])
    cd = ClipData(clip=clip)
    tr = read_json(adir / "transcript.json")
    if tr is not None:
        cd.words = tr.get("words", [])
        cd.asr_done = status.get("asr") in ("done",) or status.get("asr", "").startswith("skipped:no audio")
    vj = read_json(adir / "voices.json")
    if vj is not None and (adir / "voice_emb.npy").exists():
        windows = vj["windows"]
        emb = np.load(adir / "voice_emb.npy")
    else:
        windows = build_windows(cd.words, float(policy("voice.window_gap_s")), float(policy("voice.window_max_s")))
        emb = np.zeros((0, 192), np.float32)
    labels = label_windows(emb, windows, refs, policy) if len(emb) == len(windows) else [UNKNOWN] * len(windows)
    cd.turns = build_turns(cd.words, windows, labels, float(policy("moments.conversation.join_gap_s")))
    fj = read_json(adir / "faces.json")
    if fj is not None and (adir / "face_emb.npy").exists():
        cd.face_dets = fj["dets"]
        cd.face_fps = float(fj.get("sample_fps") or 2.0)
        cd.face_labels = label_faces(cd.face_dets, np.load(adir / "face_emb.npy"), refs, policy)
    qj = read_json(adir / "quality.json")
    if qj is not None:
        desc = np.load(adir / "visual_desc.npy") if (adir / "visual_desc.npy").exists() else None
        cd.quality = QualityTrack(qj, desc)
    tj = read_json(adir / "tags.json")
    if tj is not None:
        cd.tags = tj.get("frames", [])
    return cd


def is_couple_speaker(speaker: str, policy: Policy) -> bool:
    if speaker in PARTNERS:
        return True
    return speaker == UNKNOWN and bool(policy("identity.unknown_speech_is_couple"))


__all__ = ["ClipData", "build_turns", "load_clip", "is_couple_speaker", "PARTNERS", "OTHER", "UNKNOWN"]
