"""Assembly: selected moments -> frame-exact timeline (brief §6.6)."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from ..policy import Policy
from .budget import eff_len
from .camera360 import camera_path
from .data import ClipData
from .model import Chapter, Moment

FPS_FAMILIES = [(Fraction(24000, 1001), (23.976,)), (Fraction(24), (24.0, 48.0)), (Fraction(25), (25.0, 50.0, 100.0)),
                (Fraction(30000, 1001), (29.97, 59.94, 119.88)), (Fraction(30), (30.0, 60.0, 120.0))]


def fps_family(fps: float) -> Fraction:
    for fam, rates in FPS_FAMILIES:
        if any(abs(fps - r) < 0.02 for r in rates):
            return fam
    return Fraction(30)


def choose_fps(policy: Policy, weighted: list[tuple[float, float]]) -> Fraction:
    setting = str(policy("output.fps"))
    if setting != "dominant_family":
        return Fraction(setting)
    totals: dict[Fraction, float] = {}
    for fps, dur in weighted:
        if fps > 0:
            fam = fps_family(fps)
            totals[fam] = totals.get(fam, 0.0) + dur
    if not totals:
        return Fraction(30)
    return sorted(totals.items(), key=lambda kv: (-kv[1], float(kv[0])))[0][0]


def display_orientation(clip: dict, rotate: int = 0) -> str:
    w, h = clip.get("display_w", 0), clip.get("display_h", 0)
    if rotate % 180 == 90:
        w, h = h, w
    return "portrait" if h > w else ("square" if h == w else "landscape")


def choose_orientation(policy: Policy, selected: list[Moment], clips: dict[str, ClipData], overrides: dict) -> str:
    setting = policy("output.orientation")
    if setting in ("landscape", "portrait"):
        return setting
    portrait = landscape = 0.0
    for m in selected:
        cd = clips[m.clip_id]
        if cd.is360 or m.kind not in ("conversation", "action"):
            continue
        rot = int(((overrides.get("clips") or {}).get(m.clip_id) or {}).get("rotate", 0))
        o = display_orientation(cd.clip, rot)
        if o == "portrait":
            portrait += eff_len(m)
        else:
            landscape += eff_len(m)
    total = portrait + landscape
    return "portrait" if total > 0 and portrait / total >= float(policy("output.portrait_threshold")) else "landscape"


@dataclass
class Item:
    clip_id: str
    t0: float
    t1: float
    kind: str
    event_id: str
    chapter: int
    moments: list[Moment] = field(default_factory=list)
    pauses: list[list[float]] = field(default_factory=list)


def _merge(selected: list[Moment], chapter_of: dict[str, int], gap: float) -> list[Item]:
    order = sorted(selected, key=lambda m: (chapter_of[m.event_id], m.abs_t0, m.clip_id, m.t0))
    items: list[Item] = []
    for m in order:
        t1 = m.t0 + eff_len(m)
        last = items[-1] if items else None
        if last and last.clip_id == m.clip_id and last.chapter == chapter_of[m.event_id] and m.t0 <= last.t1 + gap \
                and t1 > last.t0:
            last.t1 = max(last.t1, t1)
            last.t0 = min(last.t0, m.t0)
            last.moments.append(m)
            last.pauses += [p for p in m.pauses if last.t0 < p[0] and p[1] < last.t1]
            if m.kind == "conversation":
                last.kind = "conversation"
            continue
        items.append(Item(m.clip_id, m.t0, t1, m.kind, m.event_id, chapter_of[m.event_id], [m],
                          [p for p in m.pauses]))
    return items


class CoverPool:
    """Coverage shots usable as cutaways, per event: unused shots first, then selected ones (moved)."""

    def __init__(self, moments: list[Moment], min_len: float):
        self.free: dict[str, list[Moment]] = {}
        self.selected: dict[str, list[Moment]] = {}
        for m in sorted(moments, key=lambda m: (-m.score, m.abs_t0)):
            if m.kind == "coverage" and m.cls in ("coverage", "transit") and m.max_len != 0.0 \
                    and m.dur >= min_len and "kept in review" not in m.reason:
                (self.selected if m.selected else self.free).setdefault(m.event_id, []).append(m)

    @staticmethod
    def _pick(pool: list[Moment], length: float, avoid_clip: str | None) -> Moment | None:
        for prefer_other in (True, False):
            for i, m in enumerate(pool):
                if m.dur >= length and (not prefer_other or m.clip_id != avoid_clip):
                    return pool.pop(i)
        return None

    def take(self, event_id: str, length: float, avoid_clip: str | None = None,
             allow_selected: bool = False) -> Moment | None:
        m = self._pick(self.free.get(event_id, []), length, avoid_clip)
        if m is None and allow_selected:
            m = self._pick(self.selected.get(event_id, []), length, avoid_clip)
            if m is not None:
                m.selected = False  # moved: becomes a cutaway instead of a standalone shot
        return m


def _reframe(cd: ClipData, t0: float, t1: float, kind: str, frames: int, fps: float, master: str,
             policy: Policy, rotate: int) -> dict:
    if cd.is360:
        return {"mode": "v360", "projection": cd.clip.get("render_projection", cd.clip.get("projection")),
                "path": camera_path(cd, t0, frames, fps, kind, policy)}
    o = display_orientation(cd.clip, rotate)
    center = cd.face_center(t0, t1)
    cx, cy = (center if center else (0.5, 0.45))
    spec: dict = {"rotate": rotate} if rotate else {}
    same = (o == master) or o == "square"
    if same:
        spec.update({"mode": "fill", "cx": round(cx, 3), "cy": round(cy, 3)})
        return spec
    short = min(cd.clip.get("display_w", 0), cd.clip.get("display_h", 0))
    if short >= int(policy("reframe.min_crop_short_side")):
        spec.update({"mode": "crop", "cx": round(cx, 3), "cy": round(cy, 3)})
    else:
        spec.update({"mode": "static_bg", "bg_t": round((t0 + t1) / 2, 3)})
    return spec


def _stabilize(cd: ClipData, t0: float, t1: float, policy: Policy) -> bool:
    if cd.clip.get("camera", {}).get("kind") in ("gimbal", "360") or cd.is360:
        return False
    return cd.quality.jitter_p90(t0, t1) >= float(policy("quality.jitter.medium"))


def build_timeline(name: str, selected: list[Moment], all_moments: list[Moment], clips: dict[str, ClipData],
                   chapters: list[Chapter], chapter_of_event: dict[str, int], policy: Policy, overrides: dict
                   ) -> dict:
    fps = choose_fps(policy, [(clips[m.clip_id].clip.get("fps", 0.0), eff_len(m)) for m in selected])
    master = choose_orientation(policy, selected, clips, overrides)
    width, height = policy("output.portrait_size") if master == "portrait" else policy("output.landscape_size")
    fpsf = float(fps)
    gap = float(policy("assembly.merge_gap_s"))
    cover_len = float(policy("assembly.cover_len_s"))
    shorten = float(policy("moments.conversation.shorten_pause_to_s"))
    defect_min = float(policy("assembly.defect_min_s"))
    pool = CoverPool(all_moments, cover_len)
    rot_of = {cid: int((rule or {}).get("rotate", 0)) for cid, rule in (overrides.get("clips") or {}).items()}

    # pre-pass: pick a cutaway for every shortenable pause (may move a selected shot of the same event)
    pause_cover: dict[tuple[str, float], Moment] = {}
    for m in sorted(selected, key=lambda m: m.abs_t0):
        if m.kind != "conversation":
            continue
        for p0, p1 in m.pauses:
            if p1 - p0 <= shorten:
                continue
            cover = pool.take(m.event_id, cover_len, avoid_clip=m.clip_id, allow_selected=True)
            if cover is not None:
                pause_cover[(m.clip_id, round(p0, 4))] = cover
    selected = [m for m in selected if m.selected]

    segments: list[dict] = []
    overlays: list[dict] = []
    frame = 0

    def add_segment(item: Item, s0: float, s1: float, join: str) -> dict:
        nonlocal frame
        cd = clips[item.clip_id]
        n = max(1, int(round((s1 - s0) * fpsf)))
        seg = {
            "id": f"s{len(segments) + 1:05d}", "clip_id": item.clip_id, "src_in": round(s0, 4), "frames": n,
            "start_frame": frame, "kind": item.kind, "moment_id": item.moments[0].id,
            "moment_ids": [m.id for m in item.moments], "event_id": item.event_id, "chapter": item.chapter,
            "join": join, "gain_db": 0.0,
            "reframe": _reframe(cd, s0, s1, item.kind, n, fpsf, master, policy, rot_of.get(item.clip_id, 0)),
            "stabilize": _stabilize(cd, s0, s1, policy),
        }
        segments.append(seg)
        frame += n
        return seg

    def add_overlay(cover: Moment, start_frame: int, n: int, reason: str, kind: str = "coverage") -> None:
        cd = clips[cover.clip_id]
        cover.reason = f"used as cutaway ({reason})"
        src = cover.t0 + max(0.0, (cover.dur - n / fpsf) / 2)
        overlays.append({
            "id": f"o{len(overlays) + 1:05d}", "clip_id": cover.clip_id, "src_in": round(src, 4), "frames": n,
            "start_frame": start_frame, "reason": reason, "moment_id": cover.id,
            "reframe": _reframe(cd, src, src + n / fpsf, kind, n, fpsf, master, policy, rot_of.get(cover.clip_id, 0)),
            "stabilize": _stabilize(cd, src, src + n / fpsf, policy),
        })

    for item in _merge(selected, chapter_of_event, gap):
        cd = clips[item.clip_id]
        cuts: list[tuple[float, float]] = []  # removed source spans inside the item
        covers: list[Moment] = []
        for p0, p1 in sorted(item.pauses):
            cover = pause_cover.get((item.clip_id, round(p0, 4)))
            if p1 - p0 <= shorten or cover is None:
                continue
            cuts.append((p0 + shorten / 2, p1 - shorten / 2))
            covers.append(cover)
        bounds = [item.t0] + [x for c in cuts for x in c] + [item.t1]
        seg_first = None
        for k in range(0, len(bounds), 2):
            seg = add_segment(item, bounds[k], bounds[k + 1], "start" if k == 0 else "hidden_pause")
            seg_first = seg_first or seg
            if k > 0:
                half = int(round(cover_len * fpsf / 2))
                prev = segments[-2]
                start = max(prev["start_frame"], seg["start_frame"] - half)
                end = min(seg["start_frame"] + seg["frames"], seg["start_frame"] + half)
                add_overlay(covers[k // 2 - 1], start, end - start, "cover_pause")
        # picture defects inside conversations (black, whiteout, violent shake): cover, keep the audio
        if item.kind == "conversation" and seg_first is not None:
            item_segs = [s for s in segments if s["start_frame"] >= seg_first["start_frame"]]
            for d0, d1 in cd.quality.defect_runs(item.t0, item.t1, policy, defect_min):
                for s in item_segs:
                    s_end = s["src_in"] + s["frames"] / fpsf
                    if not (s["src_in"] <= d0 < s_end):
                        continue
                    f0 = s["start_frame"] + int(round((d0 - s["src_in"] - 0.2) * fpsf))
                    f1 = s["start_frame"] + int(round((min(d1, s_end) - s["src_in"] + 0.2) * fpsf))
                    f0, f1 = max(s["start_frame"], f0), min(s["start_frame"] + s["frames"], f1)
                    if f1 - f0 < 2 or any(o["start_frame"] < f1 and f0 < o["start_frame"] + o["frames"] for o in overlays):
                        continue
                    cover = pool.take(item.event_id, (f1 - f0) / fpsf, avoid_clip=item.clip_id)
                    if cover is not None:
                        add_overlay(cover, f0, f1 - f0, "cover_defect")
                    break

    chapter_rows = []
    for ch in chapters:
        segs = [s for s in segments if s["chapter"] == ch.index]
        if not segs:
            continue
        chapter_rows.append({"index": ch.index, "name": ch.name, "date": ch.date,
                             "start_frame": segs[0]["start_frame"],
                             "end_frame": segs[-1]["start_frame"] + segs[-1]["frames"]})
    return {
        "version": 1, "name": name, "fps": [fps.numerator, fps.denominator], "width": int(width),
        "height": int(height), "orientation": master, "sample_rate": int(policy("audio.sample_rate")),
        "chapters": chapter_rows, "segments": segments, "overlays": sorted(overlays, key=lambda o: o["start_frame"]),
        "total_frames": frame,
    }
