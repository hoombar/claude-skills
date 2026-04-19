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

BUILD_TOOL_HINTS = {
    "pandoc": "Install pandoc before running the full pipeline.",
    "dot": "Install Graphviz (`dot`) for diagram rendering in the EPUB.",
    "mmdc": "Install Mermaid CLI (`mmdc`) only if you want Mermaid fallback rendering.",
}

QUALITY_DEFAULTS = {
    "enabled": True,
    "mode": "hybrid",
    "gate_scope": "selection_top_k",
    "top_k": 5,
    "reject_cache_days": 7,
    "fail_mode": "closed",
    "hard_filter": {
        "exclude_title_patterns": [
            r"(?i)\bterms?( and| &)conditions\b",
            r"(?i)\bterms? of (service|use)\b",
            r"(?i)\bprivacy policy\b",
            r"(?i)\bofficial rules?\b",
            r"(?i)\bcontest\b",
            r"(?i)\bsweepstakes\b",
            r"(?i)\beligibility\b",
            r"(?i)\blegal notice\b",
        ],
        "exclude_url_patterns": [
            r"(?i)/legal/",
            r"(?i)/terms",
            r"(?i)/privacy",
            r"(?i)/contest",
            r"(?i)/sweepstakes",
            r"(?i)/official-rules",
        ],
        "allow_title_patterns": [
            r"(?i)\b(technical report|research|benchmark|evaluation|method|architecture|paper|arxiv)\b",
            r"(?i)\b(how to|guide|deep dive|case study)\b",
        ],
    },
}

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_queue():
    if not QUEUE_FILE.exists():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        return {"pending": [], "processed": [], "rejected": []}

    queue = json.loads(QUEUE_FILE.read_text())
    queue.setdefault("pending", [])
    queue.setdefault("processed", [])
    queue.setdefault("rejected", [])
    return queue


def save_queue(queue):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2, default=str))


def load_sources():
    if not SOURCES_FILE.exists():
        print(f"sources.yaml not found. Expected at: {SOURCES_FILE}")
        print("Copy kobo_reader_state/sources.yaml from the vault and configure it.")
        sys.exit(1)
    return yaml.safe_load(SOURCES_FILE.read_text())


def require_build_dependencies():
    """Fail fast on missing required build tools before expensive generation."""
    missing = []
    for tool in ("pandoc", "dot"):
        if not shutil.which(tool):
            message = BUILD_TOOL_HINTS.get(tool, "Install the missing dependency and retry.")
            missing.append(f"  [!] Missing required build tool: {tool}. {message}")

    for tool in ("mmdc",):
        if shutil.which(tool):
            continue
        message = BUILD_TOOL_HINTS.get(tool, "Install the missing dependency and retry.")
        print(f"  [!] Optional build tool missing: {tool}. {message}")

    if missing:
        for line in missing:
            print(line)
        raise RuntimeError("Build dependencies are incomplete; aborting before generation.")


def make_topic_id(url, title):
    """Stable short ID from URL (preferred) or title hash."""
    return hashlib.sha1((url or title).encode()).hexdigest()[:14]


def is_processed(queue, tid):
    return any(p["id"] == tid for p in queue.get("processed", []))


def now_utc():
    return datetime.now(timezone.utc)


