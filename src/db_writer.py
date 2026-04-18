"""
src/db_writer.py
────────────────
Creates and writes to two temp tables:
  - detection_queue   (input — what needs processing)
  - detection_results (output — what Whisper found)
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import _cursor

logger = logging.getLogger(__name__)


# ── Table DDL ──────────────────────────────────────────────────────────────

_CREATE_QUEUE = """
CREATE TABLE IF NOT EXISTS detection_queue (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    event_id         VARCHAR(64)  NOT NULL,
    cdn_url          TEXT,
    current_lang_ids JSON,
    current_lang_names TEXT,
    queued_at        DATETIME     DEFAULT CURRENT_TIMESTAMP,
    processed        TINYINT DEFAULT 0,
    UNIQUE KEY uq_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_CREATE_RESULTS = """
CREATE TABLE IF NOT EXISTS detection_results (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    event_id             VARCHAR(64)  NOT NULL,
    cdn_url              TEXT,
    current_lang_ids     JSON,
    current_lang_names   TEXT,
    detected_lang        VARCHAR(10),
    detected_lang_id     INT,
    detected_lang_name   VARCHAR(64),
    confidence           FLOAT,
    lang_match_status    VARCHAR(20),
    whisper_model        VARCHAR(20),
    ts_sampled           INT,
    audio_duration_s     INT,
    status               VARCHAR(10)  DEFAULT 'ok',
    error                TEXT,
    processed_at         DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


# ── Queue operations ───────────────────────────────────────────────────────


def ensure_tables() -> None:
    with _cursor() as cur:
        cur.execute(_CREATE_QUEUE)
        cur.execute(_CREATE_RESULTS)
    logger.debug("Tables ready: detection_queue, detection_results")


def enqueue_video(
    event_id: str, cdn_url: str, current_lang_ids: list[int], current_lang_names: str
) -> None:
    """Insert or replace a video into detection_queue (always re-queues)."""
    ensure_tables()
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO detection_queue
                (event_id, cdn_url, current_lang_ids, current_lang_names, queued_at)
            VALUES
                (%(event_id)s, %(cdn_url)s, %(lang_ids)s, %(lang_names)s, %(now)s)
            ON DUPLICATE KEY UPDATE
                cdn_url            = VALUES(cdn_url),
                current_lang_ids   = VALUES(current_lang_ids),
                current_lang_names = VALUES(current_lang_names),
                processed = 0,
                queued_at          = VALUES(queued_at)
        """,
            {
                "event_id": event_id,
                "cdn_url": (cdn_url or "")[:2000],
                "lang_ids": json.dumps(current_lang_ids),
                "lang_names": current_lang_names,
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )


def get_queue() -> list[dict]:
    """Return all rows from detection_queue."""
    ensure_tables()
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM detection_queue WHERE processed = 0 ORDER BY queued_at ASC"
        )
        return cur.fetchall()


# ── Result operations ──────────────────────────────────────────────────────


