---
name: youtube-podcast-generator
description: Generate NotebookLM audio podcasts from curated YouTube channels. Fetches recent videos, splits into News and Tutorial podcasts, tracks processed videos in a markdown feed file, and cleans up old notebooks automatically.
allowed-tools: Bash(python3 *, notebooklm *)
---

# YouTube Podcast Generator

Automates the pipeline: curated YouTube channels -> fetch recent videos -> split News/Tutorial -> NotebookLM podcasts.

## Prerequisites

The following must be installed and authenticated before use:

```bash
# YouTube video metadata fetcher
pip3 install yt-dlp
# or: brew install yt-dlp

# Unofficial NotebookLM CLI (uses reverse-engineered Google APIs)
pip3 install "notebooklm-py[browser]"

# One-time browser login to NotebookLM
notebooklm login
```

> `notebooklm-py` uses unofficial APIs and updates frequently. Run `pip3 install --upgrade "notebooklm-py[browser]"` if you hit errors.

## Setup

1. Copy `youtube_feed.example.md` to `youtube_feed.md` (or any name you like)
2. Edit it to add your YouTube channels using the format shown in the example
3. Run the script

## Feed File Format

```markdown
Description of the channel (optional, for your reference)
## [Channel Name](https://www.youtube.com/@ChannelHandle)
- [x] https://www.youtube.com/watch?v=xxx (Already processed video)
```

The script discovers new videos via yt-dlp and appends them as `- [x]` entries after processing.

## Running

The script is bundled at `youtube_research_podcast.py` in this skill's directory.

```bash
# Standard run — fetches, splits, creates notebooks, updates feed
python3 <skill-dir>/youtube_research_podcast.py

# Preview what would happen without making changes
python3 <skill-dir>/youtube_research_podcast.py --dry-run

# Point to a custom feed file
python3 <skill-dir>/youtube_research_podcast.py --feed path/to/my_feed.md

# Clean up duplicate entries in the feed file
python3 <skill-dir>/youtube_research_podcast.py --cleanup-dupes

# Delete old notebooks (standalone)
python3 <skill-dir>/youtube_research_podcast.py --cleanup --dry-run
```

## CLI Flags

| Flag | Default | Description |
|---|---|---|
| `--feed` | `youtube_feed.md` | Path to the markdown feed file |
| `--max-per-channel` | `10` | Videos to fetch per channel |
| `--max-age-days` | `14` | Drop videos older than N days |
| `--dry-run` | off | Preview only, no uploads or feed changes |
| `--cleanup-dupes` | off | Remove duplicate entries from feed and exit |
| `--cleanup` | off | Delete old script-created notebooks and exit |
| `--cleanup-max-age-days` | `60` | Notebooks older than N days are deleted |
| `--output-dir` | `.` | Directory for companion note output |

## What It Does

1. Parses your feed file to find YouTube channels and already-processed videos
2. Fetches the 10 most recent videos per channel via yt-dlp
3. Filters out videos already in the feed (dedup) and videos older than 14 days
4. Splits new videos into **News** and **Tutorial** categories by title keywords
5. Creates two NotebookLM notebooks and triggers audio podcast generation for each
6. Updates the feed file with newly processed videos
7. Writes a companion note listing what was included and what was skipped
8. Cleans up script-created notebooks older than 60 days

## Output

After running, the script prints:
- Notebook IDs and Task IDs for tracking generation progress
- Path to the companion note

Check generation status with:
```bash
notebooklm artifact poll <task_id>
```
