"""`magicvideo plan`: analysis + policy + overrides -> plan_vNNN.json + timeline_vNNN.json (deterministic)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .. import ingest
from ..enroll import load_refs
from ..project import Project
from ..util import dumps, log, next_version, vtag, write_json
from .assemble import build_timeline
from .budget import eff_len, select_all
from .data import ClipData, load_clip
from .events import build_chapters, build_events
from .moments import build_clip_moments
from .storyboard import write_storyboard


def plannable_clips(project: Project, warnings: list[str]) -> list[dict]:
    pol = project.policy
    excluded = {cid for cid, rule in (project.overrides().get("clips") or {}).items() if (rule or {}).get("exclude")}
    out = []
    for c in ingest.plannable(project.inventory()):
        if c["clip_id"] in excluded:
            continue
        if c.get("render_projection", c.get("projection")) == "dual_fisheye" and not pol("insta360.allow_unstitched_render"):
            warnings.append(f"{c['rel_path']}: unstitched 360 recording skipped (export it from Insta360 Studio, "
                            "or set insta360.allow_unstitched_render)")
            continue
        out.append(c)
    return out


def make_plan(project: Project) -> dict:
    policy = project.policy
    overrides = project.overrides()
    refs = load_refs(project.people_dir)
    warnings: list[str] = []
    if not refs or "voice_a" not in refs:
        warnings.append("no voice enrollment: all speech is treated as "
                        + ("couple speech" if policy("identity.unknown_speech_is_couple") else "other people")
                        + " (run `magicvideo enroll`)")
    if not refs or "face_a" not in refs:
        warnings.append("no face enrollment: partner visibility unknown (solo-shot rule and partner-gap check off)")
    clips = plannable_clips(project, warnings)
    cds: dict[str, ClipData] = {c["clip_id"]: load_clip(project, c, refs, policy) for c in clips}
    missing_asr = [cd.clip["rel_path"] for cd in cds.values() if cd.clip.get("has_audio") and not cd.asr_done]
    if missing_asr:
        warnings.append(f"{len(missing_asr)} clip(s) without transcripts: their speech is not protected")
    events, clip_event = build_events(list(cds.values()), policy)
    chapters = build_chapters(events)
    ev_by_id = {e.id: e for e in events}
    moments = []
    for cd in sorted(cds.values(), key=lambda c: (c.abs_start, c.id)):
        ev = ev_by_id[clip_event[cd.id]]
        for m in build_clip_moments(cd, ev.type, policy):
            m.event_id = ev.id
            moments.append(m)
    from .budget import apply_overrides
    apply_overrides(moments, cds, overrides)
    warnings += select_all(events, moments, cds, policy, overrides)
    selected = [m for m in moments if m.selected]
    timeline = build_timeline(project.name, selected, moments, cds, chapters, {e.id: e.chapter for e in events},
                              policy, overrides)
    total = sum(eff_len(m) for m in selected)
    shares = {}
    for cls in ("couple", "coverage", "transit", "third_party"):
        amt = sum(eff_len(m) for m in selected if m.cls == cls)
        shares[cls] = {"seconds": amt, "share": (amt / total) if total else 0.0}
    policy_hash = hashlib.sha256(dumps(policy.data).encode()).hexdigest()[:16]
    plan = {
        "version": 1, "name": project.name, "policy_sha": policy_hash,
        "warnings": warnings,
        "stats": {"clips": len(cds), "moments": len(moments), "selected": len(selected),
                  "planned_seconds": total, "shares": shares,
                  "raw_seconds": sum(cd.duration for cd in cds.values())},
        "events": [e.to_dict() for e in events],
        "chapters": [c.to_dict() for c in chapters],
        "moments": [m.to_dict() for m in moments],
    }
    return {"plan": plan, "timeline": timeline}


def run_plan(project: Project, thumbs: bool = False) -> dict[str, Path]:
    result = make_plan(project)
    v = next_version(project.plan_dir, "plan_v*.json")
    tag = vtag(v)
    plan_path = write_json(project.plan_dir / f"plan_{tag}.json", result["plan"])
    tl_path = write_json(project.plan_dir / f"timeline_{tag}.json", result["timeline"])
    sb_path = write_storyboard(project, result["plan"], result["timeline"], project.plan_dir / f"storyboard_{tag}.html",
                               thumbs=thumbs)
    st = result["plan"]["stats"]
    log.info("plan %s: %d/%d moments selected, %.1f min planned from %.1f min raw", tag, st["selected"],
             st["moments"], st["planned_seconds"] / 60, st["raw_seconds"] / 60)
    for w in result["plan"]["warnings"]:
        log.warning("plan: %s", w)
    return {"plan": plan_path, "timeline": tl_path, "storyboard": sb_path}
