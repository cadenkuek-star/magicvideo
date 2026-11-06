import pytest

from helpers import policy

from magicvideo.qc.runner import rendered_speech_check, speech_tokens


def test_cjk_words_split_into_characters():
    assert speech_tokens(["很多年", "Akita是"], False) == ["很", "多", "年", "akita", "是"]


def test_latin_words_stay_whole():
    assert speech_tokens(["Hello", "world's"], False) == ["hello", "world's"]


def test_scripts_fold_together():
    pytest.importorskip("zhconv")
    res = rendered_speech_check([("說來", 1.0)], ["说来"], True, 3)
    assert res["ratio"] == 1.0 and res["folded"] is True


def test_regrouped_words_still_match():
    res = rendered_speech_check([("很多年", 1.0)], ["很多", "年"], False, 3)
    assert res["ratio"] == 1.0


def test_missing_runs_reported_with_master_times():
    planned = [(w, 10.0 + i) for i, w in enumerate(["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"])]
    heard = ["alpha", "echo", "foxtrot"]
    res = rendered_speech_check(planned, heard, False, 3)
    assert res["missing_runs"] == [{"t0": 11.0, "t1": 13.0, "text": "bravo charlie delta"}]
    assert res["matched"] == 3 and res["total"] == 6
    assert rendered_speech_check(planned, heard, False, 4)["missing_runs"] == []


def test_planned_words_follow_film_order():
    from helpers import clip, clipdata

    from magicvideo.qc.runner import collect_planned_words

    p = policy()
    ca = clipdata(clip(cid="c_a"), [(1.0, 1.5, "alpha")], speakers=["PARTNER_A"])
    cb = clipdata(clip(cid="c_b"), [(1.0, 1.5, "bravo")], speakers=["PARTNER_A"])
    convs = [{"id": "ma", "clip_id": "c_a", "kind": "conversation", "selected": True, "abs_t0": 100.0,
              "t0": 0.5, "t1": 3.0},
             {"id": "mb", "clip_id": "c_b", "kind": "conversation", "selected": True, "abs_t0": 200.0,
              "t0": 0.5, "t1": 3.0}]
    timeline = {"segments": [{"clip_id": "c_b", "src_in": 0.0, "frames": 90, "start_frame": 0},
                             {"clip_id": "c_a", "src_in": 0.0, "frames": 90, "start_frame": 90}]}
    seg_spans = {"c_a": [(0.0, 3.0)], "c_b": [(0.0, 3.0)]}
    total, kept, planned = collect_planned_words(convs, {"c_a": ca, "c_b": cb}, seg_spans, timeline, 30.0, p)
    assert (total, kept) == (2, 2)
    assert [w for w, _ in planned] == ["bravo", "alpha"]


def _seg(cid, start, frames=30):
    return {"clip_id": cid, "start_frame": start, "frames": frames}


def test_language_spans_merge_same_language():
    from magicvideo.qc.runner import language_spans

    spans = language_spans([_seg("a", 0), _seg("b", 60)], {"a": "zh", "b": "zh"}, 30.0, 2.0)
    assert spans == [{"t0": 0.0, "t1": 3.0, "lang": "zh"}]


def test_language_spans_split_on_language_change():
    from magicvideo.qc.runner import language_spans

    spans = language_spans([_seg("a", 0), _seg("b", 30), _seg("c", 60)], {"a": "en", "b": "zh", "c": "zh"},
                           30.0, 2.0)
    assert spans == [{"t0": 0.0, "t1": 1.0, "lang": "en"}, {"t0": 1.0, "t1": 3.0, "lang": "zh"}]


def test_transcribe_passes_language(monkeypatch):
    from magicvideo.analysis import asr

    seen = {}

    class Stub:
        def transcribe(self, path, **kw):
            seen.update(kw)
            return iter([]), type("I", (), {"language": "en"})()

    monkeypatch.setattr(asr, "load_model", lambda policy: Stub())
    asr.transcribe("x.wav", policy(), language="en")
    assert seen["language"] == "en"


def test_analysis_passes_policy_language():
    from magicvideo.analysis import runner

    assert runner._asr_language(policy()) is None
    assert runner._asr_language(policy(compute={"asr_language": "yue"})) == "yue"
