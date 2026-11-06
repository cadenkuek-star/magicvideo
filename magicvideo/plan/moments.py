"""Moments: conversations, third-party speech, actions, coverage candidates (brief §6.3)."""
from __future__ import annotations

import numpy as np

from ..analysis.tags import TYPE_OF_TAG, event_type
from ..analysis.voices import COUPLE, OTHER
from ..policy import Policy
from ..util import merge_intervals, subtract_intervals
from .data import PARTNERS, ClipData, is_couple_speaker
from .model import Moment, Turn

GUARD = 0.05


def moment_id(clip_id: str, kind: str, t0: float) -> str:
    return f"{clip_id}:{kind}:{int(round(t0 * 10)):06d}"


def _snap_bounds(cd: ClipData, t0: float, t1: float, first_word: int, last_word: int) -> tuple[float, float]:
    """Move edges outside any word they would cut (words outside the moment)."""
    start, end = t0, t1
    for i, w in enumerate(cd.words):
        if i < first_word and w["t1"] > start:
            start = max(start, w["t1"] + GUARD)
        if i > last_word and w["t0"] < end:
            end = min(end, w["t0"] - GUARD)
    start = max(0.0, min(start, cd.words[first_word]["t0"]))
    end = min(cd.duration, max(end, cd.words[last_word]["t1"]))
    return start, end


def _chains(turns: list[Turn], include, join_gap: float) -> list[list[Turn]]:
    chains: list[list[Turn]] = []
    cur: list[Turn] = []
    for t in turns:
        if cur and t.t0 - cur[-1].t1 > join_gap:
            chains.append(cur)
            cur = []
        cur.append(t)
    if cur:
        chains.append(cur)
    out = []
    for ch in chains:
        # trim leading/trailing turns that are not "include"
        while ch and not include(ch[0]):
            ch = ch[1:]
        while ch and not include(ch[-1]):
            ch = ch[:-1]
        if ch:
            out.append(ch)
    return out


def _identity(cd: ClipData, t0: float, t1: float) -> dict:
    """Speaker-identity evidence from the voice windows overlapping [t0, t1] (empty when there is none)."""
    ev = [w for w in cd.window_evidence if w["t1"] > t0 and w["t0"] < t1]
    if not ev:
        return {}
    out = {}
    scores = [w["voice_best"] for w in ev if w["voice_best"] is not None]
    if scores:
        out["voice_best"] = round(max(scores), 3)
    out["stranger_on_screen"] = any(w["stranger"] for w in ev)
    out["assumed_couple"] = sum(1 for w in ev if w["raw"] == OTHER and w["label"] == COUPLE)
    return out


def conversations(cd: ClipData, policy: Policy) -> list[Moment]:
    p = "moments.conversation."
    join_gap = float(policy(p + "join_gap_s"))
    keep_pause = float(policy(p + "keep_pause_up_to_s"))
    split_pause = float(policy(p + "split_pause_over_s"))
    keep_others = bool(policy(p + "keep_other_speakers_inside"))
    couple = lambda t: is_couple_speaker(t.speaker, policy)  # noqa: E731
    turns = cd.turns if keep_others else [t for t in cd.turns if couple(t)]
    out: list[Moment] = []
    for chain in _chains(turns, couple, join_gap):
        w0, w1 = chain[0].w0, chain[-1].w1  # word index range [w0, w1)
        # split on very long pauses
        pieces, start = [], w0
        for i in range(w0 + 1, w1):
            if cd.words[i]["t0"] - cd.words[i - 1]["t1"] > split_pause:
                pieces.append((start, i))
                start = i
        pieces.append((start, w1))
        for a, b in pieces:
            if not any(couple(t) for t in chain if t.w0 < b and t.w1 > a):
                continue
            t0 = cd.words[a]["t0"] - float(policy(p + "pre_roll_s"))
            t1 = cd.words[b - 1]["t1"] + float(policy(p + "post_roll_s"))
            t0, t1 = _snap_bounds(cd, t0, t1, a, b - 1)
            pauses = [[cd.words[i - 1]["t1"], cd.words[i]["t0"]] for i in range(a + 1, b)
                      if keep_pause < cd.words[i]["t0"] - cd.words[i - 1]["t1"] <= split_pause]
            speakers = sorted({cd.word_speaker(i) for i in range(a, b)})
            partner_words = sum(1 for i in range(a, b) if is_couple_speaker(cd.word_speaker(i), policy))
            out.append(Moment(id=moment_id(cd.id, "conversation", t0), clip_id=cd.id, kind="conversation",
                              t0=t0, t1=t1, abs_t0=cd.abs_start + t0, speakers=speakers, words=b - a,
                              partner_words=partner_words, pauses=pauses, cls="couple",
                              partners_visible=cd.partners_visible(t0, t1), score=1.0,
                              identity=_identity(cd, t0, t1)))
    return out


