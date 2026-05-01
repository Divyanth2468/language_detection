"""
src/pipeline.py
───────────────
Orchestrates: fetch → merge → extract audio → VAD → detect → write DB + CSV.

VAD gate:
  - get_speech_ratio() is called after audio extraction
  - If speech_ratio < SPEECH_RATIO_THRESHOLD (0.15), Whisper is skipped entirely
  - Result is written with lang_match_status="no_speech" and error="VAD: no speech detected"
  - This prevents false language detections on music-only or silent videos
"""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    AUDIO_CLIP_SECONDS,
    OUTPUT_CSV,
    RETRY_FETCH_DELAY,
    SPEECH_RATIO_THRESHOLD,
    TS_RETRY_SAMPLE_COUNT,
    TS_SAMPLE_COUNT,
    WHISPER_MODEL,
)
from src.db_writer import (
    export_mismatched_to_csv,
    get_queue,
    mark_processed_bulk,
    write_error,
    write_result,
)
from src.detector import detect_language
from src.exporter import write_error as csv_error
from src.exporter import write_result as csv_write
from src.fetcher import fetch_segments, fetch_segments_retry
from src.lang_utils import (
    lang_ids_to_names,
    resolve_match_status,
    whisper_code_to_lang_id,
)
from src.processor import cleanup_ts_files, get_speech_ratio, merge_and_extract_audio

logger = logging.getLogger(__name__)


# ── URL mode (no DB) ───────────────────────────────────────────────────────


def process_url(
    url: str,
    sample_count: int = TS_SAMPLE_COUNT,
    model_size: str = WHISPER_MODEL,
    output_path: Path = OUTPUT_CSV,
) -> dict:
    logger.info("=" * 60)
    logger.info(f"Processing: {url}")
    logger.info("=" * 60)

    ts_files = []
    wav_path = None
    start = time.perf_counter()

    try:
        logger.info("[1/4] Fetching M3U8 segments …")
        import uuid

        prefix = f"url_{uuid.uuid4().hex}"
        ts_files = fetch_segments(url, sample_count=sample_count, prefix=prefix)

        logger.info("[2/4] Merging TS + extracting audio …")
        wav_path = merge_and_extract_audio(ts_files)

        logger.info("[3/4] VAD check …")
        speech_ratio = get_speech_ratio(wav_path)
        logger.info(
            f"speech_ratio={speech_ratio:.3f} (threshold={SPEECH_RATIO_THRESHOLD})"
        )

        if speech_ratio < SPEECH_RATIO_THRESHOLD:
            logger.info("Skipping Whisper — no speech detected (music/silent content)")
            csv_write(
                url=url,
                language_code="",
                language_name="",
                confidence=0.0,
                model_used=model_size,
                ts_sampled=len(ts_files),
                audio_duration=AUDIO_CLIP_SECONDS,
                status="ok",
                error="VAD: no speech detected",
                output_path=output_path,
            )
            elapsed = time.perf_counter() - start
            logger.info(f"Skipped in {elapsed:.1f}s — speech_ratio={speech_ratio:.3f}")
            return {
                "url": url,
                "status": "ok",
                "skip_reason": "no_speech",
                "speech_ratio": speech_ratio,
            }

        logger.info("[4/4] Detecting language …")
        result = detect_language(wav_path, model_size=model_size)

        csv_write(
            url=url,
            language_code=result.language_code,
            language_name=result.language_name,
            confidence=result.confidence,
            model_used=result.model_used,
            ts_sampled=len(ts_files),
            audio_duration=AUDIO_CLIP_SECONDS,
            output_path=output_path,
        )
        elapsed = time.perf_counter() - start
        logger.info(
            f"Done in {elapsed:.1f}s — "
            f"Language: {result.language_name} ({result.language_code}), "
            f"Confidence: {result.confidence:.3f}, "
            f"speech_ratio={speech_ratio:.3f}"
        )
        return {
            "url": url,
            "status": "ok",
            "language_code": result.language_code,
            "language_name": result.language_name,
            "confidence": result.confidence,
            "speech_ratio": speech_ratio,
            "error": "",
        }

    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.error(f"Failed ({elapsed:.1f}s): {exc}")
        csv_error(url=url, error=str(exc), output_path=output_path)
        return {"url": url, "status": "error", "error": str(exc)}

    finally:
        cleanup_ts_files(ts_files)
        if wav_path and wav_path.exists():
            wav_path.unlink(missing_ok=True)


