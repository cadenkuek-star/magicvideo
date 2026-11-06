"""Budgets and selection per event, film-level guards, runtime target (brief §6.5)."""
from __future__ import annotations

import numpy as np

from ..policy import Policy
from .data import ClipData, is_couple_speaker
from .model import Event, Moment


def eff_len(m: Moment) -> float:
    return min(m.dur, m.max_len) if m.max_len is not None else m.dur


def apply_overrides(moments: list[Moment], clips: dict[str, ClipData], overrides: dict) -> None:
    rules = overrides.get("moments", {}) or {}
    for m in moments:
        rule = rules.get(m.id)
        if isinstance(rule, dict):
            dur = clips[m.clip_id].duration
            m.t0 = max(0.0, m.t0 - float(rule.get("extend_start_s", 0.0)))
            m.t1 = min(dur, m.t1 + float(rule.get("extend_end_s", 0.0)))
            m.abs_t0 = clips[m.clip_id].abs_start + m.t0
        elif rule == "couple":  # "this is us": the moment counts as couple time, not as other people
            m.cls = "couple"


def _override(m: Moment, overrides: dict) -> str | None:
    rule = (overrides.get("moments", {}) or {}).get(m.id)
    return rule if isinstance(rule, str) else None


def _third_party_score(m: Moment, cd: ClipData, policy: Policy) -> float:
    win = float(policy("third_party.reaction_window_s"))
    reaction = any(is_couple_speaker(t.speaker, policy) and m.t1 - 1.0 <= t.t0 <= m.t1 + win for t in cd.turns)
    frames = cd.tags_in(m.t0, m.t1, 0.0)
    interest = float(np.mean([f.get("interest", 0.5) for f in frames])) if frames else 0.5
    return (0.5 if reaction else 0.0) + 0.5 * interest


def _trim_excerpt(m: Moment, cd: ClipData, policy: Policy) -> None:
    """Keep the best excerpt: the end of the moment when the couple reacts, else its start."""
    mx = float(policy("third_party.excerpt_max_s"))
    if m.dur <= mx:
        return
    win = float(policy("third_party.reaction_window_s"))
    reacts = any(is_couple_speaker(t.speaker, policy) and m.t1 - 1.0 <= t.t0 <= m.t1 + win for t in cd.turns)
    if reacts:
        m.t0 = m.t1 - mx
    else:
        m.t1 = m.t0 + mx
    m.abs_t0 = cd.abs_start + m.t0


def select_event(ev: Event, moments: list[Moment], clips: dict[str, ClipData], policy: Policy,
                 overrides: dict, coverage_scale: float = 1.0) -> None:
    ev_rule = (overrides.get("events", {}) or {}).get(ev.id) or {}
    budgets = policy("budgets_s")
    lo_hi = budgets.get(ev.type) or budgets["general"]
    ev.coverage_budget = float(ev_rule.get("coverage_budget_s", lo_hi[1] * coverage_scale))
    tp_budget = float(budgets["third_party_per_event"])

    for m in moments:
        m.selected, m.reason = False, m.reason if m.reason.startswith("dropped: silent") else ""

    # 1. protected couple moments
    for m in moments:
        if m.kind in ("conversation", "action"):
            if _override(m, overrides) == "drop":
                m.reason = "dropped in review"
            else:
                m.selected, m.reason = True, "couple moment (protected)"
    ev.couple_time = sum(eff_len(m) for m in moments if m.selected)

    # 2. third-party, best first, within budget
    # a third-party moment the owner marked "couple" has cls couple by now; it is still handled here, like "keep"
    tp = [m for m in moments if m.kind in ("third_party", "coverage")
          and (m.cls == "third_party" or (m.kind == "third_party" and _override(m, overrides) == "couple"))]
    for m in tp:
        if m.kind == "third_party":  # score on the full moment, then keep the best excerpt
            m.score = _third_party_score(m, clips[m.clip_id], policy)
            _trim_excerpt(m, clips[m.clip_id], policy)
    used = 0.0
    for m in sorted(tp, key=lambda m: (-m.score, m.abs_t0)):
        rule = _override(m, overrides)
        if rule == "drop":
            m.reason = "dropped in review"
            continue
        keep = rule in ("keep", "couple")
        if keep or used + eff_len(m) <= tp_budget:
            m.selected, m.reason = True, "third-party excerpt" + (" (kept in review)" if keep else "")
            used += eff_len(m)
        else:
            m.reason = "over third-party budget"
    ev.third_party_used = used

    # 3. coverage via MMR (quality x novelty) up to the event budget
    cands = [m for m in moments if m.kind == "coverage" and m.max_len != 0.0
             and (m.cls in ("coverage", "transit") or _override(m, overrides) == "couple")]
    lam = float(policy("coverage.mmr_lambda"))
    max_sim = float(policy("coverage.max_similarity"))
    chosen_desc: list[np.ndarray] = []
    used = 0.0
    descs = {m.id: clips[m.clip_id].quality.desc_at(m.t0, m.t1) for m in cands}
    forced = [m for m in cands if _override(m, overrides) in ("keep", "couple")]
    for m in forced:
        m.selected, m.reason = True, "coverage (kept in review)"
        used += eff_len(m)
        if descs[m.id] is not None:
            chosen_desc.append(descs[m.id])
    pool = [m for m in cands if m not in forced and _override(m, overrides) != "drop"]
    for m in cands:
        if _override(m, overrides) == "drop":
            m.reason = "dropped in review"
    ceiling = ev.coverage_budget * (1.0 + float(policy("coverage.budget_overshoot_max")))
    while pool and used < ev.coverage_budget:
        best, best_val = None, -1e9
        for m in pool:
            if used + eff_len(m) > ceiling:
                continue
            d = descs[m.id]
            sim = max((float(d @ c) for c in chosen_desc), default=0.0) if d is not None else 0.0
            if sim >= max_sim:
                continue
            val = lam * m.score - (1 - lam) * sim
            if val > best_val + 1e-12 or (abs(val - best_val) <= 1e-12 and best is not None and m.abs_t0 < best.abs_t0):
                best, best_val = m, val
        if best is None:
            break
        pool.remove(best)
        best.selected, best.reason = True, "coverage"
        used += eff_len(best)
        if descs[best.id] is not None:
            chosen_desc.append(descs[best.id])
    for m in pool:
        if not m.reason:
            m.reason = "near-duplicate of a chosen shot" if descs[m.id] is not None and chosen_desc and \
                max(float(descs[m.id] @ c) for c in chosen_desc) >= max_sim else "over event coverage budget"
    ev.coverage_used = used


