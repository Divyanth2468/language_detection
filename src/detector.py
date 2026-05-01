"""
src/detector.py
───────────────
Loads a Whisper model (lazily, cached across calls) and detects
the spoken language in a WAV file.

Thread safety:
  - _model_lock  : ensures only one thread loads the model
  - _infer_lock  : serializes inference across workers (model is not thread-safe)
"""

import logging
import ssl
import threading
from dataclasses import dataclass
from pathlib import Path

import certifi
import torch
import whisper

# Fix macOS SSL certificate verification for Whisper model downloads
ssl._create_default_https_context = lambda: ssl.create_default_context(
    cafile=certifi.where()
)

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import LANGUAGE_NAMES, WHISPER_MODEL

logger = logging.getLogger(__name__)

# ── Model cache ────────────────────────────────────────────────────────────

_whisper_model = None
_whisper_model_size = None
_model_lock = threading.Lock()  # guards model loading
_infer_lock = threading.Lock()  # guards inference (model not thread-safe)


@dataclass
class DetectionResult:
    language_code: str  # ISO 639-1, e.g. "en"
    language_name: str  # Human name, e.g. "English"
    confidence: float  # Whisper's top-1 probability (0-1)
    model_used: str  # Which Whisper model was used


# ── Public API ─────────────────────────────────────────────────────────────


def detect_language(wav_path: Path, model_size: str = WHISPER_MODEL) -> DetectionResult:
    """
    Detect the spoken language in `wav_path`.

    Uses Whisper's `detect_language()` which runs on the first 30 s
    of audio — very fast even for large models.

    Thread-safe: model loading and inference are each protected by
    their own lock so multiple workers share one model safely.

    Returns a DetectionResult.
    Raises RuntimeError on model or file errors.
    """
    if not wav_path.exists():
        raise FileNotFoundError(f"Audio file not found: {wav_path}")

    model = _get_model(model_size)

    logger.info(f"Detecting language in {wav_path.name} (model={model_size})")

    # Load and pad/trim audio to 30 s (Whisper's window)
    # Audio loading is file I/O — fine to do outside the lock
    audio = whisper.load_audio(str(wav_path))
    audio = whisper.pad_or_trim(audio)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    mel = whisper.log_mel_spectrogram(audio).to(device)

    # Serialize inference — Whisper model object is not thread-safe
    with _infer_lock:
        _, probs = model.detect_language(mel)

    # Top-1 result (outside lock — just dict ops)
    lang_code = max(probs, key=probs.get)
    confidence = float(probs[lang_code])
    lang_name = LANGUAGE_NAMES.get(lang_code, lang_code.upper())

    logger.info(f"Detected: {lang_code} ({lang_name}) — confidence={confidence:.3f}")

    return DetectionResult(
        language_code=lang_code,
        language_name=lang_name,
        confidence=round(confidence, 4),
        model_used=model_size,
    )


# ── Internals ──────────────────────────────────────────────────────────────


def _get_model(model_size: str):
    """
    Load Whisper model once and cache it.
    Double-checked locking ensures only one thread loads even under contention.
    """
    global _whisper_model, _whisper_model_size

    # Fast path — no lock needed if already loaded
    if _whisper_model is not None and _whisper_model_size == model_size:
        return _whisper_model

    with _model_lock:
        # Re-check inside lock — another thread may have loaded while we waited
        if _whisper_model is None or _whisper_model_size != model_size:
            logger.info(f"Loading Whisper model: '{model_size}' …")
            _whisper_model = whisper.load_model(model_size)
            _whisper_model_size = model_size
            logger.info("Whisper model loaded.")

    return _whisper_model