def process_urls(
    urls: list[str],
    sample_count: int = TS_SAMPLE_COUNT,
    model_size: str = WHISPER_MODEL,
    output_path: Path = OUTPUT_CSV,
) -> list[dict]:
    results = []
    for i, url in enumerate(urls, 1):
        logger.info(f"\n── URL {i}/{len(urls)} ──────────────────────────")
        results.append(process_url(url, sample_count, model_size, output_path))
    return results


# ── Queue mode (from DB) ───────────────────────────────────────────────────


def process_queue(
    sample_count: int = TS_SAMPLE_COUNT,
    model_size: str = WHISPER_MODEL,
    output_path: Path = OUTPUT_CSV,
) -> list[dict]:
    """
    Reads detection_queue, processes each video sequentially,
    writes results to detection_results table + CSV.
    """
    rows = get_queue()
    if not rows:
        logger.info("detection_queue is empty. Run fetch_urls.py first.")
        return []

    results = []
    total = len(rows)

    for i, row in enumerate(rows, 1):
        event_id = str(row["event_id"])
        cdn_url = row["cdn_url"] or ""
        lang_names = row["current_lang_names"] or ""

        raw_ids = row.get("current_lang_ids")
        if isinstance(raw_ids, str):
            try:
                current_lang_ids = json.loads(raw_ids)
            except Exception:
                current_lang_ids = []
        elif isinstance(raw_ids, list):
            current_lang_ids = raw_ids
        else:
            current_lang_ids = []

        logger.info(f"\n── [{i}/{total}] event_id={event_id} ──────────────")

        ts_files = []
        retry_ts_files = []
        wav_path = None
        retry_wav_path = None
        start = time.perf_counter()

        try:
            logger.info("[1/4] Fetching M3U8 segments …")
            ts_files = fetch_segments(
                cdn_url, sample_count=sample_count, prefix=event_id
            )

            logger.info("[2/4] Merging TS + extracting audio …")
            wav_path = merge_and_extract_audio(ts_files)

            logger.info("[3/4] VAD check …")
            speech_ratio = get_speech_ratio(wav_path)
            logger.info(
                f"[{event_id}] speech_ratio={speech_ratio:.3f} (threshold={SPEECH_RATIO_THRESHOLD})"
            )

            if speech_ratio < SPEECH_RATIO_THRESHOLD:
                logger.info(f"[{event_id}] Skipping Whisper — no speech detected")
                write_result(
                    event_id=event_id,
                    cdn_url=cdn_url,
                    current_lang_ids=current_lang_ids,
                    current_lang_names=lang_names,
                    detected_lang="",
                    detected_lang_id=0,
                    detected_lang_name="",
                    confidence=0.0,
                    retry_confidence=None,
                    lang_match_status="no_speech",
                    whisper_model=model_size,
                    ts_sampled=len(ts_files),
                    audio_duration_s=AUDIO_CLIP_SECONDS,
                    status="ok",
                    error="VAD: no speech detected",
                )
                elapsed = time.perf_counter() - start
                logger.info(f"[{event_id}] Skipped in {elapsed:.1f}s")
                results.append(
                    {"event_id": event_id, "status": "ok", "skip_reason": "no_speech"}
                )
                continue

            logger.info("[4/4] Detecting language …")
            detection = detect_language(wav_path, model_size=model_size)

            detected_lang_id = whisper_code_to_lang_id(detection.language_code) or 0
            lang_match_status = resolve_match_status(current_lang_ids, detected_lang_id)

            # ── Mismatch retry ────────────────────────────────────────────
            retry_confidence = None

            if lang_match_status == "mismatch":
                logger.info(f"[{event_id}] Mismatch on first pass — starting retry")

                if RETRY_FETCH_DELAY > 0:
                    time.sleep(RETRY_FETCH_DELAY)

                try:
                    retry_prefix = f"{event_id}_retry"
                    retry_ts_files = fetch_segments_retry(
                        cdn_url,
                        sample_count=TS_RETRY_SAMPLE_COUNT,
                        prefix=retry_prefix,
                    )
                    retry_wav_path = merge_and_extract_audio(ts_files + retry_ts_files)
                    retry_detection = detect_language(
                        retry_wav_path, model_size=model_size
                    )

                    retry_confidence = retry_detection.confidence
                    retry_lang_id = (
                        whisper_code_to_lang_id(retry_detection.language_code) or 0
                    )
                    retry_match_status = resolve_match_status(
                        current_lang_ids, retry_lang_id
                    )

                    logger.info(
                        f"[{event_id}] Retry result: {retry_detection.language_name}"
                        f"({retry_lang_id}) status={retry_match_status} "
                        f"conf={retry_confidence:.3f}"
                    )

                    # Retry result wins — overwrite detection fields
                    detection = retry_detection
                    detected_lang_id = retry_lang_id
                    lang_match_status = retry_match_status

                except Exception as retry_exc:
                    logger.warning(
                        f"[{event_id}] Retry fetch/detect failed, using first-pass result: {retry_exc}"
                    )
            # ─────────────────────────────────────────────────────────────

            write_result(
                event_id=event_id,
                cdn_url=cdn_url,
                current_lang_ids=current_lang_ids,
                current_lang_names=lang_names,
                detected_lang=detection.language_code,
                detected_lang_id=detected_lang_id,
                detected_lang_name=detection.language_name,
                confidence=detection.confidence,
                retry_confidence=retry_confidence,
                lang_match_status=lang_match_status,
                whisper_model=detection.model_used,
                ts_sampled=len(ts_files) + len(retry_ts_files),
                audio_duration_s=AUDIO_CLIP_SECONDS,
                status="ok",
            )

            elapsed = time.perf_counter() - start
            logger.info(
                f"Done in {elapsed:.1f}s — "
                f"{detection.language_name}({detected_lang_id}) "
                f"status={lang_match_status} conf={detection.confidence:.3f}"
                + (
                    f" retry_conf={retry_confidence:.3f}"
                    if retry_confidence is not None
                    else ""
                )
            )

            results.append(
                {
                    "event_id": event_id,
                    "status": "ok",
                    "detected_lang": detection.language_code,
                    "detected_lang_id": detected_lang_id,
                    "lang_match_status": lang_match_status,
                    "confidence": detection.confidence,
                    "retry_confidence": retry_confidence,
                }
            )

        except Exception as exc:
            elapsed = time.perf_counter() - start
            logger.error(f"event_id={event_id} failed ({elapsed:.1f}s): {exc}")
            write_error(
                event_id=event_id,
                error=str(exc),
                cdn_url=cdn_url,
                current_lang_ids=current_lang_ids,
                current_lang_names=lang_names,
            )
            results.append({"event_id": event_id, "status": "error", "error": str(exc)})

        finally:
            cleanup_ts_files(ts_files + retry_ts_files)  # both lists, one pass
            if wav_path and wav_path.exists():
                wav_path.unlink(missing_ok=True)
            if retry_wav_path and retry_wav_path.exists():
                retry_wav_path.unlink(missing_ok=True)

    processed_ids = [r["event_id"] for r in results if r.get("event_id")]
    mark_processed_bulk(processed_ids)
    export_mismatched_to_csv(output_path)

    return results