def runtime(moments: list[Moment]) -> float:
    return sum(eff_len(m) for m in moments if m.selected)


def apply_guards(moments: list[Moment], policy: Policy) -> list[str]:
    """Enforce film-level shares by dropping the lowest-scored items of the offending class."""
    notes = []
    limits = (("transit", float(policy("film_limits.transit_share_max"))),
              ("third_party", float(policy("film_limits.third_party_share_max"))))
    for _ in range(len(moments) + 1):
        total = runtime(moments)
        changed = False
        for cls, share in limits:
            items = [m for m in moments if m.selected and m.cls == cls and "kept in review" not in m.reason]
            amount = sum(eff_len(m) for m in moments if m.selected and m.cls == cls)
            if total <= 0 or amount <= share * total or not items:
                continue
            per_event: dict[str, int] = {}
            for m in items:
                per_event[m.event_id] = per_event.get(m.event_id, 0) + 1
            droppable = [m for m in items if per_event[m.event_id] > 1]
            if not droppable:
                continue
            victim = min(droppable, key=lambda m: (m.score, -m.abs_t0))
            victim.selected, victim.reason = False, f"film limit: {cls} share above {share:.0%}"
            changed = True
            break
        if not changed:
            break
    for cls, share in limits:
        total = runtime(moments)
        amount = sum(eff_len(m) for m in moments if m.selected and m.cls == cls)
        if total > 0 and amount > share * total:
            notes.append(f"{cls} share {amount / total:.1%} still above {share:.0%} (one item kept per event)")
    return notes


def select_all(events: list[Event], moments: list[Moment], clips: dict[str, ClipData], policy: Policy,
               overrides: dict) -> list[str]:
    warnings: list[str] = []
    by_event: dict[str, list[Moment]] = {}
    for m in moments:
        by_event.setdefault(m.event_id, []).append(m)

    def run(scale: float) -> None:
        for ev in events:
            select_event(ev, by_event.get(ev.id, []), clips, policy, overrides, scale)

    run(1.0)
    warnings += apply_guards(moments, policy)
    target = policy("film_limits.target_runtime_min")
    if target:
        goal = float(target) * 60.0
        if runtime(moments) > goal:
            lo, hi = 0.2, 1.0
            for _ in range(12):  # binary search on the coverage scale
                mid = (lo + hi) / 2
                run(mid)
                apply_guards(moments, policy)
                if runtime(moments) > goal:
                    hi = mid
                else:
                    lo = mid
            run(lo)
            warnings += apply_guards(moments, policy)
            if runtime(moments) > goal:
                convs = sorted((m for m in moments if m.selected and m.kind == "conversation"
                                and "kept in review" not in m.reason),
                               key=lambda m: (m.partner_words / max(m.dur, 1e-6), m.abs_t0))
                for m in convs:
                    if runtime(moments) <= goal:
                        break
                    m.selected, m.reason = False, "dropped to meet target_runtime_min"
                    warnings.append(f"conversation {m.id} ({m.dur:.0f}s) dropped to meet target runtime")
    return warnings
