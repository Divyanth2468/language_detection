#!/usr/bin/env python3
"""
export_csv.py
─────────────
Reads detection_results from DB and exports to CSV.

Usage:
    python export_csv.py --output output/results.csv
    python export_csv.py --output output/results.csv --min-confidence 0.7
    python export_csv.py --output output/results.csv --max-confidence 0.7
"""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from src.db import _cursor, test_connection
from src.db_writer import _encrypt_video_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("export_csv")


# EXACT columns (no processed_at, no id)
CSV_COLUMNS = [
    "event_id",
    "cdn_url",
    "current_lang_ids",
    "current_lang_names",
    "detected_lang",
    "detected_lang_id",
    "detected_lang_name",
    "confidence",
    "lang_match_status",
    "whisper_model",
    "ts_sampled",
    "audio_duration_s",
    "status",
    "error",
    "video_link",
]


def _parse_args():
    p = argparse.ArgumentParser(description="Export detection_results to CSV.")
    p.add_argument("--output", "-o", required=True, type=Path)

    p.add_argument("--from", dest="from_date")
    p.add_argument("--to", dest="to_date")

    p.add_argument(
        "--status",
        choices=[
            "ok",
            "error",
            "mismatch",
            "match",
            "dialect_match",
            "untagged",
            "unmapped",
        ],
    )

    # Confidence filters
    p.add_argument("--min-confidence", type=float, help="confidence >= value")
    p.add_argument("--max-confidence", type=float, help="confidence < value")

    return p.parse_args()


def fetch_results(
    from_date=None, to_date=None, status_filter=None, min_conf=None, max_conf=None
):

    conditions = ["1=1"]
    params = {}

    if from_date:
        conditions.append("processed_at >= %(from_date)s")
        params["from_date"] = from_date

    if to_date:
        conditions.append("processed_at <= %(to_date)s")
        params["to_date"] = to_date + " 23:59:59"

    if status_filter:
        if status_filter in ("ok", "error"):
            conditions.append("status = %(sf)s")
        else:
            conditions.append("lang_match_status = %(sf)s")
        params["sf"] = status_filter

    if min_conf is not None:
        conditions.append(
            "GREATEST(confidence, COALESCE(retry_confidence, 0)) >= %(min_conf)s"
        )
        params["min_conf"] = min_conf

    if max_conf is not None:
        conditions.append(
            "GREATEST(confidence, COALESCE(retry_confidence, 0)) < %(max_conf)s"
        )
        params["max_conf"] = max_conf

    query = f"""
        SELECT
            event_id,
            cdn_url,
            current_lang_ids,
            current_lang_names,
            detected_lang,
            detected_lang_id,
            detected_lang_name,
            confidence,
            retry_confidence,
            lang_match_status,
            whisper_model,
            ts_sampled,
            audio_duration_s,
            status,
            error
        FROM detection_results
        WHERE {' AND '.join(conditions)}
        ORDER BY event_id ASC
    """

    with _cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def main():
    args = _parse_args()

    if not test_connection():
        print("Cannot connect to DB.")
        sys.exit(1)

    rows = fetch_results(
        from_date=args.from_date,
        to_date=args.to_date,
        status_filter=args.status,
        min_conf=args.min_confidence,
        max_conf=args.max_confidence,
    )

    if not rows:
        print("No results found.")
        sys.exit(0)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for row in rows:
            # Normalize JSON
            raw = row.get("current_lang_ids")
            if isinstance(raw, str):
                try:
                    row["current_lang_ids"] = json.dumps(json.loads(raw))
                except Exception:
                    pass
            elif isinstance(raw, list):
                row["current_lang_ids"] = json.dumps(raw)

            # Use the stronger confidence signal for the CSV output
            conf = row.get("confidence") or 0.0
            retry_conf = row.get("retry_confidence")
            row["confidence"] = retry_conf if retry_conf is not None else conf

            try:
                row["video_link"] = _encrypt_video_url(row["event_id"])
            except Exception:
                row["video_link"] = ""

            writer.writerow(row)

    print(f"\nExported {len(rows)} rows → {args.output}\n")


if __name__ == "__main__":
    main()
