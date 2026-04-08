---
name: kobo-epub-pipeline
description: Generate daily long-form AI deep-dive EPUBs for Kobo and deliver them through Google Drive pull sync. Use when the user wants to set up, run, debug, or automate a Kobo EPUB pipeline with topic discovery, queueing, Claude generation, critic pass, EPUB build, and Drive upload.
allowed-tools: Bash(python3 *), Bash(pip3 *), Bash(claude *), Bash(gws *), Bash(mmdc *), Bash(pandoc *)
---

# Kobo EPUB Pipeline

Build and run a daily Kobo deep-dive EPUB pipeline backed by a persistent topic queue and Google Drive pull delivery.

## What This Skill Includes

- `kobo_daily_reader.py` — end-to-end pipeline script
- `kobo_reader_state/sources.example.yaml` — editable source and delivery config template
- Runtime queue state in `kobo_reader_state/queue.json` (auto-created)

## Prerequisites

Install and authenticate before running:

```bash
pip3 install feedparser arxiv requests pyyaml beautifulsoup4
pip3 install pdfminer.six
claude --version
gws drive files list --params '{"pageSize":1}'
```

Also required for EPUB rendering:

```bash
mmdc -h
pandoc --version
```

## Initial Setup

1. Copy config template:

```bash
cp <skill-dir>/kobo_reader_state/sources.example.yaml <skill-dir>/kobo_reader_state/sources.yaml
```

2. Edit `sources.yaml`:
- Set `delivery.gws_drive.folder_id` to your Kobo Drive folder ID.
- If needed, set `delivery.gws_drive.config_dir` to your write-profile config directory.
- Tune RSS feeds, scoring, and model settings.

3. Keep delivery mode as `gws_drive` unless you explicitly want local staging (`pull`).

## Running

```bash
# Crawl and score only
python3 <skill-dir>/kobo_daily_reader.py --dry-run

# Build one EPUB and upload to Drive
python3 <skill-dir>/kobo_daily_reader.py

# Build only, skip delivery
python3 <skill-dir>/kobo_daily_reader.py --no-sync --output-dir ~/Desktop

# Force one queued topic ID
python3 <skill-dir>/kobo_daily_reader.py --topic-id arxiv:2401.12345v1
```

## Delivery Behavior

- Delivery is pull-based: script uploads EPUBs to Drive, Kobo fetches them on `Sync now`.
- The script only moves a topic to `processed` after successful delivery.
- Failed delivery keeps the topic in `pending` for retry on the next run.

## Cron

```cron
0 5 * * * /usr/bin/python3 /path/to/kobo_daily_reader.py >> ~/logs/kobo_daily_reader.log 2>&1
```

## Troubleshooting

- `sources.yaml not found`: copy from `sources.example.yaml`.
- `gws upload failed`: verify machine profile auth and folder ID.
- `pandoc not found` or `mmdc` failures: install required tooling and re-run.
- Kobo does not show file: run Kobo `Sync now` and verify file exists in the target Drive folder.
