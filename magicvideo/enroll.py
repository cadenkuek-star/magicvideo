"""Deletion-only enrollment of the two partners (faces + voices). Brief §4, PROPOSAL §8.

prepare(): cluster faces and voices across the trip, export candidate folders for review.
finalize(): the user deleted wrong folders/files; exactly two of each kind remain -> refs.npz.
"""
from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np
import yaml

from . import ffmpeg, ingest
from .analysis.views360 import analysis_view_filter, view_yaws
from .project import Project, ProjectError
from .util import read_json, safe_name, sha256_file, write_json

REVIEW_TEXT = """\
# Who are the two of you?  (takes ~2 minutes, once)

This folder has candidate PEOPLE (faces/review/{trip}/person_NNN) and VOICES
(voices/review/{trip}/voice_NNN) found in your footage.

## Easiest: the clickable page (nothing is deleted)
Run:   magicvideo enroll "{work}" --page
Tap A or B on each group that is one of you, and Not us on the others. Tap a photo or clip to leave it out if it
is someone else. Then press Finish. If one of you hardly speaks, tick "Accept fewer clips than usual".

## Alternative: delete folders yourself
1. Faces: open each person_NNN folder. Delete every folder that is not one of you two.
   Inside your two folders, delete any image of somebody else. Keep at least {min_face} images each.
2. Voices: play the clips in each voice_NNN folder. Delete every folder that is not one of you two.
   Inside your two folders, delete clips where somebody else is talking. Keep at least {min_voice} each.
3. If one of you shows up under two folders (for example your voice behind the camera is in
   voice_003 as well as voice_001), keep both folders and join them when you finish:
   magicvideo enroll "{work}" --finalize --merge voice_003:voice_001
   (the first folder is added to the second; you can repeat --merge).
4. If one of you hardly speaks and has fewer clips than the minimum, add --allow-sparse. That
   accepts even a single clip; recognition then leans on the assumption that speech is yours.
5. Do not rename or move anything. Then run:   magicvideo enroll "{work}" --finalize
"""


def cluster(emb: np.ndarray, order: np.ndarray, threshold: float, iters: int = 3) -> np.ndarray:
    """Deterministic leader clustering on L2-normalised rows; returns labels (-1 never used)."""
    n = len(emb)
    if n == 0:
        return np.zeros(0, int)
    centroids: list[np.ndarray] = []
    labels = np.full(n, -1, int)
    for i in order:
        if centroids:
            sims = np.stack(centroids) @ emb[i]
            j = int(np.argmax(sims))
            if sims[j] >= threshold:
                labels[i] = j
                c = centroids[j] + emb[i]
                centroids[j] = c / (np.linalg.norm(c) + 1e-9)
                continue
        centroids.append(emb[i].copy())
        labels[i] = len(centroids) - 1
    for _ in range(iters):
        C = np.stack(centroids)
        labels = np.argmax(emb @ C.T, axis=1)
        new = []
        for j in range(len(centroids)):
            m = emb[labels == j]
            new.append(m.mean(axis=0) / (np.linalg.norm(m.mean(axis=0)) + 1e-9) if len(m) else C[j])
        centroids = new
    return labels


def _people_paths(project: Project) -> dict[str, Path]:
    base = project.people_dir
    trip = project.name
    return {
        "base": base,
        "face_review": base / "faces" / "review" / trip,
        "voice_review": base / "voices" / "review" / trip,
        "face_approved": base / "faces" / "approved",
        "voice_approved": base / "voices" / "approved",
        "refs": base / "refs.npz",
        "enrollment": base / "enrollment.yaml",
    }


def _frame(path: Path, t: float, vf: str | None, size: tuple[int, int]) -> np.ndarray | None:
    for _, f in ffmpeg.read_frames(path, fps=1, size=size, start=max(0.0, t), duration=1.0, extra_vf=vf):
        return f
    return None


def _write_jpg(path: Path, img: np.ndarray) -> None:
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])


