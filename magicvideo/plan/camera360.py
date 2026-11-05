"""Virtual camera paths for 360° segments (brief §6.7)."""
from __future__ import annotations

from ..analysis.views360 import angle_diff, circular_mean, circular_spread, min_hfov_for_width, view_yaws, wrap180
from ..policy import Policy
from .data import PARTNERS, ClipData

STEP_S = 0.1          # path resolution
CUT_DEG = 60.0        # target changes larger than this are cuts, not pans
STILL_EDGE_S = 1.0    # no movement in the first/last second of a shot


def _targets(cd: ClipData, t: float, kind: str, policy: Policy, min_hfov: float) -> tuple[float, float, float] | None:
    spread_max = float(policy("insta360.both_partners_max_spread_deg"))
    yaws = cd.partner_yaws(t - 1.5, t + 1.5)
    pitches = [d["pitch"] for d, lab in zip(cd.face_dets, cd.face_labels)
               if lab in PARTNERS and abs(d["t"] - t) <= 1.5 and "pitch" in d]
    pitch = 0.5 * (sum(pitches) / len(pitches)) if pitches else 0.0
    if kind in ("conversation", "action"):
        both = [circular_mean(v) for v in yaws.values()]
        if len(both) == 2 and circular_spread(both) <= spread_max:
            spread = circular_spread(both)
            return circular_mean(both), pitch, min(120.0, max(min_hfov, spread + 40.0))
        speaker = None
        for turn in cd.turns:
            if turn.t0 - 0.3 <= t <= turn.t1 + 0.3 and turn.speaker in PARTNERS:
                speaker = turn.speaker
        if speaker and speaker in yaws:
            return circular_mean(yaws[speaker]), pitch, min_hfov
        if len(both) >= 1:
            return both[0], pitch, min_hfov
        return None
    # coverage / third-party: best tagged view in the shot
    return None


def _coverage_target(cd: ClipData, t0: float, t1: float, policy: Policy) -> float:
    views = view_yaws(int(policy("insta360.analysis_views")))
    best = None
    for f in cd.tags_in(t0, t1, 1.5):
        if "view" in f and (best is None or f.get("interest", 0) > best.get("interest", 0)):
            best = f
    return views[int(best["view"])] if best is not None and int(best["view"]) < len(views) else 0.0


def camera_path(cd: ClipData, src_in: float, frames: int, fps: float, kind: str, policy: Policy) -> list[list[float]]:
    """[[frame_offset, yaw, pitch, hfov], ...] keyframes every STEP_S, rate-limited, with holds before cuts."""
    width = int(cd.clip.get("width") or 0)
    min_hfov = min_hfov_for_width(width, policy("insta360.min_hfov_deg"))
    max_speed = float(policy("insta360.max_yaw_speed_dps"))
    min_hold = float(policy("insta360.min_shot_hold_s"))
    plimit = float(policy("insta360.pitch_limit_deg"))
    dur = frames / fps
    n = max(1, int(dur / STEP_S) + 1)
    if kind not in ("conversation", "action"):
        yaw = _coverage_target(cd, src_in, src_in + dur, policy)
        return [[0, round(wrap180(yaw), 2), 0.0, round(min_hfov, 2)]]
    path: list[list[float]] = []
    cur = None
    last_cut = 0.0
    for k in range(n):
        tr = k * STEP_S
        tgt = _targets(cd, src_in + tr, kind, policy, min_hfov)
        if cur is None:
            cur = list(tgt) if tgt else [_coverage_target(cd, src_in, src_in + dur, policy), 0.0, min_hfov]
        elif tgt is not None and STILL_EDGE_S <= tr <= dur - STILL_EDGE_S:
            d = angle_diff(tgt[0], cur[0])
            if abs(d) > CUT_DEG:
                if tr - last_cut >= min_hold:
                    cur = list(tgt)
                    last_cut = tr
            else:
                step = max(-max_speed * STEP_S, min(max_speed * STEP_S, d * 0.35))  # eased approach
                cur[0] = wrap180(cur[0] + step)
                cur[1] += max(-2.0, min(2.0, (tgt[1] - cur[1]) * 0.35))
                cur[2] += max(-3.0, min(3.0, (tgt[2] - cur[2]) * 0.35))
        cur[1] = max(-plimit, min(plimit, cur[1]))
        cur[2] = max(min_hfov, min(120.0, cur[2]))
        frame = int(round(tr * fps))
        if frame < frames:
            path.append([frame, round(cur[0], 2), round(cur[1], 2), round(cur[2], 2)])
    return path
