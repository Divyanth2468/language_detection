"""
src/detector.py
───────────────
Loads a Whisper model (lazily, cached across calls) and detects
the spoken language in a WAV file.
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

# Module-level cache so the model loads only once per process
_whisper_model = None
_whisper_model_size = None


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

    Returns a DetectionResult.
    Raises RuntimeError on model or file errors.
    """
    if not wav_path.exists():
        raise FileNotFoundError(f"Audio file not found: {wav_path}")

    model = _get_model(model_size)

    logger.info(f"Detecting language in {wav_path.name} (model={model_size})")

    # Load and pad/trim audio to 30 s (Whisper's window)
    audio = whisper.load_audio(str(wav_path))
    audio = whisper.pad_or_trim(audio)

    # Compute log-Mel spectrogram on the correct device
    device = "cuda" if torch.cuda.is_available() else "cpu"
    mel = whisper.log_mel_spectrogram(audio).to(device)

    # detect_language returns (language_token, probabilities_dict)
    _, probs = model.detect_language(mel)

    # Top-1 result
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

_whisper_model = None
_whisper_model_size = None
_model_lock = threading.Lock()


def _get_model(model_size: str):
    global _whisper_model, _whisper_model_size

    if _whisper_model is None or _whisper_model_size != model_size:
        with _model_lock:  # ensures only one thread loads
            if _whisper_model is None or _whisper_model_size != model_size:
                import whisper

                logger.info(f"Loading Whisper model: '{model_size}' …")
                _whisper_model = whisper.load_model(model_size)
                _whisper_model_size = model_size
                logger.info("Model loaded.")

    return _whisper_model
