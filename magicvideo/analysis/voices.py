"""Voice windows, speaker embeddings (speechbrain ECAPA, optional) and partner labelling."""
from __future__ import annotations

import os
import wave
from pathlib import Path

import numpy as np

from .. import ffmpeg
from ..policy import Policy
from .asr import BackendMissing

PARTNER_A, PARTNER_B, OTHER, UNKNOWN = "PARTNER_A", "PARTNER_B", "OTHER", "UNKNOWN"


def build_windows(words: list[dict], gap: float, max_len: float) -> list[dict]:
    """Group consecutive words into voice windows: split on gap > `gap` or length > `max_len`."""
    windows: list[dict] = []
    cur = None
    for i, w in enumerate(words):
        if cur is not None and (w["t0"] - words[i - 1]["t1"] > gap or w["t1"] - cur["t0"] > max_len):
            windows.append(cur)
            cur = None
        if cur is None:
            cur = {"t0": w["t0"], "t1": w["t1"], "w0": i, "w1": i + 1}
        else:
            cur["t1"] = w["t1"]
            cur["w1"] = i + 1
    if cur is not None:
        windows.append(cur)
    return windows


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        ch = wf.getnchannels()
        data = np.frombuffer(wf.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


_ENCODER = None


def _encoder(policy: Policy):
    global _ENCODER
    if _ENCODER is not None:
        return _ENCODER
    import importlib.util
    if importlib.util.find_spec("torch") is None:
        raise BackendMissing("torch not installed (pip install 'magicvideo[voice]')")
    try:
        try:
            from speechbrain.inference.speaker import EncoderClassifier  # type: ignore
        except ImportError:
            from speechbrain.pretrained import EncoderClassifier  # type: ignore
    except ImportError as e:
        raise BackendMissing("speechbrain/torch not installed (pip install 'magicvideo[voice]')") from e
    dev = policy("compute.device")
    if dev == "auto":
        dev = "cuda" if ffmpeg.gpu_available() else "cpu"
    kwargs = {"savedir": str(Path.home() / ".cache" / "magicvideo" / "spkrec-ecapa-voxceleb")}
    if os.name == "nt":
        # speechbrain links model files with symlinks by default; Windows refuses them without
        # Developer Mode ("symbolic link privilege not held"), so copy instead.
        try:
            from speechbrain.utils.fetching import LocalStrategy  # type: ignore
            kwargs["local_strategy"] = LocalStrategy.COPY
        except ImportError:
            pass
    _ENCODER = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                              run_opts={"device": dev}, **kwargs)
    return _ENCODER


def embed_windows(audio16k: Path, windows: list[dict], policy: Policy, batch: int = 32) -> np.ndarray:
    if not windows:
        return np.zeros((0, 192), np.float32)
    import torch  # type: ignore
    enc = _encoder(policy)
    audio, sr = read_wav_mono(audio16k)
    min_len = int(0.5 * sr)
    chunks = []
    for w in windows:
        a = audio[int(w["t0"] * sr):int(w["t1"] * sr)]
        if len(a) < min_len:  # pad very short windows by centring a 0.5 s span
            mid = int((w["t0"] + w["t1"]) / 2 * sr)
            a = audio[max(0, mid - min_len // 2):max(0, mid - min_len // 2) + min_len]
        chunks.append(a)
    out = []
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        longest = max(len(c) for c in part)
        x = np.zeros((len(part), longest), np.float32)
        lens = np.zeros(len(part), np.float32)
        for k, c in enumerate(part):
            x[k, :len(c)] = c
            lens[k] = len(c) / longest
        with torch.no_grad():
            e = enc.encode_batch(torch.from_numpy(x), torch.from_numpy(lens)).squeeze(1).cpu().numpy()
        out.append(e)
    emb = np.concatenate(out).astype(np.float32)
    return emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)


def label_windows(emb: np.ndarray, windows: list[dict], refs: dict | None, policy: Policy) -> list[str]:
    """PARTNER_A / PARTNER_B / OTHER per window, UNKNOWN when no voice refs exist."""
    n = len(windows)
    if n == 0:
        return []
    if not refs or refs.get("voice_a") is None or refs.get("voice_b") is None or len(emb) != n:
        return [UNKNOWN] * n
    a = np.asarray(refs["voice_a"], np.float32)
    b = np.asarray(refs["voice_b"], np.float32)
    sa, sb = emb @ a, emb @ b
    thr = float(policy("identity.voice.min_similarity"))
    margin = float(policy("identity.voice.margin"))
    labels = []
    for x, y in zip(sa, sb):
        if x >= thr and x - y >= margin:
            labels.append(PARTNER_A)
        elif y >= thr and y - x >= margin:
            labels.append(PARTNER_B)
        else:
            labels.append(OTHER)
    # short windows inherit the label of the longest neighbour within the gap
    min_len = float(policy("voice.min_window_s"))
    gap = float(policy("voice.window_gap_s")) * 2
    out = list(labels)
    for i, w in enumerate(windows):
        if w["t1"] - w["t0"] >= min_len:
            continue
        cands = []
        if i > 0 and w["t0"] - windows[i - 1]["t1"] <= gap:
            cands.append(i - 1)
        if i + 1 < n and windows[i + 1]["t0"] - w["t1"] <= gap:
            cands.append(i + 1)
        cands = [j for j in cands if windows[j]["t1"] - windows[j]["t0"] >= min_len]
        if cands:
            j = max(cands, key=lambda j: windows[j]["t1"] - windows[j]["t0"])
            out[i] = labels[j]
    return out
