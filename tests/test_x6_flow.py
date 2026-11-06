"""Insta360 flow: plan unstitched .insv from its preview, list what to export, refuse to render without it."""
import pytest
from helpers import clip, policy

from magicvideo import ingest
from magicvideo.project import Project, ProjectError
from magicvideo.plan.planner import filter_plannable, x6_export_list


def _x6(cid="c_x6", rel="026_VID_20260919_110940_00_004.insv"):
    return clip(cid, rel_path=rel, render_projection="dual_fisheye", projection="dual_fisheye")


def test_unstitched_kept_when_plan_unstitched():
    c, flat = _x6(), clip("c_flat")
    warns: list[str] = []
    out = filter_plannable([c, flat], set(), policy(), warns)
    assert [x["clip_id"] for x in out] == ["c_x6", "c_flat"]
    assert warns == [f"{c['rel_path']}: planned from its preview; if the film uses it you will be asked to "
                     "export it from Insta360 Studio before render"]
    warns = []
    off = policy(insta360={"plan_unstitched": False})
    out = filter_plannable([c, flat], set(), off, warns)
    assert [x["clip_id"] for x in out] == ["c_flat"]
    assert warns == [f"{c['rel_path']}: unstitched 360 recording skipped (export it from Insta360 Studio, "
                     "or set insta360.allow_unstitched_render)"]
    assert filter_plannable([flat], {"c_flat"}, policy(), []) == []


def test_export_list_names_used_unstitched_only():
    used, unused, stitched = _x6("c_a", "a.insv"), _x6("c_b", "b.insv"), clip("c_s", render_projection="equirect")
    tl = {"fps": [30, 1],
          "segments": [{"clip_id": "c_a", "src_in": 12.0, "frames": 60}, {"clip_id": "c_s", "src_in": 1.0, "frames": 30},
                       {"clip_id": "c_a", "src_in": 2.0, "frames": 30}],
          "overlays": [{"clip_id": "c_a", "src_in": 40.04, "frames": 30}]}
    got = x6_export_list(tl, [used, unused, stitched], policy())
    assert got == [{"rel_path": "a.insv", "uses": [[2.0, 3.0], [12.0, 14.0], [40.0, 41.0]]}]
    assert x6_export_list(tl, [used], policy(insta360={"allow_unstitched_render": True})) == []


def test_renderer_refuses_before_writing(tmp_path, monkeypatch):
    import json

    from magicvideo.render import renderer as R

    (tmp_path / "raw").mkdir()
    p = Project.init(tmp_path / "work", [tmp_path / "raw"], "T", tmp_path / "people")
    tl = {"name": "T", "fps": [30, 1], "width": 640, "height": 360, "segments": [], "overlays": [],
          "chapters": [], "total_frames": 0}
    (p.plan_dir / "timeline_v001.json").write_text(json.dumps(tl), encoding="utf-8")
    p.inventory_path.write_text(json.dumps({"version": 1, "clips": []}), encoding="utf-8")
    monkeypatch.setattr(R, "x6_export_list", lambda *a, **k: [{"rel_path": "a.insv", "uses": [[1.0, 2.0]]}])
    before = sorted(p.root.rglob("*"))
    with pytest.raises(ProjectError) as e:
        R.Renderer(p, "v001").run()
    assert "a.insv" in str(e.value) and "x6_exports_v001.md" in str(e.value)
    assert sorted(p.root.rglob("*")) == before


def test_clip_id_stable_when_export_added():
    def member(rel, proj, make="Insta360"):
        return {"clip_id": "c_" + rel, "path": f"/x/{rel}", "rel_path": rel, "camera": {"make": make},
                "projection": proj, "render_path": f"/x/{rel}"}

    def build(with_export):
        ms = [member("VID_20260919_110940_00_004.insv", "dual_fisheye"),
              member("LRV_20260919_110940_11_004.lrv", "flat")]
        if with_export:
            ms.append(member("VID_20260919_110940_00_004.mp4", "equirect"))
        ingest.group_insta360(ms)
        return ms

    before, after = build(False), build(True)
    prim = lambda ms: next(c for c in ms if "role" not in c)  # noqa: E731
    assert prim(before)["clip_id"] == prim(after)["clip_id"] == "c_VID_20260919_110940_00_004.insv"
    assert prim(before)["render_projection"] == "dual_fisheye" and prim(after)["render_projection"] == "equirect"