def process_queue_parallel(
    sample_count: int = TS_SAMPLE_COUNT,
    model_size: str = WHISPER_MODEL,
    output_path: Path = OUTPUT_CSV,
    max_workers: int = 8,
):
    """
    Parallel version of queue processor (DB + CSV).
    VAD runs per-worker before Whisper — Silero model is shared (loaded once).
    Whisper inference is serialized via _infer_lock in detector.py.
    """
    queue = get_queue()

    if not queue:
        logger.info("Queue empty.")
        return []

    total = len(queue)
    print(f"\n Processing {total} videos with {max_workers} workers...\n")

    results = []

    def worker(row, idx):
        event_id = str(row["event_id"])
        cdn_url = row["cdn_url"] or ""
        lang_names = row.get("current_lang_names") or ""

        raw_ids = row.get("current_lang_ids")
        if isinstance(raw_ids, str):
            try:
                current_lang_ids = json.loads(raw_ids)
            except Exception:
                current_lang_ids = []
        elif isinstance(raw_ids, list):
            current_lang_ids = raw_ids
        else:
            current_lang_ids = []

        logger.info(f"[{idx}/{total}] START event_id={event_id}")

        ts_files = []
        retry_ts_files = []
        wav_path = None
        retry_wav_path = None

        try:
            ts_files = fetch_segments(
                cdn_url, sample_count=sample_count, prefix=event_id
            )
            wav_path = merge_and_extract_audio(ts_files)

            speech_ratio = get_speech_ratio(wav_path)
            logger.info(f"[{event_id}] speech_ratio={speech_ratio:.3f}")

            if speech_ratio < SPEECH_RATIO_THRESHOLD:
                logger.info(f"[{event_id}] Skipping — no speech detected")
                write_result(
                    event_id=event_id,
                    cdn_url=cdn_url,
                    current_lang_ids=current_lang_ids,
                    current_lang_names=lang_names,
                    detected_lang="",
                    detected_lang_id=0,
                    detected_lang_name="",
                    confidence=0.0,
                    retry_confidence=None,
                    lang_match_status="no_speech",
                    whisper_model=model_size,
                    ts_sampled=len(ts_files),
                    audio_duration_s=AUDIO_CLIP_SECONDS,
                    status="ok",
                    error="VAD: no speech detected",
                )
                return {
                    "event_id": event_id,
                    "status": "ok",
                    "skip_reason": "no_speech",
                }

            detection = detect_language(wav_path, model_size=model_size)
            detected_lang_id = whisper_code_to_lang_id(detection.language_code) or 0
            lang_match_status = resolve_match_status(current_lang_ids, detected_lang_id)

            # ── Mismatch retry ─────────────────────────────────────────────────
            retry_confidence = None

            if lang_match_status == "mismatch":
                logger.info(f"[{event_id}] Mismatch on first pass — starting retry")

                if RETRY_FETCH_DELAY > 0:
                    time.sleep(RETRY_FETCH_DELAY)

                try:
                    retry_prefix = f"{event_id}_retry"
                    retry_ts_files = fetch_segments_retry(
                        cdn_url,
                        sample_count=TS_RETRY_SAMPLE_COUNT,
                        prefix=retry_prefix,
                    )
                    retry_wav_path = merge_and_extract_audio(ts_files + retry_ts_files)
                    retry_detection = detect_language(
                        retry_wav_path, model_size=model_size
                    )

                    retry_confidence = retry_detection.confidence
                    retry_lang_id = (
                        whisper_code_to_lang_id(retry_detection.language_code) or 0
                    )
                    retry_match_status = resolve_match_status(
                        current_lang_ids, retry_lang_id
                    )

                    logger.info(
                        f"[{event_id}] Retry result: {retry_detection.language_name}"
                        f"({retry_lang_id}) status={retry_match_status} "
                        f"conf={retry_confidence:.3f}"
                    )

                    # Retry result wins — overwrite detection fields
                    detection = retry_detection
                    detected_lang_id = retry_lang_id
                    lang_match_status = retry_match_status

                except Exception as retry_exc:
                    # Retry failed — log and fall through to write the original result
                    logger.warning(
                        f"[{event_id}] Retry fetch/detect failed, using first-pass result: {retry_exc}"
                    )
            # ──────────────────────────────────────────────────────────────────

            write_result(
                event_id=event_id,
                cdn_url=cdn_url,
                current_lang_ids=current_lang_ids,
                current_lang_names=lang_names,
                detected_lang=detection.language_code,
                detected_lang_id=detected_lang_id,
                detected_lang_name=detection.language_name,
                confidence=detection.confidence,
                retry_confidence=retry_confidence,
                lang_match_status=lang_match_status,
                whisper_model=detection.model_used,
                ts_sampled=len(ts_files) + len(retry_ts_files),
                audio_duration_s=AUDIO_CLIP_SECONDS,
                status="ok",
            )

            logger.info(
                f"[{idx}/{total}] DONE event_id={event_id} — "
                f"{detection.language_name}({detected_lang_id}) "
                f"conf={detection.confidence:.3f}"
                + (
                    f" retry_conf={retry_confidence:.3f}"
                    if retry_confidence is not None
                    else ""
                )
            )
            return {"event_id": event_id, "status": "ok"}

        except Exception as e:
            logger.error(f"[{idx}/{total}] ERROR event_id={event_id}: {e}")
            write_error(
                event_id=event_id,
                error=str(e),
                cdn_url=cdn_url,
                current_lang_ids=current_lang_ids,
                current_lang_names=lang_names,
            )
            return {"event_id": event_id, "status": "error", "error": str(e)}

        finally:
            cleanup_ts_files(ts_files + retry_ts_files)  # both lists, one pass
            if wav_path and wav_path.exists():
                wav_path.unlink(missing_ok=True)
            if retry_wav_path and retry_wav_path.exists():
                retry_wav_path.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker, row, i) for i, row in enumerate(queue, 1)]
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                logger.error(f"Worker crashed: {e}")

    print("\n Parallel queue processing complete.\n")

    processed_ids = [r["event_id"] for r in results if r.get("event_id")]
    mark_processed_bulk(processed_ids)
    export_mismatched_to_csv(output_path)

    return results
