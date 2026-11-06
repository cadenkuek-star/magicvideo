import pytest

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
