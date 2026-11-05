"""Cloud tagger request/response handling with a stub client (no network, no cost)."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from helpers import policy

anthropic = pytest.importorskip("anthropic")

from magicvideo.analysis import tags as T  # noqa: E402


class StubMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return self.response


def _tagger(response):
    t = object.__new__(T.Tagger)
    t.anthropic = anthropic
    t.client = SimpleNamespace(beta=SimpleNamespace(messages=StubMessages(response)))
    t.model, t.effort, t.policy = T.DEFAULT_MODEL, "low", policy()
    return t


def _frames(n):
    return [np.full((90, 160, 3), 40 * i % 255, np.uint8) for i in range(n)]


def test_request_shape_and_parsing():
    cells = {"cells": [
        {"cell": 1, "tags": ["food", "not-a-tag"], "people": "partners", "interest": 1.7, "desc": "noodles"},
        {"cell": 2, "tags": ["train"], "people": "weird", "interest": 0.3, "desc": "window"},
    ]}
    resp = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(cells))])
    t = _tagger(resp)
    out = t.tag_grid(_frames(3))
    call = t.client.beta.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert out[0] == {"tags": ["food"], "people": "partners", "interest": 1.0, "desc": "noodles"}
    assert out[1]["people"] == "none" and out[2] is None  # unknown values sanitised; missing cell -> None


def test_refusal_leaves_frames_untagged():
    resp = SimpleNamespace(stop_reason="refusal", content=[])
    assert _tagger(resp).tag_grid(_frames(2)) is None


def test_event_type_majority():
    assert T.event_type([["food", "table"], ["train"]]) == "meal"
    assert T.event_type([["car"], ["road"], ["food"]]) == "transit"
    assert T.event_type([[]]) == "general"
