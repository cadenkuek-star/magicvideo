import numpy as np
import pytest
from helpers import policy

from magicvideo import ffmpeg
from magicvideo.qc.runner import signal_word_presence, word_present

SR = 16000


def _noise(n=8000, seed=1):
    return np.random.default_rng(seed).normal(size=n).astype(np.float32) * 0.2


def _pad(x, k=1000):
    return np.concatenate([np.zeros(k, np.float32), x, np.zeros(k, np.float32)])


def test_word_present_with_gain_and_small_lag():
    s = _noise()
    m = np.concatenate([np.zeros(160, np.float32), s])[: len(s)] * 0.5       # 10 ms later, half level
    ok, corr, lvl = word_present(m, s, SR, 0.05, 0.6, -12.0, -6.02)
    assert ok and corr > 0.9 and abs(lvl) < 0.1


def test_word_absent_when_master_silent():
    s = _noise()
    ok, corr, _ = word_present(np.zeros_like(s), s, SR, 0.05, 0.6, -12.0, 0.0)
    assert not ok and corr == 0.0


def test_word_absent_when_shifted_far():
    s = _noise(16000)
    m = np.concatenate([np.zeros(4800, np.float32), s])[: len(s)]            # 300 ms
    assert not word_present(m, s, SR, 0.05, 0.6, -12.0, 0.0)[0]


def test_word_absent_below_level_floor():
    s = _noise()
    ok, corr, lvl = word_present(s * 0.1, s, SR, 0.05, 0.6, -12.0, 0.0)
    assert corr > 0.9 and lvl < -12 and not ok


def _files(tmp_path, silent_master):
    rng = np.random.default_rng(3)
    x = np.zeros(3 * SR, np.float32)
    for a, b in ((0.5, 0.8), (1.5, 1.9)):
        x[int(a * SR):int(b * SR)] = rng.normal(size=int((b - a) * SR)) * 0.3
    raw = tmp_path / "src.f32"
    raw.write_bytes(x.tobytes())
    src = tmp_path / "src.wav"
    ffmpeg.run(["-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(raw), str(src)])
    master = tmp_path / "master.mp4"
    afilter = "adelay=1000,volume=0" if silent_master else "adelay=1000"
    ffmpeg.run(["-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x64:r=10:d=4", "-i", str(src),
                "-af", afilter, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-t", "4", str(master)])
    words = [{"w": "a", "clip_id": "c1", "src_t0": 0.5, "src_t1": 0.8, "m_t0": 1.5, "m_t1": 1.8, "seg_id": "s1"},
             {"w": "b", "clip_id": "c1", "src_t0": 1.5, "src_t1": 1.9, "m_t0": 2.5, "m_t1": 2.9, "seg_id": "s1"}]
    return master, words, {"c1": {"render_path": str(src)}}


def test_signal_presence_on_real_files(tmp_path):
    master, words, inv = _files(tmp_path, False)
    res = signal_word_presence(master, words, inv, {}, policy())
    assert res["ratio"] == 1.0 and res["present"] == 2 and res["total"] == 2 and res["absent_runs"] == []


def test_signal_presence_detects_muted_master(tmp_path):
    master, words, inv = _files(tmp_path, True)
    res = signal_word_presence(master, words, inv, {}, policy(qc={"speech_missing_run_min": 2}))
    assert res["ratio"] == 0.0 and len(res["absent_runs"]) == 1
    assert res["absent_runs"][0]["t0"] == 1.5 and res["absent_runs"][0]["t1"] == 2.5
