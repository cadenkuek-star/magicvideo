"""Storyboard page for review. Served by `magicvideo review` (clicks save to overrides.yaml); opened as a file it
offers a downloadable overrides.yaml instead."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .. import ffmpeg
from ..analysis.views360 import analysis_view_filter
from ..util import read_json, safe_name, version_of, vtag

STALE_REFS_TEXT = "Your partner references changed after this plan was made. Run magicvideo plan again."

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--keep:#1f7a4d;--drop:#b3261e;--accent:#2f5bd3}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--ink:#ececee;--muted:#9a9aa2;--line:#2c2c31;--keep:#4cc38a;--drop:#ff7b72;--accent:#7ea2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;z-index:2}
h1{font-size:18px;margin:0 0 4px}h2{font-size:16px;margin:28px 16px 8px}h3{font-size:14px;margin:16px 16px 6px;color:var(--muted)}
.warn{color:var(--drop);margin:2px 0}.stats{color:var(--muted)}
.stale{background:var(--drop);color:#fff;padding:8px 12px;border-radius:6px;margin:6px 0;font-weight:600}
#bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:3}
#bar button{flex:none;padding:6px 14px;background:var(--accent);color:#fff;border-color:var(--accent)}#bar .hint{color:var(--muted);font-size:12px}
body{padding-bottom:64px}.btns button.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}.btns button.u{color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;padding:0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.card.off{opacity:.55}.card img{width:100%;display:block;aspect-ratio:16/9;object-fit:cover;background:#000}
.body{padding:8px}.kind{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--accent)}
.meta{color:var(--muted);font-size:12px}.text{font-size:12px;margin-top:4px;max-height:5.6em;overflow:hidden}
.btns{display:flex;gap:6px;margin-top:6px}button{flex:1;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:5px;padding:3px 0;cursor:pointer}
button.k{color:var(--keep)}button.d{color:var(--drop)}code{font-size:11px;word-break:break-all;color:var(--muted)}
"""

