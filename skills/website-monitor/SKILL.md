---
name: website-monitor
description: Configure and operate deterministic website monitoring for page regions, listings, pagination, meaningful changes, and optional semantic relevance evaluation. Use when the user wants to watch websites, detect new items, replace changedetection.io watches, inspect monitor history, or debug website checks.
allowed-tools: Bash(python3 *), Bash(codex *), Read, Grep, Glob
---

# Website Monitor

Use `website_monitor.py` to fetch configured websites, extract canonical document content or structured items, compare against persistent state, and report semantic events to `skill-scheduler`.

## Principles

- Keep personal URLs, selectors, evaluator commands, and runtime paths in a machine-local config file.
- Prefer static HTTP. Use the optional Playwright fetcher only when target content requires JavaScript rendering or interaction.
- Prefer structured item extraction for listings. Stable item keys prevent reorder and pagination changes from generating false alerts.
- Use deterministic relevance rules first. Invoke an evaluator only after a real delta and only when `semantic_intent` is configured.
- Extract a public `url` field for listing items when possible. A single added item becomes the notification tap target; otherwise notifications open the monitor source URL.
- Preview extraction before establishing a baseline.

## Commands

```bash
python3 website_monitor.py doctor --config /path/to/monitors.toml
python3 website_monitor.py list --config /path/to/monitors.toml
python3 website_monitor.py preview <monitor-id> --config /path/to/monitors.toml
python3 website_monitor.py baseline <monitor-id> --config /path/to/monitors.toml
python3 website_monitor.py run <monitor-id> --config /path/to/monitors.toml
python3 website_monitor.py history <monitor-id> --config /path/to/monitors.toml
```

`baseline` stores the current observation without raising a change event. `run` emits `initialized`, `unchanged`, `changed`, or `changed_suppressed` through `SKILL_SCHEDULER_RESULT_FILE` when invoked by the scheduler.

See `README.md` and `website_monitor.example.toml` for configuration details.