def _cut_wav(src: Path, dst: Path, t0: float, t1: float) -> None:
    with wave.open(str(src), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        w.setpos(max(0, int(t0 * sr)))
        data = w.readframes(max(1, int((t1 - t0) * sr)))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as o:
        o.setnchannels(ch); o.setsampwidth(sw); o.setframerate(sr)
        o.writeframes(data)


# --------------------------------------------------------------------------- prepare
def prepare(project: Project) -> dict:
    pol = project.policy
    paths = _people_paths(project)
    clips = {c["clip_id"]: c for c in ingest.plannable(project.inventory())}
    result = {"faces": 0, "voices": 0}

    # ---------------- faces: one embedding per track (mean of good detections)
    rows, meta = [], []
    for cid, clip in clips.items():
        adir = project.analysis_dir(cid)
        data = read_json(adir / "faces.json")
        if not data or not (adir / "face_emb.npy").exists():
            continue
        emb = np.load(adir / "face_emb.npy")
        tracks: dict[int, list[int]] = {}
        for i, d in enumerate(data["dets"]):
            if d.get("q", 0) >= 0.4:
                tracks.setdefault(d["track"], []).append(i)
        for tid, idx in sorted(tracks.items()):
            v = emb[idx].mean(axis=0)
            rows.append(v / (np.linalg.norm(v) + 1e-9))
            best = max(idx, key=lambda i: data["dets"][i]["q"])
            meta.append({"clip_id": cid, "track": tid, "n": len(idx), "best": best, "det": data["dets"][best]})
    if rows:
        E = np.stack(rows)
        order = np.argsort([-m["n"] for m in meta], kind="stable")
        labels = cluster(E, order, float(pol("enrollment.cluster_similarity.face")))
        ranked = _rank_clusters(labels, [m["clip_id"] for m in meta], [m["n"] for m in meta])
        shutil.rmtree(paths["face_review"], ignore_errors=True)
        manifest = {}
        per = int(pol("enrollment.samples_per_candidate.face"))
        for rank, lab in enumerate(ranked[: int(pol("enrollment.max_candidates"))], 1):
            members = [k for k in np.where(labels == lab)[0]]
            members.sort(key=lambda k: (-meta[k]["det"]["q"], meta[k]["clip_id"], meta[k]["track"]))
            picked, seen_clips = [], set()
            for k in members:  # prefer variety across clips
                if meta[k]["clip_id"] not in seen_clips or len(seen_clips) >= per:
                    picked.append(k); seen_clips.add(meta[k]["clip_id"])
                if len(picked) >= per:
                    break
            folder = paths["face_review"] / f"person_{rank:03d}"
            for k in picked:
                m = meta[k]
                clip = clips[m["clip_id"]]
                crop = _face_crop(clip, m["det"], pol)
                if crop is None:
                    continue
                name = f"{safe_name(Path(clip['rel_path']).stem, 30)}_{m['det']['t']:07.1f}s.jpg"
                _write_jpg(folder / name, crop)
                manifest[f"person_{rank:03d}/{name}"] = {"embedding": E[k].tolist(), "clip_id": m["clip_id"],
                                                         "track": m["track"], "t": m["det"]["t"]}
            result["faces"] += 1
        write_json(paths["face_review"] / "manifest.json", manifest)

    # ---------------- voices: windows >= 1 s
    vrows, vmeta = [], []
    for cid, clip in clips.items():
        adir = project.analysis_dir(cid)
        data = read_json(adir / "voices.json")
        tr = read_json(adir / "transcript.json")
        if not data or not (adir / "voice_emb.npy").exists() or not (adir / "audio16k.wav").exists():
            continue
        emb = np.load(adir / "voice_emb.npy")
        for i, w in enumerate(data["windows"]):
            if w["t1"] - w["t0"] >= 1.0 and i < len(emb):
                text = " ".join(x["w"] for x in tr["words"][w["w0"]:w["w1"]]) if tr else ""
                vrows.append(emb[i]); vmeta.append({"clip_id": cid, **w, "text": text})
    if vrows:
        V = np.stack(vrows)
        order = np.argsort([-(m["t1"] - m["t0"]) for m in vmeta], kind="stable")
        labels = cluster(V, order, float(pol("enrollment.cluster_similarity.voice")))
        ranked = _rank_clusters(labels, [m["clip_id"] for m in vmeta], [m["t1"] - m["t0"] for m in vmeta])
        shutil.rmtree(paths["voice_review"], ignore_errors=True)
        manifest = {}
        per = int(pol("enrollment.samples_per_candidate.voice"))
        for rank, lab in enumerate(ranked[: int(pol("enrollment.max_candidates"))], 1):
            members = sorted(np.where(labels == lab)[0], key=lambda k: (-(vmeta[k]["t1"] - vmeta[k]["t0"]), k))
            folder = paths["voice_review"] / f"voice_{rank:03d}"
            for n, k in enumerate(members[:per], 1):
                m = vmeta[k]
                words = safe_name(m["text"], 40) if m["text"] else "speech"
                name = f"{n:02d}_{int(m['t0'] // 60):02d}m{int(m['t0'] % 60):02d}s_{words}.wav"
                _cut_wav(project.analysis_dir(m["clip_id"]) / "audio16k.wav", folder / name,
                         max(0.0, m["t0"] - 0.2), m["t1"] + 0.2)
                manifest[f"voice_{rank:03d}/{name}"] = {"embedding": V[k].tolist(), "clip_id": m["clip_id"],
                                                        "t0": m["t0"], "t1": m["t1"]}
            result["voices"] += 1
        write_json(paths["voice_review"] / "manifest.json", manifest)

    text = REVIEW_TEXT.format(trip=project.name, work=project.root,
                              min_face=pol("enrollment.min_kept_per_partner.face"),
                              min_voice=pol("enrollment.min_kept_per_partner.voice"))
    paths["base"].mkdir(parents=True, exist_ok=True)
    (paths["base"] / f"REVIEW_{project.name}.md").write_text(text, encoding="utf-8")
    _write_enrollment(paths, {"status": "REVIEW_REQUIRED", "trip": project.name})
    return result


def _rank_clusters(labels: np.ndarray, clip_ids: list[str], weights: list[float]) -> list[int]:
    stats: dict[int, list] = {}
    for lab, cid, w in zip(labels, clip_ids, weights):
        s = stats.setdefault(int(lab), [set(), 0.0])
        s[0].add(cid); s[1] += float(w)
    return sorted(stats, key=lambda lab: (-len(stats[lab][0]), -stats[lab][1], lab))


def _face_crop(clip: dict, det: dict, pol) -> np.ndarray | None:
    path = Path(clip["analysis_path"])
    proj = clip.get("analysis_projection", clip.get("projection", "flat"))
    if "view" in det:
        yaws = view_yaws(int(pol("insta360.analysis_views")))
        size = (640, 480)
        vf = analysis_view_filter(proj, yaws[det["view"]], float(pol("insta360.analysis_view_fov_deg")), size,
                                  float(pol("insta360.fisheye_fov_deg")))
    else:
        size = ffmpeg.scaled_size(clip["display_w"], clip["display_h"], int(pol("identity.face.frame_px")))
        vf = None
    img = _frame(path, det["t"], vf, size)
    if img is None:
        return None
    w, h = size
    x, y, bw, bh = det["box"]
    cx, cy, s = (x + bw / 2) * w, (y + bh / 2) * h, max(bw * w, bh * h) * 1.6
    x0, y0 = int(max(0, cx - s / 2)), int(max(0, cy - s / 2))
    x1, y1 = int(min(w, cx + s / 2)), int(min(h, cy + s / 2))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return img[y0:y1, x0:x1]


# --------------------------------------------------------------------------- finalize
KINDS = (("face", "person_", ".jpg"), ("voice", "voice_", ".wav"))
UNIT = {"face": "images", "voice": "clips"}
NOUN = {"face": "face images", "voice": "voice clips"}


def _surviving(review: Path, prefix: str, ext: str) -> dict[str, list[str]]:
    """Every non-empty candidate folder (name -> sorted file names); the minimum is checked later."""
    out: dict[str, list[str]] = {}
    if not review.exists():
        return out
    for d in sorted(p for p in review.iterdir() if p.is_dir() and p.name.startswith(prefix)):
        files = sorted(f.name for f in d.iterdir() if f.suffix.lower() == ext)
        if files:
            out[d.name] = files
    return out


def _kind_of(name: str) -> str | None:
    for kind, prefix, _ in KINDS:
        if name.startswith(prefix):
            return kind
    return None


def _parse_merges(project: Project, merges, paths: dict) -> list[tuple[str, str]]:
    """Validate --merge SRC:DST pairs; raises ProjectError (nothing has been written yet)."""
    pairs: list[tuple[str, str]] = []
    for m in merges or []:
        src, sep, dst = (m if isinstance(m, str) else f"{m[0]}:{m[1]}").partition(":")
        if not sep or not src or not dst:
            raise ProjectError(f"--merge needs SRC:DST (for example voice_003:voice_001), got {m!r}")
        pairs.append((src, dst))
    dsts = {d for _, d in pairs}
    seen: set[str] = set()
    for src, dst in pairs:
        ks, kd = _kind_of(src), _kind_of(dst)
        if ks is None or kd is None:
            raise ProjectError(f"--merge {src}:{dst}: folder names must start with person_ or voice_")
        if ks != kd:
            raise ProjectError(f"--merge {src}:{dst}: a {ks} folder cannot be merged into a {kd} folder")
        for name, kind in ((src, ks), (dst, kd)):
            if not (paths[f"{kind}_review"] / name).is_dir():
                raise ProjectError(f"--merge {src}:{dst}: folder {name} not found in {paths[f'{kind}_review']}")
        if src in dsts:
            raise ProjectError(f"--merge {src}:{dst}: {src} is also used as a destination; merges cannot be chained")
        if src in seen:
            raise ProjectError(f"--merge: {src} is merged more than once")
        seen.add(src)
    return pairs


def _group_line(groups: dict[str, list], kind: str, minimum: int) -> str:
    parts = []
    for i, (name, items) in enumerate(groups.items()):
        n = len(items)
        label = f"{n} {UNIT[kind]}" if i == 0 else str(n)
        if n < minimum:
            label += f" \u2014 below minimum {minimum}"
        parts.append(f"{name} ({label})")
    return ", ".join(parts) if parts else "none"


def _assigned_slots(review: Path, prefix: str, ext: str, kind: str, assign: dict, excluded: set[str],
                    minimum: int):
    """[(first folder, folders, items)] for slots a and b exactly as assigned, or (None, problem text)."""
    slots, problems = [], []
    for slot in ("a", "b"):
        folders = list(assign.get(slot, []))
        items = []
        for fo in folders:
            d = review / fo
            if d.is_dir():
                items += [(fo, f.name) for f in sorted(d.iterdir(), key=lambda f: f.name)
                          if f.suffix.lower() == ext and f"{kind}/{fo}/{f.name}" not in excluded]
        if not items:
            problems.append(f"partner_{slot} has no {UNIT[kind]} assigned")
        elif len(items) < minimum:
            problems.append(f"partner_{slot} has {len(items)} {UNIT[kind]}, below the minimum {minimum}: add more "
                            f"groups, or accept it with --allow-sparse")
        slots.append((folders[0] if folders else None, folders, items))
    if problems:
        return None, "; ".join(problems)
    return slots, None


def finalize(project: Project, merges=(), allow_sparse: bool = False, assignment: dict | None = None,
             excluded: set[str] | None = None, names: dict | None = None) -> dict:
    pol = project.policy
    paths = _people_paths(project)
    pairs = _parse_merges(project, merges, paths)
    assignment = assignment or {}
    excluded = excluded or set()
    assigned_done: set[str] = set()
    refs = dict(np.load(paths["refs"])) if paths["refs"].exists() else {}
    report: dict = {"faces": "unchanged", "voices": "unchanged"}
    sparse_notes: list[str] = []
    warnings: list[str] = []

    for kind, prefix, ext in KINDS:
        review = paths[f"{kind}_review"]
        manifest = read_json(review / "manifest.json", {})
        if not manifest:
            continue
        minimum = 1 if allow_sparse else int(pol(f"enrollment.min_kept_per_partner.{kind}"))
        if kind in assignment:
            slots, problem = _assigned_slots(review, prefix, ext, kind, assignment[kind], excluded, minimum)
            if problem:
                report[f"{kind}s"] = problem
                continue
        else:
            groups: dict[str, list[tuple[str, str]]] = {n: [(n, f) for f in fs]
                                                        for n, fs in _surviving(review, prefix, ext).items()}
            for src, dst in pairs:
                if _kind_of(src) != kind:
                    continue
                moved = groups.pop(src, [])
                groups.setdefault(dst, []).extend(moved)
            groups = {n: items for n, items in sorted(groups.items()) if items}
            if len(groups) != 2:
                line = (f"need exactly 2 partners, found {len(groups)} after merges: "
                        f"{_group_line(groups, kind, minimum)}.")
                if len(groups) > 2:
                    by_size = sorted(groups.items(), key=lambda kv: (len(kv[1]), kv[0]))
                    line += (f" Delete folders that are not you two, or fold one into another: "
                             f"--merge {by_size[0][0]}:{by_size[1][0]}")
                report[f"{kind}s"] = line
                continue
            low = [(n, len(items)) for n, items in groups.items() if len(items) < minimum]
            if low:
                report[f"{kind}s"] = "; ".join(
                    f"{n} has {c} {UNIT[kind]}, below the minimum {minimum}: add more (or --merge another folder "
                    f"into it), or accept it with --allow-sparse" for n, c in low)
                continue
            slots = [(folder, [folder], items) for folder, items in groups.items()]
        approved = paths[f"{kind}_approved"]
        for slot, (dst_folder, _folders, items) in zip(("a", "b"), slots):
            keys = [(f"{fo}/{f}", fo, f) for fo, f in items if f"{fo}/{f}" in manifest]
            vecs = [np.asarray(manifest[k]["embedding"], np.float32) for k, _, _ in keys]
            if not vecs:
                continue
            vecs = [v / (np.linalg.norm(v) + 1e-9) for v in vecs]
            c = np.mean(vecs, axis=0)
            refs[f"{kind}_{slot}"] = c / (np.linalg.norm(c) + 1e-9)
            refs[f"{kind}_{slot}_count"] = np.array(len(vecs))
            refs[f"{kind}_{slot}_all"] = np.stack(vecs).astype(np.float32)
            dst = approved / f"partner_{slot}"
            dst.mkdir(parents=True, exist_ok=True)
            for fo, f in items:
                name = f"{project.name}_{f}" if fo == dst_folder else f"{project.name}_{fo}_{f}"
                shutil.copy2(review / fo / f, dst / name)
            if len(items) < int(pol(f"enrollment.min_kept_per_partner.{kind}")):
                sparse_notes.append(f"partner_{slot} has {len(items)} {NOUN[kind]} (minimum "
                                    f"{int(pol(f'enrollment.min_kept_per_partner.{kind}'))}); "
                                    f"recognition will rely on the couple prior")
            clips_used = {manifest[k].get("clip_id") for k, _, _ in keys}
            if len(clips_used) == 1:
                warnings.append(f"partner_{slot}'s {kind} reference comes from 1 clip; "
                                f"add clips from other cameras for better recognition")
        report[f"{kind}s"] = f"approved from {[f for _, fl, _ in slots for f in fl]}"
        if kind in assignment:
            assigned_done.add(kind)
    if sparse_notes:
        report["sparse"] = sparse_notes
    if warnings:
        report["warning"] = warnings

    if not refs:
        return report
    if assigned_done:   # the owner's explicit A/B choice is never overridden by the swap heuristic
        swap = None
        if assigned_done == {"face", "voice"}:
            report["voice_face_link"] = "set by owner on the enrollment page"
        else:
            kind = next(iter(assigned_done))
            other = "voice" if kind == "face" else "face"
            report["voice_face_link"] = (f"set by owner for {kind}s on the enrollment page; "
                                         f"{other}s kept from before (not cross-checked)")
    else:
        swap = _voice_face_swap(project, refs)
        if swap is not None:
            report["voice_face_link"] = "swapped voices to match faces" if swap else "voices match faces"
            if swap:
                _swap_voices(refs)
        else:
            report["voice_face_link"] = "not verified (needs both face and voice refs plus overlapping footage)"
    paths["base"].mkdir(parents=True, exist_ok=True)
    np.savez(paths["refs"], **refs)
    meta = {"status": "APPROVED" if all(k in refs for k in ("face_a", "face_b", "voice_a", "voice_b"))
            else "PARTIAL", "trip": project.name, "voice_face_link": report["voice_face_link"],
            "swap_voices": False}
    if names:
        meta["names"] = {k: str(names.get(k, "")).strip()[:40] for k in ("a", "b")}
    _write_enrollment(paths, meta)
    return report


def _swap_voices(refs: dict) -> None:
    """Swap partner a/b voice references (centroid, count and stored embeddings stay aligned)."""
    for suffix in ("", "_count", "_all"):
        a, b = f"voice_a{suffix}", f"voice_b{suffix}"
        if a in refs and b in refs:
            refs[a], refs[b] = refs[b], refs[a]


def _voice_face_swap(project: Project, refs: dict) -> bool | None:
    """Decide whether voice_a belongs to face_b, from co-occurrence of speech and visible faces."""
    if not all(k in refs for k in ("face_a", "face_b", "voice_a", "voice_b")):
        return None
    score = np.zeros((2, 2))  # [voice a/b, face a/b] overlapping seconds
    for clip in ingest.plannable(project.inventory()):
        adir = project.analysis_dir(clip["clip_id"])
        fj, vj = read_json(adir / "faces.json"), read_json(adir / "voices.json")
        if not fj or not vj or not (adir / "face_emb.npy").exists() or not (adir / "voice_emb.npy").exists():
            continue
        fe, ve = np.load(adir / "face_emb.npy"), np.load(adir / "voice_emb.npy")
        if len(fe) != len(fj["dets"]) or len(ve) != len(vj["windows"]) or not len(fe) or not len(ve):
            continue
        if fe.shape[1] != refs["face_a"].shape[0]:
            continue
        fl = np.argmax(np.stack([fe @ refs["face_a"], fe @ refs["face_b"]], 1), 1)
        vl = np.argmax(np.stack([ve @ refs["voice_a"], ve @ refs["voice_b"]], 1), 1)
        step = 1.0 / float(fj.get("sample_fps") or 2)
        for w, v in zip(vj["windows"], vl):
            for d, f in zip(fj["dets"], fl):
                if w["t0"] <= d["t"] < w["t1"]:
                    score[v, f] += step
    same, crossed = score[0, 0] + score[1, 1], score[0, 1] + score[1, 0]
    # Ambiguous by nature: in selfies the speaker is visible, but a partner filming the other also talks.
    # Only act on strong (3:1) evidence. The mapping is low-stakes: the planner protects speech from
    # either partner alike; it only affects per-partner statistics. Users can set swap_voices.
    if crossed >= 3 * max(same, 1e-6) and crossed >= 10:
        return True
    if same >= 3 * max(crossed, 1e-6) and same >= 10:
        return False
    return None


def _write_enrollment(paths: dict, data: dict) -> None:
    p = paths["enrollment"]
    old = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    old = old or {}
    old.update(data)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(old, sort_keys=True), encoding="utf-8")


def refs_fingerprint(people_dir: Path) -> str | None:
    """sha256 (hex) of refs.npz, or None when there are no references yet."""
    p = Path(people_dir) / "refs.npz"
    return sha256_file(p) if p.exists() else None


def load_refs(people_dir: Path) -> dict | None:
    p = Path(people_dir) / "refs.npz"
    if not p.exists():
        return None
    refs = {k: v for k, v in np.load(p).items()}
    e = Path(people_dir) / "enrollment.yaml"
    meta = yaml.safe_load(e.read_text(encoding="utf-8")) if e.exists() else {}
    if (meta or {}).get("swap_voices") and "voice_a" in refs and "voice_b" in refs:
        _swap_voices(refs)
    return refs
