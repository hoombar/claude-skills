#!/usr/bin/env python3
"""YouTube Research Podcast Generator

Pipeline: Fetch 10/channel → date filter (14d) → dedup
          → split News/Tutorial → two notebooks → companion note
"""

import os
import re
import argparse
import subprocess
import json
import yt_dlp
from datetime import datetime, timedelta
from pathlib import Path


# --- Constants ---

# Matches notebook titles created by this script
SCRIPT_NB_PATTERN = re.compile(
    r'^AI (?:News |Tutorials )?Catch-up(?: Podcast)? \((\d{4}-\d{2}-\d{2})\)$'
)

# --- Classification keywords ---

TUTORIAL_SIGNALS = [
    'how to', 'tutorial', 'guide', 'course', 'walkthrough', 'step by step',
    'in minutes', 'hands-on', 'hands on', 'master', 'build a', 'build an',
    'create a', 'automate', 'set up', 'setup', 'install',
    'explained', 'full course', 'use cases', 'practical',
]

NEWS_SIGNALS = [
    'news', 'announc', 'just dropped', 'just launched', 'just released',
    ' vs ', 'versus', 'review', 'this week', 'breaking', 'update',
    'compari', 'benchmark', 'prediction', 'future of', 'analysis',
    'sandbox', 'livestream', 'live stream', 'is here', 'recap',
    'opinion', 'terrifying', 'scary',
]


# --- Helpers ---

def run_notebooklm_cmd(cmd_args):
    """Run a notebooklm CLI command, return stdout or None on error."""
    try:
        result = subprocess.run(
            ["notebooklm"] + cmd_args,
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"  notebooklm error: {e.stderr.strip()}")
        return None


def normalize_yt_url(url):
    """Extract video ID and return canonical YouTube URL."""
    m = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    m = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


def classify_video(title):
    """Classify as 'news' or 'tutorial'. Defaults to 'news' when ambiguous."""
    title_lower = title.lower()
    t_score = sum(1 for kw in TUTORIAL_SIGNALS if kw in title_lower)
    n_score = sum(1 for kw in NEWS_SIGNALS if kw in title_lower)
    return 'tutorial' if t_score > n_score else 'news'


# --- Core functions ---

def fetch_latest_videos(channel_url, limit=10):
    """Fetch the latest videos from a channel with upload dates."""
    print(f"  Fetching up to {limit} videos...")
    ydl_opts = {
        'extract_flat': 'in_playlist',
        'playlist_items': f'1-{limit}',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }

    videos = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            fetch_url = channel_url
            if '@' in fetch_url and not fetch_url.endswith('/videos'):
                fetch_url = fetch_url.rstrip('/') + '/videos'

            info = ydl.extract_info(fetch_url, download=False)
            if info and 'entries' in info:
                for entry in info['entries']:
                    if not entry or not entry.get('id'):
                        continue
                    raw_url = entry.get('url', f"https://www.youtube.com/watch?v={entry['id']}")
                    url = normalize_yt_url(raw_url)
                    videos.append({
                        'url': url,
                        'title': entry.get('title', 'Unknown Title'),
                        'upload_date': entry.get('upload_date'),  # YYYYMMDD or None
                    })
    except Exception as e:
        print(f"  Error fetching {channel_url}: {e}")

    return videos


def parse_markdown_feed(filepath):
    """Parse the feed file — returns channels with descriptions and known video URLs."""
    if not os.path.exists(filepath):
        print(f"Error: Feed file not found at {filepath}")
        return None

    content = Path(filepath).read_text(encoding="utf-8")
    channel_pattern = re.compile(r'##\s+\[(.*?)\]\((https?://[^\)]+)\)')
    video_pattern = re.compile(r'-\s+\[(x| )\]\s+(https?://[^\s]+)')

    data = []
    current_channel = None
    pending_desc = []

    for line in content.splitlines():
        chan_match = channel_pattern.search(line)
        if chan_match:
            current_channel = {
                'name': chan_match.group(1),
                'url': chan_match.group(2),
                'description': ' '.join(pending_desc).strip(),
                'videos': {},
            }
            data.append(current_channel)
            pending_desc = []
            continue

        if current_channel:
            vid_match = video_pattern.search(line)
            if vid_match:
                vid_url = normalize_yt_url(vid_match.group(2))
                current_channel['videos'][vid_url] = True
                continue

        # Accumulate description text between channels
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            pending_desc.append(stripped)
        elif stripped.startswith('#'):
            pending_desc = []

    return data


