"""Scene tags from a cloud vision model (Anthropic API). Low-res frames only (brief §2 rule 7).

Frames (long side <= cloud.max_frame_px) are tiled into labelled grids, one grid per request.
Nothing else (audio, transcripts, face crops, embeddings, GPS) is ever sent.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import numpy as np

from .. import ffmpeg
from ..policy import Policy
from ..util import log
from .asr import BackendMissing
from .views360 import analysis_view_filter, view_yaws

DEFAULT_MODEL = "claude-opus-5-5"   # change with cloud.model in policy.yaml (e.g. a cheaper Haiku for volume)

TAGS = [
    "food", "drink", "restaurant", "cafe", "table", "cooking", "market", "street", "shop", "crowd",
    "car", "train", "bus", "plane", "airport", "boat", "station", "road", "walking",
    "landmark", "temple", "museum", "architecture", "nature", "mountain", "lake", "beach", "snow",
    "sunset", "night", "viewpoint", "scenery", "hotel", "room", "pool", "gym",
    "performance", "guide", "staff", "selfie", "couple",
    "taste", "toast", "cheers", "reveal", "game", "dance", "purchase",
]
PEOPLE = ["none", "partners", "others", "crowd", "mixed"]

TYPE_OF_TAG = {
    **{t: "meal" for t in ("food", "drink", "restaurant", "cafe", "table", "cooking", "taste", "toast", "cheers")},
    **{t: "transit" for t in ("car", "train", "bus", "plane", "airport", "boat", "station", "road")},
    **{t: "landmark" for t in ("landmark", "temple", "museum", "architecture", "nature", "mountain", "lake",
                               "beach", "snow", "sunset", "viewpoint", "scenery")},
    **{t: "street" for t in ("street", "market", "shop", "walking", "crowd")},
    **{t: "hotel" for t in ("hotel", "room", "pool", "gym")},
    **{t: "performance" for t in ("performance", "guide")},
}
EVENT_TYPES = ["meal", "transit", "landmark", "street", "hotel", "performance", "general"]

SYSTEM_PROMPT = """You label frames from a couple's personal travel videos so an editing program can organise them.
Each image is a grid of numbered cells; every cell is one frame. For every cell return:
- tags: the visible content, chosen only from the allowed list (empty list if nothing fits)
- people: "partners" if the travelling couple (the people the camera follows or who hold it) are the focus,
  "others" if other featured people (guides, staff, performers, strangers) are the focus, "crowd" for incidental
  background people only, "mixed" if both partners and others are featured, "none" if nobody is visible
- interest: how visually interesting the frame is as a shot in a travel film, from 0.0 (floor, pocket, blur,
  blank wall) to 1.0 (striking view, food close-up, joyful moment)
