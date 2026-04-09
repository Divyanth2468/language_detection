#!/usr/bin/env python3
"""
export_csv.py
─────────────
Reads detection_results from DB and exports to CSV.
This is the only script that touches the filesystem for CSV output.

Usage:
    python export_csv.py --output output/results.csv
    python export_csv.py --output output/results.csv --from 2026-01-01 --to 2026-03-31
    python export_csv.py --output output/results.csv --status mismatch
"""

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.db import _cursor, test_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("export_csv")

# Final CSV column order for the Go dashboard
CSV_COLUMNS = [
    "event_id",
    "cdn_url",
    "current_lang_ids",       # raw  e.g. [7, 22]
    "current_lang_names",     # expanded e.g. "Hindi, Telugu"
    "detected_lang",          # ISO code e.g. "hi"
    "detected_lang_id",       # your DB ID e.g. 7
    "detected_lang_name",     # human name e.g. "Hindi"
    "confidence",
    "lang_match_status",      # match | dialect_match | mismatch | untagged | unmapped
    "whisper_model",
    "ts_sampled",
    "audio_duration_s",
    "status",
    "error",
    "processed_at",
]


def _parse_args():
    p = argparse.ArgumentParser(description="Export detection_results to CSV.")
    p.add_argument("--output", "-o", required=True, type=Path,
                   help="Path to write CSV e.g. output/results.csv")
    p.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD",
                   help="Filter by processed_at start date.")
    p.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD",
                   help="Filter by processed_at end date.")
    p.add_argument("--status", choices=["ok", "error", "mismatch", "match",
                                         "dialect_match", "untagged", "unmapped"],
                   help="Filter by lang_match_status or status.")
    return p.parse_args()


def fetch_results(from_date=None, to_date=None, status_filter=None) -> list[dict]:
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

    query = f"""
        SELECT
            event_id, cdn_url,
            current_lang_ids, current_lang_names,
            detected_lang, detected_lang_id, detected_lang_name,
            confidence, lang_match_status, whisper_model,
            ts_sampled, audio_duration_s, status, error, processed_at
        FROM detection_results
        WHERE {' AND '.join(conditions)}
        ORDER BY processed_at ASC
    """

    with _cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def main():
    args = _parse_args()

    if not test_connection():
        print("Cannot connect to DB. Check DB_* in .env")
        sys.exit(1)

    rows = fetch_results(
        from_date     = args.from_date,
        to_date       = args.to_date,
        status_filter = args.status,
    )

    if not rows:
        print("No results found for given filters.")
        sys.exit(0)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Normalize current_lang_ids from JSON string to readable form
            raw = row.get("current_lang_ids")
            if isinstance(raw, str):
                try:
                    row["current_lang_ids"] = json.dumps(json.loads(raw))
                except Exception:
                    pass
            elif isinstance(raw, list):
                row["current_lang_ids"] = json.dumps(raw)
            writer.writerow(row)

    print(f"\n✅  Exported {len(rows)} rows → {args.output}\n")

    # Quick summary
    ok       = sum(1 for r in rows if r.get("status") == "ok")
    match    = sum(1 for r in rows if r.get("lang_match_status") == "match")
    dialect  = sum(1 for r in rows if r.get("lang_match_status") == "dialect_match")
    mismatch = sum(1 for r in rows if r.get("lang_match_status") == "mismatch")
    untagged = sum(1 for r in rows if r.get("lang_match_status") == "untagged")
    errors   = sum(1 for r in rows if r.get("status") == "error")

    print(f"  Total        : {len(rows)}")
    print(f"  Successful   : {ok}")
    print(f"  Errors       : {errors}")
    print(f"  Match        : {match}")
    print(f"  Dialect match: {dialect}")
    print(f"  Mismatch     : {mismatch}")
    print(f"  Untagged     : {untagged}\n")


if __name__ == "__main__":
    main()