def dedup_feed_file(filepath):
    """Remove duplicate video entries from the feed file (one-time cleanup)."""
    if not os.path.exists(filepath):
        return 0

    lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    video_pattern = re.compile(r'-\s+\[(x| )\]\s+(https?://[^\s]+)')
    channel_pattern = re.compile(r'##\s+\[')

    new_lines = []
    seen_urls = set()
    removed = 0

    for line in lines:
        if channel_pattern.search(line):
            seen_urls = set()  # reset per channel
            new_lines.append(line)
            continue

        vid_match = video_pattern.search(line)
        if vid_match:
            url = normalize_yt_url(vid_match.group(2))
            if url in seen_urls:
                removed += 1
                continue
            seen_urls.add(url)

        new_lines.append(line)

    if removed > 0:
        Path(filepath).write_text('\n'.join(new_lines) + '\n', encoding="utf-8")

    return removed


def cleanup_old_notebooks(max_age_days, dry_run=False):
    """Delete script-created notebooks older than max_age_days."""
    out = run_notebooklm_cmd(["list", "--json"])
    if not out:
        print("Error: Could not list notebooks.")
        return

    notebooks = json.loads(out)
    if isinstance(notebooks, dict):
        notebooks = notebooks.get("notebooks", [])

    cutoff = datetime.now() - timedelta(days=max_age_days)
    candidates = []

    for nb in notebooks:
        title = nb.get("title", "")
        nb_id = nb.get("id", "")
        match = SCRIPT_NB_PATTERN.match(title)
        if match:
            nb_date = datetime.strptime(match.group(1), "%Y-%m-%d")
            if nb_date < cutoff:
                candidates.append((nb_id, title, nb_date))

    if not candidates:
        print(f"No script-created notebooks older than {max_age_days} days found.")
        return

    print(f"Found {len(candidates)} notebook(s) to clean up:\n")
    for nb_id, title, nb_date in candidates:
        age = (datetime.now() - nb_date).days
        if dry_run:
            print(f"  [DRY RUN] Would delete: {title} ({age}d old) [{nb_id}]")
        else:
            print(f"  Deleting: {title} ({age}d old)...", end=" ")
            result = run_notebooklm_cmd(["delete", "-n", nb_id, "-y"])
            print("OK" if result is not None else "FAILED")

    if dry_run:
        print(f"\nRe-run without --dry-run to delete these {len(candidates)} notebook(s).")
    else:
        print(f"\nDeleted {len(candidates)} notebook(s).")


def update_markdown_feed(filepath, new_urls_by_channel):
    """Append newly processed videos to the feed, with dedup protection."""
    if not os.path.exists(filepath):
        return

    lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    channel_pattern = re.compile(r'##\s+\[(.*?)\]\((https?://[^\)]+)\)')
    video_pattern = re.compile(r'-\s+\[(x| )\]\s+(https?://[^\s]+)')

    # Build set of ALL existing URLs per channel for dedup
    existing_urls = {}
    current_ch = None
    for line in lines:
        chan_match = channel_pattern.search(line)
        if chan_match:
            current_ch = chan_match.group(2)
            existing_urls.setdefault(current_ch, set())
            continue
        if current_ch:
            vid_match = video_pattern.search(line)
            if vid_match:
                existing_urls[current_ch].add(normalize_yt_url(vid_match.group(2)))

    # Rebuild file, inserting only genuinely new videos below each channel header
    new_lines = []
    for line in lines:
        new_lines.append(line)

        chan_match = channel_pattern.search(line)
        if chan_match:
            ch_url = chan_match.group(2)
            if ch_url in new_urls_by_channel:
                ch_existing = existing_urls.get(ch_url, set())
                for vid in new_urls_by_channel[ch_url]:
                    normalized = normalize_yt_url(vid['url'])
                    if normalized not in ch_existing:
                        new_lines.append(f"- [x] {vid['url']} ({vid['title']})")
                        ch_existing.add(normalized)

    Path(filepath).write_text('\n'.join(new_lines) + '\n', encoding="utf-8")


