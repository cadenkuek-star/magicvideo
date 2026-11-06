"""Review page, review server and stale-reference detection (synthetic, no models)."""
import numpy as np

from magicvideo.enroll import refs_fingerprint
from magicvideo.plan.planner import stale_refs
from magicvideo.project import Project


def _project(tmp_path):
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    return Project.init(tmp_path / "work", [tmp_path / "raw"], "T", tmp_path / "people")


def test_stale_refs_detected(tmp_path):
    p = _project(tmp_path)
    assert refs_fingerprint(p.people_dir) is None
    assert stale_refs(p, {"refs_sha256": None}) is False            # no refs then, none now
    np.savez(p.people_dir / "refs.npz", voice_a=np.ones(4, np.float32))
    fp = refs_fingerprint(p.people_dir)
    assert fp and len(fp) == 64
    assert stale_refs(p, {"refs_sha256": fp}) is False
    assert stale_refs(p, {"refs_sha256": None}) is True             # refs appeared after the plan
    np.savez(p.people_dir / "refs.npz", voice_a=np.zeros(4, np.float32))
    assert refs_fingerprint(p.people_dir) != fp
    assert stale_refs(p, {"refs_sha256": fp}) is True               # refs changed after the plan


# ---------------------------------------------------------------------------- W7: review server
import json  # noqa: E402
import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

import pytest  # noqa: E402
import yaml  # noqa: E402

BOM = b"\xef\xbb\xbf"
M1, M2 = "c_1:conversation:000033", "c_1:third_party:000100"


