"""Enrollment finalize: merges, sparse partners, clear errors, multi-reference voices (synthetic, no models)."""
import json

import numpy as np
import pytest

from helpers import policy

from magicvideo import enroll
from magicvideo.analysis.voices import PARTNER_A, label_windows
from magicvideo.project import Project, ProjectError

A_DIR = np.array([1.0, 0, 0, 0], np.float32)
B_DIR = np.array([0, 1.0, 0, 0], np.float32)
C_DIR = np.array([0, 0, 1.0, 0], np.float32)


def _unit(v):
    v = np.asarray(v, np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _project(tmp_path, folders: dict[str, list[tuple[np.ndarray, str]]], kind="voice"):
    """folders: name -> [(embedding, clip_id)] ; writes review folders, dummy files and manifest.json."""
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    p = Project.init(tmp_path / "work", [tmp_path / "raw"], "T", tmp_path / "people")
    p.inventory_path.write_text(json.dumps({"version": 1, "clips": []}), encoding="utf-8")
    review = p.people_dir / ("voices" if kind == "voice" else "faces") / "review" / "T"
    ext = ".wav" if kind == "voice" else ".jpg"
    manifest = {}
    for name, items in folders.items():
        (review / name).mkdir(parents=True, exist_ok=True)
        for i, (emb, cid) in enumerate(items, 1):
            fname = f"{i:02d}_x{ext}"
            (review / name / fname).write_bytes(b"x")
            manifest[f"{name}/{fname}"] = {"embedding": _unit(emb), "clip_id": cid}
    (review / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return p


def _refs(p):
    return dict(np.load(p.people_dir / "refs.npz"))


def _three(extra_noise=0.0):
    return {
        "voice_001": [(A_DIR, "c1"), (A_DIR, "c2"), (A_DIR, "c1"), (A_DIR, "c2")],
        "voice_002": [(B_DIR, "c1"), (B_DIR, "c2"), (B_DIR, "c3")],
        "voice_003": [(A_DIR + 0.1 * C_DIR, "c4"), (A_DIR + 0.1 * C_DIR, "c5")],
    }


def test_merge_folds_folder_into_partner(tmp_path):
    p = _project(tmp_path, _three())
    # invalid merges are rejected before anything is written
    for bad in (["voice_009:voice_001"], ["voice_003:voice_009"], ["voice_003:voice_001", "voice_003:voice_002"],
                ["voice_003:voice_001", "voice_001:voice_002"], ["voice_003:voice_003"]):
        with pytest.raises(ProjectError):
            enroll.finalize(p, merges=bad)
        assert not (p.people_dir / "refs.npz").exists()
    with pytest.raises(ProjectError):
        enroll.finalize(p, merges=["person_001:voice_001"])
    assert not (p.people_dir / "refs.npz").exists()

    report = enroll.finalize(p, merges=["voice_003:voice_001"])
    assert "approved from" in report["voices"]
    refs = _refs(p)
    assert refs["voice_a_all"].shape == (6, 4)             # voice_001 (4) + voice_003 (2) under partner a
    assert refs["voice_b_all"].shape == (3, 4)
    assert int(refs["voice_a_count"]) == 6
    assert len(list((p.people_dir / "voices" / "approved" / "partner_a").iterdir())) == 6
    assert len(list((p.people_dir / "voices" / "approved" / "partner_b").iterdir())) == 3


def test_below_minimum_message_names_folder_and_flag(tmp_path):
    # three folders, one below the minimum: it is still counted and the message says how to fold it
    p = _project(tmp_path, _three())
    msg = enroll.finalize(p)["voices"]
    assert "need exactly 2 partners, found 3 after merges" in msg
    assert "voice_001 (4 clips)" in msg and "voice_002 (3)" in msg
    assert "voice_003 (2 — below minimum 3)" in msg
    assert "--merge voice_003:voice_002" in msg
    assert not (p.people_dir / "refs.npz").exists()

    # two folders, one partner below the minimum, no flag
    q = _project(tmp_path / "q", {"voice_001": [(A_DIR, "c1")] * 4, "voice_002": [(B_DIR, "c2")] * 2})
    msg = enroll.finalize(q)["voices"]
    assert "voice_002" in msg and "2" in msg and "3" in msg and "--allow-sparse" in msg
    assert not (q.people_dir / "refs.npz").exists()


def test_allow_sparse_accepts_two_clips(tmp_path):
    p = _project(tmp_path, {"voice_001": [(A_DIR, "c1"), (A_DIR, "c2"), (A_DIR, "c3"), (A_DIR, "c1")],
                            "voice_002": [(B_DIR, "c1"), (B_DIR, "c2")]})
    report = enroll.finalize(p, allow_sparse=True)
    assert "approved from" in report["voices"]
    assert "partner_b has 2 voice clips (minimum 3); recognition will rely on the couple prior" in report["sparse"]
    assert _refs(p)["voice_b_all"].shape == (2, 4)


def test_single_clip_reference_warns(tmp_path):
    p = _project(tmp_path, {"voice_001": [(A_DIR, "c1"), (A_DIR, "c2"), (A_DIR, "c3")],
                            "voice_002": [(B_DIR, "c9"), (B_DIR, "c9"), (B_DIR, "c9")]})
    report = enroll.finalize(p)
    warnings = report["warning"]
    assert ("partner_b's voice reference comes from 1 clip; "
            "add clips from other cameras for better recognition") in warnings
    assert not any("partner_a" in w for w in warnings)


def test_multi_reference_uses_best_match():
    a_rows = np.eye(5, dtype=np.float32)[:4]                  # four distinct sides of partner a
    centroid = a_rows.mean(axis=0)
    centroid /= np.linalg.norm(centroid)                       # 0.5 to every row: below min_similarity 0.55
    b = np.eye(5, dtype=np.float32)[4]
    emb = np.stack([a_rows[0]])
    windows = [{"t0": 0, "t1": 2}]
    only_centroid = {"voice_a": centroid, "voice_b": b}
    assert label_windows(emb, windows, only_centroid, policy()) == ["OTHER"]
    multi = {**only_centroid, "voice_a_all": a_rows, "voice_b_all": b[None, :]}
    assert label_windows(emb, windows, multi, policy()) == [PARTNER_A]


def test_finalize_without_assignment_unchanged(tmp_path, monkeypatch):
    p = _project(tmp_path, {"voice_001": [(A_DIR, "c1"), (A_DIR, "c2"), (A_DIR, "c3")],
                            "voice_002": [(B_DIR, "c1"), (B_DIR, "c2"), (B_DIR, "c3")]})
    consulted = []
    real = enroll._voice_face_swap
    monkeypatch.setattr(enroll, "_voice_face_swap", lambda *a: (consulted.append(1), real(*a))[1])
    report = enroll.finalize(p)
    assert report["voices"] == "approved from ['voice_001', 'voice_002']"
    assert consulted == [1]
    assert report["voice_face_link"].startswith("not verified")
    refs = _refs(p)
    assert refs["voice_a_all"].shape == (3, 4) and refs["voice_b_all"].shape == (3, 4)
