"""End-to-end on synthetic footage: real ffmpeg + real quality analysis; transcripts/tags stand in for models."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from magicvideo import ffmpeg
from magicvideo.analysis.runner import run_analysis
from magicvideo.plan.planner import run_plan
from magicvideo.project import Project
from magicvideo.qc.runner import run_qc
from magicvideo.render.renderer import Renderer
from magicvideo.util import write_json

pytestmark = pytest.mark.skipif(not ffmpeg.has_filter("v360"), reason="needs ffmpeg with v360")


def _make(path: Path, size: str, dur: float, tone: int | None, vf: str | None = None) -> None:
    """A steady 'camera': one still frame with temporal sensor noise; vf can add camera motion."""
    still = path.with_suffix(".png")
    ffmpeg.run(["-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}", "-frames:v", "1", str(still)])
    args = ["-y", "-v", "error", "-loop", "1", "-framerate", "30", "-t", str(dur), "-i", str(still)]
    vf = ",".join(x for x in ("noise=alls=6:allf=t", vf) if x)
    if tone:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={dur}"]
    args += ["-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    args += (["-c:a", "aac", "-b:a", "96k", "-shortest"] if tone else ["-an"]) + [str(path)]
    ffmpeg.run(args)
    still.unlink()


@pytest.fixture(scope="module")
def trip(tmp_path_factory):
    root = tmp_path_factory.mktemp("trip")
    src = root / "raw" / "Seoul"
    src.mkdir(parents=True)
    _make(src / "DJI_20260419083601_0001_D.MP4", "640x360", 12, 440)                 # conversation
    _make(src / "DJI_20260419084051_0002_D.MP4", "360x640", 8, 660)                  # portrait
    _make(src / "DJI_20260419090000_0003_D.MP4", "800x450", 8, None,                 # shaky, no audio
          vf="crop=640:360:x='80+60*sin(n*1.3)':y='45+40*cos(n*1.7)'")
    _make(src / "VID_20260419_120000_00_001.mp4", "1024x512", 8, 520)                # 360 equirect export
    _make(src / "DJI_20260420100000_0005_D.MP4", "640x360", 8, 330)                  # day 2
    p = Project.init(root / "work" / "Seoul", [src], "Seoul", root / "people")
    pol = yaml.safe_load((p.root / "policy.yaml").read_text())
    pol["output"].update({"landscape_size": [640, 360], "portrait_size": [360, 640]})
    pol["output"]["video"].update({"preset": "veryfast", "crf": 23})
    (p.root / "policy.yaml").write_text(yaml.safe_dump(pol))
    p = Project(p.root)
    run_analysis(p, steps=["quality"])
    clips = {Path(c["path"]).name: c for c in p.inventory()}
    speech = {
        "DJI_20260419083601_0001_D.MP4": [(1.0, 1.6, "this"), (1.7, 2.3, "is"), (2.4, 3.0, "great"),
                                          (7.2, 7.8, "look"), (7.9, 8.6, "there")],    # 4.2 s pause inside
        "VID_20260419_120000_00_001.mp4": [(1.0, 2.0, "wow"), (2.2, 3.0, "amazing")],
        "DJI_20260420100000_0005_D.MP4": [(2.0, 3.0, "morning")],
    }
    tags = {
        "DJI_20260419083601_0001_D.MP4": [{"t": 0.0, "tags": ["food", "table"], "people": "partners", "interest": 0.7, "desc": "table"}],
        "DJI_20260419084051_0002_D.MP4": [{"t": 0.0, "tags": ["food"], "people": "none", "interest": 0.9, "desc": "dish"},
                                          {"t": 3.0, "tags": ["food"], "people": "none", "interest": 0.9, "desc": "dish"}],
        "DJI_20260419090000_0003_D.MP4": [{"t": 0.0, "tags": ["street"], "people": "crowd", "interest": 0.6, "desc": "street"}],
        "VID_20260419_120000_00_001.mp4": [{"t": 0.0, "view": 2, "tags": ["viewpoint"], "people": "none", "interest": 0.9, "desc": "view"}],
    }
    for name, c in clips.items():
        d = p.analysis_dir(c["clip_id"])
        ws = [{"t0": a, "t1": b, "w": w, "p": 0.9} for a, b, w in speech.get(name, [])]
        write_json(d / "transcript.json", {"backend": "synthetic", "words": ws, "segments": []})
        p.set_step_status(c["clip_id"], "asr", "done")
        write_json(d / "tags.json", {"backend": "synthetic", "frames": tags.get(name, [])})
        p.set_step_status(c["clip_id"], "tags", "done")
    return p


def test_inventory(trip):
    clips = {Path(c["path"]).name: c for c in trip.inventory()}
    assert len(clips) == 5
    c360 = clips["VID_20260419_120000_00_001.mp4"]
    assert c360["camera"]["make"] == "Insta360" and c360["projection"] == "equirect"
    assert clips["DJI_20260419084051_0002_D.MP4"]["orientation"] == "portrait"
    assert clips["DJI_20260420100000_0005_D.MP4"]["capture_start"] == "2026-04-20T10:00:00"


def test_shaky_clip_measures_more_jitter(trip):
    clips = {Path(c["path"]).name: c for c in trip.inventory()}
    def p90(name):
        q = json.loads((trip.analysis_dir(clips[name]["clip_id"]) / "quality.json").read_text())
        j = sorted(q["jitter"])
        return j[int(len(j) * 0.9)]
    assert p90("DJI_20260419090000_0003_D.MP4") > 3 * p90("DJI_20260419083601_0001_D.MP4")


def test_plan_render_qc(trip, monkeypatch):
    paths = run_plan(trip)
    tl = json.loads(paths["timeline"].read_text())
    plan = json.loads(paths["plan"].read_text())
    assert tl["orientation"] == "landscape" and len(tl["chapters"]) == 2
    modes = {s["reframe"]["mode"] for s in tl["segments"] + tl["overlays"]}
    assert {"static_bg", "v360", "fill"} <= modes, modes
    assert any(o["reason"] == "cover_pause" for o in tl["overlays"]), "4 s pause should be shortened under a cutaway"
    conv = [m for m in plan["moments"] if m["kind"] == "conversation"]
    assert conv and all(m["selected"] for m in conv)

    # determinism: re-planning gives identical files (new version number only)
    again = run_plan(trip)
    assert again["timeline"].read_text() == paths["timeline"].read_text()
    assert again["plan"].read_text() == paths["plan"].read_text()

    out = Renderer(trip, "v001").run()
    master = Path(out["master"])
    assert master.exists() and len(out["chapters"]) == 2
    info = ffmpeg.probe(master)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert int(v["nb_frames"]) == tl["total_frames"]
    assert abs(float(v["duration"]) - float(a["duration"])) < 0.021

    import opentimelineio as otio
    t = otio.adapters.read_from_file(out["otio"])
    assert [tr.name for tr in t.tracks] == ["V1", "V2 cutaways", "A1"]

    from magicvideo.analysis import asr

    def _no_asr(*a, **k):
        raise asr.BackendMissing("disabled in test")

    monkeypatch.setattr(asr, "transcribe", _no_asr)
    verdict, qc_path = run_qc(trip, "v001")
    checks = json.loads(qc_path.read_text())["checks"]
    failed = [c for c in checks if c["status"] == "FAIL"]
    assert not failed, failed
    skipped = {c["id"] for c in checks if c["status"] == "SKIPPED"}
    assert verdict == "INCOMPLETE" and "speech.partner_words_rendered" in skipped  # no ASR backend here
    with pytest.raises(Exception):
        Renderer(trip, "v001").run()  # never overwrite an existing output
