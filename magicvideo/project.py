"""Trip work-directory layout (docs/IMPLEMENTATION_BRIEF.md §4)."""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from .policy import DEFAULT_POLICY_PATH, Policy
from .util import read_json, safe_name, write_json

OVERRIDES_TEMPLATE = """\
# Review decisions. IDs come from plan/storyboard_vNNN.html.
# moments:   {<moment_id>: drop | keep | couple | {extend_start_s: 1.0, extend_end_s: 2.0}}
#            couple = this is us: count as couple time
# events:    {<event_id>: {coverage_budget_s: 60}}
# clips:     {<clip_id>: {exclude: true, rotate: 90}}
moments: {}
events: {}
clips: {}
"""

DEVICES_TEMPLATE = """\
# Optional per-camera clock corrections, matched on camera make/model from inventory.json.
# offset_s is added to every capture time from that camera.
# devices:
#   - {make: DJI, model: null, offset_s: 0}
devices: []
"""


class ProjectError(RuntimeError):
    pass


class Project:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        cfg_path = self.root / "project.yaml"
        if not cfg_path.exists():
            raise ProjectError(f"{self.root} is not a magicvideo trip folder (run `magicvideo init` first)")
        self.config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        self._policy: Policy | None = None

    # ---- creation -------------------------------------------------------
    @classmethod
    def init(cls, root: Path, sources: list[Path], name: str | None = None,
             people: Path | None = None) -> "Project":
        root = Path(root).resolve()
        srcs = [Path(s).resolve() for s in sources]
        for s in srcs:
            if not s.is_dir():
                raise ProjectError(f"source folder not found: {s}")
            if root == s or s in root.parents or root in s.parents:
                raise ProjectError(f"work folder {root} must be outside source folder {s}")
            if s.parent == s:
                raise ProjectError(f"refusing to use a drive root as source: {s}")
        if root.parent == root:
            raise ProjectError("refusing to use a drive root as work folder")
        root.mkdir(parents=True, exist_ok=True)
        people_dir = Path(people).resolve() if people else root.parent / "people"
        cfg = {
            "name": safe_name(name or srcs[0].name),
            "source_dirs": [str(s) for s in srcs],
            "people_dir": str(people_dir),
        }
        (root / "project.yaml").write_text(yaml.safe_dump(cfg, sort_keys=True, allow_unicode=True), encoding="utf-8")
        if not (root / "policy.yaml").exists():
            shutil.copyfile(DEFAULT_POLICY_PATH, root / "policy.yaml")
        if not (root / "overrides.yaml").exists():
            (root / "overrides.yaml").write_text(OVERRIDES_TEMPLATE, encoding="utf-8")
        if not (root / "devices.yaml").exists():
            (root / "devices.yaml").write_text(DEVICES_TEMPLATE, encoding="utf-8")
        for sub in ("analysis", "plan", "render", "output", "qc"):
            (root / sub).mkdir(exist_ok=True)
        people_dir.mkdir(parents=True, exist_ok=True)
        return cls(root)

    # ---- properties -----------------------------------------------------
    @property
    def name(self) -> str:
        return self.config.get("name", self.root.name)

    @property
    def source_dirs(self) -> list[Path]:
        return [Path(p) for p in self.config.get("source_dirs", [])]

    @property
    def people_dir(self) -> Path:
        return Path(self.config.get("people_dir", self.root.parent / "people"))

    @property
    def policy(self) -> Policy:
        if self._policy is None:
            self._policy = Policy.load(self.root / "policy.yaml")
        return self._policy

    @property
    def inventory_path(self) -> Path:
        return self.root / "inventory.json"

    def analysis_dir(self, clip_id: str) -> Path:
        d = self.root / "analysis" / clip_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def plan_dir(self) -> Path:
        return self.root / "plan"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def qc_dir(self) -> Path:
        return self.root / "qc"

    def render_dir(self, version: str) -> Path:
        return self.root / "render" / version

    # ---- data -----------------------------------------------------------
    def inventory(self) -> list[dict]:
        inv = read_json(self.inventory_path)
        if inv is None:
            raise ProjectError("inventory.json missing: run `magicvideo analyze` first")
        return inv["clips"]

    def save_inventory(self, clips: list[dict]) -> None:
        write_json(self.inventory_path, {"version": 1, "clips": clips})

    def overrides(self) -> dict:
        p = self.root / "overrides.yaml"
        data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None
        data = data or {}
        for k in ("moments", "events", "clips"):
            data.setdefault(k, {})
            if data[k] is None:
                data[k] = {}
        return data

    def devices(self) -> list[dict]:
        p = self.root / "devices.yaml"
        data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None
        return (data or {}).get("devices") or []

    # ---- analysis step status --------------------------------------------
    def step_status(self, clip_id: str) -> dict:
        return read_json(self.analysis_dir(clip_id) / "status.json", {}) or {}

    def set_step_status(self, clip_id: str, step: str, status: str) -> None:
        st = self.step_status(clip_id)
        st[step] = status
        write_json(self.analysis_dir(clip_id) / "status.json", st)
