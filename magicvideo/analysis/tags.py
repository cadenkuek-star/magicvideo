"""Scene tags from a vision model: the coding agent (default) or the Anthropic API. Low-res frames only.

Frames (long side <= cloud.max_frame_px) are tiled into labelled 3x3 grids, one grid per request.
Only these low-res grids are ever seen by a model: with `cloud.provider: anthropic` they are sent to the API,
with `cloud.provider: agent` they are written to `<work>/tagging/` and the agent's model (for example Gemini in
Antigravity) views them there. Nothing else (audio, transcripts, face crops, embeddings, GPS) is ever sent or shown.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from .. import ffmpeg
from ..policy import Policy
from ..util import log
from ..util import read_json, write_json
from .asr import BackendMissing
from .views360 import analysis_view_filter, view_yaws

if TYPE_CHECKING:
    from ..project import Project

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


def clean_cells(cells: list, n: int) -> list[dict | None]:
    """Sanitise model answers into one entry (or None) per cell 1..n: allowed tags only, clamped interest."""
    by_cell = {int(c.get("cell", 0)): c for c in cells if isinstance(c, dict)}
    out: list[dict | None] = []
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
        if not key and not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            raise BackendMissing("no Anthropic key: set cloud.provider: agent (default) or set ANTHROPIC_API_KEY")
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
            return clean_cells(cells, n)
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


# --------------------------------------------------------------------------- agent (no API key)
def tagging_dir(project: "Project") -> Path:
    return project.root / "tagging"


def _grid_stem(i: int) -> str:
    return f"grid_{i:03d}"


def export_for_agent(project: "Project", clip: dict, path: Path, policy: Policy) -> int:
    """Write this clip's frame grids to <work>/tagging/<clip_id>/ for the agent to look at; returns grids written.

    Grids are cut from the full frame list so their numbers stay stable; a grid whose frames are all in
    analysis/<clip>/tags.json already is skipped.
    """
    import cv2
    per = int(policy("cloud.frames_per_request"))
    cid = clip["clip_id"]
    previous = read_json(project.analysis_dir(cid) / "tags.json") or {}
    done = {(round(f["t"], 2), f.get("view")) for f in previous.get("frames", [])}
    frames = sample_frames(Path(path), clip, policy)
    out_dir = tagging_dir(project) / cid
    written = 0
    for g, i in enumerate(range(0, len(frames), per), 1):
        chunk = frames[i:i + per]
        if all((round(t, 2), v) in done for t, v, _ in chunk):
            continue
        ok, buf = cv2.imencode(".jpg", make_grid([img for _, _, img in chunk]), [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{_grid_stem(g)}.jpg").write_bytes(buf.tobytes())
        write_json(out_dir / f"{_grid_stem(g)}.cells.json",
                   [{"cell": k, "t": t, "view": v} for k, (t, v, _) in enumerate(chunk, 1)])
        written += 1
    return written


def pending_grids(project: "Project") -> list[Path]:
    """Every exported grid image that has no answer file yet, in a stable order."""
    base = tagging_dir(project)
    if not base.exists():
        return []
    return [g for g in sorted(base.glob("*/grid_*.jpg")) if not g.with_suffix(".answer.json").exists()]


TASKS_TEXT = """# Scene tagging tasks

Each grid image below is a 3x3 contact sheet of numbered frames from one video (cell 1 is top left).
Look at every grid in the checklist and write one answer file for it.

## Instructions

{system_prompt}

Allowed tags: {tags}

Allowed people values: {people}

## Answer files

Next to each grid write `grid_NNN.answer.json` (same folder, same number as the grid image), containing
only JSON of this shape, with one entry per cell. The grid's `grid_NNN.cells.json` lists how many cells it has
(a grid can have fewer than 9); use cell numbers 1..n only, and `interest` between 0.0 and 1.0.

```json
{schema}
```

When you are done, run: magicvideo tags import "{work}"

## Grids to answer ({count})

