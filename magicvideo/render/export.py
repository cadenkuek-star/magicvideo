"""Editable exports: OpenTimelineIO (DaVinci Resolve 18.5+ imports it) and a CSV EDL."""
from __future__ import annotations

import csv
from fractions import Fraction
from pathlib import Path


def timecode(frame: int, fps: Fraction) -> str:
    total = frame / fps
    h, rem = divmod(float(total), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def write_otio(timeline: dict, clips: dict[str, dict], path: Path) -> Path:
    import opentimelineio as otio
    rate = float(Fraction(*timeline["fps"]))
    RT, TR = otio.opentime.RationalTime, otio.opentime.TimeRange
    tl = otio.schema.Timeline(name=timeline["name"])
    tl.global_start_time = RT(0, rate)

    def media(clip_id: str):
        c = clips[clip_id]
        return otio.schema.ExternalReference(
            target_url=Path(c["render_path"]).resolve().as_uri(),
            available_range=TR(RT(0, rate), RT(float(c["duration"]) * rate, rate)))

    def clip_item(item: dict, kind: str):
        c = clips[item["clip_id"]]
        cl = otio.schema.Clip(name=f"{Path(c['rel_path']).name} [{kind}]", media_reference=media(item["clip_id"]),
                              source_range=TR(RT(float(item["src_in"]) * rate, rate), RT(item["frames"], rate)))
        cl.metadata["magicvideo"] = {"moment_id": item.get("moment_id"), "kind": item.get("kind", kind),
                                     "reframe": item["reframe"].get("mode"), "stabilize": item.get("stabilize", False)}
        return cl

    v1 = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    a1 = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)
    for s in timeline["segments"]:
        v1.append(clip_item(s, "segment"))
        a1.append(clip_item(s, "segment"))
    v2 = otio.schema.Track(name="V2 cutaways", kind=otio.schema.TrackKind.Video)
    pos = 0
    for o in sorted(timeline["overlays"], key=lambda o: o["start_frame"]):
        if o["start_frame"] > pos:
            v2.append(otio.schema.Gap(source_range=TR(RT(0, rate), RT(o["start_frame"] - pos, rate))))
        v2.append(clip_item(o, o["reason"]))
        pos = o["start_frame"] + o["frames"]
    for ch in timeline["chapters"]:
        v1.markers.append(otio.schema.Marker(name=ch["name"], marked_range=TR(RT(ch["start_frame"], rate), RT(0, rate))))
    tl.tracks.append(v1)
    tl.tracks.append(v2)
    tl.tracks.append(a1)
    path.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(tl, str(path))
    return path


def write_edl_csv(timeline: dict, clips: dict[str, dict], path: Path) -> Path:
    fps = Fraction(*timeline["fps"])
    rows = []
    for track, items in (("V1+A1", timeline["segments"]), ("V2", timeline["overlays"])):
        for it in items:
            src_out = float(it["src_in"]) + it["frames"] / float(fps)
            rows.append({
                "track": track, "id": it["id"], "timeline_in": timecode(it["start_frame"], fps),
                "timeline_out": timecode(it["start_frame"] + it["frames"], fps), "frames": it["frames"],
                "kind": it.get("kind", it.get("reason", "")), "chapter": it.get("chapter", ""),
                "event_id": it.get("event_id", ""), "moment_id": it.get("moment_id", ""),
                "source": clips[it["clip_id"]]["rel_path"], "src_in": f"{float(it['src_in']):.3f}",
                "src_out": f"{src_out:.3f}", "reframe": it["reframe"].get("mode", ""),
                "stabilize": it.get("stabilize", False), "join": it.get("join", ""),
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["track"])
        w.writeheader()
        w.writerows(rows)
    return path
