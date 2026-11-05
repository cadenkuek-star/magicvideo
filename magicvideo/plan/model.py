"""Planner data structures (brief §6.3–6.6)."""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

EPOCH = dt.datetime(1970, 1, 1)


def abs_seconds(iso_local: str) -> float:
    """Machine-independent seconds for a naive local ISO time."""
    return (dt.datetime.fromisoformat(iso_local) - EPOCH).total_seconds()


@dataclass
class Turn:
    t0: float
    t1: float
    speaker: str      # PARTNER_A | PARTNER_B | OTHER | UNKNOWN
    w0: int
    w1: int


@dataclass
class Moment:
    id: str
    clip_id: str
    kind: str                     # conversation | action | third_party | coverage
    t0: float
    t1: float
    abs_t0: float
    score: float = 0.5
    speakers: list[str] = field(default_factory=list)
    partner_words: int = 0
    words: int = 0
    pauses: list[list[float]] = field(default_factory=list)  # shortenable [p0, p1]
    tags: list[str] = field(default_factory=list)
    cls: str = ""                 # budget class: couple | coverage | transit | third_party
    partners_visible: list[str] = field(default_factory=list)
    interest: float = 0.5
    desc: str = ""
    event_id: str = ""
    selected: bool = False
    reason: str = ""
    max_len: float | None = None  # cap (e.g. silent solo shot)

    @property
    def dur(self) -> float:
        return max(0.0, self.t1 - self.t0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dur"] = self.dur
        return d


@dataclass
class Event:
    id: str
    type: str
    label: str
    date: str
    abs_t0: float
    abs_t1: float
    clip_ids: list[str]
    chapter: int = 0
    coverage_budget: float = 0.0
    coverage_used: float = 0.0
    third_party_used: float = 0.0
    couple_time: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Chapter:
    index: int
    date: str
    name: str
    event_ids: list[str]

    def to_dict(self) -> dict:
        return asdict(self)
