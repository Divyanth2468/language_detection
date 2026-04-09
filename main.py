#!/usr/bin/env python3
"""
main.py
───────
Usage:
    # From DB queue (run fetch_urls.py first)
    python main.py --queue

    # Direct URL (testing)
    python main.py --url "https://..."

    # Batch URL file (testing)
    python main.py --input urls.txt

    # Options
    python main.py --queue --model small --samples 10
    python main.py --queue --no-db          # skip DB writes, CSV only
"""

import argparse
import logging
import sys
from pathlib import Path

from config import OUTPUT_CSV, TS_SAMPLE_COUNT, WHISPER_MODEL, WHISPER_MODELS
from src.exporter import print_summary
from src.pipeline import process_queue_parallel, process_url, process_urls


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("logs/run.log", encoding="utf-8"),
        ],
    )
    for lib in ("urllib3", "requests", "httpx", "numba", "pymysql"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def _parse_args():
    p = argparse.ArgumentParser(description="M3U8 Language Mapper")
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--queue", action="store_true", help="Process all videos in detection_queue."
    )
    src.add_argument("--url", "-u", help="Single M3U8 URL.")
    src.add_argument(
        "--input", "-i", type=Path, help="Text file with one URL per line."
    )

    p.add_argument("--model", "-m", default=WHISPER_MODEL, choices=WHISPER_MODELS)
    p.add_argument("--samples", "-s", type=int, default=TS_SAMPLE_COUNT)
    p.add_argument("--output", "-o", type=Path, default=OUTPUT_CSV)
    p.add_argument(
        "--no-db",
        action="store_true",
        help="Skip DB writes (CSV only). Only affects --queue mode.",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    _setup_logging(args.verbose)

    results = []

    if args.queue:
        from src.db import test_connection

        if not test_connection():
            print("Cannot connect to DB. Check DB_* in .env")
            return 1
        if args.no_db:
            # Monkey-patch db_writer to no-ops
            import src.db_writer as dbw

            dbw.write_result = lambda **kw: None
            dbw.write_error = lambda **kw: None
        results = process_queue_parallel(
            sample_count=args.samples,
            model_size=args.model,
            output_path=args.output,
            max_workers=10,
        )

    elif args.url:
        results = [
            process_url(
                url=args.url.strip(),
                sample_count=args.samples,
                model_size=args.model,
                output_path=args.output,
            )
        ]

    elif args.input:
        if not args.input.exists():
            print(f"File not found: {args.input}")
            return 1
        urls = [
            l.strip()
            for l in args.input.read_text().splitlines()
            if l.strip() and not l.startswith("#")
        ]
        results = process_urls(urls, args.samples, args.model, args.output)

    else:
        print("No input. Use --queue, --url, or --input. See --help.")
        return 1

    if results:
        print_summary(args.output)
        failed = sum(1 for r in results if r.get("status") != "ok")
        return 1 if failed == len(results) else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
