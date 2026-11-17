"""Events (time-gap clusters) and chapters (one per local day). Brief §6.4."""
from __future__ import annotations

import datetime as dt

from ..analysis.tags import event_type
from ..policy import Policy
from .data import ClipData
from .model import Chapter, Event

TRANSIT_WORDS = {"train": "Train ride", "car": "On the road", "road": "On the road", "bus": "Bus ride",
                 "plane": "Flight", "airport": "Airport", "boat": "Boat ride", "station": "Station"}
TYPE_LABEL = {"landmark": "Sightseeing", "street": "Exploring", "hotel": "Hotel", "performance": "Show",
              "general": "Moments"}


def _meal_label(hour: int) -> str:
    if 5 <= hour < 11:
        return "Breakfast"
    if 11 <= hour < 16:
        return "Lunch"
    if 17 <= hour < 23:
        return "Dinner"
    return "Snack"


def _place(cds: list[ClipData]) -> str | None:
    locs = [c.clip["location"] for c in cds if c.clip.get("location")]
    if not locs:
        return None
    try:
        import reverse_geocoder  # type: ignore  # offline GeoNames data; GPS never leaves the machine
    except ImportError:
        return None
    try:
        res = reverse_geocoder.search([tuple(locs[0])], mode=1, verbose=False)
        return res[0].get("name") if res else None
    except Exception:
        return None


def label_for(etype: str, start: dt.datetime, tag_lists: list[list[str]]) -> str:
    if etype == "meal":
        return _meal_label(start.hour)
    if etype == "transit":
        counts: dict[str, int] = {}
        for tags in tag_lists:
            for t in tags:
                if t in TRANSIT_WORDS:
                    counts[t] = counts.get(t, 0) + 1
        if counts:
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            return TRANSIT_WORDS[top]
        return "On the move"
    return TYPE_LABEL.get(etype, "Moments")


def build_events(cds: list[ClipData], policy: Policy) -> tuple[list[Event], dict[str, str]]:
    gap = float(policy("events.gap_min")) * 60.0
    groups: list[list[ClipData]] = []
    prev_end = None
    prev_date = None
    for cd in sorted(cds, key=lambda c: (c.abs_start, c.id)):
        date = dt.datetime.fromisoformat(cd.clip["capture_start"]).date()
        if not groups or prev_end is None or cd.abs_start - prev_end > gap or date != prev_date:
            groups.append([])
        groups[-1].append(cd)
        end = cd.abs_start + cd.duration
        prev_end = end if prev_end is None else max(prev_end, end)
        prev_date = date
    events: list[Event] = []
    clip_event: dict[str, str] = {}
    per_day: dict[str, int] = {}
    for g in groups:
        start = dt.datetime.fromisoformat(g[0].clip["capture_start"])
        day = start.strftime("%Y%m%d")
        per_day[day] = per_day.get(day, 0) + 1
        tag_lists = [f.get("tags", []) for cd in g for f in cd.tags]
        etype = event_type(tag_lists)
        label = label_for(etype, start, tag_lists)
        place = _place(g)
        if place:
            label = f"{label} · {place}"
        ev = Event(id=f"e{day}_{per_day[day]:02d}", type=etype, label=label, date=start.date().isoformat(),
                   abs_t0=g[0].abs_start, abs_t1=max(c.abs_start + c.duration for c in g),
                   clip_ids=[c.id for c in g])
        events.append(ev)
        for c in g:
            clip_event[c.id] = ev.id
    return events, clip_event


def build_chapters(events: list[Event]) -> list[Chapter]:
    by_date: dict[str, list[Event]] = {}
    for e in events:
        by_date.setdefault(e.date, []).append(e)
    chapters = []
    for k, date in enumerate(sorted(by_date), 1):
        labels: list[str] = []
        for e in by_date[date]:
            base = e.label
            if base not in labels:
                labels.append(base)
        name = f"Day {k} · " + ", ".join(labels[:3])
        chapters.append(Chapter(index=k, date=date, name=name, event_ids=[e.id for e in by_date[date]]))
        for e in by_date[date]:
            e.chapter = k
    return chapters