def third_party(cd: ClipData, occupied: list[tuple[float, float]], policy: Policy) -> list[Moment]:
    join_gap = float(policy("moments.conversation.join_gap_s"))
    others = [t for t in cd.turns if not is_couple_speaker(t.speaker, policy)
              and not any(a <= t.t0 and t.t1 <= b for a, b in occupied)]
    out = []
    for chain in _chains(others, lambda t: True, join_gap):
        t0 = max(0.0, chain[0].t0 - 0.5)
        t1 = min(cd.duration, chain[-1].t1 + 1.0)
        out.append(Moment(id=moment_id(cd.id, "third_party", t0), clip_id=cd.id, kind="third_party",
                          t0=t0, t1=t1, abs_t0=cd.abs_start + t0, speakers=sorted({t.speaker for t in chain}),
                          words=chain[-1].w1 - chain[0].w0, cls="third_party",
                          identity=_identity(cd, t0, t1)))
    return out


def actions(cd: ClipData, occupied: list[tuple[float, float]], policy: Policy) -> list[Moment]:
    act_tags = set(policy("moments.action.tags"))
    win = float(policy("moments.action.partner_window_s"))
    spans = []
    for f in cd.tags:
        hit = act_tags.intersection(f.get("tags", []))
        if not hit:
            continue
        t = float(f["t"])
        visible = cd.partners_visible(t - win, t + win, min_share=0.1) or f.get("people") in ("partners", "mixed")
        if visible:
            spans.append((max(0.0, t - float(policy("moments.action.pre_s"))),
                          min(cd.duration, t + float(policy("moments.action.post_s")))))
    out = []
    for t0, t1 in merge_intervals(spans):
        if any(a <= t0 and t1 <= b for a, b in occupied):
            continue
        tags = sorted({t for f in cd.tags_in(t0, t1, 0) for t in f.get("tags", [])})
        out.append(Moment(id=moment_id(cd.id, "action", t0), clip_id=cd.id, kind="action", t0=t0, t1=t1,
                          abs_t0=cd.abs_start + t0, tags=tags, cls="couple", score=0.9,
                          partners_visible=cd.partners_visible(t0, t1, 0.1)))
    return out


def _interest(frames: list[dict]) -> float:
    return float(np.mean([f.get("interest", 0.5) for f in frames])) if frames else 0.5


def coverage(cd: ClipData, occupied: list[tuple[float, float]], event_type_hint: str, policy: Policy) -> list[Moment]:
    smin, smax = float(policy("coverage.shot_min_s")), float(policy("coverage.shot_max_s"))
    step = float(policy("coverage.step_s"))
    margin = float(policy("coverage.margin_s"))
    holes = [(a - margin, b + margin) for a, b in occupied]
    out: list[Moment] = []
    for free in subtract_intervals((0.0, cd.duration), holes):
        for c0, c1 in cd.quality.clean_spans(free[0], free[1], policy):
            if c1 - c0 < smin:
                continue
            # candidate windows, then greedy best-first without overlap
            L = min(smax, c1 - c0)
            starts = list(np.arange(c0, c1 - L + 1e-6, step)) or [c0]
            cands = []
            for s in starts:
                e = s + L
                frames = cd.tags_in(s, e, 0.0)
                score = cd.quality.score(s, e, policy) * (0.5 + 0.5 * _interest(frames))
                cands.append((score, s, e, frames))
            cands.sort(key=lambda x: (-x[0], x[1]))
            chosen: list[tuple[float, float]] = []
            for score, s, e, frames in cands:
                if any(s < b and e > a for a, b in chosen):
                    continue
                chosen.append((s, e))
                tags = sorted({t for f in frames for t in f.get("tags", [])})
                people = [f.get("people") for f in frames]
                visible = cd.partners_visible(s, e)
                speech = cd.speech_in(s, e)
                featured_others = (people and people.count("others") > len(people) / 2) or \
                    any(t in ("performance", "guide") for t in tags)
                ttype = event_type([f.get("tags", []) for f in frames]) if frames else event_type_hint
                cls = "third_party" if featured_others and not visible else (
                    "transit" if ttype == "transit" else "coverage")
                m = Moment(id=moment_id(cd.id, "coverage", s), clip_id=cd.id, kind="coverage", t0=s, t1=e,
                           abs_t0=cd.abs_start + s, score=score, tags=tags, cls=cls,
                           partners_visible=visible, interest=_interest(frames),
                           desc=(frames[0].get("desc", "") if frames else ""))
                if len(visible) == 1 and not speech:
                    cap = float(policy("identity.silent_solo_shot_max_s").get(visible[0], smax))
                    if cap <= 0:
                        m.reason = f"dropped: silent solo shot of {visible[0]}"
                        m.max_len = 0.0
                    else:
                        m.max_len = cap
                out.append(m)
    out.sort(key=lambda m: m.t0)
    return out


def tag_types(cd: ClipData) -> list[str]:
    return [TYPE_OF_TAG[t] for f in cd.tags for t in f.get("tags", []) if t in TYPE_OF_TAG]


def build_clip_moments(cd: ClipData, event_type_hint: str, policy: Policy) -> list[Moment]:
    conv = conversations(cd, policy)
    occ = [(m.t0, m.t1) for m in conv]
    tp = third_party(cd, occ, policy)
    act = actions(cd, occ, policy)
    occ_all = occ + [(m.t0, m.t1) for m in tp] + [(m.t0, m.t1) for m in act]
    cov = coverage(cd, occ_all, event_type_hint, policy)
    return sorted(conv + tp + act + cov, key=lambda m: (m.t0, m.kind))


__all__ = ["build_clip_moments", "conversations", "third_party", "actions", "coverage", "moment_id", "PARTNERS"]