def write_result(
    event_id: str,
    cdn_url: str = "",
    current_lang_ids: list = None,
    current_lang_names: str = "",
    detected_lang: str = "",
    detected_lang_id: int = None,
    detected_lang_name: str = "",
    confidence: float = 0.0,
    lang_match_status: str = "",
    whisper_model: str = "",
    ts_sampled: int = 0,
    audio_duration_s: int = 0,
    status: str = "ok",
    error: str = "",
) -> None:
    ensure_tables()
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO detection_results (
                event_id, cdn_url, current_lang_ids, current_lang_names,
                detected_lang, detected_lang_id, detected_lang_name,
                confidence, lang_match_status, whisper_model,
                ts_sampled, audio_duration_s, status, error, processed_at
            ) VALUES (
                %(event_id)s, %(cdn_url)s, %(current_lang_ids)s, %(current_lang_names)s,
                %(detected_lang)s, %(detected_lang_id)s, %(detected_lang_name)s,
                %(confidence)s, %(lang_match_status)s, %(whisper_model)s,
                %(ts_sampled)s, %(audio_duration_s)s, %(status)s, %(error)s, %(processed_at)s
            )
            ON DUPLICATE KEY UPDATE
                cdn_url            = VALUES(cdn_url),
                current_lang_ids   = VALUES(current_lang_ids),
                current_lang_names = VALUES(current_lang_names),
                detected_lang      = VALUES(detected_lang),
                detected_lang_id   = VALUES(detected_lang_id),
                detected_lang_name = VALUES(detected_lang_name),
                confidence         = VALUES(confidence),
                lang_match_status  = VALUES(lang_match_status),
                whisper_model      = VALUES(whisper_model),
                ts_sampled         = VALUES(ts_sampled),
                audio_duration_s   = VALUES(audio_duration_s),
                status             = VALUES(status),
                error              = VALUES(error),
                processed_at       = VALUES(processed_at)
        """,
            {
                "event_id": event_id,
                "cdn_url": (cdn_url or "")[:2000],
                "current_lang_ids": json.dumps(current_lang_ids or []),
                "current_lang_names": current_lang_names,
                "detected_lang": detected_lang,
                "detected_lang_id": detected_lang_id,
                "detected_lang_name": detected_lang_name,
                "confidence": round(confidence, 4),
                "lang_match_status": lang_match_status,
                "whisper_model": whisper_model,
                "ts_sampled": ts_sampled,
                "audio_duration_s": audio_duration_s,
                "status": status,
                "error": str(error)[:1000] if error else "",
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
    logger.info(
        f"DB write OK — event_id={event_id} "
        f"detected={detected_lang_name}({detected_lang_id}) "
        f"status={lang_match_status} conf={confidence:.3f}"
    )


def write_error(
    event_id: str,
    error: str,
    cdn_url: str = "",
    current_lang_ids: list = None,
    current_lang_names: str = "",
) -> None:
    write_result(
        event_id=event_id,
        cdn_url=cdn_url,
        current_lang_ids=current_lang_ids or [],
        current_lang_names=current_lang_names,
        status="error",
        error=str(error)[:1000],
    )


def bulk_enqueue_videos(rows):
    ensure_tables()

    query = """
    INSERT INTO detection_queue (
        event_id,
        cdn_url,
        current_lang_ids,
        current_lang_names
    )
    VALUES (%s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        cdn_url = VALUES(cdn_url),
        current_lang_ids = VALUES(current_lang_ids),
        current_lang_names = VALUES(current_lang_names),
        processed = 0,
        queued_at = CURRENT_TIMESTAMP
    """

    with _cursor() as cur:
        cur.executemany(query, rows)

    logger.info(f"Bulk inserted {len(rows)} rows into detection_queue")


def export_mismatched_to_csv(output_path: Path):
    import csv

    query = """
    SELECT
        event_id,
        cdn_url,
        current_lang_ids,
        current_lang_names,
        detected_lang,
        detected_lang_id,
        detected_lang_name,
        confidence,
        lang_match_status,
        whisper_model,
        ts_sampled,
        audio_duration_s,
        status,
        error
    FROM detection_results
    WHERE lang_match_status = 'mismatch'
      AND status = 'ok'
      AND detected_lang_id > 0
    ORDER BY processed_at DESC
    """

    with _cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    if not rows:
        print("No mismatched rows found.")
        return

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ Exported {len(rows)} mismatched rows to {output_path}")


def mark_processed_bulk(event_ids: list[str]):
    if not event_ids:
        return

    CHUNK_SIZE = 500

    with _cursor() as cur:
        for i in range(0, len(event_ids), CHUNK_SIZE):
            chunk = event_ids[i : i + CHUNK_SIZE]

            query = f"""
            UPDATE detection_queue
            SET processed = 1
            WHERE event_id IN ({','.join(['%s'] * len(chunk))})
            """

            cur.execute(query, chunk)

    logger.info(f"Marked {len(event_ids)} rows as processed")
