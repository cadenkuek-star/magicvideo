"""Retake detection: the same moment recorded more than once -> keep the best take (brief §15).

People re-record a selfie line until they are happy with it. Every take is a protected conversation, so without
this the film would hold all of them. Two moments are retakes of each other when they are in the same event,
close in time, and say the same thing (transcript tokens) or, without enough words, look the same (visual
descriptor) with the same partners on screen. Groups are transitive. The best take is chosen by a score; the
others are left out with a reason, and the owner can rescue any of them with `keep` in the review page.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from ..policy import Policy
from .data import ClipData
from .model import Moment

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
_TOKEN = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]|[^\W_]+", re.U)


def tokens(text: str) -> list[str]:
    """Lower-case comparison tokens: Latin words stay whole, each CJK/kana character is one token."""
    out = []
    for w in text.lower().split():
        w = "".join(c for c in w if unicodedata.category(c)[0] not in "PS")
        out += _TOKEN.findall(w)
    return out


def text_similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def moment_tokens(m: Moment, cd: ClipData) -> list[str]:
    return tokens(" ".join(cd.words[i]["w"] for i in cd.words_in(m.t0, m.t1)))


class _Union:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, i: int) -> int:
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def join(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _complete(m: Moment, cd: ClipData, edge_s: float) -> bool:
    """A take whose last word runs into the end of the file is probably cut off."""
    idx = cd.words_in(m.t0, m.t1)
    if not idx:
        return True
    return cd.words[idx[-1]]["t1"] <= cd.duration - edge_s


def take_score(m: Moment, cd: ClipData, policy: Policy) -> tuple:
    """Higher is better. Complete sentence, then more partner words, picture quality, fewer long pauses, later take."""
    edge = float(policy("moments.edge_speech.end_s"))
    q = cd.quality.score(m.t0, m.t1, policy) if not cd.quality.empty else 0.5
    return (1 if _complete(m, cd, edge) else 0, m.partner_words, round(q, 3), -len(m.pauses), m.abs_t0)


def find_retake_groups(moments: list[Moment], clips: dict[str, ClipData], policy: Policy) -> list[list[Moment]]:
    """Groups (size >= 2) of conversation/action moments that are takes of the same thing, per event."""
    if not policy("retakes.enabled"):
        return []
    window = float(policy("retakes.window_s"))
    text_min = float(policy("retakes.text_similarity_min"))
    vis_min = float(policy("retakes.visual_similarity_min"))
    min_words = int(policy("retakes.min_words"))
    cands = sorted((m for m in moments if m.kind in ("conversation", "action")), key=lambda m: (m.abs_t0, m.id))
    by_event: dict[str, list[Moment]] = {}
    for m in cands:
        by_event.setdefault(m.event_id, []).append(m)
    groups: list[list[Moment]] = []
    for eid in sorted(by_event):
        ms = by_event[eid]
        toks = [moment_tokens(m, clips[m.clip_id]) for m in ms]
        descs = [clips[m.clip_id].quality.desc_at(m.t0, m.t1) for m in ms]
        uf = _Union(len(ms))
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                if ms[j].abs_t0 - ms[i].abs_t0 > window:
                    break
                same = False
                if len(toks[i]) >= min_words and len(toks[j]) >= min_words:
                    same = text_similarity(toks[i], toks[j]) >= text_min
                elif len(toks[i]) < min_words and len(toks[j]) < min_words:
                    di, dj = descs[i], descs[j]
                    same = (di is not None and dj is not None and float(di @ dj) >= vis_min
                            and ms[i].partners_visible == ms[j].partners_visible and ms[i].kind == ms[j].kind)
                if same:
                    uf.join(i, j)
        members: dict[int, list[Moment]] = {}
        for k, m in enumerate(ms):
            members.setdefault(uf.find(k), []).append(m)
        groups += [g for _, g in sorted(members.items()) if len(g) >= 2]
    return groups


def apply_retakes(moments: list[Moment], clips: dict[str, ClipData], policy: Policy, overrides: dict) -> dict:
    """Mark the losers of every retake group (`retake_of`), unless the owner kept them. Returns stats."""
    rules = overrides.get("moments", {}) or {}
    groups = find_retake_groups(moments, clips, policy)
    dropped = 0
    for n, g in enumerate(groups, 1):
        gid = f"rt{n:03d}"
        best = max(g, key=lambda m: take_score(m, clips[m.clip_id], policy))
        for m in g:
            m.retake_group = gid
            m.retake_of = None if m is best else best.id
            if m is not best and rules.get(m.id) not in ("keep", "couple"):
                dropped += 1
    return {"retake_groups": len(groups), "retakes_dropped": dropped}
