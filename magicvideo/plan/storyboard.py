"""Static storyboard page for review (no server). Click keep/drop to build overrides.yaml lines."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .. import ffmpeg
from ..analysis.views360 import analysis_view_filter
from ..util import read_json, safe_name

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--keep:#1f7a4d;--drop:#b3261e;--accent:#2f5bd3}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--ink:#ececee;--muted:#9a9aa2;--line:#2c2c31;--keep:#4cc38a;--drop:#ff7b72;--accent:#7ea2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;z-index:2}
h1{font-size:18px;margin:0 0 4px}h2{font-size:16px;margin:28px 16px 8px}h3{font-size:14px;margin:16px 16px 6px;color:var(--muted)}
.warn{color:var(--drop);margin:2px 0}.stats{color:var(--muted)}
textarea{width:100%;height:84px;font:12px ui-monospace,Consolas,monospace;margin-top:6px;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;padding:0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.card.off{opacity:.55}.card img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover;background:#000}
.body{padding:8px}.kind{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--accent)}
.meta{color:var(--muted);font-size:12px}.text{font-size:12px;margin-top:4px;max-height:5.6em;overflow:hidden}
.btns{display:flex;gap:6px;margin-top:6px}button{flex:1;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:5px;padding:3px 0;cursor:pointer}
button.k{color:var(--keep)}button.d{color:var(--drop)}code{font-size:11px;word-break:break-all;color:var(--muted)}
"""

JS = """
const picks={};function pick(id,v){picks[id]=v;const t=document.getElementById('ov');
t.value='moments:\\n'+Object.entries(picks).map(([k,x])=>'  "'+k+'": '+x).join('\\n');}
"""


def _snippet(project, clip_id: str, t0: float, t1: float, cache: dict) -> str:
    if clip_id not in cache:
        tr = read_json(project.analysis_dir(clip_id) / "transcript.json") or {}
        cache[clip_id] = tr.get("words", [])
    words = [w["w"] for w in cache[clip_id] if w["t1"] > t0 and w["t0"] < t1]
    text = " ".join(words)
    return text[:220] + ("…" if len(text) > 220 else "")


def _thumb(project, clip: dict, m: dict, out_dir: Path) -> str | None:
    out = out_dir / f"{safe_name(m['id'], 80)}.jpg"
    if not out.exists():
        t = (m["t0"] + m["t1"]) / 2
        proj = clip.get("analysis_projection", clip.get("projection", "flat"))
        if proj in ("equirect", "dual_fisheye"):
            vf = analysis_view_filter(proj, 0.0, 100.0, (320, 180), 200.0)
        else:
            vf = "scale=320:-2"
        try:
            ffmpeg.frame_png(Path(clip["analysis_path"]), t, out, vf=vf)
        except Exception:
            return None
    return out.name


def _identity_line(project, ident: dict) -> str:
    needs = float(project.policy("identity.voice.min_similarity"))
    line = (f"voice match {ident['voice_best']:.2f} (needs {needs:.2f}) · "
            f"stranger on screen: {'yes' if ident['stranger_on_screen'] else 'no'}")
    n = int(ident.get("assumed_couple", 0))
    if n:
        line += f" · treated as you two ({n} window{'s' if n != 1 else ''})"
    return line


def write_storyboard(project, plan: dict, timeline: dict, path: Path, thumbs: bool = False) -> Path:
    clips = {c["clip_id"]: c for c in project.inventory()}
    thumb_dir = path.parent / "thumbs"
    if thumbs:
        thumb_dir.mkdir(parents=True, exist_ok=True)
    cache: dict = {}
    st = plan["stats"]
    sh = st["shares"]
    head = (f"<h1>{html.escape(plan['name'])} · storyboard</h1>"
            f"<div class=stats>{st['selected']} of {st['moments']} moments · "
            f"{st['planned_seconds'] / 60:.1f} min planned from {st['raw_seconds'] / 60:.1f} min raw · "
            f"couple {sh['couple']['share']:.0%} · coverage {sh['coverage']['share']:.0%} · "
            f"transit {sh['transit']['share']:.0%} · other people {sh['third_party']['share']:.0%}</div>"
            + "".join(f"<div class=warn>⚠ {html.escape(w)}</div>" for w in plan["warnings"])
            + "<textarea id=ov placeholder='Click keep/drop below, then paste these lines into overrides.yaml and run magicvideo plan again'></textarea>")
    body = []
    by_event: dict[str, list[dict]] = {}
    for m in plan["moments"]:
        by_event.setdefault(m["event_id"], []).append(m)
    for ch in plan["chapters"]:
        body.append(f"<h2>{html.escape(ch['name'])}</h2>")
        for eid in ch["event_ids"]:
            ev = next(e for e in plan["events"] if e["id"] == eid)
            body.append(f"<h3>{html.escape(ev['label'])} · {ev['type']} · couple {ev['couple_time']:.0f}s · "
                        f"coverage {ev['coverage_used']:.0f}/{ev['coverage_budget']:.0f}s · other people "
                        f"{ev['third_party_used']:.0f}s · <code>{eid}</code></h3><div class=grid>")
            for m in sorted(by_event.get(eid, []), key=lambda m: m["abs_t0"]):
                if m["kind"] == "coverage" and not m["selected"] and "cutaway" not in m["reason"]:
                    continue  # unselected coverage candidates would swamp the page
                clip = clips.get(m["clip_id"], {})
                img = _thumb(project, clip, m, thumb_dir) if thumbs and clip else None
                text = _snippet(project, m["clip_id"], m["t0"], m["t1"], cache)
                mid = html.escape(m["id"])
                body.append(
                    f"<div class='card{'' if m['selected'] else ' off'}'>"
                    + (f"<img src='thumbs/{html.escape(img)}' loading=lazy>" if img else "")
                    + f"<div class=body><div class=kind>{m['kind']} · {m['cls']}</div>"
                    f"<div class=meta>{html.escape(clip.get('rel_path', m['clip_id']))} · "
                    f"{m['t0']:.1f}–{m['t1']:.1f}s ({m['dur']:.1f}s)</div>"
                    f"<div class=meta>{html.escape(m['reason'])}</div>"
                    + (f"<div class=meta>{html.escape(_identity_line(project, m['identity']))}</div>"
                       if m.get("identity") else "")
                    + (f"<div class=text>“{html.escape(text)}”</div>" if text else "")
                    + (f"<div class=text>{html.escape(m['desc'])}</div>" if m.get("desc") else "")
                    + f"<div class=btns><button class=k onclick=\"pick('{mid}','keep')\">keep</button>"
                    f"<button class=d onclick=\"pick('{mid}','drop')\">drop</button></div>"
                    f"<code>{mid}</code></div></div>")
            body.append("</div>")
    page = (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(plan['name'])} storyboard</title><style>{CSS}</style><script>{JS}</script></head>"
            f"<body><header>{head}</header>{''.join(body)}"
            f"<script>window.TIMELINE_FRAMES={json.dumps(timeline.get('total_frames', 0))}</script></body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
