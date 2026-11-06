import numpy as np
from helpers import clip, clipdata, policy

from magicvideo.analysis.quality import QualityTrack
from magicvideo.plan.budget import apply_guards, eff_len, select_all, select_event
from magicvideo.plan.model import Event, Moment

A, B, O = "PARTNER_A", "PARTNER_B", "OTHER"


def _ev(eid="e1", typ="transit"):
    return Event(id=eid, type=typ, label="x", date="2026-04-19", abs_t0=0, abs_t1=1, clip_ids=["c_1"])


def _cov(i, cd, t0, score, cls="transit", eid="e1"):
    return Moment(id=f"m{i}", clip_id=cd.id, kind="coverage", t0=t0, t1=t0 + 6, abs_t0=t0, score=score, cls=cls,
                  event_id=eid)


def test_coverage_budget_and_overshoot_cap():
    p = policy()
    cd = clipdata(clip(duration=600), desc_seed=1)
    ms = [_cov(i, cd, i * 10.0, 0.9 - i * 0.01) for i in range(30)]
    ev = _ev()
    select_event(ev, ms, {cd.id: cd}, p, {"moments": {}, "events": {}})
    used = sum(eff_len(m) for m in ms if m.selected)
    lo, hi = p("budgets_s.transit")
    assert used <= hi * (1 + p("coverage.budget_overshoot_max")) + 1e-9
    assert used >= hi - 6.0
    assert sum(m.selected for m in ms) == 7  # 7 x 6 s = 42 s: reaches the 40 s budget, under the 46 s ceiling


def test_mmr_skips_near_duplicates():
    p = policy()
    n = 300
    same = np.tile(np.eye(1, 176, 0, dtype=np.float32), (301, 1))  # every second looks identical
    q = QualityTrack({"fps": 10, "t": [i / 10 for i in range(n * 10)], "sharp": [0.6] * (n * 10),
                      "luma": [0.45] * (n * 10), "white": [0.0] * (n * 10), "black": [0.0] * (n * 10),
                      "jitter": [0.001] * (n * 10), "desc_t": [float(i) for i in range(301)]}, same)
    cd = clipdata(clip(duration=n), quality=q)
    ms = [_cov(i, cd, i * 10.0, 0.9) for i in range(20)]
    select_event(_ev(), ms, {cd.id: cd}, p, {"moments": {}, "events": {}})
    assert sum(m.selected for m in ms) == 1
    assert any("near-duplicate" in m.reason for m in ms)


def test_protected_couple_moments_and_overrides():
    p = policy()
    cd = clipdata(clip(duration=600))
    conv = Moment(id="conv1", clip_id=cd.id, kind="conversation", t0=0, t1=300, abs_t0=0, cls="couple", event_id="e1")
    conv2 = Moment(id="conv2", clip_id=cd.id, kind="conversation", t0=310, t1=320, abs_t0=310, cls="couple", event_id="e1")
    ms = [conv, conv2] + [_cov(i, cd, 330 + i * 10.0, 0.5) for i in range(5)]
    over = {"moments": {"conv2": "drop", "m4": "keep"}, "events": {}}
    select_event(_ev(), ms, {cd.id: cd}, p, over)
    assert conv.selected and "protected" in conv.reason   # a 5-minute conversation is never budgeted away
    assert not conv2.selected and conv2.reason == "dropped in review"
    assert next(m for m in ms if m.id == "m4").selected


def test_third_party_budget_and_excerpts():
    p = policy()
    cd = clipdata(clip(duration=600), [(111, 112, "wow")], speakers=[A])
    tps = [Moment(id=f"t{i}", clip_id=cd.id, kind="third_party", t0=i * 40.0, t1=i * 40.0 + 30, abs_t0=i * 40.0,
                  cls="third_party", event_id="e1") for i in range(4)]
    ev = _ev(typ="performance")
    select_event(ev, tps, {cd.id: cd}, p, {"moments": {}, "events": {}})
    sel = [m for m in tps if m.selected]
    assert all(m.dur <= p("third_party.excerpt_max_s") + 1e-9 for m in tps)
    assert sum(m.dur for m in sel) <= p("budgets_s.third_party_per_event")
    # the moment the couple reacts to ("wow" at 111 s, right after 80-110 s) ranks first and keeps its end
    assert tps[2].selected and abs(tps[2].t1 - 110.0) < 1e-9


def test_film_guard_limits_transit_share():
    p = policy()
    cd = clipdata(clip(duration=4000))
    ms = [Moment(id="c", clip_id=cd.id, kind="conversation", t0=0, t1=100, abs_t0=0, cls="couple", event_id="e0",
                 selected=True)]
    for e in range(10):
        for i in range(5):
            m = _cov(e * 10 + i, cd, 200 + e * 100 + i * 10, 0.5 + i * 0.01, eid=f"e{e + 1}")
            m.selected = True
            ms.append(m)
    notes = apply_guards(ms, p)
    total = sum(eff_len(m) for m in ms if m.selected)
    transit = sum(eff_len(m) for m in ms if m.selected and m.cls == "transit")
    # one shot per event is always kept, so the limit may stay above 10% and is reported
    per_event = {m.event_id for m in ms if m.selected and m.cls == "transit"}
    assert len(per_event) == 10
    assert transit / total <= 0.10 or notes


def test_select_all_is_deterministic():
    p = policy()
    cd = clipdata(clip(duration=300), [(10, 11, "a"), (12, 13, "b")], speakers=[A, B])
    from magicvideo.plan.moments import build_clip_moments
    out = []
    for _ in range(2):
        ms = build_clip_moments(cd, "general", p)
        for m in ms:
            m.event_id = "e1"
        select_all([_ev(typ="general")], ms, {cd.id: cd}, p, {"moments": {}, "events": {}})
        out.append([(m.id, m.selected, m.reason) for m in ms])
    assert out[0] == out[1]


def test_couple_override_counts_as_couple():
    from magicvideo.plan.budget import apply_overrides

    p = policy()
    cd = clipdata(clip(duration=600))
    tp = Moment(id="t1", clip_id=cd.id, kind="third_party", t0=100, t1=105, abs_t0=100, cls="third_party",
                event_id="e1")
    other = Moment(id="t2", clip_id=cd.id, kind="third_party", t0=200, t1=205, abs_t0=200, cls="third_party",
                   event_id="e1")
    over = {"moments": {"t1": "couple"}, "events": {}}
    ms = [tp, other]
    apply_overrides(ms, {cd.id: cd}, over)
    assert tp.cls == "couple" and other.cls == "third_party"
    select_event(_ev(typ="performance"), ms, {cd.id: cd}, p, over)
    assert tp.selected and "kept in review" in tp.reason
    selected = [m for m in ms if m.selected]
    couple = sum(eff_len(m) for m in selected if m.cls == "couple")
    third = sum(eff_len(m) for m in selected if m.cls == "third_party")
    assert couple == 5.0 and third == (5.0 if other.selected else 0.0)
    assert tp not in [m for m in selected if m.cls == "third_party"]
