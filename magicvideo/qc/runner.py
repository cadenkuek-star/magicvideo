"""`magicvideo qc`: measured checks, computed verdict (brief §6.9). Nobody edits qc_*.json."""
from __future__ import annotations

import difflib
import re
import struct
from fractions import Fraction
from pathlib import Path

from .. import ffmpeg
from ..enroll import load_refs
from ..policy import Policy
from ..project import Project, ProjectError
from ..render import audio as A
from ..util import read_json, version_of, vtag, write_json
from ..plan.assemble import display_orientation
from ..plan.data import PARTNERS, is_couple_speaker, load_clip

PASS, FAIL, SKIPPED = "PASS", "FAIL", "SKIPPED"


def check(cid: str, status: str, value=None, limit=None, detail: str = "") -> dict:
    return {"id": cid, "status": status, "value": value, "limit": limit, "detail": detail}


def verdict(checks: list[dict]) -> str:
    if any(c["status"] == FAIL for c in checks):
        return "FAIL"
    if any(c["status"] == SKIPPED for c in checks):
        return "INCOMPLETE"
    return "PASS"


def top_level_atoms(path: Path, limit: int = 64) -> list[str]:
    atoms = []
    with open(path, "rb") as f:
        size_total = path.stat().st_size
        pos = 0
        while pos < size_total and len(atoms) < limit:
            f.seek(pos)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            size, typ = struct.unpack(">I4s", hdr)
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
            elif size == 0:
                size = size_total - pos
            atoms.append(typ.decode("latin-1"))
            if size < 8:
                break
            pos += size
    return atoms


# --------------------------------------------------------------------------- technical
def technical(master: Path, timeline: dict, render_log: dict, policy: Policy, chapters: list[Path]) -> list[dict]:
    out = []
    fps = Fraction(*timeline["fps"])
    proc = ffmpeg.run(["-v", "error", "-i", str(master), "-f", "null", "-"], check=False)
    err = (proc.stderr or "").strip()
    out.append(check("decode.clean", PASS if proc.returncode == 0 and not err else FAIL,
                     value=(err[:300] or "no errors"), limit="no decoder errors"))
    info = ffmpeg.probe(master)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    res = f"{v.get('width')}x{v.get('height')}"
    want = f"{timeline['width']}x{timeline['height']}"
    out.append(check("video.resolution", PASS if res == want else FAIL, res, want))
    vr = ffmpeg.parse_rate(v.get("r_frame_rate"))
    out.append(check("video.fps", PASS if vr == fps else FAIL, str(vr), str(fps)))
    out.append(check("video.pix_fmt", PASS if v.get("pix_fmt") == "yuv420p" else FAIL, v.get("pix_fmt"), "yuv420p"))
    want_prof = str(policy("output.video.profile")).lower()
    out.append(check("video.profile", PASS if str(v.get("profile", "")).lower() == want_prof else FAIL,
                     v.get("profile"), want_prof))
    afmt = f"{a.get('codec_name')}/{a.get('sample_rate')}/{a.get('channels')}"
    want_a = f"aac/{policy('audio.sample_rate')}/2"
    out.append(check("audio.format", PASS if afmt == want_a else FAIL, afmt, want_a))
    vd, ad = float(v.get("duration") or 0), float(a.get("duration") or 0)
    drift = abs(vd - ad) * 1000
    lim = float(policy("qc.av_drift_ms_max"))
    out.append(check("av.drift_ms", PASS if drift <= lim else FAIL, round(drift, 2), f"<= {lim}"))
    expect = timeline["total_frames"] / float(fps)
    frame_s = 1 / float(fps)
    out.append(check("duration.matches_timeline", PASS if abs(vd - expect) <= frame_s + 1e-6 else FAIL,
                     round(vd, 3), f"{expect:.3f} ± 1 frame"))
    target_i = float(policy("audio.integrated_lufs"))
    tol = float(policy("audio.integrated_tolerance"))
    tp_lim = float(policy("audio.true_peak_dbtp"))
    try:
        m = A.measure(master, int(policy("audio.sample_rate")), False, target_i, tp_lim)
        out.append(check("loudness.integrated", PASS if abs(m["I"] - target_i) <= tol else FAIL, m["I"],
                         f"{target_i} ± {tol} LUFS"))
        out.append(check("loudness.true_peak", PASS if m["TP"] <= tp_lim else FAIL, m["TP"], f"<= {tp_lim} dBTP"))
    except ffmpeg.FFmpegError as e:
        out.append(check("loudness.integrated", FAIL, None, target_i, str(e)[:200]))
    lin = (render_log.get("loudness") or {}).get("linear")
    out.append(check("loudness.linear", PASS if lin is True else (SKIPPED if lin is None else FAIL), lin, True,
                     "gain applied with volume=; no dynamic normalisation"))
    atoms = top_level_atoms(master)
    fast = "moov" in atoms and "mdat" in atoms and atoms.index("moov") < atoms.index("mdat")
    out.append(check("container.faststart", PASS if fast else FAIL, atoms[:6], "moov before mdat"))
    if chapters:
        total = sum(float(ffmpeg.probe(c)["format"]["duration"]) for c in chapters)
        mdur = float(info["format"]["duration"])
        ok = abs(total - mdur) <= 2 * frame_s * len(chapters)
        out.append(check("chapters.sum", PASS if ok else FAIL, round(total, 3), f"{mdur:.3f}"))
    return out


