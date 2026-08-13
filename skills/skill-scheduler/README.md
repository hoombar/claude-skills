# Skill Scheduler

Run one cron heartbeat that dispatches recurring skills and scripts from local config.

## Quick Start

```bash
cd skills/skill-scheduler
cp skill_cron.example.toml skill_cron.toml
python3 skill_cron.py doctor
python3 skill_cron.py list
python3 skill_cron.py tick --dry-run
```

Add one cron entry on the host that should run the jobs:

```cron
* * * * * /usr/bin/python3 /path/to/skill-scheduler/skill_cron.py tick --quiet --config /path/to/skill-scheduler/skill_cron.toml >> /path/to/logs/skill_cron.log 2>&1
```

## Config Model

The scheduler reads `skill_cron.toml` by default.

```toml
[settings]
state_dir = "/home/ben/.local/state/skill-cron"
max_jobs_per_tick = 3

[[notifications]]
id = "phone"
provider = "ntfy"
enabled = true
events = ["failed", "timeout"]
url = "http://127.0.0.1:2586"
topic = "skill-scheduler"

[commands.example]
argv = ["/usr/bin/python3", "/path/to/script.py", "--count", "1"]
timeout_seconds = 2700
log_path = "/path/to/logs/example.log"

[[jobs]]
id = "example-job"
title = "Example Job"
enabled = true
command_id = "example"
schedule = { weekly = "mon,thu 05:00" }
```

Schedules support:

```toml
schedule = { every = "15m" }
schedule = { every = "1h" }
schedule = { daily_at = "05:00" }
schedule = { weekly = "sun 18:00" }
schedule = { weekly = "mon,thu 05:00" }
```

## Commands

```bash
python3 skill_cron.py doctor
python3 skill_cron.py list
python3 skill_cron.py tick
python3 skill_cron.py tick --dry-run
python3 skill_cron.py tick --quiet
python3 skill_cron.py run <job-id>
python3 skill_cron.py run <job-id> --dry-run
```

## State

The runner writes these files under `settings.state_dir`:

- `state.json` - latest per-job status.
- `runs.jsonl` - append-only run log.
- `locks/scheduler.lock` - global tick lock.
- `locks/<job-id>.lock` - per-job lock.

## Notifications

Notifications are optional `[[notifications]]` tables. They run after a job finishes and do not change the job result if notification delivery fails.

Supported providers:

- `ntfy` - posts to `<url>/<topic>` using ntfy's HTTP API.
- `webhook` - posts JSON to `url` for custom integrations.

Supported events:

- `success` - successful job runs.
- `failed` - non-zero exit status or launch errors.
- `timeout` - job exceeded `timeout_seconds`.
- `failure` - shorthand for `failed` and `timeout`.
- `completion` - shorthand for `success`, `failed`, and `timeout`.

For ntfy token auth, set `token_env = "NTFY_TOKEN"` and provide that environment variable to cron. Do not store secrets in TOML.

## Design Notes

- Scheduling and locking are deterministic Python, not LLM reasoning.
- Jobs dispatch to explicit argv arrays, never shell strings.
- Agentic skills should usually be slow-cadence and checkpoint-driven.
- High-frequency jobs should usually run cheap deterministic handlers that exit quickly when there is no new work.

See [`SKILL.md`](SKILL.md) for operational guidance.
