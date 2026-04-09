#!/usr/bin/env python3
"""
fetch_urls.py
─────────────
Queries the DB for videos in a date range and loads them
into the detection_queue table (always re-queues everything).

Usage:
    python fetch_urls.py --from 2026-01-01 --to 2026-03-31
    python fetch_urls.py --all
    python fetch_urls.py --event-id 295134
"""

import argparse
import json
import logging
import sys
from datetime import datetime

from config import DB_HOST, DB_NAME
from src.db import get_all_videos, get_video_by_id, get_videos_by_date, test_connection
from src.db_writer import bulk_enqueue_videos, ensure_tables
from src.lang_utils import lang_ids_to_names

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/fetch.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("fetch_urls")


def _parse_args():
    p = argparse.ArgumentParser(description="Load videos into detection_queue.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    src.add_argument("--all", action="store_true", help="Queue all videos.")
    src.add_argument("--event-id", metavar="ID")
    p.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be queued without writing to DB.",
    )
    return p.parse_args()


def main():
    args = _parse_args()

    if not test_connection():
        print("Cannot connect to DB. Check DB_* in .env")
        sys.exit(1)

    ensure_tables()

    # ── Fetch rows ─────────────────────────────────────────────────────────
    if args.from_date:
        if not args.to_date:
            print("--from requires --to")
            sys.exit(1)
        videos = get_videos_by_date(args.from_date, args.to_date)

    elif args.all:
        videos = get_all_videos()

    else:
        v = get_video_by_id(args.event_id)
        videos = [v] if v else []
        if not videos:
            print(f"No video found for event_id={args.event_id}")
            sys.exit(1)

    if not videos:
        print("No videos found for given criteria.")
        sys.exit(0)

    print(f"\nFound {len(videos)} videos to queue.\n")

    # ── Enqueue ────────────────────────────────────────────────────────────
    rows = []
    for i, v in enumerate(videos, 1):
        lang_names = lang_ids_to_names(v.current_lang_ids)
        if args.dry_run:
            print(
                f"  [{i:>4}] event_id={v.event_id:<10} "
                f"lang_ids={v.current_lang_ids}  ({lang_names})"
            )
        else:
            rows.append(
                (
                    v.event_id,
                    v.cdn_url,
                    json.dumps(v.current_lang_ids),
                    lang_names,
                )
            )

    if args.dry_run:
        print("\n[dry-run] Nothing written to DB.")
    if not args.dry_run:
        bulk_enqueue_videos(rows)


if __name__ == "__main__":
    main()
