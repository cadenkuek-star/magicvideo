import wave
from pathlib import Path

import numpy as np
import pytest
from helpers import policy

from magicvideo.render import audio as A
from magicvideo.render.renderer import Renderer

SR = 1000


def test_overshoot_times_merges_nearby_spots():
    x = np.zeros((1000, 2), np.float32)
    x[100, 0] = 1.2
    x[110, 1] = -1.5        # 10 ms later, larger (other channel)
    x[300, 0] = 1.1         # 200 ms later
    x[500, 0] = 0.5         # below threshold
    assert A.overshoot_times(x, SR, 1.0) == [0.11, 0.3]


def test_apply_dips_shape():
    sr, win_ms, dip = 10000, 40.0, 4.0
    x = np.ones((10000, 2), np.float32)
    A.apply_dips(x, sr, [0.5], dip, win_ms)
    c, half = 5000, 200
    assert abs(20 * np.log10(x[c, 0]) + dip) < 1e-3
    assert x[c - half, 0] == pytest.approx(1.0, abs=1e-6) and x[c + half, 1] == pytest.approx(1.0, abs=1e-6)
    assert np.all(x[:c - half] == 1.0) and np.all(x[c + half + 1:] == 1.0)
    assert 0.6 < x[c - half // 2, 0] < 1.0              # raised cosine, not a constant gain
    y = np.ones((10000, 2), np.float32)
    A.apply_dips(y, sr, [0.5, 0.505], dip, win_ms)       # overlapping: minimum, not product
    assert y[c, 0] == pytest.approx(10 ** (-dip / 20), abs=1e-6)
    assert y[c + 5, 1] == pytest.approx(10 ** (-dip / 20), abs=1e-6) or y[c + 5, 1] >= 10 ** (-dip / 20)
    assert y[c + 50, 0] == pytest.approx(10 ** (-dip / 20), abs=1e-6)
    z = np.ones((100, 2), np.float32)
    A.apply_dips(z, sr, [0.0, 0.0099], dip, win_ms)      # clipped to the array bounds
    assert z.shape == (100, 2)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    sr = 48000
    t = np.arange(sr * 2) / sr
    pcm = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    wav = tmp_path / "master_audio.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())
    r = object.__new__(Renderer)
    r.policy, r.work, r.log = policy(), tmp_path, {"loudness": {}}
    monkeypatch.setattr(Renderer, "_encode_master", lambda self, wav, mvid, out: Path(out).write_bytes(b"x"))
    calls = []
    real = A.apply_dips
    monkeypatch.setattr(A, "apply_dips", lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    return r, wav, tmp_path / "out.mp4", calls, monkeypatch


def _measure(monkeypatch, values):
    seq = iter(values)
    monkeypatch.setattr(A, "measure", lambda *a, **k: {"I": -16.0, "TP": next(seq), "LRA": 1.0, "thresh": -26.0})


def test_encode_verified_repairs_then_stops(rig):
    r, wav, out, calls, mp = rig
    _measure(mp, [2.9, -1.9])
    mp.setattr(A, "scan_true_peaks", lambda *a, **k: [1.0])
    log = r._encode_verified(wav, None, out)
    assert log["passes"] == 2 and log["note"] == "repaired" and log["dips"] == [1.0]
    assert log["tp_first"] == 2.9 and log["tp_final"] == -1.9 and len(calls) == 1
    assert out.exists() and not (rig[0].work / "master_try.mp4").exists()
    assert r.log["loudness"]["post_encode"] == log


def test_encode_verified_global_fallback(rig):
    r, wav, out, calls, mp = rig
    lim = float(r.policy("audio.true_peak_dbtp"))
    margin = float(r.policy("audio.post_encode_margin_db"))
    _measure(mp, [lim + 0.5 - margin, lim - 1.0])
    mp.setattr(A, "scan_true_peaks", lambda *a, **k: [])
    log = r._encode_verified(wav, None, out)
    assert log["global_db"] == pytest.approx(0.5) and log["note"] == "repaired" and calls == []


def test_encode_verified_gives_up(rig):
    r, wav, out, calls, mp = rig
    _measure(mp, [3.0] * 10)
    mp.setattr(A, "scan_true_peaks", lambda *a, **k: [1.0])
    log = r._encode_verified(wav, None, out)
    assert log["note"].startswith("gave up") and log["passes"] == 3 and out.exists()
    r2, wav2, out2, calls2, mp2 = rig
    _measure(mp2, [3.0] * 10)
    mp2.setattr(A, "scan_true_peaks", lambda *a, **k: [])
    log = r2._encode_verified(wav2, None, tmp := out2.with_name("o2.mp4"))
    assert log["note"].startswith("gave up") and log["passes"] == 1 and tmp.exists()


def test_encode_verified_check_off(rig):
    r, wav, out, calls, mp = rig
    r.policy = policy(audio={"post_encode_check": False})
    spy = []
    mp.setattr(A, "measure", lambda *a, **k: spy.append("measure"))
    mp.setattr(A, "scan_true_peaks", lambda *a, **k: spy.append("scan"))
    encodes = []
    mp.setattr(Renderer, "_encode_master", lambda self, w, m, o: (encodes.append(1), Path(o).write_bytes(b"x")))
    log = r._encode_verified(wav, None, out)
    assert encodes == [1] and spy == [] and out.exists()
    assert log["passes"] == 1 and log["note"] == "ok" and log["tp_first"] is None



def test_dip_wav_leaves_no_open_handle_and_matches_whole_file_dips(rig):
    """Region-wise dips equal dips on the whole signal, and the raw file is deleted (no lingering Windows lock)."""
    import subprocess
    from magicvideo import ffmpeg
    r, wav, out, calls, mp = rig
    with wave.open(str(wav), "rb") as w:
        expect = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2).astype(np.float32) / 32768
    times, dip, win = [0.5, 0.51, 1.5], 6.0, float(r.policy("audio.post_encode_dip_win_ms"))
    r._dip_wav(wav, 48000, times, dip)
    assert not wav.with_suffix(".f32").exists()
    assert len(calls) == 2                                   # 0.5 and 0.51 overlap -> one region; 1.5 another
    A.apply_dips(expect, 48000, times, dip, win)            # same dips on the whole signal at once
    got = np.frombuffer(subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-i", str(wav), "-f", "f32le", "-"],
                                       capture_output=True).stdout, "<f4").reshape(-1, 2)
    assert got.shape == expect.shape and np.max(np.abs(got - expect)) < 1e-6
