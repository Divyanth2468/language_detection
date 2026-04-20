.PHONY: install setup freeze \
        queue queue-workers queue-model queue-no-db \
        fetch fetch-all fetch-event \
        export export-mismatch \
        run-url run-batch \
        clean clean-temp clean-logs clean-all

# ──────────────────────────────────────────
# Setup
# ──────────────────────────────────────────

install:
	pip install -r requirements.txt

setup:
	pip install -r requirements.txt
	bash setup.sh

freeze:
	pip freeze > requirements.txt


# ──────────────────────────────────────────
# Step 1 — Load videos into queue
# ──────────────────────────────────────────

fetch:
	python fetch_urls.py --from $(FROM) --to $(TO)

fetch-all:
	python fetch_urls.py --all

fetch-event:
	python fetch_urls.py --event-id $(ID)


# ──────────────────────────────────────────
# Step 2 — Process queue
# ──────────────────────────────────────────

queue:
	python main.py --queue

queue-workers:
	python main.py --queue --workers $(WORKERS)

queue-model:
	python main.py --queue --model $(MODEL)

queue-no-db:
	python main.py --queue --no-db


# ──────────────────────────────────────────
# Step 3 — Export results
# ──────────────────────────────────────────

export:
	python export_csv.py --output output/results.csv

export-mismatch:
	python export_csv.py --output output/mismatches.csv --status mismatch

export-range:
	python export_csv.py --output output/results.csv --from $(FROM) --to $(TO)


# ──────────────────────────────────────────
# Testing (no DB)
# ──────────────────────────────────────────

run-url:
	python main.py --url "$(URL)"

run-batch:
	python main.py --input $(FILE)


# ──────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────

clean-temp:
	rm -rf temp/*

clean-logs:
	rm -rf logs/*

clean-output:
	rm -rf output/*

clean-all:
	rm -rf temp/* logs/* output/*
