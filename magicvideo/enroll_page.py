"""`magicvideo enroll <work> --page`: tap A / B / Not us on candidate groups instead of deleting folders.

Standard library plus the shared local-server base. Candidate files are only read: nothing is deleted or moved.
The owner's choices live in `people/review_<trip>.json` (written atomically) so the page can be closed and reopened.
"""
from __future__ import annotations

import html
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from . import enroll
from .localserver import BaseHandler, make_loopback_server
from .project import Project, ProjectError
from .util import read_json, write_json

KINDS = {"face": ("person_", ".jpg"), "voice": ("voice_", ".wav")}
SLOTS = ("a", "b", "none")
MEDIA_SUFFIX = {"face": {".jpg"}, "voice": {".wav"}}
MAX_NAME = 40


def _review_dir(project: Project, kind: str) -> Path:
    return enroll._people_paths(project)[f"{kind}_review"]


def candidates(project: Project) -> dict[str, dict[str, list[str]]]:
    """{kind: {folder: [files]}} for review folders and files that also appear in that kind's manifest.json."""
    out: dict[str, dict[str, list[str]]] = {"face": {}, "voice": {}}
    for kind, (prefix, ext) in KINDS.items():
        review = _review_dir(project, kind)
        manifest = read_json(review / "manifest.json", {}) or {}
        if not review.is_dir():
            continue
        for d in sorted(p for p in review.iterdir() if p.is_dir() and p.name.startswith(prefix)):
            files = sorted(f.name for f in d.iterdir() if f.suffix.lower() == ext and f"{d.name}/{f.name}" in manifest)
            if files:
                out[kind][d.name] = files
    return out


class _State:
    def __init__(self, project: Project):
        self.project = project
        self.lock = threading.Lock()
        self.path = project.people_dir / f"review_{project.name}.json"

    def load(self) -> dict:
        cands = candidates(self.project)
        raw = read_json(self.path, {}) or {}
        assign = {k: {f: (raw.get("assign", {}).get(k, {}).get(f) if raw.get("assign", {}).get(k, {}).get(f) in SLOTS
                          else "none") for f in cands[k]} for k in KINDS}
        keys = {f"{k}/{fo}/{fi}" for k in KINDS for fo, files in cands[k].items() for fi in files}
        excluded = sorted(k for k in set(raw.get("excluded", [])) if k in keys)
        names = raw.get("names", {}) or {}
        return {"assign": assign, "excluded": excluded,
                "names": {"a": str(names.get("a", "")), "b": str(names.get("b", ""))}}

    def save(self, state: dict) -> None:
        write_json(self.path, state)          # temp file + os.replace

    def summary(self, state: dict, cands: dict) -> dict:
        pol = self.project.policy
        ex = set(state["excluded"])
        out = {}
        for slot in ("a", "b"):
            row = {"min_face": int(pol("enrollment.min_kept_per_partner.face")),
                   "min_voice": int(pol("enrollment.min_kept_per_partner.voice"))}
            for kind, gk, ik in (("face", "face_groups", "face_photos"), ("voice", "voice_groups", "voice_clips")):
                folders = [f for f, s in state["assign"][kind].items() if s == slot]
                row[gk] = len(folders)
                row[ik] = sum(1 for fo in folders for fi in cands[kind][fo] if f"{kind}/{fo}/{fi}" not in ex)
            out[slot] = row
        return out

    def payload(self, state: dict | None = None) -> dict:
        state = state or self.load()
        cands = candidates(self.project)
        return {"state": state, "candidates": cands, "summary": self.summary(state, cands)}


def _label(kind: str, fname: str) -> str:
    parts = Path(fname).stem.split("_", 2)
    return parts[2].replace("_", " ") if kind == "voice" and len(parts) > 2 else ""


CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--on:#2f5bd3;--ok:#1f7a4d;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--ink:#ececee;--muted:#9a9aa2;--line:#2c2c31;--on:#7ea2ff;--ok:#4cc38a;--bad:#ff7b72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;padding-bottom:110px}
header{padding:14px 16px;border-bottom:1px solid var(--line)}h1{font-size:19px;margin:0 0 6px}h2{font-size:16px;margin:22px 16px 8px}
.names{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}.names input{padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;padding:0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}.card h3{margin:0 0 8px;font-size:14px;color:var(--muted)}
.thumbs{display:flex;flex-wrap:wrap;gap:6px}.ph{position:relative;cursor:pointer;border-radius:6px;overflow:hidden}.ph img{width:84px;height:84px;object-fit:cover;display:block}
.ph.off img{opacity:.25;filter:grayscale(1)}.ph.off::after{content:"\\2715";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:28px;color:var(--bad)}
.clip{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0;font-size:13px}.clip.off{opacity:.4}.clip audio{height:32px;max-width:100%}
.clip button{font-size:12px;padding:2px 8px}
.pick{display:flex;gap:6px;margin-top:10px}.pick button{flex:1;padding:6px 0;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:6px;cursor:pointer;font-size:14px}
.pick button.on{background:var(--on);border-color:var(--on);color:#fff}
#bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px;z-index:3}
#bar .row{display:flex;gap:16px;flex-wrap:wrap;align-items:center}.s.ok{color:var(--ok)}.s.low{color:var(--bad)}
#finish{padding:8px 18px;background:var(--on);color:#fff;border:0;border-radius:6px;font-size:15px;cursor:pointer}
#report{margin-top:8px;white-space:pre-wrap;font-size:13px}
"""

JS = r"""
(function(){
var S=null,C=null,SUM=null;
function api(path,body){return fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined}).then(function(r){return r.json();});}
function nm(slot){var n=(S&&S.names[slot])||'';return n||slot.toUpperCase();}
function apply(p){S=p.state;C=p.candidates;SUM=p.summary;paint();}
function paint(){
document.querySelectorAll('.card[data-kind]').forEach(function(c){var cur=S.assign[c.dataset.kind][c.dataset.folder]||'none';
c.querySelectorAll('.pick button').forEach(function(b){b.classList.toggle('on',b.dataset.slot===cur);
if(b.dataset.slot==='a'||b.dataset.slot==='b')b.textContent=nm(b.dataset.slot);});});
var ex={};S.excluded.forEach(function(k){ex[k]=1;});
document.querySelectorAll('[data-file]').forEach(function(e){var off=!!ex[e.dataset.key];e.classList.toggle('off',off);
var t=e.querySelector('button');if(t)t.textContent=off?'use it':'leave out';});
var html=['a','b'].map(function(s){var r=SUM[s];
var fOk=r.face_groups>0&&r.face_photos>=r.min_face,vOk=r.voice_groups>0&&r.voice_clips>=r.min_voice;
return '<span class="s '+((fOk&&vOk)?'ok':'low')+'"><b>'+nm(s)+'</b>: '+r.face_groups+' face group'+(r.face_groups==1?'':'s')+', '+r.face_photos+
' photo'+(r.face_photos==1?'':'s')+(fOk?'':' (needs '+r.min_face+')')+' · '+r.voice_groups+' voice group'+(r.voice_groups==1?'':'s')+', '+
r.voice_clips+' clip'+(r.voice_clips==1?'':'s')+(vOk?' ✓':' (needs '+r.min_voice+')')+'</span>';}).join(' | ');
document.getElementById('summary').innerHTML=html;
document.getElementById('na').value=document.getElementById('na').value||S.names.a;}
document.addEventListener('click',function(e){
var b=e.target.closest('.pick button');
if(b){var c=b.closest('.card');api('/api/assign',{kind:c.dataset.kind,folder:c.dataset.folder,slot:b.dataset.slot}).then(apply);return;}
var x=e.target.closest('[data-file]');
if(x&&(x.classList.contains('ph')||e.target.tagName==='BUTTON')){var off=!x.classList.contains('off');
api('/api/exclude',{kind:x.dataset.kind,folder:x.dataset.folder,file:x.dataset.file,excluded:off}).then(apply);}});
['na','nb'].forEach(function(id){document.getElementById(id).addEventListener('change',function(){
api('/api/names',{a:document.getElementById('na').value,b:document.getElementById('nb').value}).then(apply);});});
document.getElementById('finish').onclick=function(){var btn=this;btn.disabled=true;
api('/api/finalize',{allow_sparse:document.getElementById('sparse').checked}).then(function(r){btn.disabled=false;
var lines=[];Object.keys(r.report||{}).forEach(function(k){var v=r.report[k];(Array.isArray(v)?v:[v]).forEach(function(l){lines.push(k+': '+l);});});
if(r.next)lines.push('next: '+r.next);if(!r.ok)lines.push(r.error||'failed');
document.getElementById('report').textContent=lines.join('\n');}).catch(function(){btn.disabled=false;});};
window.addEventListener('DOMContentLoaded',function(){api('/api/state').then(apply);});
})();
"""


def render_page(project: Project, payload: dict) -> str:
    cands, state = payload["candidates"], payload["state"]
    ex = set(state["excluded"])

    def card(kind: str, folder: str, files: list[str]) -> str:
        body = []
        for fi in files:
            key = f"{kind}/{folder}/{fi}"
            url = f"/media/{kind}/{quote(folder)}/{quote(fi)}"
            attrs = (f"data-file=\"{html.escape(fi)}\" data-kind=\"{kind}\" data-folder=\"{html.escape(folder)}\" "
                     f"data-key=\"{html.escape(key)}\"")
            off = " off" if key in ex else ""
            if kind == "face":
                body.append(f"<div class=\"ph{off}\" {attrs}><img loading=lazy src=\"{url}\" alt=\"\"></div>")
            else:
                body.append(f"<div class=\"clip{off}\" {attrs}><audio controls preload=none src=\"{url}\"></audio>"
                            f"<span>{html.escape(_label(kind, fi))}</span><button type=button>leave out</button></div>")
        cur = state["assign"][kind].get(folder, "none")
        pick = "".join(f"<button type=button data-slot=\"{s}\" class=\"{'on' if s == cur else ''}\">{lab}</button>"
                       for s, lab in (("a", "A"), ("b", "B"), ("none", "Not us")))
        wrap = "thumbs" if kind == "face" else "clips"
        return (f"<div class=card data-kind=\"{kind}\" data-folder=\"{html.escape(folder)}\"><h3>{html.escape(folder)}</h3>"
                f"<div class={wrap}>{''.join(body)}</div><div class=pick>{pick}</div></div>")

    faces = "".join(card("face", f, fs) for f, fs in cands["face"].items())
    voices = "".join(card("voice", f, fs) for f, fs in cands["voice"].items())
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(project.name)} enrollment</title><style>{CSS}</style></head><body>"
        "<header><h1>Who are the two of you?</h1>"
        "<div>Tap A or B on each group that is one of you, and Not us on the others. Tap a photo or clip to leave "
        "it out if it's someone else. Then press Finish.</div>"
        "<div class=names><input id=na placeholder='Partner A name' maxlength=40>"
        f"<input id=nb placeholder='Partner B name' maxlength=40 value=\"{html.escape(state['names']['b'])}\"></div>"
        f"</header><h2>Faces</h2><div class=grid>{faces}</div><h2>Voices</h2><div class=grid>{voices}</div>"
        "<div id=bar><div class=row><span id=summary></span>"
        "<label><input type=checkbox id=sparse> Accept fewer clips than usual</label>"
        "<button id=finish type=button>Finish</button></div><div id=report></div></div>"
        f"<script>{JS}</script></body></html>")


def _handler(project: Project, st: _State):
    class Handler(BaseHandler):
        server_version = "magicvideo-enroll"

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._error(403, "forbidden host")
            path = urlsplit(self.path).path
            if path == "/":
                page = render_page(project, st.payload()).encode("utf-8")
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/api/state":
                return self._json(200, st.payload())
            if path.startswith("/media/"):
                parts = unquote(path[len("/media/"):]).split("/", 1)
                if len(parts) == 2 and parts[0] in KINDS:
                    return self.serve_file(_review_dir(project, parts[0]), parts[1], MEDIA_SUFFIX[parts[0]])
            return self._error(404, "not found")

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._error(403, "forbidden host")
            body = self._read_json_body()
            if body is None:
                return
            path = urlsplit(self.path).path
            try:
                with st.lock:
                    if path == "/api/assign":
                        return self._assign(body)
                    if path == "/api/exclude":
                        return self._exclude(body)
                    if path == "/api/names":
                        return self._names(body)
                    if path == "/api/finalize":
                        return self._finalize(body)
            except ProjectError as e:
                return self._error(400, str(e))
            return self._error(404, "not found")

        def _done(self, state: dict) -> None:
            st.save(state)
            self._json(200, {"ok": True, **st.payload(state)})

        def _assign(self, body: dict) -> None:
            kind, folder, slot = body.get("kind"), body.get("folder"), body.get("slot")
            state = st.load()
            if kind not in KINDS or slot not in SLOTS or folder not in state["assign"].get(kind, {}):
                return self._error(400, "unknown kind, folder or slot")
            state["assign"][kind][folder] = slot
            self._done(state)

        def _exclude(self, body: dict) -> None:
            kind, folder, fname, flag = body.get("kind"), body.get("folder"), body.get("file"), body.get("excluded")
            cands = candidates(project)
            if kind not in KINDS or fname not in cands[kind].get(folder, []) or not isinstance(flag, bool):
                return self._error(400, "unknown kind, folder or file")
            state = st.load()
            key = f"{kind}/{folder}/{fname}"
            ex = set(state["excluded"])
            ex.add(key) if flag else ex.discard(key)
            state["excluded"] = sorted(ex)
            self._done(state)

        def _names(self, body: dict) -> None:
            vals = [body.get("a"), body.get("b")]
            if not all(isinstance(v, str) and len(v.strip()) <= MAX_NAME for v in vals):
                return self._error(400, f"names must be text of at most {MAX_NAME} characters")
            state = st.load()
            state["names"] = {"a": vals[0].strip(), "b": vals[1].strip()}
            self._done(state)

        def _finalize(self, body: dict) -> None:
            state = st.load()
            cands = candidates(project)
            assignment = {k: {s: sorted(f for f, v in state["assign"][k].items() if v == s) for s in ("a", "b")}
                          for k in KINDS if cands[k]}
            report = enroll.finalize(project, allow_sparse=bool(body.get("allow_sparse")), assignment=assignment,
                                     excluded=set(state["excluded"]),
                                     names=state["names"] if any(state["names"].values()) else None)
            self._json(200, {"ok": True, "report": report, "next": f'magicvideo plan "{project.root}"'})

    return Handler


def make_server(project: Project, port: int | None = None) -> ThreadingHTTPServer:
    """Enrollment page server bound to 127.0.0.1 only (port 0 picks a free port)."""
    if not any(candidates(project).values()):
        raise ProjectError(f'no candidates yet: run magicvideo enroll "{project.root}" first')
    if port is None:
        port = int(project.policy("enrollment.page_port"))
    return make_loopback_server(_handler(project, _State(project)), port)


def serve(project: Project, port: int | None = None, open_browser: bool = True) -> None:
    server = make_server(project, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"enrollment page: {url}   (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
