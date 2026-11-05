"""Speech-to-text with word timestamps (faster-whisper backend, optional dependency)."""
from __future__ import annotations

from pathlib import Path

from .. import ffmpeg
from ..policy import Policy
from ..util import log


class BackendMissing(RuntimeError):
    pass


_MODEL = None
_MODEL_KEY = None


def _device(policy: Policy) -> str:
    dev = policy("compute.device")
    if dev == "auto":
        return "cuda" if ffmpeg.gpu_available() else "cpu"
    return dev


def load_model(policy: Policy):
    global _MODEL, _MODEL_KEY
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise BackendMissing("faster-whisper not installed (pip install 'magicvideo[asr]')") from e
    device = _device(policy)
    compute = policy("compute.asr_compute_type")
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    key = (policy("compute.asr_model"), device, compute)
    if _MODEL is None or _MODEL_KEY != key:
        log.info("loading whisper %s on %s (%s)", *key)
        _MODEL = WhisperModel(key[0], device=device, compute_type=compute)
        _MODEL_KEY = key
    return _MODEL


def transcribe(audio_path: Path, policy: Policy) -> dict:
    model = load_model(policy)
    segments, info = model.transcribe(str(audio_path), word_timestamps=True, vad_filter=True,
                                      beam_size=5, condition_on_previous_text=False)
    words, segs = [], []
    for seg in segments:
        segs.append({"t0": seg.start, "t1": seg.end, "text": seg.text.strip()})
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"t0": w.start, "t1": max(w.end, w.start + 0.01), "w": text, "p": w.probability})
    return {
        "backend": f"faster-whisper:{_MODEL_KEY[0] if _MODEL_KEY else '?'}",
        "language": getattr(info, "language", None),
        "words": words,
        "segments": segs,
    }
