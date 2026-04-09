"""
src/exporter.py
───────────────
Writes detection results to a CSV file.
Appends to an existing CSV if it already exists,
so multiple runs accumulate in one file.
"""

import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CSV_COLUMNS, OUTPUT_CSV

logger = logging.getLogger(__name__)


# ── Public API ─────────────────────────────────────────────────────────────


def write_result(
    url: str,
    language_code: str,
    language_name: str,
    confidence: float,
    model_used: str,
    ts_sampled: int,
    audio_duration: int,
    status: str = "ok",
    error: str = "",
    output_path: Path = OUTPUT_CSV,
) -> None:
    """
    Append one result row to the CSV.
    Creates the file with headers if it does not yet exist.
    """
    row = {
        "url": url,
        "detected_language": language_code,
        "language_name": language_name,
        "confidence": confidence,
        "whisper_model": model_used,
        "ts_sampled": ts_sampled,
        "audio_duration_s": audio_duration,
        "status": status,
        "error": error,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    _ensure_headers(output_path)

    with open(output_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writerow(row)

    logger.info(f"Result written → {output_path}")


def write_error(
    url: str,
    error: str,
    output_path: Path = OUTPUT_CSV,
) -> None:
    """Convenience wrapper to record a failed URL."""
    write_result(
        url=url,
        language_code="",
        language_name="",
        confidence=0.0,
        model_used="",
        ts_sampled=0,
        audio_duration=0,
        status="error",
        error=str(error)[:500],  # cap error message length
        output_path=output_path,
    )


def print_summary(output_path: Path = OUTPUT_CSV) -> None:
    """Print a summary table of all results to stdout."""
    if not output_path.exists():
        print("No results yet.")
        return

    rows = _read_csv(output_path)
    if not rows:
        print("CSV is empty.")
        return

    # Safe status handling (some CSVs may not have status)
    ok_rows = [r for r in rows if r.get("status", "ok") == "ok"]
    err_rows = [r for r in rows if r.get("status", "ok") != "ok"]

    print("\n" + "═" * 72)
    print(f"  Results: {output_path}")
    print("═" * 72)
    print(f"  Total processed : {len(rows)}")
    print(f"  Successful      : {len(ok_rows)}")
    print(f"  Failed          : {len(err_rows)}")

    if ok_rows:
        print("\n  Detected languages:")
        from collections import Counter

        def get_lang(r):
            # Support both schemas
            return r.get("language_name") or r.get("detected_lang_name") or "unknown"

        counts = Counter(get_lang(r) for r in ok_rows)

        for lang, n in counts.most_common():
            print(f"    {lang:<20} {n}")

    print("═" * 72 + "\n")


# ── Internals ──────────────────────────────────────────────────────────────


def _ensure_headers(path: Path) -> None:
    """Write CSV header row if the file does not yet exist."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
        logger.info(f"Created CSV: {path}")


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