@pytest.fixture
def served(tmp_path):
    from magicvideo import review

    p = _project(tmp_path)
    (p.plan_dir / "plan_v001.json").write_text(json.dumps(
        {"refs_sha256": None, "moments": [{"id": M1, "cls": "couple"}, {"id": M2, "cls": "third_party"}]}),
        encoding="utf-8")
    (p.plan_dir / "storyboard_v001.html").write_text("<html>storyboard v001</html>", encoding="utf-8")
    (p.plan_dir / "thumbs").mkdir()
    (p.plan_dir / "thumbs" / "a.jpg").write_bytes(b"jpegdata")
    srv = review.make_server(p, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield p, srv
    srv.shutdown()
    srv.server_close()
    t.join(5)


def _call(srv, path, body=None, headers=None, method=None, raw=None):
    port = srv.server_address[1]
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdrs = dict(headers or {})
    if data is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _overrides_file(p):
    return yaml.safe_load((p.root / "overrides.yaml").read_text(encoding="utf-8-sig"))


def test_post_keep_writes_overrides(served):
    p, srv = served
    original = BOM + b"# my notes\nevents:\n  e1:\n    coverage_budget_s: 60\nmoments: {}\nclips: {}\n"
    (p.root / "overrides.yaml").write_bytes(original)
    status, body = _call(srv, "/api/moment", {"id": M1, "value": "keep"})
    assert status == 200 and json.loads(body)["ok"] is True
    raw = (p.root / "overrides.yaml").read_bytes()
    assert not raw.startswith(BOM)
    data = yaml.safe_load(raw.decode("utf-8"))
    assert data["moments"] == {M1: "keep"}
    assert data["events"] == {"e1": {"coverage_budget_s": 60}}
    assert (p.root / "overrides.yaml.bak").read_bytes() == original
    # a second write in the same session does not replace the backup of the original
    _call(srv, "/api/moment", {"id": M2, "value": "couple"})
    assert (p.root / "overrides.yaml.bak").read_bytes() == original
    assert _overrides_file(p)["moments"] == {M1: "keep", M2: "couple"}


def test_clear_removes_entry(served):
    p, srv = served
    _call(srv, "/api/moment", {"id": M1, "value": "drop"})
    assert _overrides_file(p)["moments"] == {M1: "drop"}
    status, body = _call(srv, "/api/moment", {"id": M1, "value": "clear"})
    assert status == 200
    assert _overrides_file(p)["moments"] == {}                       # deleted, not set to null
    status, body = _call(srv, "/api/overrides")
    got = json.loads(body)
    assert status == 200 and got["overrides"]["moments"] == {} and got["version"] == "v001"
    assert got["stale_refs"] is False


def test_unknown_moment_rejected(served):
    p, srv = served
    before = (p.root / "overrides.yaml").read_bytes()
    status, _ = _call(srv, "/api/moment", {"id": "nope:conversation:000001", "value": "keep"})
    assert status == 400
    assert (p.root / "overrides.yaml").read_bytes() == before


def test_bad_value_rejected(served):
    p, srv = served
    before = (p.root / "overrides.yaml").read_bytes()
    assert _call(srv, "/api/moment", {"id": M1, "value": "maybe"})[0] == 400
    assert _call(srv, "/api/moment", {"id": M1})[0] == 400
    assert _call(srv, "/api/moment", raw=b"{not json")[0] == 400
    assert _call(srv, "/api/moment", {"id": M1, "value": "keep"}, headers={"Content-Type": "text/plain"})[0] == 415
    assert (p.root / "overrides.yaml").read_bytes() == before


def test_foreign_host_rejected(served):
    p, srv = served
    port = srv.server_address[1]
    assert _call(srv, "/api/overrides", headers={"Host": f"evil.example:{port}"})[0] == 403
    assert _call(srv, "/api/overrides", headers={"Host": "127.0.0.1:1"})[0] == 403
    assert _call(srv, "/api/moment", {"id": M1, "value": "keep"}, headers={"Host": f"evil.example:{port}"})[0] == 403
    assert _call(srv, "/api/overrides", headers={"Host": f"localhost:{port}"})[0] == 200
    assert "keep" not in (p.root / "overrides.yaml").read_text(encoding="utf-8")


def test_server_binds_loopback(served):
    p, srv = served
    assert srv.server_address[0] == "127.0.0.1"
    status, body = _call(srv, "/")
    assert status == 200 and b"storyboard v001" in body


def test_thumb_path_traversal_blocked(served):
    p, srv = served
    (p.plan_dir / "secret.txt").write_text("secret", encoding="utf-8")
    assert _call(srv, "/thumbs/a.jpg") == (200, b"jpegdata")
    for bad in ("/thumbs/../secret.txt", "/thumbs/..%2Fsecret.txt", "/thumbs/%2e%2e/secret.txt",
                "/thumbs/..%5Csecret.txt", "/thumbs/missing.jpg"):
        status, body = _call(srv, bad)
        assert status == 404 and b"secret" not in body, bad


def test_storyboard_has_offline_download(tmp_path):
    from magicvideo.plan.storyboard import write_storyboard

    p = _project(tmp_path)
    p.inventory_path.write_text(json.dumps({"version": 1, "clips": []}), encoding="utf-8")
    mom = {"id": M2, "clip_id": "c_1", "kind": "third_party", "cls": "third_party", "t0": 1.0, "t1": 4.0,
           "abs_t0": 1.0, "dur": 3.0, "selected": True, "reason": "third-party excerpt", "event_id": "e1",
           "desc": "", "identity": {}}
    plan = {"name": "T", "warnings": [], "chapters": [{"index": 1, "date": "2026-04-19", "name": "Day 1",
                                                       "event_ids": ["e1"]}],
            "events": [{"id": "e1", "label": "Lunch", "type": "meal", "couple_time": 0, "coverage_used": 0,
                        "coverage_budget": 0, "third_party_used": 3}],
            "stats": {"selected": 1, "moments": 1, "planned_seconds": 3, "raw_seconds": 3,
                      "shares": {k: {"share": 0.0} for k in ("couple", "coverage", "transit", "third_party")}},
            "moments": [mom]}
    out = write_storyboard(p, plan, {"total_frames": 0}, p.plan_dir / "storyboard_v001.html")
    page = out.read_text(encoding="utf-8")
    assert "window.OVERRIDES" in page and "window.PLAN_VERSION" in page
    assert 'id="download-overrides"' in page
    assert "<textarea" not in page
    assert "this is us" in page                       # shown for a third-party card
