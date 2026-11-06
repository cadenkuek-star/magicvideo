from helpers import clip, clipdata, policy

from magicvideo.analysis.voices import build_windows, label_windows
from magicvideo.plan.moments import build_clip_moments, conversations

import numpy as np

A, B, O = "PARTNER_A", "PARTNER_B", "OTHER"


def test_voice_windows_split_on_gap_and_length():
    ws = [{"t0": 0.0, "t1": 0.4}, {"t0": 0.5, "t1": 0.9}, {"t0": 2.0, "t1": 2.3}, {"t0": 2.4, "t1": 5.8}]
    win = build_windows(ws, gap=0.5, max_len=3.0)
    assert [(w["w0"], w["w1"]) for w in win] == [(0, 2), (2, 3), (3, 4)]


def test_voice_labels_with_refs_and_short_window_inheritance():
    p = policy()
    a = np.array([1.0, 0, 0], np.float32)
    b = np.array([0, 1.0, 0], np.float32)
    o = np.array([0, 0, 1.0], np.float32)
    windows = [{"t0": 0, "t1": 2}, {"t0": 2.2, "t1": 2.5}, {"t0": 3, "t1": 5}, {"t0": 6, "t1": 8}]
    emb = np.stack([a, o, b, o])
    labels = label_windows(emb, windows, {"voice_a": a, "voice_b": b}, p)
    assert labels == [A, A, B, O]  # 0.3 s window inherits from its longer neighbour
    assert label_windows(emb, windows, None, p) == ["UNKNOWN"] * 4


def test_conversation_joins_turns_and_excludes_leading_other():
    p = policy()
    cd = clipdata(clip(duration=60), [(1.0, 2.0, "guide"), (4.0, 5.0, "hi"), (6.0, 7.0, "hey"),
                                       (8.0, 9.0, "look"), (30.0, 31.0, "later")], speakers=[O, A, B, O, A])
    convs = conversations(cd, p)
    assert len(convs) == 2                      # 9 s -> 30 s gap > join_gap
    c = convs[0]
    assert abs(c.t0 - 3.3) < 1e-9                # 0.7 s pre-roll, clear of the guide's leading word
    assert 7.0 <= c.t1 < 8.0                     # post-roll stops before the trailing guide word
    assert c.speakers == ["PARTNER_A", "PARTNER_B"]


def test_pause_classes():
    p = policy()
    cd = clipdata(clip(duration=60), [(1, 2, "a"), (3, 4, "b"), (8, 9, "c"), (20, 21, "d")], speakers=[A, B, A, B])
    convs = conversations(cd, p)
    # 4 s pause (4 -> 8) is shortenable; 11 s pause (9 -> 20) splits
    assert len(convs) == 2
    assert convs[0].pauses == [[4, 8]]
    assert convs[1].pauses == []


def test_unknown_speech_policy():
    cd = clipdata(clip(duration=20), [(1, 2, "a"), (2.5, 3, "b")])
    assert len(conversations(cd, policy())) == 1
    p = policy(identity={"unknown_speech_is_couple": False})
    assert conversations(cd, p) == []


def test_coverage_avoids_conversations_and_respects_silent_solo_rule():
    p = policy()
    cd = clipdata(clip(duration=40), [(10, 11, "a"), (12, 13, "b")], speakers=[A, B])
    ms = build_clip_moments(cd, "general", p)
    conv = [m for m in ms if m.kind == "conversation"][0]
    for m in ms:
        if m.kind == "coverage":
            assert m.t1 <= conv.t0 or m.t0 >= conv.t1
            assert 3.0 <= m.dur <= 6.0 + 1e-9


def test_third_party_speech_is_separate_from_couple():
    p = policy()
    cd = clipdata(clip(duration=120), [(5, 6, "welcome"), (6.2, 30, "long guide talk"), (60, 61, "wow")],
                  speakers=[O, O, A])
    ms = build_clip_moments(cd, "general", p)
    kinds = sorted({m.kind for m in ms})
    assert "third_party" in kinds and "conversation" in kinds
    tp = [m for m in ms if m.kind == "third_party"][0]
    assert tp.cls == "third_party"


# ---------------------------------------------------------------------------- W4: couple prior
def _win(t0, t1):
    return {"t0": t0, "t1": t1, "w0": 0, "w1": 1}


def test_couple_prior_relabels_unmatched_voice():
    from magicvideo.plan.data import apply_couple_prior

    out = apply_couple_prior([_win(1, 2), _win(3, 4)], [O, A], [], policy())
    assert out == ["COUPLE", A]


def test_stranger_on_screen_keeps_third_party():
    from magicvideo.plan.data import apply_couple_prior

    p = policy()  # pad_s 1.0
    w = [_win(10, 12)]
    assert apply_couple_prior(w, [O], [11.0], p) == [O]       # inside the window
    assert apply_couple_prior(w, [O], [13.0], p) == [O]       # exactly t1 + pad
    assert apply_couple_prior(w, [O], [9.0], p) == [O]        # exactly t0 - pad
    assert apply_couple_prior(w, [O], [13.01], p) == ["COUPLE"]   # just outside t1 + pad
    assert apply_couple_prior(w, [O], [8.99], p) == ["COUPLE"]    # just outside t0 - pad
    # a stranger near one window does not touch a distant window
    two = [_win(10, 12), _win(40, 42)]
    assert apply_couple_prior(two, [O, O], [13.0], p) == [O, "COUPLE"]


