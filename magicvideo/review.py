"""`magicvideo review`: a local page where clicking keep / drop / "this is us" saves to overrides.yaml.

Standard library only. The server listens on 127.0.0.1 and refuses any request whose Host header is not
127.0.0.1:<port> or localhost:<port> (DNS-rebinding guard).
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from .localserver import BaseHandler, make_loopback_server
from .plan.planner import run_plan, stale_refs, warn_if_stale
from .project import Project, ProjectError
from .util import latest_version, read_json, version_of, vtag

VALUES = ("keep", "drop", "couple", "clear")
THUMB_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _latest_tag(project: Project) -> str:
    v = latest_version(project.plan_dir.glob("plan_v*.json")) if project.plan_dir.exists() else None
    if v is None:
        raise ProjectError("no plan yet: run `magicvideo plan` first")
    return vtag(v)


class _State:
    """Per-server state: the pinned plan version (None = latest) and the once-per-session backup flag."""

    def __init__(self, project: Project, version: str | None):
        self.project = project
        self.version = version
        self.backed_up = False
        self.lock = threading.Lock()

    @property
    def tag(self) -> str:
        return self.version or _latest_tag(self.project)

    @property
    def overrides_path(self) -> Path:
        return self.project.root / "overrides.yaml"

    def read_overrides(self) -> dict:
        p = self.overrides_path
        data = yaml.safe_load(p.read_text(encoding="utf-8-sig")) if p.exists() else None
        return data if isinstance(data, dict) else {}

    def write_overrides(self, data: dict) -> None:
        p = self.overrides_path
        if not self.backed_up and p.exists():
            shutil.copyfile(p, p.with_name(p.name + ".bak"))
            self.backed_up = True
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=True, allow_unicode=True), encoding="utf-8")
        os.replace(tmp, p)

    def moment_ids(self) -> set[str]:
        plan = read_json(self.project.plan_dir / f"plan_{self.tag}.json") or {}
        return {m["id"] for m in plan.get("moments", [])}


def _handler(state: _State):
    class Handler(BaseHandler):
        server_version = "magicvideo-review"

        # ---- GET
        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._error(403, "forbidden host")
            path = urlsplit(self.path).path
            try:
                if path == "/":
                    page = state.project.plan_dir / f"storyboard_{state.tag}.html"
                    if not page.is_file():
                        return self._error(404, "storyboard page missing")
                    return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
                if path.startswith("/thumbs/"):
                    return self._thumb(unquote(path[len("/thumbs/"):]))
                if path == "/api/overrides":
                    plan = read_json(state.project.plan_dir / f"plan_{state.tag}.json") or {}
                    return self._json(200, {"overrides": state.read_overrides(), "version": state.tag,
                                            "stale_refs": stale_refs(state.project, plan)})
            except ProjectError as e:
                return self._error(404, str(e))
            return self._error(404, "not found")

        def _thumb(self, name: str) -> None:
            self.serve_file(state.project.plan_dir / "thumbs", name, THUMB_SUFFIXES)

        # ---- POST
        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok():
                return self._error(403, "forbidden host")
            path = urlsplit(self.path).path
            body = self._read_json_body()
            if body is None:
                return
            try:
                if path == "/api/moment":
                    return self._moment(body)
                if path == "/api/replan":
                    return self._replan()
            except ProjectError as e:
                return self._error(400, str(e))
            return self._error(404, "not found")

        def _moment(self, body: dict) -> None:
            mid, value = body.get("id"), body.get("value")
            if not isinstance(mid, str) or value not in VALUES:
                return self._error(400, f"value must be one of {', '.join(VALUES)}")
            if mid not in state.moment_ids():
                return self._error(400, "unknown moment id")
            with state.lock:
                data = state.read_overrides()
                moments = data.get("moments")
                moments = dict(moments) if isinstance(moments, dict) else {}
                if value == "clear":
                    moments.pop(mid, None)
                else:
                    moments[mid] = value
                data["moments"] = moments
                state.write_overrides(data)
            self._json(200, {"ok": True, "overrides": data})

        def _replan(self) -> None:
            with state.lock:
                paths = run_plan(state.project, thumbs=True)
            tag = vtag(version_of(paths["plan"]) or 1)
            if state.version is not None:
                state.version = tag
            self._json(200, {"version": tag})

    return Handler


def make_server(project: Project, version: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    """A review server bound to 127.0.0.1 only. port=None uses policy review.port; 0 picks a free port."""
    if port is None:
        port = int(project.policy("review.port"))
    if version is None:
        _latest_tag(project)  # fail early when there is no plan
    return make_loopback_server(_handler(_State(project, version)), port)


def serve(project: Project, version: str | None = None, port: int | None = None, open_browser: bool = True) -> None:
    server = make_server(project, version, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    warn_if_stale(project, version or _latest_tag(project))
    print(f"review page: {url}   (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
