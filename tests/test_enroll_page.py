"""The enrollment page: candidates, assignment state, media confinement, finalize by assignment (synthetic)."""
import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest
import yaml

from magicvideo import enroll_page
from magicvideo.project import Project

A = np.array([1.0, 0, 0, 0], np.float32)
B = np.array([0, 1.0, 0, 0], np.float32)


def _unit(v):
    return (np.asarray(v, np.float32) / np.linalg.norm(v)).tolist()


def _folder(review, manifest, kind, name, n, emb, ext, clip_prefix="c"):
    (review / name).mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        f = f"{i:02d}_00m0{i}s_hello_there{ext}"
        (review / name / f).write_bytes(b"x")
        manifest[f"{name}/{f}"] = {"embedding": _unit(emb), "clip_id": f"{clip_prefix}{i}"}


@pytest.fixture
def project(tmp_path):
    (tmp_path / "raw").mkdir()
    p = Project.init(tmp_path / "work", [tmp_path / "raw"], "T", tmp_path / "people")
    p.inventory_path.write_text(json.dumps({"version": 1, "clips": []}), encoding="utf-8")
    fr, vr = p.people_dir / "faces" / "review" / "T", p.people_dir / "voices" / "review" / "T"
    fm, vm = {}, {}
    _folder(fr, fm, "face", "person_001", 4, A, ".jpg")
    _folder(fr, fm, "face", "person_002", 4, B, ".jpg")
    _folder(fr, fm, "face", "person_003", 4, A + B, ".jpg")
    _folder(vr, vm, "voice", "voice_001", 3, A, ".wav")
    _folder(vr, vm, "voice", "voice_002", 3, B, ".wav")
    _folder(vr, vm, "voice", "voice_003", 2, B + 0.1 * A, ".wav")
    (fr / "manifest.json").write_text(json.dumps(fm), encoding="utf-8")
    (vr / "manifest.json").write_text(json.dumps(vm), encoding="utf-8")
    return p