# --------------------------------------------------------------------------- editorial
_NORM = re.compile(r"[^\w']+", re.U)


def _norm(w: str) -> str:
    return _NORM.sub("", w.lower())


def _covered(seg_spans: dict[str, list[tuple[float, float]]], clip_id: str, t: float) -> bool:
    return any(a <= t < b for a, b in seg_spans.get(clip_id, []))


def editorial(project: Project, plan: dict, timeline: dict, policy: Policy, master: Path | None) -> list[dict]:
    out = []
    fps = float(Fraction(*timeline["fps"]))
    refs = load_refs(project.people_dir)
    inv = {c["clip_id"]: c for c in project.inventory()}
    moments = {m["id"]: m for m in plan["moments"]}
    seg_spans: dict[str, list[tuple[float, float]]] = {}
    for s in timeline["segments"]:
        seg_spans.setdefault(s["clip_id"], []).append((s["src_in"], s["src_in"] + s["frames"] / fps))
    used_clips = sorted({s["clip_id"] for s in timeline["segments"]} |
                        {m["clip_id"] for m in plan["moments"] if m["kind"] == "conversation"})
    cds = {cid: load_clip(project, inv[cid], refs, policy) for cid in used_clips if cid in inv}

    # planned partner-word retention over kept conversations
    total = kept = 0
    planned_words: list[str] = []
    convs = [m for m in plan["moments"] if m["kind"] == "conversation" and m["selected"]]
    for m in sorted(convs, key=lambda m: m["abs_t0"]):
        cd = cds[m["clip_id"]]
        for i in cd.words_in(m["t0"], m["t1"]):
            if not is_couple_speaker(cd.word_speaker(i), policy):
                continue
            w = cd.words[i]
            total += 1
            if _covered(seg_spans, m["clip_id"], (w["t0"] + w["t1"]) / 2):
                kept += 1
                planned_words.append(_norm(w["w"]))
    dropped = [m["id"] for m in plan["moments"] if m["kind"] == "conversation" and not m["selected"]]
    lim = float(policy("qc.couple_word_retention_min"))
    if total == 0:
        out.append(check("speech.partner_words_planned", SKIPPED, None, f">= {lim}", "no transcribed couple speech"))
    else:
        r = kept / total
        out.append(check("speech.partner_words_planned", PASS if r >= lim else FAIL, round(r, 4), f">= {lim}",
                         f"{kept}/{total} words; conversations dropped by review/runtime: {len(dropped)}"))

    # independent check: re-transcribe the rendered master
    lim_r = float(policy("qc.rendered_word_match_min"))
    try:
        if master is None or not planned_words:
            raise RuntimeError("nothing to compare")
        from ..analysis import asr
        wav = project.qc_dir / f"{master.stem}_16k.wav"
        ffmpeg.extract_audio(master, wav)
        heard = [_norm(w["w"]) for w in asr.transcribe(wav, policy)["words"]]
        wav.unlink(missing_ok=True)
        sm = difflib.SequenceMatcher(a=planned_words, b=[h for h in heard if h], autojunk=False)
        matched = sum(b.size for b in sm.get_matching_blocks())
        r = matched / len(planned_words)
        out.append(check("speech.partner_words_rendered", PASS if r >= lim_r else FAIL, round(r, 4), f">= {lim_r}",
                         f"{matched}/{len(planned_words)} planned partner words heard in the rendered master"))
    except Exception as e:
        out.append(check("speech.partner_words_rendered", SKIPPED, None, f">= {lim_r}", f"not run: {e}"[:200]))

    # unhidden jump cuts inside a conversation
    segs = timeline["segments"]
    ovs = timeline["overlays"]
    bad = 0
    for prev, cur in zip(segs, segs[1:]):
        same_conv = cur["kind"] == "conversation" and cur["clip_id"] == prev["clip_id"] and \
            set(cur.get("moment_ids", [])) & set(prev.get("moment_ids", []))
        if not same_conv:
            continue
        jump = abs(cur["src_in"] - (prev["src_in"] + prev["frames"] / fps)) > 0.5 / fps
        hidden = any(o["start_frame"] < cur["start_frame"] < o["start_frame"] + o["frames"] for o in ovs)
        if jump and not hidden:
            bad += 1
    lim_j = int(policy("qc.unhidden_conversation_jump_cuts_max"))
    out.append(check("edit.unhidden_conversation_jump_cuts", PASS if bad <= lim_j else FAIL, bad, f"<= {lim_j}"))

    # shares by class (segment time, primary moment's class)
    total_f = sum(s["frames"] for s in segs) or 1
    for cls, key in (("transit", "film_limits.transit_share_max"), ("third_party", "film_limits.third_party_share_max")):
        f = sum(s["frames"] for s in segs if moments.get(s["moment_id"], {}).get("cls") == cls)
        share, lim_s = f / total_f, float(policy(key))
        out.append(check(f"edit.{cls}_share", PASS if share <= lim_s + 1e-9 else FAIL, round(share, 4), f"<= {lim_s}"))

    # longest stretch without either partner seen or heard
    have_refs = bool(refs) and any(k in refs for k in ("voice_a", "face_a"))
    lim_g = float(policy("film_limits.max_gap_without_partner_s"))
    if not have_refs:
        out.append(check("edit.max_gap_without_partner_s", SKIPPED, None, f"<= {lim_g}", "no enrollment refs"))
    else:
        longest = run = 0.0
        step = 0.5
        for s in segs:
            cd = cds.get(s["clip_id"])
            n = max(1, int(s["frames"] / fps / step))
            for k in range(n):
                t = s["src_in"] + k * step
                heard = _partner_heard(cd, t, step, policy)
                seen = bool(cd and cd.partners_visible(t - 1.0, t + 1.0, min_share=0.1))
                run = 0.0 if (heard or seen) else run + step
                longest = max(longest, run)
        out.append(check("edit.max_gap_without_partner_s", PASS if longest <= lim_g else FAIL, longest, f"<= {lim_g}"))

    # coverage budget overrun per event
    lim_b = float(policy("qc.event_over_budget_max"))
    worst, worst_id = 0.0, None
    for e in plan["events"]:
        if e["coverage_budget"] > 0:
            over = e["coverage_used"] / e["coverage_budget"] - 1.0
            if over > worst:
                worst, worst_id = over, e["id"]
    out.append(check("edit.event_over_budget", PASS if worst <= lim_b + 1e-9 else FAIL, round(worst, 4),
                     f"<= {lim_b}", f"worst event {worst_id}" if worst_id else ""))

    # orientation / reframe validity
    master_o = timeline.get("orientation", "landscape")
    min_short = int(policy("reframe.min_crop_short_side"))
    problems = []
    for it in segs + ovs:
        c = inv.get(it["clip_id"], {})
        mode = it["reframe"].get("mode")
        is360 = c.get("render_projection", c.get("projection")) in ("equirect", "dual_fisheye")
        o = display_orientation(c, int(it["reframe"].get("rotate", 0)))
        same = o == master_o or o == "square"
        ok = (mode == "v360") == is360 and (
            is360 or (mode == "fill" and same) or (mode == "crop" and not same and
                                                   min(c.get("display_w", 0), c.get("display_h", 0)) >= min_short)
            or (mode == "static_bg" and not same))
        if not ok:
            problems.append(f"{it['id']}:{mode}")
    out.append(check("edit.orientation", PASS if not problems else FAIL, len(problems), 0, ", ".join(problems[:10])))
    return out