- desc: at most 12 words describing the frame
Action tags (taste, toast, cheers, reveal, game, dance, purchase) only when that action is clearly happening.
Describe what is visible; do not guess names, identities or exact locations."""


def response_schema(n: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "cells": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cell": {"type": "integer"},
                        "tags": {"type": "array", "items": {"type": "string", "enum": TAGS}},
                        "people": {"type": "string", "enum": PEOPLE},
                        "interest": {"type": "number"},
                        "desc": {"type": "string"},
                    },
                    "required": ["cell", "tags", "people", "interest", "desc"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["cells"],
        "additionalProperties": False,
    }


def event_type(tag_lists: list[list[str]]) -> str:
    counts: dict[str, float] = {}
    for tags in tag_lists:
        for t in tags:
            typ = TYPE_OF_TAG.get(t)
            if typ:
                counts[typ] = counts.get(typ, 0.0) + 1.0
    if not counts:
        return "general"
    return sorted(counts.items(), key=lambda kv: (-kv[1], EVENT_TYPES.index(kv[0])))[0][0]


# --------------------------------------------------------------------------- frame sampling
def sample_frames(path: Path, clip: dict, policy: Policy) -> list[tuple[float, int | None, np.ndarray]]:
    """[(t, view, bgr)] low-res frames for tagging."""
    interval = float(policy("cloud.frame_interval_s"))
    px = int(policy("cloud.max_frame_px"))
    proj = clip.get("analysis_projection", clip.get("projection", "flat"))
    out: list[tuple[float, int | None, np.ndarray]] = []
    if proj in ("equirect", "dual_fisheye"):
        size = ffmpeg.scaled_size(16, 9, px)
        for k, yaw in enumerate(view_yaws(int(policy("insta360.analysis_views")))):
            vf = analysis_view_filter(proj, yaw, float(policy("insta360.analysis_view_fov_deg")), size,
                                      float(policy("insta360.fisheye_fov_deg")))
            for t, frame in ffmpeg.read_frames(path, fps=1.0 / (interval * 2), size=size, extra_vf=vf):
                out.append((t, k, frame))
    else:
        size = ffmpeg.scaled_size(clip["display_w"], clip["display_h"], px)
        for t, frame in ffmpeg.read_frames(path, fps=1.0 / interval, size=size):
            out.append((t, None, frame))
    return out


def make_grid(frames: list[np.ndarray], cols: int = 3) -> np.ndarray:
    import cv2
    h = max(f.shape[0] for f in frames)
    w = max(f.shape[1] for f in frames)
    rows = (len(frames) + cols - 1) // cols
    grid = np.zeros((rows * h, cols * w, 3), np.uint8)
    for i, f in enumerate(frames):
        r, c = divmod(i, cols)
        y, x = r * h + (h - f.shape[0]) // 2, c * w + (w - f.shape[1]) // 2
        grid[y:y + f.shape[0], x:x + f.shape[1]] = f
        label = str(i + 1)
        cv2.rectangle(grid, (c * w + 4, r * h + 4), (c * w + 40, r * h + 34), (0, 0, 0), -1)
        cv2.putText(grid, label, (c * w + 10, r * h + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return grid


# --------------------------------------------------------------------------- API
class Tagger:
    def __init__(self, policy: Policy):
        if not policy("cloud.scene_tagging"):
            raise BackendMissing("cloud.scene_tagging is false")
        if policy("cloud.provider") != "anthropic":
            raise BackendMissing(f"unsupported cloud.provider {policy('cloud.provider')}")
        try:
            import anthropic  # type: ignore
        except ImportError as e:
            raise BackendMissing("anthropic SDK not installed (pip install 'magicvideo[tags]')") from e
        self.anthropic = anthropic
        key_env = policy("cloud.api_key_env")
        key = os.environ.get(key_env) if key_env else None
        # without an explicit key the SDK resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login`
        self.client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        self.model = policy("cloud.model") or DEFAULT_MODEL
        self.effort = policy("cloud.effort")
        self.policy = policy

    def tag_grid(self, frames: list[np.ndarray]) -> list[dict] | None:
        import cv2
        grid = make_grid(frames)
        ok, buf = cv2.imencode(".jpg", grid, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        data = base64.standard_b64encode(buf.tobytes()).decode("ascii")
        n = len(frames)
        a = self.anthropic
        for attempt in range(3):
            try:
                response = self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=16000,
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    system=SYSTEM_PROMPT,
                    output_config={"effort": self.effort,
                                   "format": {"type": "json_schema", "schema": response_schema(n)}},
                    messages=[{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                        {"type": "text", "text": f"Label cells 1 to {n}. Allowed tags: {', '.join(TAGS)}."},
                    ]}],
                )
            except a.RateLimitError as e:
                wait = int(e.response.headers.get("retry-after", "30"))
                log.warning("tagging rate-limited, retrying in %ss", wait)
                time.sleep(wait)
                continue
            except (a.AuthenticationError, a.PermissionDeniedError, a.NotFoundError, a.BadRequestError) as e:
                raise BackendMissing(f"cloud tagging unavailable: {e}") from e
            except a.APIStatusError as e:
                if e.status_code >= 500 and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                log.warning("tagging failed: %s", e)
                return None
            except a.APIConnectionError as e:
                log.warning("tagging network error: %s", e)
                time.sleep(5 * (attempt + 1))
                continue
            if response.stop_reason in ("refusal", "max_tokens"):
                log.warning("tagging stopped (%s) for one grid; frames left untagged", response.stop_reason)
                return None
            text = next((b.text for b in response.content if b.type == "text"), None)
            if not text:
                return None
            try:
                cells = json.loads(text)["cells"]
            except (ValueError, KeyError, TypeError):
                return None
            by_cell = {int(c.get("cell", 0)): c for c in cells if isinstance(c, dict)}
            out = []
            for i in range(1, n + 1):
                c = by_cell.get(i)
                if c is None:
                    out.append(None)
                    continue
                out.append({
                    "tags": sorted({t for t in c.get("tags", []) if t in TAGS}),
                    "people": c.get("people") if c.get("people") in PEOPLE else "none",
                    "interest": float(np.clip(float(c.get("interest", 0.5)), 0.0, 1.0)),
                    "desc": str(c.get("desc", ""))[:120],
                })
            return out
        return None


def analyze(path: Path, clip: dict, policy: Policy, tagger: Tagger | None = None,
            previous: dict | None = None) -> dict:
    tagger = tagger or Tagger(policy)
    per = int(policy("cloud.frames_per_request"))
    done = {(round(f["t"], 2), f.get("view")) for f in (previous or {}).get("frames", [])}
    frames_out = list((previous or {}).get("frames", []))
    todo = [(t, v, img) for t, v, img in sample_frames(path, clip, policy) if (round(t, 2), v) not in done]
    sent = 0
    for i in range(0, len(todo), per):
        chunk = todo[i:i + per]
        result = tagger.tag_grid([img for _, _, img in chunk])
        sent += len(chunk)
        if result is None:
            continue
        for (t, v, _), r in zip(chunk, result):
            if r is not None:
                entry = {"t": t, **r}
                if v is not None:
                    entry["view"] = v
                frames_out.append(entry)
    frames_out.sort(key=lambda f: (f["t"], f.get("view", -1)))
    return {"backend": f"anthropic:{tagger.model}", "frames": frames_out,
            "frames_sent": int((previous or {}).get("frames_sent", 0)) + sent}