@pytest.fixture
def served(project):
    srv = enroll_page.make_server(project, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield project, srv
    srv.shutdown()
    srv.server_close()
    t.join(5)


def _call(srv, path, body=None, headers=None, raw=None):
    port = srv.server_address[1]
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdrs = dict(headers or {})
    if data is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(srv, path, body):
    status, raw = _call(srv, path, body)
    return status, json.loads(raw)


def _state_file(p):
    return json.loads((p.people_dir / "review_T.json").read_text(encoding="utf-8"))


def _assign_all(srv, voices_b=("voice_002", "voice_003")):
    for kind, a, b in (("face", ["person_001"], ["person_002"]), ("voice", ["voice_001"], list(voices_b))):
        for f in a:
            assert _post(srv, "/api/assign", {"kind": kind, "folder": f, "slot": "a"})[0] == 200
        for f in b:
            assert _post(srv, "/api/assign", {"kind": kind, "folder": f, "slot": "b"})[0] == 200


def test_page_lists_candidates(served):
    p, srv = served
    status, body = _call(srv, "/")
    page = body.decode("utf-8")
    assert status == 200
    for name in ("person_001", "person_002", "person_003", "voice_001", "voice_002", "voice_003"):
        assert name in page
    assert "<img" in page and "<audio" in page and "hello there" in page
    assert "/media/face/person_001/01_00m01s_hello_there.jpg" in page


def test_assign_and_exclude_saved_to_state(served):
    p, srv = served
    assert _post(srv, "/api/assign", {"kind": "voice", "folder": "voice_001", "slot": "a"})[0] == 200
    f = "01_00m01s_hello_there.wav"
    status, out = _post(srv, "/api/exclude", {"kind": "voice", "folder": "voice_001", "file": f, "excluded": True})
    assert status == 200 and out["state"]["assign"]["voice"]["voice_001"] == "a" and "summary" in out
    st = _state_file(p)
    assert st["assign"]["voice"]["voice_001"] == "a" and st["excluded"] == [f"voice/voice_001/{f}"]
    srv2 = enroll_page.make_server(p, port=0)
    t = threading.Thread(target=srv2.serve_forever, daemon=True)
    t.start()
    try:
        got = json.loads(_call(srv2, "/api/state")[1])
        assert got["state"]["assign"]["voice"]["voice_001"] == "a"
        assert got["state"]["excluded"] == [f"voice/voice_001/{f}"]
        assert got["candidates"]["voice"]["voice_001"][0] == f
        assert got["summary"]["a"]["voice_clips"] == 2 and got["summary"]["a"]["min_voice"] == 3
    finally:
        srv2.shutdown()
        srv2.server_close()
        t.join(5)
    assert _post(srv, "/api/exclude", {"kind": "voice", "folder": "voice_001", "file": f, "excluded": False})[0] == 200
    assert _state_file(p)["excluded"] == []


def test_unknown_folder_file_or_slot_rejected(served):
    p, srv = served
    assert _post(srv, "/api/assign", {"kind": "voice", "folder": "voice_999", "slot": "a"})[0] == 400
    assert _post(srv, "/api/exclude", {"kind": "voice", "folder": "voice_001", "file": "nope.wav",
                                       "excluded": True})[0] == 400
    assert _post(srv, "/api/assign", {"kind": "voice", "folder": "voice_001", "slot": "c"})[0] == 400
    assert _post(srv, "/api/assign", {"kind": "tooth", "folder": "voice_001", "slot": "a"})[0] == 400
    assert _post(srv, "/api/names", {"a": "x" * 41, "b": ""})[0] == 400


def test_media_confined(served):
    p, srv = served
    assert _call(srv, "/media/face/person_001/01_00m01s_hello_there.jpg") == (200, b"x")
    assert _call(srv, "/media/voice/voice_001/01_00m01s_hello_there.wav") == (200, b"x")
    for bad in ("/media/face/manifest.json", "/media/face/%2e%2e/%2e%2e/review_T.json",
                "/media/voice/..%2Fmanifest.json", "/media/face/../../../secret.jpg",
                "/media/face/person_001/missing.jpg", "/media/voice/voice_001/01_00m01s_hello_there.jpg",
                "/media/other/x.jpg"):
        assert _call(srv, bad)[0] == 404, bad


def test_foreign_host_rejected(served):
    p, srv = served
    port = srv.server_address[1]
    assert _call(srv, "/", headers={"Host": f"evil.example:{port}"})[0] == 403
    assert _call(srv, "/api/state", headers={"Host": f"evil.example:{port}"})[0] == 403
    assert _call(srv, "/api/assign", {"kind": "voice", "folder": "voice_001", "slot": "a"},
                 headers={"Host": f"evil.example:{port}"})[0] == 403
    assert _call(srv, "/api/state", headers={"Host": f"localhost:{port}"})[0] == 200
    assert srv.server_address[0] == "127.0.0.1"


def test_finalize_by_assignment_deletes_nothing(served):
    p, srv = served
    before = sorted(x for x in p.people_dir.rglob("*") if x.is_file())
    _assign_all(srv)
    excl = "02_00m02s_hello_there.wav"
    assert _post(srv, "/api/exclude", {"kind": "voice", "folder": "voice_002", "file": excl, "excluded": True})[0] == 200
    status, out = _post(srv, "/api/finalize", {"allow_sparse": False})
    assert status == 200 and out["ok"] is True and out["next"].startswith("magicvideo plan")
    rep = out["report"]
    assert rep["voice_face_link"] == "set by owner on the enrollment page"
    assert rep["voices"].startswith("approved") and rep["faces"].startswith("approved")
    after = set(x for x in p.people_dir.rglob("*") if x.is_file())
    assert set(before) <= after                                   # nothing deleted or moved
    refs = dict(np.load(p.people_dir / "refs.npz"))
    assert refs["voice_a_all"].shape == (3, 4)
    assert refs["voice_b_all"].shape == (4, 4)                    # voice_002 (3) + voice_003 (2) - 1 excluded
    assert refs["face_a_all"].shape == (4, 4) and refs["face_b_all"].shape == (4, 4)


def test_finalize_reports_shortfall_then_sparse(served):
    p, srv = served
    _assign_all(srv, voices_b=("voice_003",))                      # B has 2 voice clips (minimum 3)
    status, out = _post(srv, "/api/finalize", {"allow_sparse": False})
    assert status == 200 and "partner_b" in out["report"]["voices"] and "--allow-sparse" in out["report"]["voices"]
    assert "voice_b_all" not in dict(np.load(p.people_dir / "refs.npz"))
    status, out = _post(srv, "/api/finalize", {"allow_sparse": True})
    assert out["report"]["voices"].startswith("approved")
    assert any("partner_b has 2 voice clips" in x for x in out["report"]["sparse"])
    assert dict(np.load(p.people_dir / "refs.npz"))["voice_b_all"].shape == (2, 4)


def test_names_written_to_enrollment(served):
    p, srv = served
    assert _post(srv, "/api/names", {"a": " Ann ", "b": "Bo"})[0] == 200
    assert _state_file(p)["names"] == {"a": "Ann", "b": "Bo"}
    _assign_all(srv)
    _post(srv, "/api/finalize", {"allow_sparse": True})
    meta = yaml.safe_load((p.people_dir / "enrollment.yaml").read_text(encoding="utf-8"))
    assert meta["names"] == {"a": "Ann", "b": "Bo"}


def test_owner_assignment_never_swapped(project, monkeypatch):
    from magicvideo import enroll

    calls = []
    monkeypatch.setattr(enroll, "_voice_face_swap", lambda *a: (calls.append(1), True)[1])
    both = {"face": {"a": ["person_001"], "b": ["person_002"]},
            "voice": {"a": ["voice_001"], "b": ["voice_002", "voice_003"]}}
    rep = enroll.finalize(project, assignment=both, excluded=set())
    assert calls == [] and rep["voice_face_link"] == "set by owner on the enrollment page"
    rep = enroll.finalize(project, assignment={"voice": both["voice"]}, excluded=set())
    assert calls == []
    assert rep["voice_face_link"] == ("set by owner for voices on the enrollment page; "
                                      "faces kept from before (not cross-checked)")
    refs = dict(np.load(project.people_dir / "refs.npz"))
    assert np.allclose(refs["voice_a"], A) and np.allclose(refs["voice_b"][1], 1.0, atol=0.2)
    rep = enroll.finalize(project, assignment={"face": both["face"]}, excluded=set())
    assert calls == [] and rep["voice_face_link"].startswith("set by owner for faces")


def test_media_cannot_leave_review_folder(served):
    p, srv = served
    (p.people_dir / "secret.jpg").write_bytes(b"secret")
    for kind in ("face", "voice"):
        status, body = _call(srv, f"/media/{kind}/..%2F..%2F..%2Fsecret.jpg")
        assert status == 404 and b"secret" not in body
