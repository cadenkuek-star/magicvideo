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
