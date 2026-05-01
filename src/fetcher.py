"""
src/fetcher.py
──────────────
Fetches an M3U8 playlist, parses all TS segment URLs,
picks a random sample of them, and downloads them locally.
"""

import logging
import random
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import m3u8
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import REQUEST_HEADERS, REQUEST_TIMEOUT, TEMP_DIR, TS_SAMPLE_COUNT

logger = logging.getLogger(__name__)


# ── Public API ─────────────────────────────────────────────────────────────


from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

_session = requests.Session()


def fetch_segments(
    m3u8_url: str,
    sample_count: int = TS_SAMPLE_COUNT,
    prefix: str = "",
) -> list[Path]:
    """
    Fetch and download sampled TS segments from an M3U8 playlist.

    REQUIREMENT:
    - prefix MUST be provided (used for per-job isolation)

    Returns:
        Ordered list of Path objects (safe for FFmpeg concat)
    """

    if not prefix:
        raise ValueError("prefix is required (use event_id for isolation)")

    logger.info(f"Fetching M3U8: {m3u8_url} (prefix={prefix})")

    segment_urls = _get_segment_urls(m3u8_url)
    if not segment_urls:
        raise RuntimeError(f"No TS segments found in playlist: {m3u8_url}")

    logger.info(f"Found {len(segment_urls)} segments — sampling {sample_count}")

    sampled = _spaced_sample(segment_urls, sample_count)

    temp_downloaded: list[Path | None] = [None] * len(sampled)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_download_segment, url, i, prefix): i - 1
            for i, url in enumerate(sampled, 1)
        }

        for future in as_completed(futures):
            idx = futures[future]
            try:
                temp_downloaded[idx] = future.result()
            except Exception as exc:
                logger.warning(f"[segment {idx+1}] download failed: {exc}")

    # Ensure at least something succeeded
    if not any(temp_downloaded):
        raise RuntimeError("All segment downloads failed.")

    # Final ordered list (drop failed ones)
    downloaded: list[Path] = [d for d in temp_downloaded if d is not None]

    dest_dir = TEMP_DIR / prefix
    logger.info(f"Downloaded {len(downloaded)} segments to {dest_dir}")

    return downloaded


# ── Internals ──────────────────────────────────────────────────────────────


def _get_segment_urls(m3u8_url: str) -> list[str]:
    """
    Parse the playlist and return absolute URLs for every TS segment.
    Handles both master playlists (picks highest-bandwidth variant)
    and media playlists directly.
    """
    content = _http_get(m3u8_url)
    playlist = m3u8.loads(content)

    # Master playlist → pick the best (highest bandwidth) variant
    if playlist.is_variant:
        logger.info("Master playlist detected — resolving best variant...")
        variant_url = _pick_best_variant(playlist, m3u8_url)
        logger.info(f"Selected variant: {variant_url}")
        content = _http_get(variant_url)
        playlist = m3u8.loads(content)
        base_url = variant_url
    else:
        base_url = m3u8_url

    segment_urls: list[str] = []
    for seg in playlist.segments:
        uri = seg.uri
        if not uri.startswith("http"):
            uri = urljoin(base_url, uri)
        segment_urls.append(uri)

    return segment_urls


def _pick_best_variant(playlist: m3u8.M3U8, base_url: str) -> str:
    """Return absolute URL of the highest-bandwidth variant stream."""
    playlists = playlist.playlists
    if not playlists:
        raise RuntimeError("Master playlist has no variant streams.")

    best = max(
        playlists,
        key=lambda p: p.stream_info.bandwidth if p.stream_info else 0,
    )
    uri = best.uri
    if not uri.startswith("http"):
        uri = urljoin(base_url, uri)
    return uri


