---
name: kobo-epub-pipeline
description: Generate long-form AI deep-dive EPUBs for Kobo from high-signal single-source topics and deliver them through Google Drive pull sync. Use when the user wants to set up, run, debug, or automate a Kobo EPUB pipeline with source discovery, practical topic scoring, queueing, Claude/Codex generation, critic pass, EPUB build, retention, and Drive upload.
allowed-tools: Bash(python3 *), Bash(pip3 *), Bash(uv *), Bash(claude *), Bash(codex *), Bash(gws *), Bash(dot *), Bash(mmdc *), Bash(pandoc *), Bash(kepubify *)
---

# Kobo EPUB Pipeline

Build and run a Kobo deep-dive EPUB pipeline that selects one high-value single-source topic, generates a guided explainer, runs a critic pass, builds an EPUB, and delivers it through a Kobo-friendly pull sync path.

## What This Skill Includes

- `kobo_daily_reader.py` — end-to-end pipeline script.
- `kobo_reader_state/sources.example.yaml` — editable source, scoring, generation, build, and delivery config template.
- `pipeline.mmd` — architecture diagram source.
- Runtime queue state in `kobo_reader_state/queue.json` is auto-created next to the config.

## Current Strategy

- Default selection mode is `single_source_deep_read`.
- The pipeline prefers practical, durable material over news: agent harnesses, evals, context engineering, coding agents, mobile/platform implications, and personal AI workflow ideas.
- Candidate scoring combines relevance, practicality, evidence, durability, freshness, novelty, and source quality.
- Source cooldown and 120-day novelty checks reduce repeat topics.
- Multi-source clustering remains available as a fallback when no single-source candidate is eligible.
- EPUBs include source provenance and critic notes so source quality can be audited later.

## Prerequisites

Install Python packages in an isolated environment where possible:

```bash
uv venv /path/to/venv
uv pip install --python /path/to/venv/bin/python feedparser arxiv requests pyyaml beautifulsoup4 pdfminer.six
```

Required or commonly used CLIs:

```bash
claude --version
codex --version
gws drive files list --params '{"pageSize":1}'
dot -V
pandoc --version
```

Optional CLIs:

```bash
mmdc -h
kepubify --version
```

## Initial Setup

1. Copy the config template:

```bash
cp <skill-dir>/kobo_reader_state/sources.example.yaml <skill-dir>/kobo_reader_state/sources.yaml
```

2. Edit `sources.yaml`:

- Set `delivery.gws_drive.folder_id` to your Kobo Drive folder ID.
- If needed, set `delivery.gws_drive.config_dir` to a dedicated machine-profile config directory.
- Keep `delivery.mode: gws_drive` unless you explicitly want local staging through `pull`.
- Select model backend with `generation.provider`: `codex` or `claude`.
- Tune `generation.target_read_minutes`, `generation.words_per_minute`, `generation.target_words`, and `generation.hard_max_words`.
- Add high-signal manual URLs under `curated_sources` only when you want to seed a specific topic.
- Tune `rss_feeds`, `html_indexes`, and targeted `arxiv.queries` as the primary discovery surface.
- Keep `build.cover_enabled: true` unless generated covers cause a device-specific rendering issue.
- Enable `build.prefer_kepub: true` only after `kepubify` is installed and validated.

## Running

```bash
# Crawl, score, and queue only
python3 <skill-dir>/kobo_daily_reader.py --dry-run

# Build one EPUB and deliver according to delivery.mode
python3 <skill-dir>/kobo_daily_reader.py

# Build exactly one item from the ranked queue
python3 <skill-dir>/kobo_daily_reader.py --count 1

# Build only, skip delivery
python3 <skill-dir>/kobo_daily_reader.py --no-sync --output-dir ~/Desktop

# Force one queued topic ID from --dry-run output
python3 <skill-dir>/kobo_daily_reader.py --topic-id rss:abc123def45678
```

## EPUB Build Defaults

- Output filenames preserve spaces for Kobo wrapping: `YYYYMMDD - Topic Title - source id.epub`.
- Pandoc metadata includes `title`, `author`, and `publisher`.
- A simple SVG cover is generated from the title, date, source label, and publisher.
- If cover generation or Pandoc cover handling fails, the script logs a warning and retries without the cover.
- Graphviz DOT blocks render to PNG. Mermaid remains a legacy fallback only.
- Optional KEPUB conversion runs when `build.prefer_kepub: true`.

## Delivery Behavior

- Default delivery is pull-based: the script uploads EPUBs to Drive and Kobo fetches them on `Sync now`.
- The script only moves a topic to `processed` after successful delivery.
- Failed delivery keeps the topic in `pending` for retry on the next run.
- Optional Drive retention can purge old generated EPUBs by age and filename pattern.

## Cron

Use a lock and timeout so long-running generation does not overlap the next scheduled run:

```cron
0 5 * * 0,4 flock -n /home/ben/.cache/kobo_daily_reader.lock timeout --signal=TERM --kill-after=60s 45m /path/to/venv/bin/python -u /path/to/kobo_daily_reader.py --count 1 >> /path/to/logs/kobo_daily_reader.log 2>&1
```

## Troubleshooting

- `sources.yaml not found`: copy it from `sources.example.yaml`.
- `gws upload failed`: verify auth, write-profile config, and folder ID.
- `codex` or `claude` not found from cron: set an explicit cron `PATH` or use absolute binary paths.
- `pandoc not found`: install Pandoc on the machine that builds EPUBs.
- DOT diagrams fail: install Graphviz and verify `dot -V` works.
- Kobo does not show file: run Kobo `Sync now` and verify the EPUB exists in the target Drive folder.
- Generated reads feel shallow: reduce radar/news source authority, add practical `include_keywords`, or seed a known-good URL under `curated_sources`.
