#!/usr/bin/env python3
"""Kobo Daily AI Deep-Dive Reader

Crawls primary AI sources, picks the highest-scored topic from a persistent
queue, generates a 20-minute deep-dive EPUB via Claude Opus, runs a single
adversarial critic pass, and delivers via a configurable backend:
Google Drive upload (recommended) or local pull-staging.

Dependencies (pip install):
    feedparser arxiv requests pyyaml beautifulsoup4

Optional (for better arXiv PDF extraction):
    pdfminer.six

Claude Code must be installed and authenticated on this machine:
    https://claude.ai/download
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from calendar import timegm
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
STATE_DIR = SCRIPT_DIR / "kobo_reader_state"
QUEUE_FILE = STATE_DIR / "queue.json"
SOURCES_FILE = STATE_DIR / "sources.yaml"

# Keywords used to assess whether HN / Reddit content is AI-related
AI_KEYWORDS = [
    "llm", "large language model", "language model", "transformer",
    "diffusion model", "reinforcement learning", "rlhf", "fine-tuning",
    "fine tuning", "pre-training", "chain of thought", "reasoning model",
    "multimodal", "embedding", "retrieval augmented", "rag", "ai agent",
    "claude", "gpt", "gemini", "llama", "mistral", "deepseek", "qwen",
    "anthropic", "openai", "deepmind", "ai safety", "alignment",
    "neural network", "foundation model", "inference", "tokenizer",
]

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_queue():
    if not QUEUE_FILE.exists():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        return {"pending": [], "processed": []}
    return json.loads(QUEUE_FILE.read_text())


def save_queue(queue):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, default=str))


def load_sources():
    if not SOURCES_FILE.exists():
        print(f"sources.yaml not found. Expected at: {SOURCES_FILE}")
        print("Copy kobo_reader_state/sources.example.yaml to sources.yaml and configure it.")
        sys.exit(1)
    return yaml.safe_load(SOURCES_FILE.read_text())


def make_topic_id(url, title):
    """Stable short ID from URL (preferred) or title hash."""
    return hashlib.sha1((url or title).encode()).hexdigest()[:14]


def is_processed(queue, tid):
    return any(p["id"] == tid for p in queue.get("processed", []))


# ---------------------------------------------------------------------------
# Source crawlers
# ---------------------------------------------------------------------------

def fetch_arxiv(cfg, days_back):
    candidates = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    try:
        import arxiv as arxiv_lib
    except ImportError:
        print("  [arXiv] 'arxiv' package not installed — skipping. pip install arxiv")
        return candidates

    for category in cfg.get("categories", []):
        print(f"  arXiv [{category}]...")
        try:
            client = arxiv_lib.Client()
            search = arxiv_lib.Search(
                query=f"cat:{category}",
                max_results=cfg.get("max_results_per_category", 15),
                sort_by=arxiv_lib.SortCriterion.SubmittedDate,
            )
            for paper in client.results(search):
                if paper.published and paper.published < cutoff:
                    break
                raw_id = paper.entry_id.split("/")[-1]  # e.g. "2401.12345v1"
                tid = f"arxiv:{raw_id}"
                candidates.append({
                    "id": tid,
                    "title": paper.title.strip(),
                    "summary": paper.summary.replace("\n", " ")[:600],
                    "url": paper.entry_id,
                    "pdf_url": paper.pdf_url,
                    "source_name": f"arXiv ({category})",
                    "authority": 0.95,
                    "published": paper.published.isoformat() if paper.published else None,
                    "authors": [a.name for a in paper.authors[:3]],
                    "social": {"hn_points": 0, "reddit_score": 0},
                })
        except Exception as e:
            print(f"    arXiv error [{category}]: {e}")
    return candidates


def fetch_rss(feeds_cfg, days_back):
    candidates = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    for feed_conf in feeds_cfg:
        name = feed_conf["name"]
        url = feed_conf["url"]
        authority = feed_conf.get("authority", 0.7)
        print(f"  RSS [{name}]...")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                pub = datetime.fromtimestamp(timegm(parsed), tz=timezone.utc) if parsed else None
                if pub and pub < cutoff:
                    continue
                summary = re.sub(r"<[^>]+>", " ", getattr(entry, "summary", "") or "").strip()
                link = getattr(entry, "link", "")
                tid = f"rss:{make_topic_id(link, entry.title)}"
                candidates.append({
                    "id": tid,
                    "title": entry.title.strip(),
                    "summary": summary[:600],
                    "url": link,
                    "pdf_url": None,
                    "source_name": name,
                    "authority": authority,
                    "published": pub.isoformat() if pub else None,
                    "authors": [],
                    "social": {"hn_points": 0, "reddit_score": 0},
                })
        except Exception as e:
            print(f"    RSS error [{name}]: {e}")
    return candidates


def fetch_hn_signal(cfg, days_back):
    """Returns {url: hn_points} for AI-related stories."""
    if not cfg.get("enabled", True):
        return {}
    signal = {}
    cutoff_ts = int((datetime.now() - timedelta(days=days_back)).timestamp())
    try:
        r = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "tags": "story",
                "numericFilters": f"points>={cfg.get('min_points', 100)},created_at_i>={cutoff_ts}",
                "hitsPerPage": 100,
            },
            timeout=15,
        )
        r.raise_for_status()
        for hit in r.json().get("hits", []):
            title_lower = hit.get("title", "").lower()
            url = hit.get("url", "")
            if url and any(kw in title_lower for kw in AI_KEYWORDS):
                signal[url] = signal.get(url, 0) + hit.get("points", 0)
    except Exception as e:
        print(f"  HN signal error: {e}")
    return signal


def fetch_reddit_signal(cfg, days_back):
    """Returns {title_key: score} for top AI subreddit posts."""
    if not cfg.get("enabled", True):
        return {}
    signal = {}
    headers = {"User-Agent": "kobo-daily-reader/1.0"}
    for sub in cfg.get("subreddits", []):
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/top.json",
                params={"limit": 50, "t": "day"},
                headers=headers,
                timeout=15,
            )
            r.raise_for_status()
            for post in r.json().get("data", {}).get("children", []):
                data = post.get("data", {})
                score = data.get("score", 0)
                if score >= cfg.get("min_score", 50):
                    key = re.sub(r"\W+", "_", data.get("title", "").lower())[:50]
                    signal[key] = signal.get(key, 0) + score
        except Exception as e:
            print(f"  Reddit signal error [r/{sub}]: {e}")
    return signal


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_candidate(c, hn_signal, reddit_signal, queue, weights, half_life_days):
    authority = c.get("authority", 0.5) * weights.get("authority", 0.40)

    hn_pts = hn_signal.get(c.get("url", ""), 0)
    reddit_pts = reddit_signal.get(
        re.sub(r"\W+", "_", c.get("title", "").lower())[:50], 0
    )
    social = max(min(hn_pts / 800, 1.0), min(reddit_pts / 400, 1.0)) * weights.get("social", 0.30)

    recency = 0.5
    if c.get("published"):
        try:
            pub_str = c["published"].replace("Z", "+00:00")
            pub = datetime.fromisoformat(pub_str)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - pub).total_seconds() / 86400
            recency = 0.5 ** (age / max(half_life_days, 1))
        except Exception:
            pass
    recency *= weights.get("recency", 0.20)

    diversity = weights.get("diversity", 0.10)
    recent_sources = [p.get("source_name") for p in queue.get("processed", [])[-5:]]
    if c.get("source_name") in recent_sources:
        diversity *= 0.4

    return round(authority + social + recency + diversity, 4)


# ---------------------------------------------------------------------------
# Content fetching
# ---------------------------------------------------------------------------

def fetch_content(topic, max_chars):
    """Fetch full readable text for the selected topic."""
    content = topic.get("summary", "")
    url = topic.get("pdf_url") or topic.get("url", "")
    if not url:
        return content

    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; kobo-reader/1.0)"}
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        ctype = r.headers.get("content-type", "")
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            try:
                import pdfminer.high_level as pm
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(r.content)
                    tmp = f.name
                text = pm.extract_text(tmp)
                os.unlink(tmp)
                content = text[:max_chars]
            except ImportError:
                print("    pdfminer not installed — using abstract only. pip install pdfminer.six")
        else:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                content = soup.get_text(separator="\n", strip=True)[:max_chars]
            except ImportError:
                content = re.sub(r"<[^>]+>", " ", r.text)[:max_chars]
    except Exception as e:
        print(f"    Content fetch warning: {e} — using abstract only")

    return content


# ---------------------------------------------------------------------------
# Claude integration
# ---------------------------------------------------------------------------

def run_claude(prompt, model="claude-opus-4-6", timeout=600):
    """Run Claude in headless print mode via the Claude Code CLI.

    Runs from /tmp so Claude Code doesn't detect the vault working directory
    and activate its agent/tool-use mode.
    """
    try:
        result = subprocess.run(
            ["claude", "--print", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            cwd=tempfile.gettempdir(),
        )
        return result.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError(
            "'claude' CLI not found. Install Claude Code: https://claude.ai/download"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude timed out after {timeout}s.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Claude exited with error:\n{e.stderr.strip()}")


def generate_deep_dive(topic, content, gen_cfg):
    target_words = gen_cfg.get("target_words", 4000)
    model = gen_cfg.get("model", "claude-opus-4-6")
    prompt = f"""SYSTEM: You are a pure text-generation function. Your stdout output is piped directly into an EPUB builder. You MUST NOT use any tools, write any files, save anything, or add any preamble or explanation. Output ONLY the Markdown article — nothing before the first '#' heading and nothing after the last line of the article.

