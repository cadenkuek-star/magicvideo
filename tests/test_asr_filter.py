import numpy as np
from helpers import policy

from magicvideo.plan.data import drop_hallucinations


def _words(spec):
    return [{"t0": a, "t1": b, "w": w, "p": 0.9} for a, b, w in spec]


def _run(words, segs, windows=None, emb=None, **over):
    windows = windows if windows is not None else [{"t0": w["t0"], "t1": w["t1"], "w0": i, "w1": i + 1}
                                                   for i, w in enumerate(words)]
    emb = emb if emb is not None else np.eye(len(windows), 4, dtype=np.float32)
    return drop_hallucinations(words, segs, windows, emb, policy(**over))


def test_known_phrase_segment_dropped():
    words = _words([(1.0, 1.5, "Thank"), (1.5, 2.0, "you"), (5.0, 5.5, "hello")])
    segs = [{"t0": 1.0, "t1": 2.0, "text": " Thank you, for Watching! "}, {"t0": 5.0, "t1": 5.6, "text": "hello"}]
    w, win, emb, dropped = _run(words, segs)
    assert [x["w"] for x in w] == ["hello"] and len(win) == 1 and emb.shape[0] == 1
    assert dropped == [{"t0": 1.0, "t1": 2.0, "text": "Thank you, for Watching!"}]
    jp = _words([(1.8, 4.9, "ご視聴ありがとうございました")])
    w, *_rest, dropped = _run(jp, [{"t0": 1.8, "t1": 4.9, "text": "ご視聴ありがとうございました。"}])
    assert w == [] and len(dropped) == 1


def test_score_rule_needs_both_scores():
    words = _words([(1.0, 2.0, "blah")])
    base = {"t0": 1.0, "t1": 2.0, "text": "something else"}
    kept = lambda seg: len(_run(words, [seg])[0])  # noqa: E731
    assert kept({**base, "no_speech_prob": 0.9, "avg_logprob": -2.0}) == 0
    assert kept({**base, "no_speech_prob": 0.9, "avg_logprob": -0.2}) == 1
    assert kept({**base, "no_speech_prob": 0.1, "avg_logprob": -2.0}) == 1
    assert kept({**base, "no_speech_prob": 0.9}) == 1
    assert kept(base) == 1


def test_real_speech_kept_even_with_low_word_probability():
    words = [{"t0": 1.0, "t1": 2.0, "w": "mmm", "p": 0.04}]
    w, *_ = _run(words, [{"t0": 1.0, "t1": 2.0, "text": "mmm"}])
    assert len(w) == 1


def test_windows_and_embeddings_remapped():
    words = _words([(1.0, 1.4, "a"), (5.0, 5.4, "thanksforwatching"), (9.0, 9.4, "c")])
    segs = [{"t0": 1.0, "t1": 1.5, "text": "a"}, {"t0": 5.0, "t1": 5.5, "text": "thanks for watching"},
            {"t0": 9.0, "t1": 9.5, "text": "c"}]
    emb = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]], np.float32)
    w, win, e, dropped = _run(words, segs, emb=emb)
    assert [x["w"] for x in w] == ["a", "c"]
    assert [(x["t0"], x["w0"], x["w1"]) for x in win] == [(1.0, 0, 1), (9.0, 1, 2)]
    assert e.tolist() == [[1, 0, 0, 0], [0, 0, 1, 0]] and len(dropped) == 1


def test_filter_disabled_changes_nothing():
    words = _words([(1.0, 2.0, "thanks")])
    segs = [{"t0": 1.0, "t1": 2.0, "text": "thanks for watching"}]
    w, win, e, dropped = _run(words, segs, asr_filter={"enabled": False})
    assert len(w) == 1 and len(win) == 1 and e.shape[0] == 1 and dropped == []
