from helpers import clip, clipdata, policy

from magicvideo.analysis.orient import pick_rotation
from magicvideo.plan.budget import select_event
from magicvideo.plan.model import Event
from magicvideo.plan.moments import build_clip_moments
from magicvideo.plan.retakes import apply_retakes, find_retake_groups, tokens, text_similarity

A, B = "PARTNER_A", "PARTNER_B"


def _ev(eid="e1"):
    return Event(id=eid, type="landmark", label="x", date="2026-04-19", abs_t0=0, abs_t1=1, clip_ids=[])


def _takes():
    line = [(1.0, 1.4, "hi"), (1.5, 1.9, "we"), (2.0, 2.4, "are"), (2.5, 2.9, "in"), (3.0, 3.6, "hunza")]
    cds = {}
    for k, (cid, start, dur) in enumerate((("c_t1", "2026-04-19T10:00:00", 4.0),    # cut off at the end
                                            ("c_t2", "2026-04-19T10:01:00", 12.0),
                                            ("c_t3", "2026-04-19T10:02:00", 12.0))):
        cds[cid] = clipdata(clip(cid, duration=dur, start=start), line, speakers=[A] * 5, desc_seed=k)
    other = clipdata(clip("c_o", duration=12.0, start="2026-04-19T10:03:00"),
                     [(1.0, 1.5, "look"), (1.6, 2.0, "at"), (2.1, 2.5, "that"), (2.6, 3.0, "mountain")], speakers=[A] * 4)
    cds["c_o"] = other
    moments = []
    for cd in cds.values():
        for m in build_clip_moments(cd, "landmark", policy()):
            m.event_id = "e1"
            moments.append(m)
    return cds, moments


