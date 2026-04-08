# Kobo EPUB Pipeline

Generate one long-form AI deep-dive EPUB per run and deliver it with a pull-friendly sync path for Kobo.

## How It Works

Mermaid source file: [`pipeline.mmd`](pipeline.mmd)

```mermaid
flowchart TD
  A[Run: cron or manual] --> B[Load sources.yaml and queue.json]
  B --> C[Discover candidates<br/>arXiv + RSS]
  C --> D[Fetch social signals<br/>HN + Reddit]
  D --> E[Score and update pending queue]
  E --> F{--dry-run?}
  F -->|yes| G[Save queue and exit]
  F -->|no| H[Select topic<br/>top score or --topic-id]
  H --> I[Fetch full content<br/>PDF, HTML, or summary fallback]
  I --> J[Generate draft<br/>claude --print]
  J --> K[Run critic pass<br/>JSON concerns]
  K --> L[Assemble final Markdown<br/>+ Critic Notes]
  L --> M[Render Mermaid blocks to PNG]
  M --> N[Build EPUB with pandoc]
  N --> O{delivery.mode}
  O -->|gws_drive| P[Upload EPUB to Google Drive]
  O -->|pull| Q[Copy EPUB to local inbox]
  O -->|none| R[Skip delivery]
  P --> S{Delivery confirmed?}
  Q --> S
  R --> S
  S -->|yes| T[Move topic pending -> processed]
  S -->|no| U[Keep topic in pending for retry]
  T --> V[Save queue.json]
  U --> V
```

## Prerequisites

- Python: `python3`
- Python packages:
  - `feedparser`
  - `arxiv`
  - `requests`
  - `pyyaml`
  - `beautifulsoup4`
  - `pdfminer.six` (optional but recommended for PDF extraction)
- External CLIs:
  - `claude`
  - `pandoc`
  - `mmdc`
  - `gws` (required for `delivery.mode: gws_drive`)

## Quick Start

```bash
cd skills/kobo-epub-pipeline
cp kobo_reader_state/sources.example.yaml kobo_reader_state/sources.yaml
```

Edit `kobo_reader_state/sources.yaml`:

- Set `delivery.mode` (recommended: `gws_drive`)
- Set `delivery.gws_drive.folder_id`
- Optionally set `delivery.gws_drive.config_dir` for machine-profile isolation

Run the pipeline:

```bash
# Crawl, score, and queue only
python3 kobo_daily_reader.py --dry-run

# Build one EPUB and deliver according to delivery.mode
python3 kobo_daily_reader.py
```

Useful flags:

```bash
# Build only, skip delivery
python3 kobo_daily_reader.py --no-sync --output-dir ~/Desktop

# Force a specific queued topic
python3 kobo_daily_reader.py --topic-id arxiv:2401.12345v1
```

## Delivery Semantics

- A topic is moved from `pending` to `processed` only after delivery succeeds.
- If delivery fails, the topic stays in `pending` and is retried on the next run.
- This makes the pipeline queue-safe for intermittent network or service failures.

See [`SKILL.md`](SKILL.md) for full setup and troubleshooting details.