{checklist}
"""


def write_tasks(project: "Project") -> int:
    """Write <work>/tagging/TASKS.md listing every unanswered grid; returns how many are waiting."""
    pending = pending_grids(project)
    base = tagging_dir(project)
    base.mkdir(parents=True, exist_ok=True)
    text = TASKS_TEXT.format(
        system_prompt=SYSTEM_PROMPT, tags=", ".join(TAGS), people=", ".join(PEOPLE),
        schema=json.dumps(response_schema(9), indent=2), work=project.root, count=len(pending),
        checklist="\n".join(f"- [ ] {g}" for g in pending) or "(none: everything is answered)")
    (base / "TASKS.md").write_text(text, encoding="utf-8")
    return len(pending)


def export_all(project: "Project") -> int:
    """`magicvideo tags export`: grids for every plannable clip, then TASKS.md. Returns grids waiting."""
    from .. import ingest
    policy = project.policy
    if not policy("cloud.scene_tagging"):
        raise BackendMissing("cloud.scene_tagging is false")
    for clip in ingest.plannable(project.inventory()):
        export_for_agent(project, clip, Path(clip["analysis_path"]), policy)
    return write_tasks(project)


def _valid_cells(payload, n: int) -> list | None:
    """The answer's cells when every cell is a dict with an integer number in 1..n, else None."""
    cells = payload.get("cells") if isinstance(payload, dict) else None
    if not isinstance(cells, list):
        return None
    for c in cells:
        num = c.get("cell") if isinstance(c, dict) else None
        if isinstance(num, bool) or not isinstance(num, int) or not 1 <= num <= n:
            return None
    return cells


def import_agent_tags(project: "Project") -> dict:
    """Merge the agent's grid_NNN.answer.json files into analysis/<clip>/tags.json (idempotent on (t, view)).

    Returns {"imported": grids that added frames, "frames_added": int, "invalid": [reasons], "missing": grids
    still unanswered}. An invalid answer (bad JSON, cells outside 1..n) skips that grid and changes nothing.
    """
    base = tagging_dir(project)
    result = {"imported": 0, "frames_added": 0, "invalid": [], "missing": 0}
    if not base.exists():
        return result
    for cdir in sorted(d for d in base.iterdir() if d.is_dir()):
        cid = cdir.name
        grids = sorted(cdir.glob("grid_*.jpg"))
        tags_path = project.analysis_dir(cid) / "tags.json"
        data = read_json(tags_path) or {"frames": []}
        frames = list(data.get("frames", []))
        known = {(round(f["t"], 2), f.get("view")) for f in frames}
        added_total = 0
        all_ok = bool(grids)
        for g in grids:
            answer = g.with_suffix(".answer.json")
            if not answer.exists():
                result["missing"] += 1
                all_ok = False
                continue
            try:
                cells_meta = read_json(g.with_suffix(".cells.json"))
                payload = json.loads(answer.read_text(encoding="utf-8-sig"))
                cells = _valid_cells(payload, len(cells_meta))
            except (ValueError, OSError, TypeError):
                cells = None
            if cells is None:
                result["invalid"].append(f"{answer}: not valid JSON of the form {{\"cells\": [...]}} with cells 1..n")
                all_ok = False
                continue
            added = 0
            for meta, r in zip(cells_meta, clean_cells(cells, len(cells_meta))):
                key = (round(meta["t"], 2), meta.get("view"))
                if r is None or key in known:
                    continue
                entry = {"t": meta["t"], **r}
                if meta.get("view") is not None:
                    entry["view"] = meta["view"]
                frames.append(entry)
                known.add(key)
                added += 1
            if added:
                result["imported"] += 1
                added_total += added
        if added_total:
            frames.sort(key=lambda f: (f["t"], f.get("view", -1)))
            write_json(tags_path, {"backend": "agent", "frames": frames,
                                   "frames_sent": int(data.get("frames_sent", 0)) + added_total})
            result["frames_added"] += added_total
        if all_ok:
            project.set_step_status(cid, "tags", "done")
    return result