def _spaced_sample(items: list, n: int) -> list:
    """
    Return `n` items evenly distributed across the middle 50% of `items`.
    Fully deterministic — no randomness.
    """
    start = len(items) // 4
    end = (len(items) * 3) // 4
    items = items[start:end]

    if n >= len(items):
        return items[:]

    # Pick one item per bucket at the bucket midpoint (deterministic)
    bucket_size = len(items) / n
    result = []
    for i in range(n):
        mid = int((i + 0.5) * bucket_size)  # midpoint of bucket
        mid = min(mid, len(items) - 1)
        result.append(items[mid])
    return result


def _download_segment(
    url: str,
    index: int,
    prefix: str,
    retries: int = 3,
) -> Path:
    """
    Download a single TS segment to disk.

    REQUIREMENT:
    - prefix MUST be provided (no shared directory fallback)

    Returns:
        Path to downloaded .ts file
    """
    if not prefix:
        raise ValueError("prefix is required for safe downloads")
    safe_name = _url_filename(url)
    filename = f"{prefix}_seg_{index:04d}_{safe_name}"
    # Strict isolation per job
    dest_dir = TEMP_DIR / prefix
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if dest.exists():
        return dest  # resume-safe
    for attempt in range(1, retries + 1):
        try:
            resp = _session.get(
                url,
                headers=REQUEST_HEADERS,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            )
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
            return dest
        except requests.RequestException as exc:
            logger.warning(f"[{prefix}] attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"[{prefix}] Failed to download segment: {url}")


def _http_get(url: str) -> str:
    """Simple GET that returns text; raises on HTTP errors."""
    resp = _session.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _url_filename(url: str) -> str:
    """Extract safe filename from URL (last path component, no query string)."""
    path = urlparse(url).path
    name = Path(path).name or "segment.ts"
    # Keep only safe characters
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return safe[:80]  # cap length


def fetch_segments_retry(
    m3u8_url: str,
    sample_count: int,
    prefix: str,
) -> list[Path]:
    """
    Fetch additional segments for mismatch retry.
    Samples from the 15-25% and 75-85% bands of the playlist,
    guaranteed not to overlap with the middle-50% window used
    by the first-pass fetch_segments().
    """
    if not prefix:
        raise ValueError("prefix is required")

    logger.info(f"Retry fetch: {m3u8_url} (prefix={prefix}, count={sample_count})")

    segment_urls = _get_segment_urls(m3u8_url)
    if not segment_urls:
        raise RuntimeError(f"No TS segments found in playlist: {m3u8_url}")

    sampled = _retry_spaced_sample(segment_urls, sample_count)

    temp_downloaded: list[Path | None] = [None] * len(sampled)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_download_segment, url, i, prefix): i - 1
            for i, url in enumerate(sampled, 1)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                temp_downloaded[idx] = future.result()
            except Exception as exc:
                logger.warning(f"[retry segment {idx+1}] download failed: {exc}")

    if not any(temp_downloaded):
        raise RuntimeError("All retry segment downloads failed.")

    downloaded = [d for d in temp_downloaded if d is not None]
    logger.info(f"Retry: downloaded {len(downloaded)} segments (prefix={prefix})")
    return downloaded


def _retry_spaced_sample(items: list, n: int) -> list:
    """
    Sample evenly from the 15-25% band and the 75-85% band of the playlist.
    Splits n as evenly as possible between the two bands.
    """
    total = len(items)

    lo_start = int(total * 0.15)
    lo_end = int(total * 0.25)
    hi_start = int(total * 0.75)
    hi_end = int(total * 0.85)

    lo_band = items[lo_start:lo_end]
    hi_band = items[hi_start:hi_end]

    n_lo = n // 2
    n_hi = n - n_lo  # hi gets the extra 1 if n is odd

    def _pick(band, k):
        if not band:
            return []
        if k >= len(band):
            return band[:]
        bucket_size = len(band) / k
        return [
            random.choice(
                band[int(i * bucket_size) : int((i + 1) * bucket_size)] or band
            )
            for i in range(k)
        ]

    return _pick(lo_band, n_lo) + _pick(hi_band, n_hi)
