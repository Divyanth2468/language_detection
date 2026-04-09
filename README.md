# M3U8 Language Mapper

Detects the spoken language in M3U8 HLS streams using Whisper, processes videos in parallel, and exports results to CSV.

---

## Project Structure

```
language_mapping/
├── src/
│   ├── fetcher.py
│   ├── processor.py
│   ├── detector.py
│   ├── exporter.py
│   ├── db.py
│   ├── db_writer.py
│   ├── lang_utils.py
│   └── pipeline.py
├── output/
├── temp/
├── logs/
├── config.py
├── fetch_urls.py
├── main.py
├── export_csv.py
├── requirements.txt
└── setup.sh
```

---

## Workflow

```bash
# Step 1 — Load videos into queue
python fetch_urls.py --from 2026-01-01 --to 2026-03-31

# Step 2 — Process queue
python main.py --queue

# Step 3 — Export results
python export_csv.py --output output/results.csv
```

---

## Performance

- Sequential: ~6–10 seconds per video
- Parallel: ~1–2 seconds per video

Parallel processing significantly reduces total runtime for large datasets.

---

## Configuration

Edit `config.py`:

```python
WHISPER_MODEL = "small"   # or "medium"
TS_SAMPLE_COUNT = 10
AUDIO_CLIP_SECONDS = 90
```

---

## Parallel Processing

Configured in the pipeline:

```python
process_queue_parallel(max_workers=6)
```

Adjust `max_workers` based on your system.

---

## Output

CSV includes:

- event_id
- cdn_url
- detected language
- language name
- confidence
- match status

---

## Notes

- Better accuracy with `small` or `medium` models
- Very short audio clips may reduce accuracy
- Some languages may be mapped to a default value if unsupported

---

## Summary

- Queue-based processing using database
- Parallel execution for faster throughput
- Whisper-based language detection
- CSV export for reporting

---