def test_tokens_and_similarity():
    assert tokens("Hi, we're in Hunza!") == ["hi", "were", "in", "hunza"]
    assert tokens("我們到了") == ["我", "們", "到", "了"]
    assert text_similarity(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert text_similarity([], ["a"]) == 0.0


def test_same_line_groups_and_best_take_is_the_last_complete_one():
    cds, moments = _takes()
    groups = find_retake_groups(moments, cds, policy())
    assert len(groups) == 1 and sorted(m.clip_id for m in groups[0]) == ["c_t1", "c_t2", "c_t3"]
    stats = apply_retakes(moments, cds, policy(), {"moments": {}})
    assert stats == {"retake_groups": 1, "retakes_dropped": 2}
    convs = {m.clip_id: m for m in moments if m.kind == "conversation"}
    assert convs["c_t3"].retake_of is None                      # later complete take wins
    assert convs["c_t1"].retake_of == convs["c_t3"].id          # cut-off take loses even though it is a take
    assert convs["c_o"].retake_group is None                    # a different line is not a retake
    select_event(_ev(), moments, cds, policy(), {"moments": {}})
    assert convs["c_t3"].selected and convs["c_o"].selected
    assert not convs["c_t1"].selected and convs["c_t1"].reason.startswith("retake: best take is")


def test_keep_override_rescues_a_retake_and_policy_can_disable():
    cds, moments = _takes()
    apply_retakes(moments, cds, policy(), {"moments": {}})
    convs = {m.clip_id: m for m in moments if m.kind == "conversation"}
    select_event(_ev(), moments, cds, policy(), {"moments": {convs["c_t2"].id: "keep"}})
    assert convs["c_t2"].selected and not convs["c_t1"].selected
    cds, moments = _takes()
    assert apply_retakes(moments, cds, policy(retakes={"enabled": False}), {"moments": {}}) == \
        {"retake_groups": 0, "retakes_dropped": 0}


def test_takes_far_apart_are_not_grouped():
    cds, moments = _takes()
    far = policy(retakes={"window_s": 30})
    assert find_retake_groups(moments, cds, far) == []


def test_partner_shots_may_be_short_and_score_higher():
    p = policy()
    # 2.5 s clean span: too short for scenery, long enough when a partner is on screen
    c = clip(duration=2.5)
    cd = clipdata(c)
    assert [m for m in build_clip_moments(cd, "general", p) if m.kind == "coverage"] == []
    cd.face_dets = [{"t": t / 2, "box": [0.4, 0.3, 0.2, 0.3], "score": 0.9, "q": 0.8, "track": 0} for t in range(5)]
    cd.face_labels = [A] * 5
    cov = [m for m in build_clip_moments(cd, "general", p) if m.kind == "coverage"]
    assert len(cov) == 1 and cov[0].partners_visible == [A] and cov[0].max_len == p("identity.silent_solo_shot_max_s")[A]
    plain = clipdata(clip(duration=20))
    withp = clipdata(clip(duration=20))
    withp.face_dets = [{"t": t / 2, "box": [0.4, 0.3, 0.2, 0.3], "score": 0.9, "q": 0.8, "track": 0} for t in range(40)]
    withp.face_labels = [B] * 40
    s0 = max(m.score for m in build_clip_moments(plain, "general", p) if m.kind == "coverage")
    s1 = max(m.score for m in build_clip_moments(withp, "general", p) if m.kind == "coverage")
    assert s1 > s0


def test_pick_rotation():
    sc = {0: {"score": 0.0, "faces": 0}, 90: {"score": 2.7, "faces": 3}, 180: {"score": 0.0, "faces": 0}, 270: {"score": 0.9, "faces": 1}}
    assert pick_rotation(sc, min_faces=2, min_ratio=1.5) == 90
    sc[0] = {"score": 2.0, "faces": 2}
    assert pick_rotation(sc, 2, 1.5) == 0          # 2.7 < 1.5 x 2.0: not clear enough
    sc[90] = {"score": 3.5, "faces": 4}
    assert pick_rotation(sc, 2, 1.5) == 90
    assert pick_rotation({r: {"score": 0.0, "faces": 0} for r in (0, 90, 180, 270)}, 2, 1.5) == 0


def test_orientation_flags_and_portrait_drop():
    from magicvideo.plan.planner import flag_orientation
    from magicvideo.plan.model import Moment

    land = clipdata(clip("c_l", duration=20))
    port = clipdata(clip("c_p", duration=20, w=1080, h=1920))
    flipped = clipdata(clip("c_f", duration=20))
    flipped.auto_rotate = 180
    cds = {"c_l": land, "c_p": port, "c_f": flipped}
    ms = [Moment(id="a", clip_id="c_l", kind="coverage", t0=0, t1=5, abs_t0=0, cls="coverage"),
          Moment(id="b", clip_id="c_p", kind="coverage", t0=0, t1=5, abs_t0=1, cls="coverage"),
          Moment(id="c", clip_id="c_p", kind="conversation", t0=6, t1=12, abs_t0=7, cls="couple"),
          Moment(id="d", clip_id="c_f", kind="coverage", t0=0, t1=5, abs_t0=2, cls="coverage")]
    flag_orientation(ms, cds, "landscape", policy(), {"clips": {}})
    assert ms[0].flags == [] and ms[1].flags == ["portrait"] and ms[2].flags == ["portrait"]
    assert ms[3].flags == ["rotated:180"] and ms[1].max_len is None
    # drop: portrait B-roll is left out, the conversation is only flagged; an owner rotate override is labelled
    p = policy(reframe={"portrait_in_landscape": "drop"})
    for m in ms:
        m.flags, m.max_len, m.reason = [], None, ""
    flag_orientation(ms, cds, "landscape", p, {"clips": {"c_f": {"rotate": 90}}})
    assert ms[1].max_len == 0.0 and ms[1].reason.startswith("dropped: portrait")
    assert ms[2].max_len is None and ms[2].flags == ["portrait"]
    assert ms[3].flags == ["rotate:90", "portrait"]   # 90 degrees turns a landscape clip into a portrait one
    # a portrait master flags landscape clips instead
    for m in ms:
        m.flags, m.max_len, m.reason = [], None, ""
    flag_orientation(ms, cds, "portrait", p, {"clips": {}})
    assert ms[0].flags == ["landscape"] and ms[1].flags == [] and ms[0].max_len is None