You are a senior technical writer and educator. Your reader is a software engineer who follows AI closely and wants genuine depth, not headlines.

Write a deep-dive article (~{target_words} words) on the following topic, designed for a focused 20-minute reading session on a colour e-ink display.

TOPIC: {topic['title']}
SOURCE: {topic.get('source_name', '')} — {topic.get('url', '')}
AUTHORS: {', '.join(topic.get('authors', [])) or 'N/A'}

SOURCE MATERIAL:
---
{content[:gen_cfg.get('max_source_chars', 40000)]}
---

REQUIREMENTS:
- Write a cohesive article: key ideas, why they matter, implications for practitioners.
- Include at least one Mermaid diagram (```mermaid block) for architectural, flow, or conceptual structures. The reader has a colour e-ink display — use colour in diagram node styles where it aids comprehension (e.g. style nodeA fill:#4A90D9,color:#fff).
- Cite source URL inline where relevant.
- Format in clean Markdown: headings (##, ###), bold for key terms, prefer prose over bullet lists.
- End with a "Key Takeaways" section (3–5 bullets).
- Do NOT include a "Critic Notes" section — that is appended separately.

# {topic['title']}
"""
    print("  Generating article (~60–90s)...")
    return run_claude(prompt, model=model)


def critique_draft(topic, content, draft, gen_cfg):
    model = gen_cfg.get("model", "claude-opus-4-6")
    prompt = f"""SYSTEM: You are a pure text-generation function returning structured JSON. Do NOT use any tools, write any files, or add any preamble. Output ONLY the JSON object described below — no markdown fences, no commentary before or after.

You are an adversarial peer reviewer fact-checking an AI-generated article against its cited source material.

SOURCE MATERIAL (truncated):
---
{content[:20000]}
---

ARTICLE TO REVIEW:
---
{draft[:20000]}
---

Identify:
- Claims NOT supported by the source (hallucinations, fabrications)
- Misattributed quotes or statistics
- Oversimplifications that mislead
- Important nuances or caveats the article missed
- Claims that contradict the source

If the article is accurate and well-reasoned, say so briefly in the summary field.

Output exactly this JSON object (no other text):
{{
  "overall_assessment": "accurate|minor_issues|significant_issues",
  "concerns": [
    {{"severity": "high|medium|low", "claim": "...", "issue": "..."}}
  ],
  "missing_context": ["...", "..."],
  "summary": "One-sentence verdict"
}}"""
    print("  Running critic pass (~30–60s)...")
    raw = run_claude(prompt, model=model)
    match = re.search(r"\{[\s\S]+\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"overall_assessment": "unknown", "concerns": [], "missing_context": [], "summary": raw[:300]}


def assemble_final(draft, critique, topic):
    today = datetime.now().strftime("%Y-%m-%d")
    header = (
        f"---\n"
        f"title: \"{topic['title'].replace(chr(34), chr(39))}\"\n"
        f"date: {today}\n"
        f"source: \"{topic.get('source_name', '')}\"\n"
        f"url: \"{topic.get('url', '')}\"\n"
        f"---\n\n"
    )
    assessment = critique.get("overall_assessment", "N/A")
    summary = critique.get("summary", "")
    concerns = critique.get("concerns", [])
    missing = critique.get("missing_context", [])

    critic_section = [
        "",
        "---",
        "",
        "## Critic Notes",
        "",
        f"*{assessment.replace('_', ' ').title()} — {summary}*",
        "",
    ]
    if concerns:
        critic_section += ["**Flagged claims:**", ""]
        for c in concerns:
            sev = c.get("severity", "?").upper()
            critic_section.append(f"- [{sev}] *\"{c.get('claim', '')}\"* — {c.get('issue', '')}")
        critic_section.append("")
    if missing:
        critic_section += ["**Missing context:**", ""]
        for m in missing:
            critic_section.append(f"- {m}")
        critic_section.append("")

    return header + draft + "\n".join(critic_section)


# ---------------------------------------------------------------------------
# EPUB build
# ---------------------------------------------------------------------------

def render_mermaid(markdown_text, work_dir):
    pattern = re.compile(r"```mermaid\n([\s\S]+?)\n```")
    diagrams = pattern.findall(markdown_text)
    output = markdown_text
    for i, diagram in enumerate(diagrams, 1):
        png = work_dir / f"diagram_{i}.png"
        mmd = work_dir / f"diagram_{i}.mmd"
        mmd.write_text(diagram)
        try:
            subprocess.run(
                ["mmdc", "-i", str(mmd), "-o", str(png), "-t", "default", "-b", "white", "-s", "2"],
                check=True, capture_output=True, timeout=60,
            )
            output = output.replace(f"```mermaid\n{diagram}\n```", f"![Diagram {i}](diagram_{i}.png)", 1)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"    Mermaid diagram {i} skipped: {e}")
    return output


def build_epub(markdown_text, epub_path, work_dir, title):
    markdown_text = render_mermaid(markdown_text, work_dir)
    md_file = work_dir / "content.md"
    md_file.write_text(markdown_text, encoding="utf-8")
    try:
        subprocess.run(
            [
                "pandoc", str(md_file),
                "-o", str(epub_path),
                "--metadata", f"title={title}",
                "--resource-path", str(work_dir),
                "--standalone",
            ],
            check=True, capture_output=True, timeout=120,
        )
        print(f"  EPUB: {epub_path.name}")
        return epub_path
    except FileNotFoundError:
        raise RuntimeError("pandoc not found. Install: apt install pandoc")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"pandoc failed: {e.stderr.decode()}")


# ---------------------------------------------------------------------------
# Delivery backends
# ---------------------------------------------------------------------------

def stage_for_pull(epub_path, delivery_cfg):
    """Recommended backend: copy EPUB into a pull-synced folder."""
    pull_cfg = delivery_cfg.get("pull", {})
    inbox_dir_raw = pull_cfg.get("inbox_dir", "")
    if not inbox_dir_raw:
        print("  [!] delivery.pull.inbox_dir is not set in sources.yaml.")
        print("      Set this to a folder synced to Kobo (Google Drive/Dropbox/etc).")
        print(f"      EPUB is at: {epub_path}")
        return False

    inbox_dir = Path(inbox_dir_raw).expanduser()
    inbox_dir.mkdir(parents=True, exist_ok=True)

    target = inbox_dir / epub_path.name
    if target.resolve() == epub_path.resolve():
        print(f"  Pull inbox already contains output path: {target}")
    else:
        shutil.copy2(epub_path, target)
        print(f"  Staged for pull: {target}")

    if pull_cfg.get("link_latest", True):
        latest = inbox_dir / "Daily_Deep_Dive_Latest.kepub.epub"
        shutil.copy2(epub_path, latest)
        print(f"  Updated latest alias: {latest}")

    # Optional hook for integrations such as rclone or custom upload scripts.
    post_cmd = pull_cfg.get("post_stage_command", "").strip()
    if post_cmd:
        context = {
            "file": str(target),
            "name": target.name,
            "dir": str(target.parent),
        }
        try:
            formatted = post_cmd.format(**context)
        except KeyError as e:
            print(f"  [!] post_stage_command placeholder error: {e}")
            return False

        try:
            subprocess.run(
                shlex.split(formatted),
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            print("  post_stage_command completed.")
        except FileNotFoundError:
            print("  [!] post_stage_command binary not found.")
            return False
        except subprocess.CalledProcessError as e:
            print(f"  [!] post_stage_command failed: {e.stderr.strip()}")
            return False
    return True


def upload_to_gws_drive(epub_path, delivery_cfg):
    """Upload EPUB to Google Drive using the gws CLI machine profile."""
    gws_cfg = delivery_cfg.get("gws_drive", {})
    folder_id = (gws_cfg.get("folder_id") or "").strip()
    if not folder_id:
        print("  [!] delivery.gws_drive.folder_id is not set in sources.yaml.")
        print(f"      EPUB is at: {epub_path}")
        return False

    env = os.environ.copy()
    config_dir = (gws_cfg.get("config_dir") or "").strip()
    if config_dir:
        env["GOOGLE_WORKSPACE_CLI_CONFIG_DIR"] = str(Path(config_dir).expanduser())

    def upload_named(local_path, remote_name):
        metadata = {"name": remote_name, "parents": [folder_id]}
        result = subprocess.run(
            [
                "gws", "drive", "files", "create",
                "--upload", str(local_path),
                "--json", json.dumps(metadata),
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
            env=env,
        )
        try:
            payload = json.loads(result.stdout or "{}")
            file_id = payload.get("id", "unknown")
            print(f"  Uploaded to Drive: {remote_name} (id={file_id})")
        except json.JSONDecodeError:
            print(f"  Uploaded to Drive: {remote_name}")

    try:
        upload_named(epub_path, epub_path.name)
        if gws_cfg.get("upload_latest_alias", False):
            latest_name = (gws_cfg.get("latest_alias_name") or "").strip()
            if latest_name:
                upload_named(epub_path, latest_name)
        return True
    except FileNotFoundError:
        print("  [!] gws CLI not found.")
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        detail = stderr if stderr else stdout
        print(f"  [!] gws upload failed: {detail}")
    return False


def deliver_epub(epub_path, delivery_cfg):
    mode = delivery_cfg.get("mode", "pull")
    if mode == "pull":
        return stage_for_pull(epub_path, delivery_cfg)
    if mode == "gws_drive":
        return upload_to_gws_drive(epub_path, delivery_cfg)
    if mode == "none":
        print("  delivery.mode=none — skipping delivery.")
        print(f"      EPUB is at: {epub_path}")
        return False

    print(f"  [!] Unknown delivery.mode '{mode}'.")
    print("      Supported modes: pull, gws_drive, none")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Kobo Daily AI Deep-Dive Reader")
    parser.add_argument("--dry-run", action="store_true",
                        help="Crawl and score topics but skip generation and EPUB build")
    parser.add_argument("--topic-id", metavar="ID",
                        help="Force a specific topic ID from the queue (skip discovery)")
    parser.add_argument("--no-sync", action="store_true",
                        help="Build EPUB locally, skip delivery")
    parser.add_argument("--output-dir", metavar="DIR", default="~/Desktop",
                        help="Local directory for the output EPUB (default: ~/Desktop)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser()
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  Kobo Daily Deep-Dive  —  {today}")
    print(f"{'='*60}\n")

    sources = load_sources()
    queue = load_queue()
    gen_cfg = sources.get("generation", {})
    delivery_cfg = sources.get("delivery", {})

    # ── 1. Discovery ────────────────────────────────────────────────
    if args.topic_id:
        matches = [t for t in queue.get("pending", []) if t["id"] == args.topic_id]
        if not matches:
            print(f"Topic ID '{args.topic_id}' not found in pending queue.")
            sys.exit(1)
        selected = matches[0]
        print(f"Forced topic: {selected['title']}\n")
    else:
        print("Phase 1: Discovering topics...\n")
        arxiv_cfg = sources.get("arxiv", {})
        days_back = arxiv_cfg.get("days_back", 3)

        candidates = []
        candidates += fetch_arxiv(arxiv_cfg, days_back)
        candidates += fetch_rss(sources.get("rss_feeds", []), days_back)

        print("\nFetching social signals...")
        social_cfg = sources.get("social_signals", {})
        hn = fetch_hn_signal(social_cfg.get("hacker_news", {}), days_back)
        reddit = fetch_reddit_signal(social_cfg.get("reddit", {}), days_back)
        print(f"  HN: {len(hn)} AI stories  |  Reddit: {len(reddit)} posts")

        scoring_cfg = sources.get("scoring", {})
        weights = {
            "authority": scoring_cfg.get("authority_weight", 0.40),
            "social": scoring_cfg.get("social_weight", 0.30),
            "recency": scoring_cfg.get("recency_weight", 0.20),
            "diversity": scoring_cfg.get("diversity_weight", 0.10),
        }
        half_life = scoring_cfg.get("recency_half_life_days", 3)

        new_count = 0
        for c in candidates:
            if is_processed(queue, c["id"]):
                continue
            existing = next((t for t in queue["pending"] if t["id"] == c["id"]), None)
            if existing:
                existing["social"]["hn_points"] = hn.get(c.get("url", ""), existing["social"]["hn_points"])
                continue
            c["score"] = score_candidate(c, hn, reddit, queue, weights, half_life)
            c["discovered"] = today
            queue["pending"].append(c)
            new_count += 1

        for t in queue["pending"]:
            t["score"] = score_candidate(t, hn, reddit, queue, weights, half_life)
        queue["pending"].sort(key=lambda t: t["score"], reverse=True)

        print(f"\nDiscovery: {new_count} new  |  {len(queue['pending'])} pending total")

        if args.dry_run:
            print("\n[DRY RUN] Top 10 candidates:\n")
            for i, t in enumerate(queue["pending"][:10], 1):
                pub = (t.get("published") or "")[:10]
                print(f"  {i:2}. [{t['score']:.3f}] {t['title'][:70]}")
                print(f"        {t.get('source_name', '')}  |  {pub}")
            save_queue(queue)
            print("\nQueue saved. Exiting (--dry-run).\n")
            return

        if not queue["pending"]:
            print("No candidate topics found. Try widening days_back in sources.yaml.")
            sys.exit(0)

        selected = queue["pending"][0]

    print(f"\n{'─'*60}")
    print(f"  Topic : {selected['title'][:70]}")
    print(f"  Source: {selected.get('source_name', '')}  |  Score: {selected.get('score', 0):.3f}")
    print(f"  URL   : {selected.get('url', '')}")
    print(f"{'─'*60}\n")

    # ── 2. Fetch content ────────────────────────────────────────────
    print("Phase 2: Fetching source content...")
    content = fetch_content(selected, max_chars=gen_cfg.get("max_source_chars", 40000))
    print(f"  {len(content):,} chars retrieved")

    # ── 3. Generate ─────────────────────────────────────────────────
    print("\nPhase 3: Generating deep dive...")
    draft = generate_deep_dive(selected, content, gen_cfg)
    word_count = len(draft.split())
    print(f"  {word_count:,} words  (~{word_count // 200} min read)")

    # ── 4. Critic ───────────────────────────────────────────────────
    print("\nPhase 4: Critic pass...")
    critique_result = critique_draft(selected, content, draft, gen_cfg)
    n_concerns = len(critique_result.get("concerns", []))
    print(f"  {critique_result.get('overall_assessment', 'unknown')}  |  {n_concerns} concern(s)")

    # ── 5. Assemble ─────────────────────────────────────────────────
    print("\nPhase 5: Assembling final document...")
    final_md = assemble_final(draft, critique_result, selected)

    # ── 6. Build EPUB ───────────────────────────────────────────────
    print("\nPhase 6: Building EPUB...")
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\s-]", "", selected["title"])[:50].strip().replace(" ", "_")
    epub_name = f"Daily_Deep_Dive_{today}_{safe_title}.kepub.epub"
    epub_path = output_dir / epub_name

    with tempfile.TemporaryDirectory() as tmp:
        epub_path = build_epub(final_md, epub_path, Path(tmp), selected["title"])

    # ── 7. Delivery ─────────────────────────────────────────────────
    delivered = False
    if not args.no_sync:
        print("\nPhase 7: Delivering...")
        delivered = deliver_epub(epub_path, delivery_cfg)
    else:
        print(f"\n[--no-sync] EPUB saved locally: {epub_path}")

    # ── Finalise ────────────────────────────────────────────────────
    if delivered:
        queue["pending"] = [t for t in queue["pending"] if t["id"] != selected["id"]]
        queue.setdefault("processed", []).append({
            "id": selected["id"],
            "title": selected["title"],
            "delivered": today,
            "epub": epub_path.name,
        })
    else:
        print("  Delivery not confirmed; topic remains in pending queue for retry.")
    save_queue(queue)

    print(f"\n{'='*60}")
    if delivered:
        print(f"  Delivered: {epub_path.name}")
    else:
        print(f"  Built only (not delivered): {epub_path.name}")
    print(f"  Queue: {len(queue['pending'])} pending")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