def process_to_notebooklm(videos, notebook_title):
    """Create a NotebookLM notebook, add video sources, trigger podcast generation."""
    if not videos:
        return None

    print(f"\nCreating notebook: '{notebook_title}'...")
    out = run_notebooklm_cmd(["create", notebook_title, "--json"])
    if not out:
        return None

    nb_data = json.loads(out)
    nb_id = nb_data.get("notebook", {}).get("id")
    if not nb_id:
        print("Error: Could not extract notebook ID.")
        return None

    print(f"  Notebook ID: {nb_id}")

    source_ids = []
    for vid in videos:
        print(f"  Adding: {vid['title'][:60]}...")
        src_out = run_notebooklm_cmd(["source", "add", "-n", nb_id, vid['url'], "--json"])
        if src_out:
            try:
                s_id = json.loads(src_out).get("source", {}).get("id")
                if s_id:
                    source_ids.append(s_id)
            except json.JSONDecodeError:
                pass
        else:
            print(f"    Failed — skipping")

    if not source_ids:
        print("  No sources added. Aborting notebook.")
        return None

    print(f"  Waiting for {len(source_ids)} sources to index...")
    for s_id in source_ids:
        run_notebooklm_cmd(["source", "wait", "-n", nb_id, s_id])

    print("  Triggering audio generation...")
    gen_out = run_notebooklm_cmd([
        "generate", "audio", "-n", nb_id,
        "Create a deep-dive podcast covering the key themes and insights from these videos.",
        "--no-wait", "--json"
    ])

    if gen_out:
        try:
            task_id = json.loads(gen_out).get("task_id")
            print(f"  Audio triggered. Task ID: {task_id}")
        except json.JSONDecodeError:
            print("  Audio triggered (could not parse task ID).")
        return nb_id

    return None


