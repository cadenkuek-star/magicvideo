"""Agent tagging (no API key, no anthropic SDK): export frame grids, import the agent's answers."""
from __future__ import annotations

import json

import pytest

from magicvideo import ffmpeg, ingest
from magicvideo.analysis import tags as T
from magicvideo.analysis.runner import run_analysis, run_inventory
from magicvideo.project import Project
from magicvideo.util import read_json, write_json


@pytest.fixture
def trip(tmp_path):
    """A project with one 60 s synthetic clip: frames every 3 s -> 20 frames -> grids of 9, 9 and 2."""
    src = tmp_path / "raw"
    src.mkdir()
    ffmpeg.run(["-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=5", "-t", "60",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an",
                str(src / "DJI_20260419083601_0001_D.MP4")])
    p = Project.init(tmp_path / "work", [src], "T", tmp_path / "people")
    clip = ingest.plannable(run_inventory(p))[0]
    return p, clip


def _cells(n, tags=("food",), start=1):
    return {"cells": [{"cell": i, "tags": list(tags), "people": "partners", "interest": 0.8, "desc": f"cell {i}"}
                      for i in range(start, start + n)]}


def _answer(p, clip, grid, payload):
    path = p.root / "tagging" / clip["clip_id"] / f"grid_{grid:03d}.answer.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


def test_agent_export_writes_grids_and_tasks(trip):
    p, clip = trip
    n = T.export_for_agent(p, clip, clip["analysis_path"], p.policy)
    assert n == 3
    d = p.root / "tagging" / clip["clip_id"]
    assert sorted(f.name for f in d.iterdir()) == [
        "grid_001.cells.json", "grid_001.jpg", "grid_002.cells.json", "grid_002.jpg",
        "grid_003.cells.json", "grid_003.jpg"]
    cells = json.loads((d / "grid_001.cells.json").read_text())
    assert len(cells) == 9 and cells[0] == {"cell": 1, "t": 0.0, "view": None} and cells[1]["t"] == 3.0
    assert len(json.loads((d / "grid_003.cells.json").read_text())) == 2
    assert (d / "grid_001.jpg").read_bytes()[:2] == b"\xff\xd8"
    # TASKS.md: prompt, allowed lists, schema, answer rule, checklist of unanswered grids
    assert T.write_tasks(p) == 3
    text = (p.root / "tagging" / "TASKS.md").read_text(encoding="utf-8")
    assert T.SYSTEM_PROMPT in text and "viewpoint" in text and "mixed" in text
    assert '"cells"' in text and "grid_NNN.answer.json" in text
    for g in (1, 2, 3):
        assert str(d / f"grid_{g:03d}.jpg") in text
    # grids whose frames are already in tags.json are skipped
    frames = [{"t": c["t"], "tags": [], "people": "none", "interest": 0.5, "desc": ""} for c in cells]
    write_json(p.analysis_dir(clip["clip_id"]) / "tags.json", {"backend": "agent", "frames": frames})
    assert T.export_for_agent(p, clip, clip["analysis_path"], p.policy) == 2


def test_agent_import_merges_answers(trip):
    p, clip = trip
    T.export_for_agent(p, clip, clip["analysis_path"], p.policy)
    _answer(p, clip, 1, _cells(9))
    res = T.import_agent_tags(p)
    assert res["imported"] == 1 and res["invalid"] == [] and res["missing"] == 2
    tj = read_json(p.analysis_dir(clip["clip_id"]) / "tags.json")
    assert tj["backend"] == "agent" and len(tj["frames"]) == 9 and tj["frames_sent"] == 9
    assert [f["t"] for f in tj["frames"]] == [3.0 * i for i in range(9)]
    assert tj["frames"][0]["tags"] == ["food"] and tj["frames"][0]["people"] == "partners"
    assert p.step_status(clip["clip_id"]).get("tags") != "done"
    _answer(p, clip, 2, _cells(9))
    _answer(p, clip, 3, _cells(2))
    res = T.import_agent_tags(p)
    assert res["missing"] == 0
    assert len(read_json(p.analysis_dir(clip["clip_id"]) / "tags.json")["frames"]) == 20
    assert p.step_status(clip["clip_id"])["tags"] == "done"


def test_agent_import_rejects_bad_answers(trip):
    p, clip = trip
    T.export_for_agent(p, clip, clip["analysis_path"], p.policy)
    first = _cells(9)
    first["cells"][0]["tags"] = ["food", "not-a-tag"]
    _answer(p, clip, 1, first)
    bad = _cells(9)
    bad["cells"][3]["cell"] = 12                      # cell 12 of a 9-cell grid
    _answer(p, clip, 2, bad)
    _answer(p, clip, 3, "{this is not json")
    res = T.import_agent_tags(p)
    assert res["imported"] == 1 and len(res["invalid"]) == 2
    assert any("grid_002" in x for x in res["invalid"]) and any("grid_003" in x for x in res["invalid"])
    tj = read_json(p.analysis_dir(clip["clip_id"]) / "tags.json")
    assert len(tj["frames"]) == 9 and tj["frames"][0]["tags"] == ["food"]      # unknown tag dropped
    assert max(f["t"] for f in tj["frames"]) == 24.0                           # nothing from the bad grids
    assert p.step_status(clip["clip_id"]).get("tags") != "done"


def test_agent_import_is_idempotent(trip):
    p, clip = trip
    T.export_for_agent(p, clip, clip["analysis_path"], p.policy)
    for g, n in ((1, 9), (2, 9), (3, 2)):
        _answer(p, clip, g, _cells(n))
    T.import_agent_tags(p)
    path = p.analysis_dir(clip["clip_id"]) / "tags.json"
    first = path.read_text(encoding="utf-8")
    res = T.import_agent_tags(p)
    assert path.read_text(encoding="utf-8") == first
    assert res["frames_added"] == 0 and res["imported"] == 0
    assert read_json(path)["frames_sent"] == 20


def test_analyze_with_agent_provider_skips_not_fails(trip):
    p, clip = trip
    assert p.policy("cloud.provider") == "agent"
    summary = run_analysis(p, steps=["tags"])
    assert summary["tags"]["failed"] == 0 and summary["tags"]["skipped"] == 1
    assert p.step_status(clip["clip_id"])["tags"] == "skipped: awaiting agent tags"
    assert len(list((p.root / "tagging" / clip["clip_id"]).glob("grid_*.jpg"))) == 3
    assert (p.root / "tagging" / "TASKS.md").exists()
