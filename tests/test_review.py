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
