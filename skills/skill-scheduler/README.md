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
default_skill_executor = "opencode"

[skill_executors.opencode]
argv = ["/usr/local/bin/opencode", "run", "--attach", "http://127.0.0.1:4096", "--dir", "/path/to/workspace", "--model", "openai/gpt-5.6-luna", "--variant", "default"]
timeout_seconds = 3600

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

[[jobs]]
id = "weekly-review"
title = "Weekly Review"
enabled = true
skill = "weekly-review"
instructions = "Follow the workspace instructions."
log_path = "/path/to/logs/weekly-review.log"
schedule = { weekly = "sun 18:00" }
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

Script jobs reference a registered `command_id`. Agentic jobs set `skill` and inherit `settings.default_skill_executor`; use `executor_id` only when a job genuinely needs a different executor. The scheduler appends the job title and generated skill prompt to the executor argv, so the OpenCode server, model, and effort are defined once.

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
- `initialized`, `unchanged`, `changed`, `changed_suppressed` - optional semantic events reported by successful commands.

For ntfy token auth, set `token_env = "NTFY_TOKEN"` and provide that environment variable to cron. Do not store secrets in TOML.

Set `job_ids = ["job-a", "job-b"]` to limit a notification provider to specific scheduler jobs.

Commands can atomically write a versioned JSON object to the path in `SKILL_SCHEDULER_RESULT_FILE`:

```json
{"schema_version":1,"event":"changed","title":"Listings changed","message":"One item was added","click_url":"https://example.com/items/new","details":{"added":1}}
```

The result file is optional. Process exit status still determines execution success or failure.

For ntfy providers, `click_url` sets the notification tap target and adds an explicit **Open page** action.

## Design Notes

- Scheduling and locking are deterministic Python, not LLM reasoning.
- Script jobs dispatch to explicit argv arrays, never shell strings.
- Skill jobs inherit one explicit executor argv and add only their generated prompt.
- Agentic skills should usually be slow-cadence and checkpoint-driven.
- High-frequency jobs should usually run cheap deterministic handlers that exit quickly when there is no new work.

See [`SKILL.md`](SKILL.md) for operational guidance.
