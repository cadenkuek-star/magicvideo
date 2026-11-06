"""`magicvideo plan`: analysis + policy + overrides -> plan_vNNN.json + timeline_vNNN.json (deterministic)."""
from __future__ import annotations

import hashlib
from fractions import Fraction
from pathlib import Path

from .. import ingest
from ..enroll import load_refs, refs_fingerprint
from ..project import Project
from ..util import dumps, log, next_version, read_json, vtag, write_json
from .assemble import build_timeline
from .budget import eff_len, select_all
from .data import ClipData, load_clip
from .events import build_chapters, build_events
from .moments import build_clip_moments
from .storyboard import STALE_REFS_TEXT, write_storyboard


def filter_plannable(clips: list[dict], excluded: set[str], pol, warnings: list[str]) -> list[dict]:
    out = []
    for c in clips:
        if c["clip_id"] in excluded:
            continue
        if c.get("render_projection", c.get("projection")) == "dual_fisheye" and not pol("insta360.allow_unstitched_render"):
            if pol("insta360.plan_unstitched"):
                warnings.append(f"{c['rel_path']}: planned from its preview; if the film uses it you will be asked "
                                "to export it from Insta360 Studio before render")
            else:
                warnings.append(f"{c['rel_path']}: unstitched 360 recording skipped (export it from Insta360 "
                                "Studio, or set insta360.allow_unstitched_render)")
                continue
        out.append(c)
    return out


def plannable_clips(project: Project, warnings: list[str]) -> list[dict]:
    excluded = {cid for cid, rule in (project.overrides().get("clips") or {}).items() if (rule or {}).get("exclude")}
    return filter_plannable(ingest.plannable(project.inventory()), excluded, project.policy, warnings)


def x6_export_list(timeline: dict, inventory: list[dict], pol) -> list[dict]:
    """Unstitched Insta360 clips the timeline uses (they must be exported from Studio before render)."""
    if pol("insta360.allow_unstitched_render"):
        return []
    fps = float(Fraction(*timeline["fps"]))
    inv = {c["clip_id"]: c for c in inventory}
    uses: dict[str, list[list[float]]] = {}
    for it in list(timeline.get("segments", [])) + list(timeline.get("overlays", [])):
        c = inv.get(it["clip_id"])
        if c and c.get("render_projection", c.get("projection")) == "dual_fisheye":
            t0 = float(it["src_in"])
            uses.setdefault(c["clip_id"], []).append([round(t0, 1), round(t0 + it["frames"] / fps, 1)])
    return sorted(({"rel_path": inv[cid]["rel_path"], "uses": sorted(u)} for cid, u in uses.items()),
                  key=lambda e: e["rel_path"])


def x6_exports_text(exports: list[dict], tag: str) -> str:
    lines = [f"# Insta360 clips to export before render ({tag})", "",
             "The film uses these Insta360 recordings. Export each one from Insta360 Studio (whole clip):", ""]
    for e in exports:
        ranges = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in e["uses"])
        lines.append(f"- {e['rel_path']} (the film uses: {ranges}; for reference, export the whole clip)")
    lines += ["", "Steps in Insta360 Studio:", "1. Open the file.",
              "2. Export -> 360\u00b0 -> Equirectangular, with FlowState stabilization and horizon lock on.",
              "3. Save the export next to the .insv file, with Studio's default name.", "",
              "Then run `magicvideo analyze` and `magicvideo plan` again, and render.", ""]
    return "\n".join(lines)


def edge_speech_warnings(selected: list, cds: dict, policy) -> list[str]:
    """Warn when selected conversations start/end right at the edge of their source file (sentence may be cut)."""
    start_s = float(policy("moments.edge_speech.start_s"))
    end_s = float(policy("moments.edge_speech.end_s"))
    found: list[tuple[str, float, str]] = []
    for m in selected:
        if m.kind != "conversation":
            continue
        cd = cds[m.clip_id]
        idx = cd.words_in(m.t0, m.t1)
        if not idx:
            continue
        first, last = cd.words[idx[0]], cd.words[idx[-1]]
        rel = cd.clip["rel_path"]
        if last["t1"] >= cd.duration - end_s:
            found.append((rel, last["t1"], f"{rel}: speech runs to the end of the file (last word ends at "
                          f"{last['t1']:.1f}s of {cd.duration:.1f}s); the sentence may be cut. If you trimmed "
                          f"this clip, export it a few seconds longer."))
        if first["t0"] <= start_s:
            found.append((rel, first["t0"], f"{rel}: speech starts at the very beginning of the file (first word "
                          f"starts at {first['t0']:.1f}s); the sentence may be cut. If you trimmed this clip, "
                          f"export it a few seconds earlier."))
    return [text for _, _, text in sorted(found, key=lambda x: (x[0], x[1], x[2]))]


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
    for cd in sorted(cds.values(), key=lambda c: c.clip["rel_path"]):
        for d in cd.dropped_speech:
            warnings.append(f"{cd.clip['rel_path']} {d['t0']:.1f}\u2013{d['t1']:.1f}s: ignored likely Whisper "
                            f"hallucination \u201c{d['text']}\u201d")
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
    warnings += edge_speech_warnings(selected, cds, policy)
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
        "refs_sha256": refs_fingerprint(project.people_dir),
        "warnings": warnings,
        "stats": {"clips": len(cds), "moments": len(moments), "selected": len(selected),
                  "planned_seconds": total, "shares": shares,
                  "raw_seconds": sum(cd.duration for cd in cds.values())},
        "events": [e.to_dict() for e in events],
        "chapters": [c.to_dict() for c in chapters],
        "moments": [m.to_dict() for m in moments],
    }
    return {"plan": plan, "timeline": timeline}


def stale_refs(project: Project, plan: dict) -> bool:
    """True when the partner references differ from the ones the plan was made with."""
    return plan.get("refs_sha256") != refs_fingerprint(project.people_dir)


def warn_if_stale(project: Project, tag: str) -> bool:
    """Log a warning when plan <tag> is older than the partner references; returns whether it is stale."""
    plan = read_json(project.plan_dir / f"plan_{tag}.json")
    stale = bool(plan) and stale_refs(project, plan)
    if stale:
        log.warning("%s", STALE_REFS_TEXT)
    return stale


def run_plan(project: Project, thumbs: bool = False) -> dict[str, Path]:
    result = make_plan(project)
    v = next_version(project.plan_dir, "plan_v*.json")
    tag = vtag(v)
    exports = x6_export_list(result["timeline"], project.inventory(), project.policy)
    if exports:
        result["plan"]["warnings"].append(f"{len(exports)} Insta360 clip(s) need exporting before render: "
                                          f"see plan/x6_exports_{tag}.md")
    plan_path = write_json(project.plan_dir / f"plan_{tag}.json", result["plan"])
    tl_path = write_json(project.plan_dir / f"timeline_{tag}.json", result["timeline"])
    if exports:
        (project.plan_dir / f"x6_exports_{tag}.md").write_text(x6_exports_text(exports, tag), encoding="utf-8")
    sb_path = write_storyboard(project, result["plan"], result["timeline"], project.plan_dir / f"storyboard_{tag}.html",
                               thumbs=thumbs)
    st = result["plan"]["stats"]
    log.info("plan %s: %d/%d moments selected, %.1f min planned from %.1f min raw", tag, st["selected"],
             st["moments"], st["planned_seconds"] / 60, st["raw_seconds"] / 60)
    for w in result["plan"]["warnings"]:
        log.warning("plan: %s", w)
    return {"plan": plan_path, "timeline": tl_path, "storyboard": sb_path}