def parse_iso_dt(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def merge_quality_config(raw_cfg):
    cfg = dict(QUALITY_DEFAULTS)
    if isinstance(raw_cfg, dict):
        cfg.update({k: v for k, v in raw_cfg.items() if k != "hard_filter"})
        hard = dict(QUALITY_DEFAULTS["hard_filter"])
        hard.update(raw_cfg.get("hard_filter", {}))
        cfg["hard_filter"] = hard
    return cfg


def build_feed_meta_index(feeds_cfg):
    index = {}
    for feed in feeds_cfg or []:
        name = str(feed.get("name", "")).strip()
        if not name:
            continue
        index[name] = {
            "source_layer": feed.get("layer", "practitioner_core"),
            "source_role": feed.get("role", "driver"),
            "source_focus": feed.get("focus", ""),
            "source_rationale": feed.get("rationale", ""),
            "authority": feed.get("authority"),
        }
    return index


def enrich_topic_source_metadata(topic, feed_meta):
    source_name = str(topic.get("source_name", "")).strip()
    topic_id = str(topic.get("id", "")).lower()
    source_lc = source_name.lower()

    if topic_id.startswith("arxiv:") or "arxiv" in source_lc:
        if not topic.get("source_layer"):
            topic["source_layer"] = "research_primary"
        if not topic.get("source_role"):
            topic["source_role"] = "driver"
        if not topic.get("source_focus"):
            topic["source_focus"] = "peer-reviewed or preprint AI research"
        if not topic.get("source_rationale"):
            topic["source_rationale"] = "Primary research source used as technical fallback."
        return

    meta = feed_meta.get(source_name)
    if meta:
        for key in ("source_layer", "source_role", "source_focus", "source_rationale"):
            if not topic.get(key):
                topic[key] = meta.get(key, "")
        if "authority" not in topic or topic.get("authority") is None:
            topic["authority"] = meta.get("authority", topic.get("authority"))
        return

    if not topic.get("source_layer"):
        topic["source_layer"] = "unknown"
    if not topic.get("source_role"):
        topic["source_role"] = "driver"


def enrich_queue_metadata(queue, feed_meta):
    updated = 0
    for topic in queue.get("pending", []):
        before = (
            topic.get("source_layer"),
            topic.get("source_role"),
            topic.get("source_focus"),
            topic.get("source_rationale"),
        )
        enrich_topic_source_metadata(topic, feed_meta)
        after = (
            topic.get("source_layer"),
            topic.get("source_role"),
            topic.get("source_focus"),
            topic.get("source_rationale"),
        )
        if before != after:
            updated += 1
    return updated


def partition_candidates_by_layer(candidates, preferred_layers, fallback_layers=None):
    preferred = []
    fallback = []
    for topic in candidates:
        layer = str(topic.get("source_layer", "unknown")).strip()
        if layer in preferred_layers:
            preferred.append(topic)
        elif fallback_layers is None or layer in fallback_layers:
            fallback.append(topic)
        else:
            fallback.append(topic)
    return preferred, fallback


# ---------------------------------------------------------------------------
# Source crawlers
# ---------------------------------------------------------------------------

def fetch_arxiv(cfg, days_back):
    candidates = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    try:
        authority = float(cfg.get("authority", 0.72))
    except (TypeError, ValueError):
        authority = 0.72
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
                    "source_layer": "research_primary",
                    "source_role": "driver",
                    "source_focus": "peer-reviewed or preprint AI research",
                    "source_rationale": "Primary research source with highest technical fidelity.",
                    "authority": authority,
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
        layer = feed_conf.get("layer", "practitioner_core")
        role = feed_conf.get("role", "driver")
        focus = feed_conf.get("focus", "")
        rationale = feed_conf.get("rationale", "")
        ai_only = bool(feed_conf.get("ai_only", True))
        print(f"  RSS [{name}]...")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                pub = datetime.fromtimestamp(timegm(parsed), tz=timezone.utc) if parsed else None
                if pub and pub < cutoff:
                    continue
                summary = re.sub(r"<[^>]+>", " ", getattr(entry, "summary", "") or "").strip()
                if ai_only:
                    search_blob = f"{getattr(entry, 'title', '')} {summary}".lower()
                    if not any(kw in search_blob for kw in AI_KEYWORDS):
                        continue
                link = getattr(entry, "link", "")
                tid = f"rss:{make_topic_id(link, entry.title)}"
                candidates.append({
                    "id": tid,
                    "title": entry.title.strip(),
                    "summary": summary[:600],
                    "url": link,
                    "pdf_url": None,
                    "source_name": name,
                    "source_layer": layer,
                    "source_role": role,
                    "source_focus": focus,
                    "source_rationale": rationale,
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

def score_candidate(c, hn_signal, reddit_signal, queue, weights, half_life_days, include_components=False):
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

    total = round(authority + social + recency + diversity, 4)
    if not include_components:
        return total

    breakdown = {
        "authority": round(authority, 4),
        "social": round(social, 4),
        "recency": round(recency, 4),
        "diversity": round(diversity, 4),
        "total": total,
    }
    social_debug = {
        "hn_points": hn_pts,
        "reddit_score": reddit_pts,
    }
    return total, breakdown, social_debug


# ---------------------------------------------------------------------------
# Quality gate (hybrid deterministic + LLM)
# ---------------------------------------------------------------------------

def first_matching_pattern(text, patterns):
    for pattern in patterns or []:
        if re.search(pattern, text or ""):
            return pattern
    return None


def hard_filter_reason(topic, quality_cfg):
    hard_cfg = quality_cfg.get("hard_filter", {})
    title = topic.get("title", "") or ""
    url = topic.get("url", "") or ""

    allow_match = first_matching_pattern(title, hard_cfg.get("allow_title_patterns", []))
    if allow_match:
        return None

    title_match = first_matching_pattern(title, hard_cfg.get("exclude_title_patterns", []))
    if title_match:
        return f"title:{title_match}"

    url_match = first_matching_pattern(url, hard_cfg.get("exclude_url_patterns", []))
    if url_match:
        return f"url:{url_match}"

    return None


def prune_offtopic_pending(queue, feeds_cfg):
    ai_only_sources = {
        str(feed.get("name", "")).strip()
        for feed in feeds_cfg or []
        if bool(feed.get("ai_only", True))
    }
    if not ai_only_sources:
        return 0

    kept = []
    removed = 0
    for topic in queue.get("pending", []):
        source_name = str(topic.get("source_name", "")).strip()
        if source_name in ai_only_sources:
            title = str(topic.get("title", ""))
            summary = str(topic.get("summary", ""))
            blob = f"{title} {summary}".lower()
            if not any(kw in blob for kw in AI_KEYWORDS):
                removed += 1
                continue
        kept.append(topic)

    queue["pending"] = kept
    return removed


def prune_expired_rejections(queue, ref_time):
    kept = []
    expired_count = 0
    for item in queue.get("rejected", []):
        expires_at = parse_iso_dt(item.get("expires_at"))
        if expires_at and expires_at > ref_time:
            kept.append(item)
        else:
            expired_count += 1
    queue["rejected"] = kept
    return expired_count


def rejection_index(queue, ref_time):
    idx = {}
    for item in queue.get("rejected", []):
        expires_at = parse_iso_dt(item.get("expires_at"))
        if expires_at and expires_at > ref_time:
            idx[item.get("id")] = item
    return idx


def cache_rejection(queue, topic, reason, provider, model, days, ref_time):
    expires_at = ref_time + timedelta(days=max(days, 1))
    entry = {
        "id": topic.get("id"),
        "title": topic.get("title", ""),
        "reason": reason,
        "provider": provider,
        "model": model,
        "rejected_at": ref_time.isoformat(),
        "expires_at": expires_at.isoformat(),
    }

    updated = False
    for i, existing in enumerate(queue.get("rejected", [])):
        if existing.get("id") == topic.get("id"):
            queue["rejected"][i] = entry
            updated = True
            break
    if not updated:
        queue.setdefault("rejected", []).append(entry)


def parse_json_object(raw):
    match = re.search(r"\{[\s\S]+\}", raw)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def llm_quality_gate(topic, gen_cfg, quality_cfg):
    provider = resolve_generation_provider(gen_cfg)
    model = resolve_generation_model(gen_cfg, provider)
    fail_closed = str(quality_cfg.get("fail_mode", "closed")).lower() == "closed"
    source_layer = topic.get("source_layer", "unknown")
    source_role = topic.get("source_role", "unknown")

    social = topic.get("social", {})
    prompt = f"""SYSTEM: You are a strict quality gate for topic selection.
Return ONLY JSON. No markdown.

Goal: decide whether this topic is a high-learning-value deep-dive candidate for an engineer trying to keep up with meaningful AI progress.

Reject topics that are mostly legal/contest/compliance/policy boilerplate, pure promotion, or low technical depth.

Accept topics with substantive technical or research learning value.

Output exactly:
{{
  "verdict": "accept|reject",
  "confidence": "high|medium|low",
  "reason": "single sentence",
  "signals": ["technical_depth|research|benchmark|legal|contest|policy|promo|other"]
}}

TOPIC:
- title: {topic.get("title", "")}
- source: {topic.get("source_name", "")}
- url: {topic.get("url", "")}
- summary: {topic.get("summary", "")[:900]}
- score: {topic.get("score", 0)}
- source_layer: {source_layer}
- source_role: {source_role}
- social_hn_points: {social.get("hn_points", 0)}
- social_reddit_score: {social.get("reddit_score", 0)}
"""
    try:
        _, _, raw = run_generation_model(prompt, gen_cfg, timeout=120)
    except Exception as e:
        reason = f"llm_gate_error:{str(e)[:180]}"
        payload = {
            "verdict": "reject" if fail_closed else "accept",
            "confidence": "low",
            "reason": reason if fail_closed else "llm_gate_error_fail_open",
            "signals": ["other"],
            "provider": provider,
            "model": model,
        }
        if fail_closed:
            return False, payload
        return True, payload

    parsed = parse_json_object(raw)
    if not parsed:
        payload = {
            "verdict": "reject" if fail_closed else "accept",
            "confidence": "low",
            "reason": "llm_gate_parse_error" if fail_closed else "llm_gate_parse_error_fail_open",
            "signals": ["other"],
            "provider": provider,
            "model": model,
        }
        if fail_closed:
            return False, payload
        return True, payload

    verdict = str(parsed.get("verdict", "")).strip().lower()
    reason = str(parsed.get("reason", "")).strip() or "no_reason"
    confidence = str(parsed.get("confidence", "")).strip().lower() or "medium"
    signals = parsed.get("signals", [])
    if not isinstance(signals, list):
        signals = []
    payload = {
        "verdict": verdict or "unknown",
        "confidence": confidence,
        "reason": reason,
        "signals": [str(s) for s in signals[:8]],
        "provider": provider,
        "model": model,
    }
    if verdict == "accept":
        return True, payload
    if verdict == "reject":
        return False, payload

    payload["reason"] = "llm_gate_invalid_verdict"
    if fail_closed:
        return False, payload
    payload["reason"] = "llm_gate_invalid_verdict_fail_open"
    payload["verdict"] = "accept"
    return True, payload


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
# Model integration (Claude / Codex)
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


def run_codex(prompt, model="gpt-5.3-codex", timeout=900):
    """Run Codex non-interactively and return only the final response text.

    Uses --output-last-message to avoid parsing interactive progress logs.
    Runs from /tmp to avoid loading repository-local instructions/tooling.
    """
    output_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".txt", prefix="kobo_codex_last_", delete=False
        ) as f:
            output_path = Path(f.name)

        subprocess.run(
            [
                "codex", "exec",
                "--skip-git-repo-check",
                "--ephemeral",
                "--sandbox", "read-only",
                "--output-last-message", str(output_path),
                "--model", model,
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            cwd=tempfile.gettempdir(),
        )

        if output_path.exists():
            text = output_path.read_text(encoding="utf-8").strip()
            if text:
                return text
        raise RuntimeError("Codex completed but produced no final message.")
    except FileNotFoundError:
        raise RuntimeError(
            "'codex' CLI not found. Install Codex CLI and authenticate on this machine."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Codex timed out after {timeout}s.")
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        detail = stderr if stderr else stdout
        raise RuntimeError(f"Codex exited with error:\n{detail}")
    finally:
        if output_path and output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass


def resolve_generation_provider(gen_cfg):
    provider = str(gen_cfg.get("provider", "claude")).strip().lower()
    if provider not in {"claude", "codex"}:
        print(f"  [!] Unknown generation.provider '{provider}', falling back to 'claude'.")
        return "claude"
    return provider


def resolve_generation_model(gen_cfg, provider):
    legacy = str(gen_cfg.get("model", "")).strip()
    if provider == "claude":
        explicit = str(gen_cfg.get("claude_model", "")).strip()
        if explicit:
            return explicit
        if legacy.startswith("claude-"):
            return legacy
        return "claude-opus-4-6"

    explicit = str(gen_cfg.get("codex_model", "")).strip()
    if explicit:
        return explicit
    if legacy.startswith("gpt-"):
        return legacy
    return "gpt-5.3-codex"


def run_generation_model(prompt, gen_cfg, timeout=600):
    provider = resolve_generation_provider(gen_cfg)
    model = resolve_generation_model(gen_cfg, provider)
    if provider == "codex":
        # codex exec has higher orchestration overhead than claude --print.
        return provider, model, run_codex(prompt, model=model, timeout=max(timeout, 900))
    return provider, model, run_claude(prompt, model=model, timeout=timeout)


def resolve_generation_targets(gen_cfg):
    target_minutes = int(gen_cfg.get("target_read_minutes", 12))
    words_per_minute = int(gen_cfg.get("words_per_minute", 190))
    computed_target = max(target_minutes * words_per_minute, 800)
    target_words = int(gen_cfg.get("target_words", computed_target))
    hard_max_words = int(
        gen_cfg.get("hard_max_words", max(int(target_words * 1.12), target_words + 150))
    )
    if hard_max_words < target_words:
        hard_max_words = target_words
    return target_minutes, words_per_minute, target_words, hard_max_words


def is_academic_topic(topic):
    tid = str(topic.get("id", "")).lower()
    source = str(topic.get("source_name", "")).lower()
    url = str(topic.get("url", "")).lower()
    if tid.startswith("arxiv:"):
        return True
    if "arxiv" in source or "arxiv.org" in url:
        return True
    return any(token in source for token in ("journal", "conference", "proceedings", "preprint"))


def generate_deep_dive(topic, content, gen_cfg):
    target_minutes, words_per_minute, target_words, hard_max_words = resolve_generation_targets(gen_cfg)
    academic_mode = is_academic_topic(topic)
    audience_requirements = (
        "- Assume the reader is a senior mobile engineer (iOS/Android/backend integration), not an AI researcher.\n"
        "- Prioritize practical understanding for prompt/context/harness engineering decisions.\n"
        "- Keep jargon low; define advanced terms in plain English the first time they appear.\n"
    )
    if academic_mode:
        depth_requirements = (
            "- This is an academic source: translate research language into broad-audience technical explainer style.\n"
            "- Avoid unexplained math-heavy phrasing. If an advanced concept is unavoidable, define it with a concrete analogy.\n"
            "- Add a `## Plain-English Summary` section near the start (4-6 sentences).\n"
            "- Add a `## Why This Matters for Product Engineers` section focused on applied implications and limitations.\n"
        )
    else:
        depth_requirements = (
            "- Keep depth and rigor high, but stay readable for a generalist senior software engineer.\n"
        )

    prompt = f"""SYSTEM: You are a pure text-generation function. Your stdout output is piped directly into an EPUB builder. You MUST NOT use any tools, write any files, save anything, or add any preamble or explanation. Output ONLY the Markdown article — nothing before the first '#' heading and nothing after the last line of the article.

You are a senior technical writer and educator.

Write a deep-dive article targeting {target_words} words (~{target_minutes} minutes at {words_per_minute} wpm) on the following topic, designed for a focused reading session on a colour e-ink display.
Do not exceed {hard_max_words} words.

TOPIC: {topic['title']}
SOURCE: {topic.get('source_name', '')} — {topic.get('url', '')}
AUTHORS: {', '.join(topic.get('authors', [])) or 'N/A'}

SOURCE MATERIAL:
---
{content[:gen_cfg.get('max_source_chars', 40000)]}
---

REQUIREMENTS:
- Write a cohesive article: key ideas, why they matter, implications for practitioners.
- Keep readability high and acronym density low.
- On first use of any acronym, always expand it as `Long Form (ACR)`. After first use, acronym-only is allowed.
- Include a short `## Terms and Acronyms` section near the end with at most 8 entries in plain English.
- Use Graphviz DOT diagrams when they improve understanding. Include as many as needed, but keep each diagram narrowly scoped.
- Output each diagram in a fenced `dot` block (````dot ... ```).
- Prefer top-down diagrams (`rankdir=TB`) that use vertical space well on a portrait e-reader.
- Keep each diagram visually narrow: target <=4 boxes at the widest row.
- If a concept has multiple stages or many moving parts, split it into multiple DOT blocks (one block per stage/subsystem).
- Keep each DOT graph Kobo-friendly: <=8 nodes, <=10 edges, short labels.
- Do not output Mermaid blocks.
- Cite source URL inline where relevant.
- Format in clean Markdown: headings (##, ###), bold for key terms, prefer prose over bullet lists.
- End with a "Key Takeaways" section (3–5 bullets).
- Do NOT include a "Critic Notes" section — that is appended separately.
{audience_requirements}{depth_requirements}

# {topic['title']}
"""
    provider = resolve_generation_provider(gen_cfg)
    model = resolve_generation_model(gen_cfg, provider)
    print(f"  Generating article via {provider}:{model} (~60–120s)...")
    _, _, output = run_generation_model(prompt, gen_cfg, timeout=900)
    return output


def critique_draft(topic, content, draft, gen_cfg):
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
- Unexplained acronyms or jargon (especially acronym-first mentions without expansion)
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
    provider = resolve_generation_provider(gen_cfg)
    model = resolve_generation_model(gen_cfg, provider)
    print(f"  Running critic pass via {provider}:{model} (~30–90s)...")
    _, _, raw = run_generation_model(prompt, gen_cfg, timeout=900)
    match = re.search(r"\{[\s\S]+\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"overall_assessment": "unknown", "concerns": [], "missing_context": [], "summary": raw[:300]}


def format_source_provenance(topic):
    score = topic.get("score", 0)
    breakdown = topic.get("score_breakdown", {}) or {}
    social = topic.get("social", {}) or {}
    gate = topic.get("quality_gate", {}) or {}

    source_name = topic.get("source_name", "Unknown source")
    source_url = topic.get("url", "")
    source_layer = topic.get("source_layer", "unknown")
    source_role = topic.get("source_role", "unknown")
    source_focus = topic.get("source_focus", "")
    source_rationale = topic.get("source_rationale", "")
    published = (topic.get("published") or "")[:10]

    lines = [
        "## Source Provenance",
        "",
        "This deep dive is grounded in one primary source and selected from the queue using objective scoring plus a quality gate.",
        "",
        f"- Primary source: **{source_name}** ({source_url})",
        f"- Source layer: `{source_layer}`  |  Role: `{source_role}`",
    ]
    if published:
        lines.append(f"- Published date: {published}")
    if source_focus:
        lines.append(f"- Source focus: {source_focus}")
    if source_rationale:
        lines.append(f"- Why this source is trusted: {source_rationale}")

    lines += [
        f"- Selection score: **{score:.3f}**",
    ]

    if breakdown:
        lines.append(
            "- Score components: "
            f"authority `{breakdown.get('authority', 0):.3f}`, "
            f"social `{breakdown.get('social', 0):.3f}`, "
            f"recency `{breakdown.get('recency', 0):.3f}`, "
            f"diversity `{breakdown.get('diversity', 0):.3f}`"
        )
    lines.append(
        f"- Social radar used only for prioritization: HN `{social.get('hn_points', 0)}` | Reddit `{social.get('reddit_score', 0)}`"
    )

    if gate:
        confidence = gate.get("confidence", "unknown")
        reason = gate.get("reason", "no_reason")
        signals = ", ".join(gate.get("signals", [])) or "none"
        lines.append(f"- Quality gate: `{gate.get('verdict', 'unknown')}` (confidence: `{confidence}`)")
        lines.append(f"- Quality gate reason: {reason}")
        lines.append(f"- Quality gate signals: {signals}")

    lines += [
        "",
        "Use this section to judge source quality over time and adjust feed weights as needed.",
        "",
    ]
    return lines


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

    provenance_section = format_source_provenance(topic)
    body = [draft.rstrip(), "", *provenance_section, *critic_section]
    return header + "\n".join(body).strip() + "\n"


# ---------------------------------------------------------------------------
# EPUB build
# ---------------------------------------------------------------------------

def normalize_graphviz_for_kobo(diagram):
    raw = (diagram or "").strip()
    if not raw:
        raw = 'digraph G {\n  unavailable [label="Diagram unavailable"];\n}'

    if not re.match(r"^\s*(di)?graph\b", raw, flags=re.IGNORECASE):
        raw = f"digraph G {{\n{raw}\n}}"

    if "{" not in raw:
        raw = f"digraph G {{\n{raw}\n}}"

    defaults = (
        '\n  graph [bgcolor="white", rankdir=TB, splines=ortho, nodesep=0.45, '
        'ranksep=0.75, size="5.44,7.55", ratio=compress];\n'
        '  node [shape=box, style="rounded", fontname="Helvetica", fontsize=14, '
        'color="#666666", penwidth=1.4];\n'
        '  edge [color="#444444", arrowsize=0.8, penwidth=1.2, '
        'fontname="Helvetica", fontsize=12];\n'
    )
    brace_idx = raw.find("{")
    return f"{raw[:brace_idx + 1]}{defaults}{raw[brace_idx + 1:]}"


def render_graphviz(markdown_text, work_dir):
    pattern = re.compile(r"```(dot|graphviz)\n([\s\S]+?)\n```")
    diagrams = pattern.findall(markdown_text)
    output = markdown_text
    for i, (lang, diagram) in enumerate(diagrams, 1):
        block = f"```{lang}\n{diagram}\n```"
        sanitized = normalize_graphviz_for_kobo(diagram)
        png = work_dir / f"graphviz_diagram_{i}.png"
        dot_file = work_dir / f"graphviz_diagram_{i}.dot"
        dot_file.write_text(sanitized, encoding="utf-8")
        try:
            cmd = [
                "dot",
                "-Gdpi=180",
                "-Tpng",
                str(dot_file),
                "-o",
                str(png),
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
            output = output.replace(block, f"![Diagram {i}]({png.name})", 1)
        except FileNotFoundError as e:
            print(f"    Graphviz diagram {i} skipped: {e}")
            output = output.replace(
                block,
                "_Diagram omitted because Graphviz is not installed in this run._",
                1,
            )
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or "").strip() or str(e)
            print(f"    Graphviz diagram {i} skipped: {detail}")
            output = output.replace(
                block,
                "_Diagram omitted because Graphviz rendering failed in this run._",
                1,
            )
    return output


def normalize_mermaid_for_kobo(diagram):
    cleaned = (
        diagram.replace("<br />", "\\n")
        .replace("<br/>", "\\n")
        .replace("<br>", "\\n")
    )
    lines = [line.rstrip() for line in cleaned.splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return "flowchart TB\nA[Diagram unavailable]"

    body = [line for line in lines if not line.strip().startswith("%%{init:")]
    if not body:
        body = ["flowchart TB", "A[Diagram unavailable]"]

    if re.match(r"^\s*(flowchart|graph)\b", body[0], flags=re.IGNORECASE):
        body[0] = re.sub(
            r"^\s*(flowchart|graph)\s+\w+",
            "flowchart TB",
            body[0],
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        body.insert(0, "flowchart TB")

    # Force Kobo-friendly rendering defaults: vertical rank direction and plain text labels.
    init_line = (
        "%%{init: {'flowchart': {'htmlLabels': false, 'curve': 'linear', "
        "'nodeSpacing': 48, 'rankSpacing': 88}}}%%"
    )
    return "\n".join([init_line, *body])


def render_mermaid(markdown_text, work_dir):
    pattern = re.compile(r"```mermaid\n([\s\S]+?)\n```")
    diagrams = pattern.findall(markdown_text)
    output = markdown_text
    puppeteer_cfg = None
    if sys.platform.startswith("linux"):
        puppeteer_cfg = work_dir / "puppeteer-config.json"
        puppeteer_cfg.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
    for i, diagram in enumerate(diagrams, 1):
        block = f"```mermaid\n{diagram}\n```"

        sanitized = normalize_mermaid_for_kobo(diagram)
        png = work_dir / f"mermaid_diagram_{i}.png"
        mmd = work_dir / f"mermaid_diagram_{i}.mmd"
        mmd.write_text(sanitized)
        try:
            cmd = [
                "mmdc",
                "-i",
                str(mmd),
                "-o",
                str(png),
                "-t",
                "default",
                "-b",
                "white",
                "-s",
                "2",
                "-w",
                "900",
                "-H",
                "1600",
            ]
            if puppeteer_cfg:
                cmd.extend(["-p", str(puppeteer_cfg)])
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            output = output.replace(block, f"![Diagram {i}]({png.name})", 1)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"    Mermaid diagram {i} skipped: {e}")
            output = output.replace(
                block,
                "_Diagram omitted because Mermaid rendering failed in this run._",
                1,
            )
    return output


def convert_epub_to_kepub(epub_path, kepub_path, work_dir):
    source_copy = work_dir / "kepub_source.epub"
    source_copy.write_bytes(epub_path.read_bytes())
    try:
        subprocess.run(
            ["kepubify", str(source_copy)],
            check=True,
            capture_output=True,
            timeout=120,
            cwd=work_dir,
        )
    except FileNotFoundError:
        print("    [!] kepubify not found; keeping EPUB output.")
        return False
    except subprocess.CalledProcessError as e:
        detail = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        print(f"    [!] kepubify failed; keeping EPUB output. {detail.strip()}")
        return False

    candidates = sorted(
        work_dir.glob("*.kepub.epub"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        print("    [!] kepubify did not produce a .kepub.epub file; keeping EPUB output.")
        return False

    shutil.copy2(candidates[0], kepub_path)
    return True


def build_publication(markdown_text, output_stem, work_dir, title, build_cfg):
    markdown_text = render_graphviz(markdown_text, work_dir)
    markdown_text = render_mermaid(markdown_text, work_dir)
    md_file = work_dir / "content.md"
    md_file.write_text(markdown_text, encoding="utf-8")
    epub_path = output_stem.with_suffix(".epub")
    css_file = work_dir / "epub.css"
    base_font_pct = int(build_cfg.get("epub_base_font_percent", 50))
    line_height = float(build_cfg.get("epub_line_height", 1.35))
    css_file.write_text(
        "\n".join([
            "html, body {",
            f"  font-size: {base_font_pct}%;",
            f"  line-height: {line_height};",
            "}",
            "p, li, blockquote {",
            "  font-size: 1em;",
            "}",
            "h1 { font-size: 1.5em; }",
            "h2 { font-size: 1.3em; }",
            "h3 { font-size: 1.15em; }",
            "img {",
            "  max-width: 95%;",
            "  height: auto;",
            "}",
            "pre, code {",
            "  font-size: 0.9em;",
            "}",
        ]),
        encoding="utf-8",
    )
    try:
        subprocess.run(
            [
                "pandoc", str(md_file),
                "-o", str(epub_path),
                "--metadata", f"title={title}",
                "--resource-path", str(work_dir),
                "--css", str(css_file),
                "--standalone",
            ],
            check=True, capture_output=True, timeout=120,
        )
        prefer_kepub = build_cfg.get("prefer_kepub", False)
        if not prefer_kepub:
            print(f"  EPUB: {epub_path.name}")
            return epub_path

        kepub_path = output_stem.with_suffix(".kepub.epub")
        converted = convert_epub_to_kepub(epub_path, kepub_path, work_dir)
        if converted:
            if not build_cfg.get("keep_epub_when_kepub", False):
                try:
                    epub_path.unlink()
                except OSError:
                    pass
            print(f"  KEPUB: {kepub_path.name}")
            return kepub_path

        print("  Using EPUB fallback output.")
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
        latest = inbox_dir / "Latest.kepub.epub"
        shutil.copy2(epub_path, latest)
        print(f"  Updated latest alias: {latest}")

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


def purge_old_drive_epubs(folder_id, gws_cfg, env):
    retention_cfg = gws_cfg.get("retention", {})
    if not retention_cfg.get("enabled", False):
        return
    dry_run = bool(retention_cfg.get("dry_run", False))

    try:
        max_age_days = int(retention_cfg.get("max_age_days", 14))
    except (TypeError, ValueError):
        max_age_days = 14
    if max_age_days < 1:
        print("  [!] gws retention max_age_days must be >= 1; skipping cleanup.")
        return

    name_prefix = str(retention_cfg.get("name_prefix", "20") or "")
    name_suffix = str(retention_cfg.get("name_suffix", ".epub") or "")
    try:
        page_size = int(retention_cfg.get("page_size", 200))
    except (TypeError, ValueError):
        page_size = 200
    page_size = max(1, min(page_size, 1000))

    cutoff = now_utc() - timedelta(days=max_age_days)
    query = (
        f'"{folder_id}" in parents and trashed = false and '
        'mimeType = "application/epub+zip"'
    )
    params = {
        "q": query,
        "pageSize": page_size,
        "fields": "files(id,name,createdTime)",
    }

    try:
        listed = subprocess.run(
            [
                "gws", "drive", "files", "list",
                "--params", json.dumps(params),
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
            env=env,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        print(f"  [!] Drive retention list failed: {detail}")
        return

    try:
        payload = json.loads(listed.stdout or "{}")
        files = payload.get("files", [])
    except json.JSONDecodeError:
        print("  [!] Drive retention list parse failed; skipping cleanup.")
        return

    delete_candidates = []
    for item in files:
        file_id = item.get("id")
        name = item.get("name", "")
        created = parse_iso_dt(item.get("createdTime"))
        if not file_id or not created:
            continue
        if name_prefix and not name.startswith(name_prefix):
            continue
        if name_suffix and not name.endswith(name_suffix):
            continue
        if created >= cutoff:
            continue
        delete_candidates.append({"id": file_id, "name": name, "created": created})

    if not delete_candidates:
        print(f"  Drive retention: no EPUB files older than {max_age_days} day(s).")
        return

    if dry_run:
        for item in sorted(delete_candidates, key=lambda x: x["created"]):
            print(f"  Drive retention dry-run: would delete {item['name']} (id={item['id']})")
        print(
            f"  Drive retention summary: would delete {len(delete_candidates)}, "
            f"threshold {max_age_days} day(s)."
        )
        return

    deleted = 0
    failed = 0
    for item in sorted(delete_candidates, key=lambda x: x["created"]):
        try:
            subprocess.run(
                [
                    "gws", "drive", "files", "delete",
                    "--params", json.dumps({"fileId": item["id"]}),
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
                env=env,
            )
            deleted += 1
            print(f"  Drive retention deleted: {item['name']} (id={item['id']})")
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            failed += 1
            detail = getattr(e, "stderr", "") or str(e)
            print(f"  [!] Drive retention delete failed for {item['name']}: {detail}")

    print(
        f"  Drive retention summary: deleted {deleted}, failed {failed}, "
        f"threshold {max_age_days} day(s)."
    )


def upload_to_gws_drive(epub_path, delivery_cfg):
    """Upload EPUB to Google Drive using the gws CLI machine profile."""
    gws_cfg = delivery_cfg.get("gws_drive", {})
    folder_id = (gws_cfg.get("folder_id") or "").strip()
    if not folder_id:
        print("  [!] delivery.gws_drive.folder_id is not set in sources.yaml.")
        print(f"      EPUB is at: {epub_path}")
        return False

    env = os.environ.copy()
    env.pop("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE", None)
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
        purge_old_drive_epubs(folder_id=folder_id, gws_cfg=gws_cfg, env=env)
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
# Companion note
# ---------------------------------------------------------------------------

def write_companion_note(vault_root, today, delivered_items, queue):
    note_dir = vault_root / "Machine" / "AI Workflows"
    note_path = note_dir / f"kobo-deep-dive-{today}.md"
    pending = queue.get("pending", [])
    processed_count = len(queue.get("processed", []))

    lines = [
        "---",
        f'title: "Kobo Deep Dive — {today}"',
        'type: "research"',
        'topic: "AI Workflows"',
        f'captured: {today}',
        f'updated: {today}',
        'staleness: "High — single-day snapshot"',
        "---",
        "",
        f"# Kobo Deep Dive — {today}",
        "",
        "## Delivered Articles",
        "",
        "## Queue",
        "",
        f"- Topics pending: {len(pending)}",
        f"- Processed all-time: {processed_count}",
        "",
    ]
    if delivered_items:
        for item in delivered_items:
            topic = item["topic"]
            epub_path = item["epub_path"]
            lines += [
                f"**{topic['title']}**",
                "",
                f"- Source: [{topic.get('source_name', 'N/A')}]({topic.get('url', '')})",
                f"- EPUB: `{epub_path.name}`",
                "",
            ]
    else:
        lines += ["No successful deliveries in this run.", ""]

    if pending[:5]:
        lines += ["**Up next:**", ""]
        for t in pending[:5]:
            lines.append(f"- {t['title']} *(score: {t.get('score', 0):.2f})*")
        lines.append("")
    lines += [
        "---",
        "",
        "## Related",
        "- [[kobo-daily-reader-sop]]",
        "- [[kobo-daily-reader-implementation-plan]]",
        "",
    ]
    note_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Companion note: {note_path.name}")


# ---------------------------------------------------------------------------
# Vault detection
# ---------------------------------------------------------------------------

def find_vault_root(hint=None):
    if hint:
        return Path(hint).expanduser()
    p = SCRIPT_DIR
    while p != p.parent:
        if (p / "AGENTS.md").exists() or (p / "CLAUDE.md").exists():
            return p
        p = p.parent
    return SCRIPT_DIR.parent.parent


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Kobo Daily AI Deep-Dive Reader")
    parser.add_argument("--dry-run", action="store_true",
                        help="Crawl and score topics but skip generation and EPUB build")
    parser.add_argument("--topic-id", metavar="ID",
                        help="Force a specific topic ID from the queue (skip discovery)")
    parser.add_argument("--count", metavar="N", type=int, default=1,
                        help="Number of queue items to generate in this run (default: 1)")
    parser.add_argument("--no-sync", action="store_true",
                        help="Build EPUB locally, skip delivery")
    parser.add_argument("--output-dir", metavar="DIR", default="~/Desktop",
                        help="Local directory for the output EPUB (default: ~/Desktop)")
    parser.add_argument("--vault", metavar="DIR",
                        help="Obsidian vault root (auto-detected from script location if unset)")
    args = parser.parse_args()

    vault_root = find_vault_root(args.vault)
    output_dir = Path(args.output_dir).expanduser()
    today = datetime.now().strftime("%Y-%m-%d")
    file_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'='*60}")
    print(f"  Kobo Daily Deep-Dive  —  {today}")
    print(f"{'='*60}\n")

    sources = load_sources()
    queue = load_queue()
    gen_cfg = sources.get("generation", {})
    delivery_cfg = sources.get("delivery", {})
    build_cfg = sources.get("build", {})
    batch_cfg = sources.get("batch", {})
    selection_cfg = sources.get("selection", {})
    quality_cfg = merge_quality_config(sources.get("quality", {}))
    quality_enabled = bool(quality_cfg.get("enabled", True))
    prefer_layers = bool(selection_cfg.get("prefer_layers", True))
    allow_fallback_layers = bool(selection_cfg.get("allow_fallback_layers", True))
    preferred_layers = set(
        selection_cfg.get(
            "preferred_layers",
            ["practitioner_core", "practitioner_secondary"],
        )
    )
    fallback_layers = set(
        selection_cfg.get(
            "fallback_layers",
            ["research_primary", "radar", "unknown"],
        )
    )
    feed_meta = build_feed_meta_index(sources.get("rss_feeds", []))
    enriched = enrich_queue_metadata(queue, feed_meta)
    if enriched:
        print(f"  Backfilled source metadata on {enriched} pending queue item(s).")

    ref_now = now_utc()
    expired_rejections = prune_expired_rejections(queue, ref_now)
    if expired_rejections:
        print(f"  Cleared {expired_rejections} expired quality rejections from cache.")

    if not args.dry_run:
        require_build_dependencies()

    max_batch_per_run = int(batch_cfg.get("max_count_per_run", 10))
    requested_count = args.count
    if requested_count < 1:
        print("--count must be >= 1")
        sys.exit(1)
    if args.topic_id and requested_count != 1:
        print("  [!] --topic-id forces a single topic; ignoring --count.")
        requested_count = 1

    selected_topics = []
    _, words_per_minute, _, hard_max_words = resolve_generation_targets(gen_cfg)

    if args.topic_id:
        matches = [t for t in queue.get("pending", []) if t["id"] == args.topic_id]
        if not matches:
            print(f"Topic ID '{args.topic_id}' not found in pending queue.")
            sys.exit(1)
        selected_topics = [matches[0]]
        print(f"Forced topic: {selected_topics[0]['title']}\n")
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
        hard_filtered_new = 0
        for c in candidates:
            enrich_topic_source_metadata(c, feed_meta)
            if is_processed(queue, c["id"]):
                continue

            if quality_enabled:
                hard_reason = hard_filter_reason(c, quality_cfg)
                if hard_reason:
                    hard_filtered_new += 1
                    cache_rejection(
                        queue,
                        c,
                        f"hard_filter:{hard_reason}",
                        provider="hard_filter",
                        model="regex",
                        days=int(quality_cfg.get("reject_cache_days", 7)),
                        ref_time=ref_now,
                    )
                    continue

            existing = next((t for t in queue["pending"] if t["id"] == c["id"]), None)
            if existing:
                _, breakdown, social_debug = score_candidate(
                    c, hn, reddit, queue, weights, half_life, include_components=True
                )
                existing.setdefault("social", {})
                existing["social"]["hn_points"] = social_debug.get("hn_points", 0)
                existing["social"]["reddit_score"] = social_debug.get("reddit_score", 0)
                existing["score_breakdown"] = breakdown
                continue
            score, breakdown, social_debug = score_candidate(
                c, hn, reddit, queue, weights, half_life, include_components=True
            )
            c["score"] = score
            c["score_breakdown"] = breakdown
            c.setdefault("social", {})
            c["social"]["hn_points"] = social_debug.get("hn_points", 0)
            c["social"]["reddit_score"] = social_debug.get("reddit_score", 0)
            c["discovered"] = today
            queue["pending"].append(c)
            new_count += 1

        pruned_offtopic = prune_offtopic_pending(queue, sources.get("rss_feeds", []))
        hard_pruned_pending = 0
        if quality_enabled:
            kept_pending = []
            for t in queue["pending"]:
                hard_reason = hard_filter_reason(t, quality_cfg)
                if hard_reason:
                    hard_pruned_pending += 1
                    cache_rejection(
                        queue,
                        t,
                        f"hard_filter:{hard_reason}",
                        provider="hard_filter",
                        model="regex",
                        days=int(quality_cfg.get("reject_cache_days", 7)),
                        ref_time=ref_now,
                    )
                    continue
                kept_pending.append(t)
            queue["pending"] = kept_pending

        for t in queue["pending"]:
            score, breakdown, social_debug = score_candidate(
                t, hn, reddit, queue, weights, half_life, include_components=True
            )
            t["score"] = score
            t["score_breakdown"] = breakdown
            t.setdefault("social", {})
            t["social"]["hn_points"] = social_debug.get("hn_points", 0)
            t["social"]["reddit_score"] = social_debug.get("reddit_score", 0)
        queue["pending"].sort(key=lambda t: t["score"], reverse=True)

        print(f"\nDiscovery: {new_count} new  |  {len(queue['pending'])} pending total")
        if pruned_offtopic:
            print(f"  Pruned off-topic pending items: {pruned_offtopic}")
        if quality_enabled:
            print(f"  Quality hard-filtered: {hard_filtered_new} new  |  {hard_pruned_pending} existing")

        if not queue["pending"]:
            print("No candidate topics found. Try widening days_back in sources.yaml.")
            sys.exit(0)

        if requested_count > max_batch_per_run:
            print(f"  [!] --count {requested_count} exceeds max_batch_per_run={max_batch_per_run}; capping.")
        effective_count = min(requested_count, max_batch_per_run, len(queue["pending"]))

        if quality_enabled:
            reject_idx = rejection_index(queue, ref_now)
            eligible_pending = [t for t in queue["pending"] if t.get("id") not in reject_idx]
            top_k = max(1, int(quality_cfg.get("top_k", 5)))
            preferred_pending, fallback_pending = partition_candidates_by_layer(
                eligible_pending, preferred_layers, fallback_layers
            )
            selected_topics = []
            llm_rejected = 0
            llm_checked = 0

            if not args.dry_run:
                if prefer_layers:
                    phase_windows = []
                    preferred_window = preferred_pending[:top_k]
                    fallback_window = fallback_pending[:top_k]
                    if preferred_window:
                        phase_windows.append(("preferred", preferred_window))
                    if allow_fallback_layers and fallback_window:
                        phase_windows.append(("fallback", fallback_window))
                    if not phase_windows:
                        phase_windows = [("all", eligible_pending[:top_k])]
                else:
                    phase_windows = [("all", eligible_pending[:top_k])]

                for phase_name, window in phase_windows:
                    if not window:
                        continue
                    print(
                        f"  Quality LLM gate ({phase_name}): checking top {len(window)} eligible topic(s)..."
                    )
                    for topic in window:
                        accepted, gate_result = llm_quality_gate(topic, gen_cfg, quality_cfg)
                        llm_checked += 1
                        if accepted:
                            topic["quality_gate"] = gate_result
                            selected_topics.append(topic)
                            if len(selected_topics) >= effective_count:
                                break
                        else:
                            llm_rejected += 1
                            cache_rejection(
                                queue,
                                topic,
                                f"llm_gate:{gate_result.get('reason', 'no_reason')}",
                                provider=gate_result.get("provider", "unknown"),
                                model=gate_result.get("model", "unknown"),
                                days=int(quality_cfg.get("reject_cache_days", 7)),
                                ref_time=ref_now,
                            )
                    if len(selected_topics) >= effective_count:
                        break
                if len(selected_topics) < effective_count:
                    print(
                        f"  [!] Quality gate approved {len(selected_topics)} topic(s) "
                        f"out of requested {effective_count}."
                    )
                print(
                    f"  Quality LLM results: checked {llm_checked}, "
                    f"accepted {len(selected_topics)}, rejected {llm_rejected}"
                )
            else:
                if prefer_layers:
                    selected_topics = list(preferred_pending[:effective_count])
                    if len(selected_topics) < effective_count and allow_fallback_layers:
                        needed = effective_count - len(selected_topics)
                        selected_topics.extend(fallback_pending[:needed])
                    print(
                        f"  [DRY RUN] Layer preference: preferred={len(preferred_pending)} "
                        f"| fallback={len(fallback_pending)} | selected={len(selected_topics)}"
                    )
                else:
                    selected_topics = eligible_pending[:effective_count]
                print(
                    f"  [DRY RUN] Quality LLM gate skipped; showing top {len(selected_topics)} "
                    "eligible topics before LLM checks."
                )
        else:
            if prefer_layers:
                preferred_pending, fallback_pending = partition_candidates_by_layer(
                    queue["pending"], preferred_layers, fallback_layers
                )
                selected_topics = list(preferred_pending[:effective_count])
                if len(selected_topics) < effective_count and allow_fallback_layers:
                    needed = effective_count - len(selected_topics)
                    selected_topics.extend(fallback_pending[:needed])
            else:
                selected_topics = list(queue["pending"][:effective_count])

    if args.dry_run:
        if args.topic_id:
            print("\n[DRY RUN] Forced topic:\n")
            t = selected_topics[0]
            pub = (t.get("published") or "")[:10]
            print(f"   1. [{t.get('score', 0):.3f}] {t['title'][:70]}")
            print(f"      {t.get('source_name', '')}  |  {pub}")
        else:
            preview_n = max(10, requested_count)
            print(f"\n[DRY RUN] Top {preview_n} candidates:\n")
            for i, t in enumerate(queue["pending"][:preview_n], 1):
                pub = (t.get("published") or "")[:10]
                print(f"  {i:2}. [{t['score']:.3f}] {t['title'][:70]}")
                print(f"        {t.get('source_name', '')}  |  {pub}")
            print(f"\nWould generate {len(selected_topics)} topic(s) in non-dry mode.")
        save_queue(queue)
        print("\nQueue saved. Exiting (--dry-run).\n")
        return

    if not selected_topics:
        save_queue(queue)
        print("\nNo quality-approved topics available in the current gate window. Exiting.\n")
        return

    delivered_items = []
    built_only_items = []
    failed_titles = []
    total_topics = len(selected_topics)

    for index, selected in enumerate(selected_topics, 1):
        print(f"\n{'─'*60}")
        print(f"  Topic {index}/{total_topics}: {selected['title'][:70]}")
        print(f"  Source: {selected.get('source_name', '')}  |  Score: {selected.get('score', 0):.3f}")
        print(f"  URL   : {selected.get('url', '')}")
        print(f"{'─'*60}\n")

        try:
            print("Phase 2: Fetching source content...")
            content = fetch_content(selected, max_chars=gen_cfg.get("max_source_chars", 40000))
            print(f"  {len(content):,} chars retrieved")

            print("\nPhase 3: Generating deep dive...")
            draft = generate_deep_dive(selected, content, gen_cfg)
            word_count = len(draft.split())
            estimated_minutes = max(1, round(word_count / max(words_per_minute, 1)))
            print(f"  {word_count:,} words  (~{estimated_minutes} min read @ {words_per_minute} wpm)")
            if word_count > hard_max_words:
                print(f"  [!] Word count exceeds configured hard_max_words={hard_max_words}.")

            print("\nPhase 4: Critic pass...")
            critique_result = critique_draft(selected, content, draft, gen_cfg)
            n_concerns = len(critique_result.get("concerns", []))
            print(f"  {critique_result.get('overall_assessment', 'unknown')}  |  {n_concerns} concern(s)")

            print("\nPhase 5: Assembling final document...")
            final_md = assemble_final(draft, critique_result, selected)

            print("\nPhase 6: Building publication...")
            output_dir.mkdir(parents=True, exist_ok=True)
            safe_title = re.sub(r"[^\w\s-]", "", selected["title"])[:50].strip().replace(" ", "_")
            safe_topic_id = re.sub(r"[^\w-]", "_", selected.get("id", ""))[:12]
            if safe_topic_id:
                output_stem = output_dir / f"{file_date}-{safe_title}_{safe_topic_id}"
            else:
                output_stem = output_dir / f"{file_date}-{safe_title}"

            with tempfile.TemporaryDirectory() as tmp:
                publication_path = build_publication(
                    final_md,
                    output_stem,
                    Path(tmp),
                    selected["title"],
                    build_cfg,
                )

            delivered = False
            if not args.no_sync:
                print("\nPhase 7: Delivering...")
                delivered = deliver_epub(publication_path, delivery_cfg)
            else:
                print(f"\n[--no-sync] Publication saved locally: {publication_path}")

            if delivered:
                queue["pending"] = [t for t in queue["pending"] if t["id"] != selected["id"]]
                queue.setdefault("processed", []).append({
                    "id": selected["id"],
                    "title": selected["title"],
                    "source_name": selected.get("source_name"),
                    "source_layer": selected.get("source_layer"),
                    "source_role": selected.get("source_role"),
                    "delivered": today,
                    "epub": publication_path.name,
                })
                delivered_items.append({"topic": selected, "epub_path": publication_path})
            else:
                print("  Delivery not confirmed; topic remains in pending queue for retry.")
                built_only_items.append({"topic": selected, "publication_path": publication_path})
        except Exception as e:
            print(f"  [!] Topic failed: {e}")
            failed_titles.append(selected["title"])

    save_queue(queue)
    if delivered_items:
        write_companion_note(vault_root, today, delivered_items, queue)

    print(f"\n{'='*60}")
    print(f"  Requested topics: {total_topics}")
    print(f"  Delivered: {len(delivered_items)}")
    print(f"  Built only: {len(built_only_items)}")
    print(f"  Failed before build/delivery: {len(failed_titles)}")
    if delivered_items:
        print("  Delivered files:")
        for item in delivered_items[:5]:
            print(f"    - {item['epub_path'].name}")
    if failed_titles:
        print("  Failed topics:")
        for title in failed_titles[:5]:
            print(f"    - {title[:70]}")
    print(f"  Queue: {len(queue['pending'])} pending")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"\n[ERROR] {exc}")
        sys.exit(1)
