# M3U8 Language Mapper (v2)

Detect spoken language from M3U8 (HLS) video streams using Whisper, with:

- DB-backed queue processing
- Parallel workers
- Dialect-aware matching
- Structured result storage (MySQL)
- CSV export (dashboard-ready)

---

## What This System Does

1. Fetches videos from DB (`lyk_events + video_set`)
2. Queues them into `detection_queue`
3. Samples TS segments from M3U8
4. Extracts audio via FFmpeg
5. Detects language using Whisper
6. Maps to internal `languageMaster` IDs
7. Compares with existing tags
8. Stores results in DB
9. Exports mismatches to CSV

---

## Project Structure

```
language_mapping/
├── src/
│   ├── pipeline.py        # Orchestration (queue + parallel processing)
│   ├── fetcher.py         # M3U8 parsing + TS download
│   ├── processor.py       # FFmpeg merge + audio extraction
│   ├── detector.py        # Whisper language detection
│   ├── lang_utils.py      # Language mapping + match logic
│   ├── db.py              # DB read queries
│   ├── db_writer.py       # Queue + results table writes
│   └── exporter.py        # CSV writer (URL mode)
│
├── main.py                # Entry point
├── fetch_urls.py          # Load videos into queue
├── export_csv.py          # Export DB results to CSV
├── config.py              # All configs
│
├── output/                # CSV outputs
├── temp/                  # TS + WAV temp files
├── logs/                  # Logs
```

---

## Setup

```bash
pip install -r requirements.txt
bash setup.sh
```

### Requirements

- Python 3.10+
- FFmpeg installed
- MySQL access
- 2–6 GB RAM (depending on Whisper model)

---

## Database Tables

### 1. `detection_queue`

| Column           | Description            |
| ---------------- | ---------------------- |
| event_id         | Video ID               |
| cdn_url          | M3U8 URL               |
| current_lang_ids | Existing language tags |
| processed        | 0 = pending, 1 = done  |

### 2. `detection_results`

Stores final detection output:

- detected_lang (ISO)
- detected_lang_id (internal)
- confidence
- lang_match_status
- whisper_model
- error (if any)

---

## Workflow

### Step 1 — Load videos into queue

```bash
python fetch_urls.py --from 2026-01-01 --to 2026-03-31
```

Other modes:

```bash
python fetch_urls.py --all
python fetch_urls.py --event-id 295134
```

### Step 2 — Process queue (parallel)

```bash
python main.py --queue
```

Options:

```bash
python main.py --queue --workers 10
python main.py --queue --model medium
python main.py --queue --no-db   # CSV only
```

### Step 3 — Export results

```bash
python export_csv.py --output output/results.csv
```

Filters:

```bash
--from 2026-01-01
--to 2026-03-31
--status mismatch
```

---

## Testing Modes (No DB)

### Single URL

```bash
python main.py --url "https://..."
```

### Batch URLs

```bash
python main.py --input urls.txt
```

---

## Parallel Processing

Controlled via:

```python
process_queue_parallel(max_workers=10)
```

Each worker:

- Downloads segments
- Extracts audio
- Runs Whisper

Thread-safe model loading and per-video temp isolation are handled automatically.

---

## Language Detection Logic

### Whisper to Internal Mapping

ISO codes are mapped to `languageMaster` IDs. Examples:

- `hi` → 7 (Hindi)
- `te` → 22 (Telugu)

### Match Status

| Status        | Meaning                    |
| ------------- | -------------------------- |
| match         | Exact language match       |
| dialect_match | Dialect resolved to parent |
| mismatch      | Different language         |
| untagged      | No language tag in DB      |
| unmapped      | Whisper lang not mapped    |
| error         | Processing failed          |

---

## Dialect Handling

Whisper cannot detect some Indian dialects, so the following mappings are applied:

| Dialect  | Mapped To     |
| -------- | ------------- |
| Bhojpuri | Hindi         |
| Maithili | Hindi         |
| Dogri    | Hindi         |
| Sindhi   | Urdu          |
| Meitei   | Not supported |
| Santali  | Not supported |

---

## Output (CSV)

Columns:

- event_id
- cdn_url
- current_lang_ids
- current_lang_names
- detected_lang
- detected_lang_id
- detected_lang_name
- confidence
- lang_match_status
- whisper_model
- ts_sampled
- audio_duration_s
- status
- error
- processed_at

---

## Key Features

- Parallel processing for large-scale throughput
- Smart TS sampling (not naive random)
- Dialect-aware matching logic
- Idempotent queue (re-runnable without duplicates)
- Dual output: DB and CSV
- Thread-safe Whisper model loading
- Automatic temp file cleanup
- Mismatch export for QA review

---

## Limitations

- Whisper language detection uses a ~30s audio window
- Very short or silent videos may yield low confidence scores
- Some dialects are unsupported by Whisper
- FFmpeg is a hard dependency
- GPU recommended for large Whisper models

---

## Summary

This is a production-ready pipeline:

**DB → Queue → Parallel Processing → Detection → Validation → Storage → Export**
