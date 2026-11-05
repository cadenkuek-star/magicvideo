"""Small shared helpers: deterministic JSON, versioned paths, hashing, logging."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("magicvideo")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def _round_floats(obj: Any, ndigits: int = 3) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        r = round(obj, ndigits)
        return 0.0 if r == 0 else r  # avoid "-0.0"
    if isinstance(obj, dict):
        return {str(k): _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v, ndigits) for v in obj]
    if hasattr(obj, "item") and callable(obj.item):  # numpy scalar
        return _round_floats(obj.item(), ndigits)
    return obj


def dumps(obj: Any) -> str:
    """Deterministic JSON: sorted keys, floats rounded to 3 decimals."""
    return json.dumps(_round_floats(obj), sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def write_json(path: Path, obj: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dumps(obj), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def sha1_hex(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


_VERSION_RE = re.compile(r"_v(\d{3})(?=\.[^.]+$|$)")


def version_of(path: Path) -> int | None:
    m = _VERSION_RE.search(Path(path).name)
    return int(m.group(1)) if m else None


def latest_version(paths: Iterable[Path]) -> int | None:
    versions = [v for v in (version_of(p) for p in paths) if v is not None]
    return max(versions) if versions else None


def next_version(directory: Path, pattern: str) -> int:
    """Next free version number for files matching e.g. 'plan_v*.json'."""
    directory = Path(directory)
    v = latest_version(directory.glob(pattern)) if directory.exists() else None
    return (v or 0) + 1


def vtag(n: int) -> str:
    return f"v{n:03d}"


def safe_name(text: str, max_len: int = 60) -> str:
    """File-system safe name (Windows too)."""
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^\w\-.·]", "", text)
    return (text[:max_len].rstrip("._-") or "untitled")


def intervals_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def merge_intervals(items: list[tuple[float, float]], gap: float = 0.0) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, e in sorted(items):
        if out and s <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract_intervals(span: tuple[float, float], holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    s, e = span
    out = []
    cur = s
    for h0, h1 in merge_intervals(holes):
        if h1 <= cur or h0 >= e:
            continue
        if h0 > cur:
            out.append((cur, min(h0, e)))
        cur = max(cur, h1)
        if cur >= e:
            break
    if cur < e:
        out.append((cur, e))
    return out
