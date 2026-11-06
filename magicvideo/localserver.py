"""Shared plumbing for magicvideo's local web pages (review, enrollment): loopback only, Host-checked.

Every handler built on BaseHandler refuses a Host header other than 127.0.0.1:<port> / localhost:<port>
(DNS-rebinding guard) when it calls `_host_ok()`, answers JSON errors, and serves files confined to a folder.
"""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 1 << 20


class BaseHandler(BaseHTTPRequestHandler):
    server_version = "magicvideo-local"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, sort_keys=True).encode("utf-8"), "application/json")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _read_json_body(self) -> dict | None:
        """The JSON object body, or None after answering 415 (wrong Content-Type) / 400 (bad or oversized body)."""
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self._error(415, "Content-Type must be application/json")
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_BODY:
                raise ValueError
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            self._error(400, "bad JSON body")
            return None
        return body

    def serve_file(self, base: Path, rel: str, allowed_suffixes: set[str]) -> None:
        """Send base/rel when it resolves inside base, is a file and has an allowed suffix; otherwise 404."""
        try:
            base = Path(base).resolve()
            target = (base / rel).resolve()
            ok = target.is_relative_to(base) and target.is_file() and target.suffix.lower() in allowed_suffixes
        except (OSError, ValueError):
            ok = False
        if not ok:
            return self._error(404, "not found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype)


def make_loopback_server(handler_cls, port: int) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1 only (port 0 picks a free port)."""
    return ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
