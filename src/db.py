"""
src/db.py
─────────
MySQL connection + all read queries.
"""

import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

try:
    import pymysql
    import pymysql.cursors
except ImportError:
    raise ImportError("Run: pip install pymysql")


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class VideoRow:
    event_id:         str
    cdn_url:          str               # vs.hlsLink
    current_lang_ids: list[int]         # parsed from JSON array e.g. [7, 22]


# ── Connection ─────────────────────────────────────────────────────────────

def _get_conn():
    from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    return pymysql.connect(
        host     = DB_HOST,
        port     = DB_PORT,
        db       = DB_NAME,
        user     = DB_USER,
        password = DB_PASSWORD,
        charset  = "utf8mb4",
        cursorclass = pymysql.cursors.DictCursor,
        connect_timeout = 10,
    )


@contextmanager
def _cursor():
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    finally:
        conn.close()


# ── Queries ────────────────────────────────────────────────────────────────

_FETCH_BY_DATE = """
SELECT
    le.eventId          AS event_id,
    vs.hlsLink          AS cdn_url,
    le.language_ids     AS current_lang_ids
FROM lyk_events le
JOIN video_set  vs ON le.eventId = vs.eventId
JOIN lyk_user   lu ON le.userId  = lu.userId
WHERE
    le.eventEntryDate BETWEEN %(from_date)s AND %(to_date)s
    AND le.deleted       = 'N'
    AND vs.cdnTransCode  = '1'
    AND lu.isDelete      = '0'
    AND lu.isDeactive    = '0'
    AND vs.hlsLink       IS NOT NULL
    AND vs.hlsLink       != ''
GROUP BY le.eventId
ORDER BY le.eventEntryDate ASC
"""

_FETCH_ALL = """
SELECT
    le.eventId          AS event_id,
    vs.hlsLink          AS cdn_url,
    le.language_ids     AS current_lang_ids
FROM lyk_events le
JOIN video_set  vs ON le.eventId = vs.eventId
JOIN lyk_user   lu ON le.userId  = lu.userId
WHERE
    le.deleted       = 'N'
    AND vs.cdnTransCode  = '1'
    AND lu.isDelete      = '0'
    AND lu.isDeactive    = '0'
    AND vs.hlsLink       IS NOT NULL
    AND vs.hlsLink       != ''
GROUP BY le.eventId
ORDER BY le.eventId ASC
"""

_FETCH_SINGLE = """
SELECT
    le.eventId          AS event_id,
    vs.hlsLink          AS cdn_url,
    le.language_ids     AS current_lang_ids
FROM lyk_events le
JOIN video_set  vs ON le.eventId = vs.eventId
JOIN lyk_user   lu ON le.userId  = lu.userId
WHERE
    le.eventId   = %(event_id)s
    AND le.deleted       = 'N'
    AND vs.cdnTransCode  = '1'
    AND lu.isDelete      = '0'
    AND lu.isDeactive    = '0'
GROUP BY le.eventId
"""


def get_videos_by_date(from_date, to_date) -> list[VideoRow]:
    from_str = str(from_date)
    to_str   = str(to_date) + " 23:59:59"
    logger.info(f"Querying videos from {from_str} to {to_str}")
    with _cursor() as cur:
        cur.execute(_FETCH_BY_DATE, {"from_date": from_str, "to_date": to_str})
        rows = cur.fetchall()
    result = [_to_row(r) for r in rows]
    logger.info(f"Found {len(result)} videos")
    return result


def get_all_videos() -> list[VideoRow]:
    logger.info("Querying all videos")
    with _cursor() as cur:
        cur.execute(_FETCH_ALL)
        rows = cur.fetchall()
    result = [_to_row(r) for r in rows]
    logger.info(f"Found {len(result)} videos")
    return result


def get_video_by_id(event_id: str) -> VideoRow | None:
    with _cursor() as cur:
        cur.execute(_FETCH_SINGLE, {"event_id": event_id})
        row = cur.fetchone()
    return _to_row(row) if row else None


def test_connection() -> bool:
    try:
        with _cursor() as cur:
            cur.execute("SELECT 1")
        logger.info("DB connection OK")
        return True
    except Exception as exc:
        logger.error(f"DB connection failed: {exc}")
        return False


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_lang_ids(raw) -> list[int]:
    """Parse language_ids — handles JSON array, comma string, int, or None."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [int(x) for x in raw if str(x).strip().isdigit()]
    s = str(raw).strip()
    if not s or s in ("null", "[]", ""):
        return []
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [int(x) for x in parsed if str(x).strip().isdigit()]
        return [int(parsed)]
    except (json.JSONDecodeError, ValueError):
        # fallback: comma-separated
        return [int(x.strip()) for x in s.split(",") if x.strip().isdigit()]


def _to_row(r: dict) -> VideoRow:
    return VideoRow(
        event_id         = str(r["event_id"]),
        cdn_url          = r["cdn_url"] or "",
        current_lang_ids = _parse_lang_ids(r.get("current_lang_ids")),
    )
