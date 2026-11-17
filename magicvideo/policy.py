"""Policy loading. Every threshold used by the pipeline is read through Policy."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_POLICY_PATH = Path(__file__).with_name("default_policy.yaml")


class PolicyError(KeyError):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_default_dict() -> dict:
    return yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))


class Policy:
    """Dotted-path access to policy values; missing keys are an error (no silent defaults)."""

    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def load(cls, path: Path | None = None, overrides: dict | None = None) -> "Policy":
        data = load_default_dict()
        if path is not None and Path(path).exists():
            user = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            data = _deep_merge(data, user)
        if overrides:
            data = _deep_merge(data, overrides)
        return cls(data)

    def get(self, dotted: str) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                raise PolicyError(f"policy key missing: {dotted}")
            node = node[part]
        return node

    def __call__(self, dotted: str) -> Any:
        return self.get(dotted)

    def with_overrides(self, overrides: dict) -> "Policy":
        return Policy(_deep_merge(self.data, overrides))
