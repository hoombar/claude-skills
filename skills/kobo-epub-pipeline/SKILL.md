---
name: kobo-epub-pipeline
description: Generate long-form AI deep-dive EPUBs for Kobo from multi-source topic clusters and deliver them through Google Drive pull sync. Use when the user wants to set up, run, debug, or automate a Kobo EPUB pipeline with source discovery, semantic topic clustering, queueing, Claude/Codex generation, critic pass, EPUB build, and Drive upload.
allowed-tools: Bash(python3 *), Bash(pip3 *), Bash(claude *), Bash(gws *), Bash(mmdc *), Bash(pandoc *)
---

# Kobo EPUB Pipeline

Build and run a Kobo deep-dive EPUB pipeline backed by semantic topic clustering, a persistent cluster queue, and Google Drive pull delivery.

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
- Keep `build.publisher` set to the desired Kobo library publisher (default: `Ben Pearson`).
- Keep `build.cover_enabled: true` unless cover generation causes a device-specific rendering issue.

3. Keep delivery mode as `gws_drive` unless you explicitly want local staging (`pull`).

## EPUB Build Defaults

- Output filenames preserve spaces for Kobo wrapping: `YYYYMMDD - Topic Title - source id.epub`.
- The script writes Pandoc `title`, `author`, and `publisher` metadata.
- A simple per-article SVG cover is generated from the title, date, source label, and publisher, then passed to Pandoc with `--epub-cover-image`.
- If cover generation or Pandoc cover handling fails, the script logs a warning and retries without the cover.

## Running

```bash
# Crawl, cluster, and score only
python3 <skill-dir>/kobo_daily_reader.py --dry-run

# Build one EPUB and upload to Drive
python3 <skill-dir>/kobo_daily_reader.py

# Build only, skip delivery
python3 <skill-dir>/kobo_daily_reader.py --no-sync --output-dir ~/Desktop

# Force one queued cluster ID
python3 <skill-dir>/kobo_daily_reader.py --topic-id cluster:abc123def45678
```

## Delivery Behavior

- Delivery is pull-based: script uploads EPUBs to Drive, Kobo fetches them on `Sync now`.
- The script only moves a topic cluster to `processed` after successful delivery.
- Failed delivery keeps the cluster in `pending` for retry on the next run.

## Cron

```cron
0 5 * * 0,4 /usr/bin/python3 /path/to/kobo_daily_reader.py >> ~/logs/kobo_daily_reader.log 2>&1
```

## Troubleshooting

- `sources.yaml not found`: copy from `sources.example.yaml`.
- `gws upload failed`: verify machine profile auth and folder ID.
- `pandoc not found` or `mmdc` failures: install required tooling and re-run.
- Kobo does not show file: run Kobo `Sync now` and verify file exists in the target Drive folder.