def write_companion_note(output_dir, timestamp, news_videos, tutorial_videos, filtered_out):
    """Write a companion note listing included and skipped videos."""
    note_dir = Path(output_dir)
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / f"podcast-companion-{timestamp}.md"

    lines = [
        f"# Podcast Companion — {timestamp}",
        "",
    ]

    if news_videos:
        lines.append(f"## News Podcast ({len(news_videos)} sources)")
        lines.append("")
        for v in news_videos:
            lines.append(f"- [{v['title']}]({v['url']}) — {v.get('channel', '')}")
        lines.append("")

    if tutorial_videos:
        lines.append(f"## Tutorial Podcast ({len(tutorial_videos)} sources)")
        lines.append("")
        for v in tutorial_videos:
            lines.append(f"- [{v['title']}]({v['url']}) — {v.get('channel', '')}")
        lines.append("")

    if filtered_out:
        lines.append(f"## Skipped — Too Old ({len(filtered_out)} videos)")
        lines.append("")
        for v in filtered_out:
            lines.append(f"- ~~[{v['title']}]({v['url']})~~ — {v.get('upload_date', 'no date')}")
        lines.append("")

    note_path.write_text('\n'.join(lines), encoding="utf-8")
    print(f"\nCompanion note: {note_path}")
    return note_path


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description="YouTube Research Podcast Generator"
    )
    parser.add_argument("--feed", default="youtube_feed.md",
                        help="Path to the markdown feed file (default: youtube_feed.md)")
    parser.add_argument("--max-per-channel", type=int, default=10,
                        help="Max recent videos to fetch per channel (default: 10)")
    parser.add_argument("--max-age-days", type=int, default=14,
                        help="Only include videos from the last N days (default: 14)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Find and filter videos but do not upload or update feed")
    parser.add_argument("--cleanup-dupes", action="store_true",
                        help="Remove duplicate entries from feed file and exit")
    parser.add_argument("--cleanup", action="store_true",
                        help="Delete old script-created notebooks and exit")
    parser.add_argument("--cleanup-max-age-days", type=int, default=60,
                        help="Notebooks older than N days are deleted (default: 60)")
    parser.add_argument("--output-dir", default=".",
                        help="Directory for companion note output (default: current dir)")

    args = parser.parse_args()

    # One-time cleanup modes
    if args.cleanup_dupes:
        removed = dedup_feed_file(args.feed)
        print(f"Removed {removed} duplicate entries from {args.feed}")
        return

    if args.cleanup:
        cleanup_old_notebooks(args.cleanup_max_age_days, dry_run=args.dry_run)
        return

    print(f"Reading feed: {args.feed}")
    feed_data = parse_markdown_feed(args.feed)
    if not feed_data:
        print("No channels found.")
        return

    cutoff_date = datetime.now() - timedelta(days=args.max_age_days)
    cutoff_str = cutoff_date.strftime('%Y%m%d')
    print(f"Date cutoff: {cutoff_date.strftime('%Y-%m-%d')} ({args.max_age_days} days)")
    print(f"Channels: {len(feed_data)}\n")

    all_new = []
    new_by_channel = {}
    filtered_out = []

    for channel in feed_data:
        print(f"[{channel['name']}]")
        videos = fetch_latest_videos(channel['url'], limit=args.max_per_channel)

        for vid in videos:
            vid['channel'] = channel['name']
            url = normalize_yt_url(vid['url'])

            # Dedup: skip if already in feed
            if url in channel['videos']:
                continue

            # Date filter: skip old videos (if date available)
            if vid.get('upload_date') and vid['upload_date'] < cutoff_str:
                filtered_out.append({**vid, 'filter_reason': f"too old ({vid['upload_date']})"})
                print(f"    SKIP (old): {vid['title'][:50]}... [{vid['upload_date']}]")
                continue

            print(f"    NEW: {vid['title'][:60]}...")
            all_new.append(vid)
            new_by_channel.setdefault(channel['url'], []).append(vid)

    if not all_new:
        print("\nNo new videos found.")
        if filtered_out:
            print(f"({len(filtered_out)} videos were filtered out)")
        return

    # Split into news and tutorials
    news_videos = [v for v in all_new if classify_video(v['title']) == 'news']
    tutorial_videos = [v for v in all_new if classify_video(v['title']) == 'tutorial']

    print(f"\n{'='*60}")
    print(f"New videos: {len(all_new)} (News: {len(news_videos)}, Tutorial: {len(tutorial_videos)})")
    print(f"Filtered out: {len(filtered_out)}")
    print(f"{'='*60}")

    if args.dry_run:
        print("\n[DRY RUN] Would create:")
        if news_videos:
            print(f"\n  News podcast ({len(news_videos)} sources):")
            for v in news_videos:
                print(f"    - {v['title']}")
        if tutorial_videos:
            print(f"\n  Tutorial podcast ({len(tutorial_videos)} sources):")
            for v in tutorial_videos:
                print(f"    - {v['title']}")
        if filtered_out:
            print(f"\n  Skipped — too old ({len(filtered_out)}):")
            for v in filtered_out:
                print(f"    - {v['title']} [{v.get('upload_date', 'no date')}]")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d")
    notebooks_created = []

    # Generate news podcast
    if news_videos:
        nb_id = process_to_notebooklm(news_videos, f"AI News Catch-up ({timestamp})")
        if nb_id:
            notebooks_created.append(('news', nb_id))

    # Generate tutorial podcast
    if tutorial_videos:
        nb_id = process_to_notebooklm(tutorial_videos, f"AI Tutorials Catch-up ({timestamp})")
        if nb_id:
            notebooks_created.append(('tutorial', nb_id))

    # Fallback: single notebook if neither split produced results
    if not notebooks_created and all_new:
        nb_id = process_to_notebooklm(all_new, f"AI Catch-up Podcast ({timestamp})")
        if nb_id:
            notebooks_created.append(('mixed', nb_id))

    if notebooks_created:
        print("\nUpdating feed file...")
        update_markdown_feed(args.feed, new_by_channel)
        print("Feed updated.")

        write_companion_note(args.output_dir, timestamp, news_videos, tutorial_videos, filtered_out)

        # Clean up old notebooks
        print("\nCleaning up old notebooks...")
        cleanup_old_notebooks(args.cleanup_max_age_days)

        print(f"\nDone! Created {len(notebooks_created)} notebook(s):")
        for kind, nb_id in notebooks_created:
            print(f"  [{kind}] {nb_id}")
    else:
        print("\nFailed to create any notebooks. Feed not updated.")


if __name__ == "__main__":
    main()
