---
name: skill-scheduler
description: Run a single cron-invoked scheduler that dispatches recurring Claude skills, scripts, and deterministic handlers from local TOML config. Use when the user wants to consolidate cron jobs, schedule existing skills such as Kobo EPUB or YouTube podcast generation, add recurring agentic workflows, inspect scheduler state, or debug scheduled skill execution.
allowed-tools: Bash(python3 *), Bash(flock *), Bash(timeout *), Bash(claude *), Bash(codex *), Bash(git *)
---

# Skill Scheduler

Use this skill to consolidate recurring automation behind one cron entry while keeping scheduling, locking, retry, and state handling deterministic.

The scheduler's default config lives next to the skill, and its runtime state lives in a local state directory configured in `skill_cron.toml`.

## What This Skill Includes

- `skill_cron.py` - deterministic scheduler CLI.
- `skill_cron.example.toml` - starter config with examples for Kobo EPUBs, YouTube podcasts, maintenance checks, and agentic skills.
- `README.md` - quick-start and config reference.

## Core Model

```text
cron -> skill_cron.py tick -> due job decision -> registered command argv
```

The LLM should not recalculate schedules every few minutes. The Python runner decides whether a job is due. Skills, scripts, or agents do the actual work only after the runner selects a due job.

## Setup

1. Copy the example config:

```bash
cp <skill-dir>/skill_cron.example.toml <skill-dir>/skill_cron.toml
```

2. Edit `skill_cron.toml`:

- Set `settings.state_dir` to a durable local directory on the machine that runs cron.
- Add one `commands.<id>.argv` entry per allowed script or skill invocation.
- Add one `[[jobs]]` entry per scheduled recurring workflow.
- Optionally add `[[notifications]]` entries for completion or failure alerts.
- Keep commands as argv arrays. Do not use shell strings for routine automation.
- Set `commands.<id>.log_path` when a job should continue writing to an existing per-job log file.

3. Test the config:

```bash
python3 <skill-dir>/skill_cron.py doctor --config <skill-dir>/skill_cron.toml
python3 <skill-dir>/skill_cron.py list --config <skill-dir>/skill_cron.toml
python3 <skill-dir>/skill_cron.py tick --dry-run --config <skill-dir>/skill_cron.toml
```

4. Add one cron entry:

```cron
* * * * * /usr/bin/python3 /path/to/skill-scheduler/skill_cron.py tick --quiet --config /path/to/skill-scheduler/skill_cron.toml >> /path/to/logs/skill_cron.log 2>&1
```

## Supported Schedules

Use one of these schedule shapes per job:

```toml
schedule = { every = "15m" }
schedule = { every = "1h" }
schedule = { daily_at = "05:00" }
schedule = { weekly = "mon,thu 05:00" }
```

Intervals support `s`, `m`, `h`, and `d` units.

## Operating Commands

```bash
# Show config, command, and state health
python3 skill_cron.py doctor

# List jobs and due status
python3 skill_cron.py list

# Run due jobs
python3 skill_cron.py tick

# Preview due jobs without executing
python3 skill_cron.py tick --dry-run

# Suppress output when no jobs are selected
python3 skill_cron.py tick --quiet

# Force one job by id
python3 skill_cron.py run kobo-epub
```

## Notifications

Use optional `[[notifications]]` entries when the user wants alerts after job completion or failure. Providers are intentionally configurable so installations can swap notification systems later.

```toml
[[notifications]]
id = "phone"
provider = "ntfy"
enabled = true
events = ["failed", "timeout"]
url = "http://127.0.0.1:2586"
topic = "skill-scheduler"
```

Supported providers:

- `ntfy` posts to the ntfy HTTP API.
- `webhook` posts JSON to a custom endpoint.

Supported events are `success`, `failed`, `timeout`, `failure`, and `completion`. Notification delivery errors are logged to stderr but do not change the job result.

Successful commands may report `initialized`, `unchanged`, `changed`, or `changed_suppressed` by writing versioned JSON to `SKILL_SCHEDULER_RESULT_FILE`. Use notification `job_ids` to scope providers to selected jobs.

## Safety Rules

- Prefer deterministic script handlers for frequent or expensive jobs.
- Use `agent-skill` jobs sparingly; they should usually be checkpoint-driven or run on slow cadences.
- Do not put secrets in `skill_cron.toml`. Reference authenticated local CLIs or environment already configured for the cron user.
- Do not use shell pipelines or compound shell strings. Register explicit argv arrays instead.
- Use per-job `timeout_seconds` so stuck jobs cannot block later ticks indefinitely.

## First Jobs To Migrate

- Kobo EPUB generation: command points at `kobo-epub-pipeline/kobo_daily_reader.py`.
- YouTube podcast generation: command points at `youtube-podcast-generator/youtube_research_podcast.py`.
- Maintenance checks: command should call a deterministic handler that exits quickly when there is no new work.
- Agentic reviews: start disabled until the desired unattended behavior is explicit.

## Troubleshooting

- `Config file not found`: copy `skill_cron.example.toml` to `skill_cron.toml` or pass `--config`.
- `tomllib is unavailable`: run with Python 3.11 or newer.
- `Unknown command_id`: add a matching `[commands.<id>]` table.
- Job never runs: check `enabled`, schedule syntax, and `list` output.
- Job overlaps: verify `settings.state_dir` is stable and writable so lock files persist between invocations.
- Cron cannot find binaries: use absolute paths in `commands.<id>.argv`.