# --------------------------------------------------------------------------- run
def _partner_heard(cd, t: float, step: float, policy) -> bool:
    """True when a partner (or assumed-couple) speaker is heard within step of t."""
    if cd is None:
        return False
    return any(is_couple_speaker(cd.word_speaker(i), policy) for i in cd.words_in(t - step, t + step))


def run_qc(project: Project, version: str | None = None) -> tuple[str, Path]:
    policy = project.policy
    render_logs = sorted(project.root.glob("render/v*/render_v*.json"))
    if not render_logs:
        raise ProjectError("nothing rendered yet: run `magicvideo render`")
    if version is None:
        version = vtag(max(version_of(p) or 0 for p in render_logs))
    rlog = read_json(project.render_dir(version) / f"render_{version}.json")
    if rlog is None:
        raise ProjectError(f"no render log for {version}")
    timeline = read_json(project.plan_dir / f"timeline_{version}.json")
    plan = read_json(project.plan_dir / f"plan_{version}.json")
    master = Path(rlog["outputs"]["master"])
    chapters = [Path(p) for p in rlog["outputs"].get("chapters", [])]
    checks = technical(master, timeline, rlog, policy, chapters) + editorial(project, plan, timeline, policy, master)
    result = {"version": version, "master": str(master), "verdict": verdict(checks), "checks": checks,
              "generated_by": "magicvideo qc", "policy_sha": plan.get("policy_sha")}
    project.qc_dir.mkdir(parents=True, exist_ok=True)
    path = project.qc_dir / f"qc_{version}.json"
    k = 2
    while path.exists():  # never overwrite an earlier QC run
        path = project.qc_dir / f"qc_{version}_run{k}.json"
        k += 1
    write_json(path, result)
    path.with_suffix(".md").write_text(report_md(result), encoding="utf-8")
    return result["verdict"], path


def report_md(result: dict) -> str:
    lines = [f"# QC {result['version']}: **{result['verdict']}**", "", f"Master: `{result['master']}`", "",
             "| Check | Status | Value | Limit | Detail |", "|---|---|---|---|---|"]
    for c in result["checks"]:
        lines.append(f"| {c['id']} | {c['status']} | {c['value']} | {c['limit']} | {c['detail']} |")
    lines += ["", "Generated by `magicvideo qc`. Do not edit; fix the media or the policy and re-run."]
    return "\n".join(lines) + "\n"