def test_couple_prior_off_keeps_old_labels():
    from magicvideo.plan.data import apply_couple_prior

    p = policy(identity={"couple_prior": False})
    assert apply_couple_prior([_win(1, 2), _win(3, 4)], [O, A], [], p) == [O, A]


def test_couple_turns_make_a_conversation():
    cd = clipdata(clip(duration=60), [(1.0, 2.0, "hello"), (2.5, 3.5, "there")], speakers=["COUPLE", "COUPLE"])
    convs = conversations(cd, policy())
    assert len(convs) == 1
    assert convs[0].kind == "conversation" and convs[0].cls == "couple"
    assert convs[0].partner_words > 0


def test_stranger_times_thresholds():
    from magicvideo.analysis.faces import stranger_times

    fa = np.array([1.0, 0, 0, 0], np.float32)
    fb = np.array([0, 1.0, 0, 0], np.float32)
    far = np.array([0, 0, 1.0, 0], np.float32)
    near = np.array([0.25, 0, np.sqrt(1 - 0.0625), 0], np.float32)   # 0.25 to face_a: not a stranger
    dets = [{"t": 1.0, "q": 0.6}, {"t": 2.0, "q": 0.3}, {"t": 3.0, "q": 0.6}]
    emb = np.stack([far, far, near])
    assert stranger_times(dets, emb, {"face_a": fa, "face_b": fb}, policy()) == [1.0]
    assert stranger_times(dets, emb, None, policy()) == []
    assert stranger_times([], np.zeros((0, 4), np.float32), {"face_a": fa, "face_b": fb}, policy()) == []


def test_identity_omits_voice_without_refs():
    ev = {"t0": 1.0, "t1": 2.0, "raw": "UNKNOWN", "label": "UNKNOWN", "voice_best": None, "stranger": False}
    cd = clipdata(clip(duration=60), [(1.0, 2.0, "hello"), (2.5, 3.5, "there")], speakers=["COUPLE", "COUPLE"])
    cd.window_evidence = [ev]
    ident = conversations(cd, policy())[0].identity
    assert "voice_best" not in ident and ident["stranger_on_screen"] is False
    cd.window_evidence = [{**ev, "voice_best": 0.5}]
    assert conversations(cd, policy())[0].identity["voice_best"] == 0.5


def test_edge_speech_warns_at_clip_end():
    from magicvideo.plan.planner import edge_speech_warnings

    cd = clipdata(clip(cid="c_la", duration=23.1), [(15.0, 16.0, "a"), (20.5, 21.7, "end")], speakers=[A, B])
    conv = conversations(cd, policy())
    assert conv
    warns = edge_speech_warnings(conv, {cd.id: cd}, policy())
    assert warns == ["c_la.mp4: speech runs to the end of the file (last word ends at 21.7s of 23.1s); "
                     "the sentence may be cut. If you trimmed this clip, export it a few seconds longer."]


def test_edge_speech_quiet_when_there_is_room():
    from magicvideo.plan.planner import edge_speech_warnings

    cd = clipdata(clip(duration=23.1), [(1.0, 1.5, "a"), (17.0, 18.0, "b")], speakers=[A, B])
    sel = conversations(cd, policy())
    assert sel and edge_speech_warnings(sel, {cd.id: cd}, policy()) == []


def test_edge_speech_uses_last_word_not_moment_edge():
    from magicvideo.plan.model import Moment
    from magicvideo.plan.planner import edge_speech_warnings

    cd = clipdata(clip(duration=23.1), [(1.0, 1.5, "a"), (19.0, 20.0, "b")], speakers=[A, B])
    m = Moment(id="m1", clip_id=cd.id, kind="conversation", t0=0.5, t1=23.0, abs_t0=0.5, cls="couple",
               selected=True)
    assert edge_speech_warnings([m], {cd.id: cd}, policy()) == []


def test_edge_speech_skips_camera_originals():
    from magicvideo.plan.planner import edge_speech_warnings

    cd = clipdata(clip(cid="c_la", duration=23.1, capture_source="filename"),
                  [(15.0, 16.0, "a"), (20.5, 21.7, "end")], speakers=[A, B])
    conv = conversations(cd, policy())
    assert conv and edge_speech_warnings(conv, {cd.id: cd}, policy()) == []
    on = policy(moments={"edge_speech": {"camera_originals": True}})
    assert len(edge_speech_warnings(conv, {cd.id: cd}, on)) == 1


def test_edge_speech_still_warns_for_exports():
    from magicvideo.plan.planner import edge_speech_warnings

    cd = clipdata(clip(cid="c_la", duration=23.1, capture_source="mtime"),
                  [(15.0, 16.0, "a"), (20.5, 21.7, "end")], speakers=[A, B])
    conv = conversations(cd, policy())
    assert len(edge_speech_warnings(conv, {cd.id: cd}, policy())) == 1
