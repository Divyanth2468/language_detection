"""
src/processor.py
────────────────
Merges downloaded .ts segments into a single file using FFmpeg,
then extracts a mono 16 kHz WAV audio clip suitable for Whisper.

VAD (Voice Activity Detection):
  - Silero VAD model is loaded per-thread using thread-local storage
  - Each worker thread gets its own model instance — fully thread-safe
  - get_speech_ratio() returns 0.0–1.0 fraction of audio that contains speech
  - Callers should skip Whisper if speech_ratio < 0.15 (music/silent content)
"""

import logging
import subprocess
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import AUDIO_CLIP_SECONDS, TEMP_DIR

logger = logging.getLogger(__name__)

# WAV spec Whisper expects
WHISPER_SAMPLE_RATE = 16000
WHISPER_CHANNELS = 1

# Speech ratio below this → skip Whisper (music/silence)
SPEECH_RATIO_THRESHOLD = 0.1

_thread_local = threading.local()

# ── Public API ─────────────────────────────────────────────────────────────


def merge_and_extract_audio(ts_files: list[Path]) -> Path:
    """
    1. Concatenates `ts_files` into a single merged .ts.
    2. Extracts audio as a 16 kHz mono WAV, trimmed to AUDIO_CLIP_SECONDS.

    Returns the Path to the WAV file.
    Raises RuntimeError if FFmpeg fails at any step.
    """
    if not ts_files:
        raise ValueError("No TS files provided.")

    run_id = uuid.uuid4().hex[:8]
    merged = TEMP_DIR / f"merged_{run_id}.ts"
    wav_out = TEMP_DIR / f"audio_{run_id}.wav"

    try:
        _merge_ts(ts_files, merged)
        _extract_audio(merged, wav_out)
    finally:
        # Always clean up the large merged TS; keep the small WAV
        if merged.exists():
            merged.unlink(missing_ok=True)

    return wav_out


def get_speech_ratio(wav_path: Path) -> float:
    try:
        model, utils = _get_vad_model()
        read_audio = utils["read_audio"]
        get_speech_timestamps = utils["get_speech_timestamps"]

        model.reset_states()  # reset between calls within same thread

        audio = read_audio(str(wav_path), sampling_rate=16000)
        timestamps = get_speech_timestamps(audio, model, sampling_rate=16000)

        if not timestamps:
            return 0.0

        speech_samples = sum(t["end"] - t["start"] for t in timestamps)
        ratio = round(speech_samples / len(audio), 3)
        logger.debug(f"VAD speech_ratio={ratio:.3f} for {wav_path.name}")
        return ratio

    except Exception as exc:
        logger.warning(f"VAD failed for {wav_path.name}, defaulting to 0.0: {exc}")
        return 0.0


def cleanup_ts_files(ts_files: list[Path]) -> None:
    """
    Remove downloaded TS files and clean up empty parent directories.
    Safe for parallel execution.
    """
    cleaned_dirs = set()

    for f in ts_files:
        try:
            parent = f.parent
            f.unlink(missing_ok=True)
            cleaned_dirs.add(parent)
        except OSError as exc:
            logger.warning(f"Could not delete {f}: {exc}")

    for d in cleaned_dirs:
        try:
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


# ── VAD internals ──────────────────────────────────────────────────────────


def _get_vad_model():
    """
    Load Silero VAD per-thread using thread-local storage.
    Each worker thread gets its own model instance — fully thread-safe.
    """
    if not hasattr(_thread_local, "vad_model"):
        logger.info(f"Loading Silero VAD for thread {threading.current_thread().name}…")
        from silero_vad import get_speech_timestamps, load_silero_vad, read_audio

        _thread_local.vad_model = load_silero_vad()
        _thread_local.vad_utils = {
            "read_audio": read_audio,
            "get_speech_timestamps": get_speech_timestamps,
        }
        logger.info(f"Silero VAD loaded for thread {threading.current_thread().name}.")

    return _thread_local.vad_model, _thread_local.vad_utils


# ── FFmpeg internals ───────────────────────────────────────────────────────


def _merge_ts(ts_files: list[Path], output: Path) -> None:
    """
    Concatenate TS segments with FFmpeg concat demuxer (no re-encode).
    Writes a temporary filelist, then calls ffmpeg.
    """
    list_file = TEMP_DIR / f"concat_{output.stem}.txt"
    with open(list_file, "w") as fh:
        for ts in ts_files:
            fh.write(f"file '{ts.as_posix()}'\n")

    logger.info(f"Merging {len(ts_files)} TS files → {output.name}")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(output),
    ]
    _run(cmd, label="merge")
    list_file.unlink(missing_ok=True)


def _extract_audio(source: Path, wav_out: Path) -> None:
    """
    Extract audio from `source`, convert to 16 kHz mono WAV.
    Skips the first 10 s to avoid intros/silence, then takes AUDIO_CLIP_SECONDS.
    """
    offset = 0  # sampled segments are already mid-content
    duration = AUDIO_CLIP_SECONDS

    logger.info(
        f"Extracting audio: offset={offset}s, duration={duration}s → {wav_out.name}"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(offset),
        "-i",
        str(source),
        "-t",
        str(duration),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(WHISPER_SAMPLE_RATE),
        "-ac",
        str(WHISPER_CHANNELS),
        str(wav_out),
    ]
    _run(cmd, label="audio extraction")


def _run(cmd: list[str], label: str) -> None:
    """Run an FFmpeg command. Raises RuntimeError with stderr on failure."""
    logger.debug(f"FFmpeg [{label}]: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        logger.error(f"FFmpeg [{label}] stderr:\n{result.stderr[-2000:]}")
        raise RuntimeError(
            f"FFmpeg failed ({label}) with exit code {result.returncode}.\n"
            f"Stderr (last 500 chars): {result.stderr[-500:]}"
        )
    logger.debug(f"FFmpeg [{label}] succeeded.")