JS = r"""
(function(){
var live=false,changes=0,PICKS={};
function cur(id){var m=(window.OVERRIDES&&window.OVERRIDES.moments)||{};var v=PICKS.hasOwnProperty(id)?PICKS[id]:m[id];return typeof v==='string'?v:null;}
function paint(){document.querySelectorAll('.card').forEach(function(c){var v=cur(c.dataset.id);
c.querySelectorAll('.btns button').forEach(function(b){b.classList.toggle('on',b.dataset.v===v||(b.dataset.v==='clear'&&!v));});});}
function scalar(v){return JSON.stringify(v);}
function emit(o,ind){var pad=new Array(ind+1).join(' '),ks=Object.keys(o).sort(),out=[];
if(!ks.length)return null;
ks.forEach(function(k){var v=o[k];
if(v&&typeof v==='object'&&!Array.isArray(v)){var sub=emit(v,ind+2);out.push(pad+scalar(k)+': '+(sub===null?'{}':'\n'+sub));}
else out.push(pad+scalar(k)+': '+scalar(v));});
return out.join('\n');}
function yamlText(){var o=JSON.parse(JSON.stringify(window.OVERRIDES||{}));o.moments=o.moments||{};o.events=o.events||{};o.clips=o.clips||{};
Object.keys(PICKS).forEach(function(id){if(PICKS[id]==='clear')delete o.moments[id];else o.moments[id]=PICKS[id];});
return ['moments','events','clips'].map(function(k){var t=emit(o[k],2);return k+':'+(t===null?' {}':'\n'+t);}).join('\n')+'\n';}
function bar(){var b=document.getElementById('bar');
if(live){b.innerHTML='<span id=saved>Saved \u00b7 '+changes+' change'+(changes===1?'':'s')+'</span><button id=replan>Re-plan now</button>';
document.getElementById('replan').onclick=replan;}
else{b.innerHTML='<button id="download-overrides">Download overrides.yaml</button><span class=hint>Save it over '+window.WORK_OVERRIDES_PATH+', or run: magicvideo review "'+window.WORK_PATH+'"</span>';
document.getElementById('download-overrides').onclick=download;}}
function download(){var blob=new Blob([yamlText()],{type:'text/yaml'}),a=document.createElement('a');
a.href=URL.createObjectURL(blob);a.download='overrides.yaml';document.body.appendChild(a);a.click();a.remove();}
function replan(){var b=document.getElementById('replan');b.disabled=true;b.textContent='Planning...';
fetch('/api/replan',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(r){return r.json();})
.then(function(){location.href='/';}).catch(function(){b.disabled=false;b.textContent='Re-plan failed - try again';});}
function choose(id,v){
if(live){fetch('/api/moment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id,value:v})})
.then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
.then(function(x){if(!x.ok)throw new Error(x.j.error||'rejected');window.OVERRIDES=x.j.overrides;PICKS={};changes++;paint();bar();})
.catch(function(e){document.getElementById('bar').textContent='Could not save: '+e.message;});}
else{PICKS[id]=v;paint();}}
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('.btns button');if(!b)return;
var c=b.closest('.card');if(c)choose(c.dataset.id,b.dataset.v);});
window.addEventListener('DOMContentLoaded',function(){paint();bar();
fetch('/api/overrides').then(function(r){if(!r.ok)throw 0;return r.json();}).then(function(j){
live=true;window.OVERRIDES=j.overrides;if(j.stale_refs)document.getElementById('stale').hidden=false;paint();bar();}).catch(function(){});});
})();
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


def _js_json(obj) -> str:
    """JSON that is safe inside an HTML <script> element."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def write_storyboard(project, plan: dict, timeline: dict, path: Path, thumbs: bool = False) -> Path:
    v = version_of(path)
    tag = vtag(v) if v else ""
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
            + f"<div id=stale class=stale hidden>{html.escape(STALE_REFS_TEXT)}</div>")
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
                    f"<div class='card{'' if m['selected'] else ' off'}' data-id=\"{mid}\">"
                    + (f"<img src='thumbs/{html.escape(img)}' loading=lazy>" if img else "")
                    + f"<div class=body><div class=kind>{m['kind']} · {m['cls']}</div>"
                    f"<div class=meta>{html.escape(clip.get('rel_path', m['clip_id']))} · "
                    f"{m['t0']:.1f}–{m['t1']:.1f}s ({m['dur']:.1f}s)</div>"
                    f"<div class=meta>{html.escape(m['reason'])}</div>"
                    + (f"<div class=meta>{html.escape(_identity_line(project, m['identity']))}</div>"
                       if m.get("identity") else "")
                    + (f"<div class=text>“{html.escape(text)}”</div>" if text else "")
                    + (f"<div class=text>{html.escape(m['desc'])}</div>" if m.get("desc") else "")
                    + "<div class=btns><button class=k data-v=keep>keep</button>"
                    "<button class=d data-v=drop>drop</button>"
                    + ("<button class=u data-v=couple>this is us</button>" if m["cls"] == "third_party" else "")
                    + "<button data-v=clear>clear</button></div>"
                    f"<code>{mid}</code></div></div>")
            body.append("</div>")
    page = (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(plan['name'])} storyboard</title><style>{CSS}</style></head>"
            f"<body><header>{head}</header>{''.join(body)}<div id=bar></div>"
            f"<script>window.TIMELINE_FRAMES={json.dumps(timeline.get('total_frames', 0))};"
            f"window.OVERRIDES={_js_json(project.overrides())};window.PLAN_VERSION={_js_json(tag)};"
            f"window.WORK_PATH={_js_json(str(project.root))};"
            f"window.WORK_OVERRIDES_PATH={_js_json(str(project.root / 'overrides.yaml'))};</script>"
            f"<script>{JS}</script></body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
