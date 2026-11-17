"""Face detection + embeddings (insightface or OpenCV YuNet/SFace), tracking, partner labelling."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import ffmpeg
from ..policy import Policy
from .asr import BackendMissing
from .views360 import multi_view_filter, pitch_of, vfov_for, view_yaws, yaw_of

PARTNER_A, PARTNER_B, OTHER = "PARTNER_A", "PARTNER_B", "OTHER"


class _InsightFace:
    name = "insightface:buffalo_l"

    def __init__(self, policy: Policy):
        try:
            from insightface.app import FaceAnalysis  # type: ignore
        except ImportError as e:
            raise BackendMissing("insightface not installed (pip install 'magicvideo[faces]')") from e
        gpu = policy("compute.device") in ("cuda",) or (policy("compute.device") == "auto" and ffmpeg.gpu_available())
        providers = (["CUDAExecutionProvider"] if gpu else []) + ["CPUExecutionProvider"]
        self.app = FaceAnalysis(name="buffalo_l", providers=providers, allowed_modules=["detection", "recognition"])
        self.app.prepare(ctx_id=0 if gpu else -1, det_size=(640, 640))

    def detect(self, bgr: np.ndarray) -> list[tuple[list[float], float, np.ndarray]]:
        out = []
        for f in self.app.get(bgr):
            x1, y1, x2, y2 = [float(v) for v in f.bbox]
            out.append(([x1, y1, x2 - x1, y2 - y1], float(f.det_score), np.asarray(f.normed_embedding, np.float32)))
        return out


class _YuNet:
    name = "opencv:yunet+sface"

    def __init__(self, policy: Policy):
        import cv2
        det = policy("identity.face.yunet_detector")
        rec = policy("identity.face.sface_recognizer")
        if not det or not rec or not Path(det).exists() or not Path(rec).exists():
            raise BackendMissing("yunet backend needs identity.face.yunet_detector and sface_recognizer model paths")
        self.cv2 = cv2
        self.det = cv2.FaceDetectorYN.create(str(det), "", (320, 320), 0.6, 0.3, 5000)
        self.rec = cv2.FaceRecognizerSF.create(str(rec), "")

    def detect(self, bgr: np.ndarray):
        h, w = bgr.shape[:2]
        self.det.setInputSize((w, h))
        _, faces = self.det.detect(bgr)
        out = []
        if faces is None:
            return out
        for f in faces:
            crop = self.rec.alignCrop(bgr, f)
            e = self.rec.feature(crop).reshape(-1).astype(np.float32)
            e /= np.linalg.norm(e) + 1e-9
            out.append(([float(f[0]), float(f[1]), float(f[2]), float(f[3])], float(f[-1]), e))
        return out


def load_backend(policy: Policy):
    name = policy("identity.face.backend")
    if name == "insightface":
        return _InsightFace(policy)
    if name == "yunet":
        return _YuNet(policy)
    raise BackendMissing(f"unknown face backend {name}")


def _iou(a: list[float], b: list[float]) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def assign_tracks(dets: list[dict], max_gap: float, iou_min: float = 0.3) -> None:
    """Greedy one-to-one IoU tracking over time (per view for 360). Sets det['track']."""
    next_id = 0
    active: dict[int, dict] = {}  # track id -> last det
    by_time: dict[tuple, list[dict]] = {}
    for d in dets:
        by_time.setdefault((d["t"], d.get("view", 0)), []).append(d)
    for key in sorted(by_time):
        t, view = key
        frame = by_time[key]
        cands = [(tid, last) for tid, last in active.items()
                 if last.get("view", 0) == view and 0 < t - last["t"] <= max_gap]
        pairs = sorted(((_iou(d["box"], last["box"]), i, tid) for i, d in enumerate(frame) for tid, last in cands),
                       reverse=True)
        used_d, used_t = set(), set()
        for iou, i, tid in pairs:
            if iou < iou_min or i in used_d or tid in used_t:
                continue
            frame[i]["track"] = tid
            used_d.add(i); used_t.add(tid)
        for i, d in enumerate(frame):
            if i not in used_d:
                d["track"] = next_id
                next_id += 1
            active[d["track"]] = d
        active = {tid: last for tid, last in active.items() if t - last["t"] <= max_gap}


def analyze(path: Path, clip: dict, policy: Policy) -> tuple[dict, np.ndarray]:
    backend = load_backend(policy)
    fps = float(policy("identity.face.sample_fps"))
    proj = clip.get("analysis_projection", clip.get("projection", "flat"))
    dets: list[dict] = []
    embs: list[np.ndarray] = []
    if proj in ("equirect", "dual_fisheye"):
        n = int(policy("insta360.analysis_views"))
        hfov = float(policy("insta360.analysis_view_fov_deg"))
        vw, vh = 640, 480
        yaws = view_yaws(n)
        vf = multi_view_filter(proj, yaws, hfov, (vw, vh), float(policy("insta360.fisheye_fov_deg")))
        vfov = vfov_for(hfov, vw, vh)
        for t, frame in ffmpeg.read_frames(Path(path), fps=fps, size=(vw * n, vh), extra_vf=vf):
            for k, yaw in enumerate(yaws):
                view = frame[:, k * vw:(k + 1) * vw]
                for box, score, e in backend.detect(np.ascontiguousarray(view)):
                    cx = (box[0] + box[2] / 2) / vw
                    cy = (box[1] + box[3] / 2) / vh
                    dets.append({"t": t, "view": k, "box": [box[0] / vw, box[1] / vh, box[2] / vw, box[3] / vh],
                                 "score": score, "q": score * min(1.0, box[3] / (0.25 * vh)),
                                 "yaw": yaw_of(yaw, cx, hfov), "pitch": pitch_of(cy, vfov)})
                    embs.append(e)
    else:
        w, h = ffmpeg.scaled_size(clip["display_w"], clip["display_h"], int(policy("identity.face.frame_px")))
        for t, frame in ffmpeg.read_frames(Path(path), fps=fps, size=(w, h)):
            for box, score, e in backend.detect(frame):
                dets.append({"t": t, "box": [box[0] / w, box[1] / h, box[2] / w, box[3] / h],
                             "score": score, "q": score * min(1.0, box[3] / (0.2 * h))})
                embs.append(e)
    assign_tracks(dets, float(policy("identity.face.track_max_gap_s")))
    dim = embs[0].shape[0] if embs else 512
    return ({"backend": backend.name, "sample_fps": fps, "dets": dets},
            np.stack(embs).astype(np.float32) if embs else np.zeros((0, dim), np.float32))


def label_faces(dets: list[dict], emb: np.ndarray, refs: dict | None, policy: Policy) -> list[str | None]:
    """Per-detection partner label with track consensus (median similarity). None = no refs."""
    if not refs or refs.get("face_a") is None or refs.get("face_b") is None or len(emb) != len(dets) or not dets:
        return [None] * len(dets)
    a = np.asarray(refs["face_a"], np.float32)
    b = np.asarray(refs["face_b"], np.float32)
    if a.shape[0] != emb.shape[1]:
        return [None] * len(dets)  # refs from a different face model
    sa, sb = emb @ a, emb @ b
    thr = float(policy("identity.face.min_similarity"))
    margin = float(policy("identity.face.margin"))
    tracks: dict[int, list[int]] = {}
    for i, d in enumerate(dets):
        tracks.setdefault(d.get("track", -1 - i), []).append(i)
    labels: list[str | None] = [OTHER] * len(dets)
    for idx in tracks.values():
        ma, mb = float(np.median(sa[idx])), float(np.median(sb[idx]))
        lab = OTHER
        if ma >= thr and ma - mb >= margin:
            lab = PARTNER_A
        elif mb >= thr and mb - ma >= margin:
            lab = PARTNER_B
        for i in idx:
            labels[i] = lab
    return labels


def stranger_times(dets: list[dict], emb: np.ndarray, refs: dict | None, policy: Policy) -> list[float]:
    """Times of clear faces that match neither partner (similarity below stranger_face.max_similarity)."""
    if not refs or refs.get("face_a") is None or refs.get("face_b") is None or not dets or len(emb) != len(dets):
        return []
    a = np.asarray(refs["face_a"], np.float32)
    b = np.asarray(refs["face_b"], np.float32)
    if a.shape[0] != emb.shape[1] or b.shape[0] != emb.shape[1]:
        return []
    best = np.maximum(emb @ a, emb @ b)
    max_sim = float(policy("identity.stranger_face.max_similarity"))
    min_q = float(policy("identity.stranger_face.min_q"))
    return sorted(float(d["t"]) for d, s in zip(dets, best) if float(d.get("q", 0.0)) >= min_q and float(s) < max_sim)
