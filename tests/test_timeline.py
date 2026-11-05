from fractions import Fraction

from helpers import clip, clipdata, policy

from magicvideo.analysis.views360 import angle_diff, circular_mean, view_yaws, yaw_of
from magicvideo.plan.assemble import build_timeline, choose_fps, fps_family
from magicvideo.plan.camera360 import camera_path
from magicvideo.plan.model import Chapter, Moment
from magicvideo.qc.runner import check, verdict
from magicvideo.render.audio import sample_bounds
from magicvideo.render.filters import path_for_piece, per_frame_commands
from magicvideo.render.renderer import pieces_of

A, B = "PARTNER_A", "PARTNER_B"


def test_sample_bounds_have_no_drift_over_1000_segments():
    fps, sr = Fraction(30000, 1001), 48000
    frame, total = 0, 0
    for i in range(1000):
        n = 17 + (i * 7) % 90
        a, b = sample_bounds(frame, n, fps, sr)
        total += b - a
        frame += n
    assert total == sample_bounds(0, frame, fps, sr)[1]


def test_fps_family_and_choice():
    assert fps_family(59.94) == Fraction(30000, 1001)
    assert fps_family(50.0) == Fraction(25)
    assert fps_family(60.0) == Fraction(30)
    assert choose_fps(policy(), [(29.97, 100), (25.0, 20)]) == Fraction(30000, 1001)
    assert choose_fps(policy(output={"fps": "25"}), [(29.97, 100)]) == Fraction(25)


def _timeline(pause_cover=True, portrait=False, with_shot=True):
    p = policy()
    c1 = clip("c_1", duration=60)
    cd = clipdata(c1, [(1, 2, "a"), (2.2, 3, "b"), (7, 8, "c"), (8.2, 9, "d")], speakers=[A, B, A, B])
    c2 = clip("c_2", duration=30, w=720, h=1280) if portrait else clip("c_2", duration=30)
    cd2 = clipdata(c2)
    conv = Moment(id="conv", clip_id="c_1", kind="conversation", t0=0.3, t1=10.5, abs_t0=0.3, pauses=[[3, 7]],
                  cls="couple", event_id="e1", selected=True)
    cover = Moment(id="cov", clip_id="c_2", kind="coverage", t0=5, t1=11, abs_t0=100, cls="coverage",
                   event_id="e1", score=0.8, selected=False)
    shot = Moment(id="shot", clip_id="c_2", kind="coverage", t0=20, t1=25, abs_t0=120, cls="coverage",
                  event_id="e1", score=0.9, selected=True)
    sel = [conv] + ([shot] if with_shot else [])
    moments = sel + ([cover] if pause_cover else [])
    tl = build_timeline("T", sel, moments, {"c_1": cd, "c_2": cd2},
                        [Chapter(1, "2026-04-19", "Day 1", ["e1"])], {"e1": 1}, p, {"moments": {}, "clips": {}})
    return tl


def test_segments_tile_and_pause_is_hidden_by_overlay():
    tl = _timeline()
    segs = tl["segments"]
    for prev, cur in zip(segs, segs[1:]):
        assert cur["start_frame"] == prev["start_frame"] + prev["frames"]
    assert tl["total_frames"] == segs[-1]["start_frame"] + segs[-1]["frames"]
    assert [s["join"] for s in segs[:2]] == ["start", "hidden_pause"]
    # 4 s pause shortened to 1.2 s: conversation 10.2 s -> 7.4 s
    conv_frames = segs[0]["frames"] + segs[1]["frames"]
    assert abs(conv_frames / 30 - 7.4) < 0.07
    ov = tl["overlays"][0]
    assert ov["reason"] == "cover_pause" and ov["start_frame"] < segs[1]["start_frame"] < ov["start_frame"] + ov["frames"]


def test_pause_kept_without_any_broll():
    tl = _timeline(pause_cover=False, with_shot=False)
    assert tl["overlays"] == []
    assert tl["segments"][0]["frames"] == round(10.2 * 30)


def test_selected_shot_moves_under_pause_when_no_spare_broll():
    tl = _timeline(pause_cover=False, with_shot=True)
    assert [o["moment_id"] for o in tl["overlays"]] == ["shot"]
    assert all(s["clip_id"] == "c_1" for s in tl["segments"])  # the shot no longer stands alone


def test_portrait_clip_in_landscape_master_gets_static_background():
    tl = _timeline(portrait=True)
    shot = [s for s in tl["segments"] if s["clip_id"] == "c_2"][0]
    assert tl["orientation"] == "landscape"
    assert shot["reframe"]["mode"] == "static_bg"  # 720 px short side < 1600 -> no crop


def test_pieces_split_at_overlays():
    tl = _timeline()
    pieces = pieces_of(tl)
    assert sum(p["frames"] for p in pieces) == tl["total_frames"]
    assert any(p["is_overlay"] for p in pieces)
    for p in pieces:
        assert p["frames"] > 0


def test_360_helpers():
    assert view_yaws(6) == [0.0, 60.0, 120.0, 180.0, -120.0, -60.0]
    assert abs(yaw_of(90, 0.5, 100)) == 90
    assert abs(circular_mean([170, -170]) - 180) < 1e-6 or abs(circular_mean([170, -170]) + 180) < 1e-6
    assert angle_diff(-170, 170) == 20


def test_camera_path_rate_limit_and_holds():
    p = policy()
    c = clip("c_360", duration=30, w=5760, h=2880, projection="equirect", render_projection="equirect",
             camera={"make": "Insta360", "model": None, "kind": "360"})
    cd = clipdata(c, [(0.5, 1, "a"), (1, 9, "b")], speakers=[A, A])
    # partner A drifts from yaw 0 to 40 degrees over 10 s
    cd.face_dets = [{"t": t / 2, "box": [0.4, 0.4, 0.1, 0.1], "yaw": t * 2.0, "pitch": 0.0} for t in range(20)]
    cd.face_labels = [A] * len(cd.face_dets)
    path = camera_path(cd, 0.0, 300, 30.0, "conversation", p)
    yaws = [k[1] for k in path]
    for a, b in zip(yaws, yaws[1:]):
        assert abs(angle_diff(b, a)) <= p("insta360.max_yaw_speed_dps") * 0.1 + 1e-6
    assert yaws[0] == yaws[min(9, len(yaws) - 1)]  # still for the first second
    assert all(k[3] >= 90 for k in path)         # 5.7K source keeps hfov >= 90


def test_piece_path_and_commands():
    path = [[0, 0.0, 0.0, 90.0], [3, 3.0, 0.0, 90.0], [6, 90.0, 0.0, 90.0]]
    sub = path_for_piece(path, 2, 4)
    assert sub[0] == [0, 0.0, 0.0, 90.0] and sub[1] == [1, 3.0, 0.0, 90.0]
    lines = per_frame_commands(path, 8, 30.0, 640, 360)
    assert lines and all(line.endswith(";") for line in lines)
    assert any("yaw 90" in line for line in lines)  # cut to 90 is not interpolated
    assert not any("yaw 45" in line for line in lines)


def test_verdict():
    assert verdict([check("a", "PASS")]) == "PASS"
    assert verdict([check("a", "PASS"), check("b", "SKIPPED")]) == "INCOMPLETE"
    assert verdict([check("a", "FAIL"), check("b", "SKIPPED")]) == "FAIL"
