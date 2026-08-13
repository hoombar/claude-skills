#!/usr/bin/env python3
"""Deterministic scheduler for recurring skill and script jobs."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 guard
    tomllib = None  # type: ignore[assignment]


WEEKDAYS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}

NOTIFICATION_EVENTS = {
    "success",
    "failed",
    "timeout",
    "failure",
    "completion",
    "initialized",
    "unchanged",
    "changed",
    "changed_suppressed",
}
COMMAND_EVENTS = {"initialized", "unchanged", "changed", "changed_suppressed"}


class ConfigError(Exception):
    pass


class LockHeld(Exception):
    pass


def now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_duration(value: str) -> dt.timedelta:
    match = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", value.lower())
    if not match:
        raise ConfigError(f"Invalid interval {value!r}; use values like 15m, 1h, or 2d")
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        raise ConfigError("Intervals must be positive")
    return {
        "s": dt.timedelta(seconds=amount),
        "m": dt.timedelta(minutes=amount),
        "h": dt.timedelta(hours=amount),
        "d": dt.timedelta(days=amount),
    }[unit]


def parse_time(value: str) -> dt.time:
    try:
        hour, minute = value.split(":", 1)
        parsed = dt.time(int(hour), int(minute))
    except ValueError as exc:
        raise ConfigError(f"Invalid time {value!r}; use HH:MM in the cron host timezone") from exc
    if not (0 <= parsed.hour <= 23 and 0 <= parsed.minute <= 59):
        raise ConfigError(f"Invalid time {value!r}; use HH:MM")
    return parsed


def load_config(path: Path) -> dict[str, Any]:
    if tomllib is None:
        raise ConfigError("tomllib is unavailable; run with Python 3.11 or newer")
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    settings = config.get("settings", {})
    if not isinstance(settings, dict):
        raise ConfigError("[settings] must be a TOML table")
    if "state_dir" not in settings:
        raise ConfigError("settings.state_dir is required")
    commands = config.get("commands", {})
    if not isinstance(commands, dict) or not commands:
        raise ConfigError("At least one [commands.<id>] table is required")
    for command_id, command in commands.items():
        if not isinstance(command, dict):
            raise ConfigError(f"commands.{command_id} must be a table")
        argv = command.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
            raise ConfigError(f"commands.{command_id}.argv must be a non-empty string array")
        timeout = command.get("timeout_seconds", 3600)
        if not isinstance(timeout, int) or timeout <= 0:
            raise ConfigError(f"commands.{command_id}.timeout_seconds must be a positive integer")
        log_path = command.get("log_path")
        if log_path is not None and not isinstance(log_path, str):
            raise ConfigError(f"commands.{command_id}.log_path must be a string when set")
    jobs = config.get("jobs", [])
    if not isinstance(jobs, list):
        raise ConfigError("[[jobs]] entries are required")
    seen_ids: set[str] = set()
    for job in jobs:
        validate_job(job, commands, seen_ids)
    notifications = config.get("notifications", [])
    if notifications is None:
        return
    if not isinstance(notifications, list):
        raise ConfigError("[[notifications]] entries must be TOML tables")
    seen_notification_ids: set[str] = set()
    for notification in notifications:
        validate_notification(notification, seen_notification_ids, seen_ids)


def validate_job(job: Any, commands: dict[str, Any], seen_ids: set[str]) -> None:
    if not isinstance(job, dict):
        raise ConfigError("Each [[jobs]] entry must be a table")
    job_id = job.get("id")
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", job_id):
        raise ConfigError("Each job id must contain only letters, numbers, dots, underscores, and hyphens")
    if job_id in seen_ids:
        raise ConfigError(f"Duplicate job id: {job_id}")
    seen_ids.add(job_id)
    command_id = job.get("command_id")
    if command_id not in commands:
        raise ConfigError(f"Job {job_id} references unknown command_id {command_id!r}")
    schedule = job.get("schedule")
    if not isinstance(schedule, dict):
        raise ConfigError(f"Job {job_id} requires schedule table")
    keys = {key for key in schedule if key in {"every", "daily_at", "weekly"}}
    if len(keys) != 1:
        raise ConfigError(f"Job {job_id} schedule must contain exactly one of every, daily_at, weekly")
    if "every" in schedule:
        parse_duration(str(schedule["every"]))
    if "daily_at" in schedule:
        parse_time(str(schedule["daily_at"]))
    if "weekly" in schedule:
        parse_weekly(str(schedule["weekly"]))


def validate_notification(notification: Any, seen_ids: set[str], valid_job_ids: set[str]) -> None:
    if not isinstance(notification, dict):
        raise ConfigError("Each [[notifications]] entry must be a table")
    notification_id = notification.get("id")
    if not isinstance(notification_id, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", notification_id):
        raise ConfigError("Each notification id must contain only letters, numbers, dots, underscores, and hyphens")
    if notification_id in seen_ids:
        raise ConfigError(f"Duplicate notification id: {notification_id}")
    seen_ids.add(notification_id)
    provider = notification.get("provider")
    if provider not in {"ntfy", "webhook"}:
        raise ConfigError(f"notifications.{notification_id}.provider must be ntfy or webhook")
    enabled = notification.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(f"notifications.{notification_id}.enabled must be boolean")
    events = notification.get("events", ["failed", "timeout"])
    if not isinstance(events, list) or not events or not all(isinstance(item, str) for item in events):
        raise ConfigError(f"notifications.{notification_id}.events must be a non-empty string array")
    unknown_events = sorted(set(events) - NOTIFICATION_EVENTS)
    if unknown_events:
        raise ConfigError(f"notifications.{notification_id}.events has unknown values: {', '.join(unknown_events)}")
    job_ids = notification.get("job_ids", [])
    if not isinstance(job_ids, list) or not all(isinstance(item, str) and item for item in job_ids):
        raise ConfigError(f"notifications.{notification_id}.job_ids must be a string array when set")
    unknown_job_ids = sorted(set(job_ids) - valid_job_ids)
    if unknown_job_ids:
        raise ConfigError(f"notifications.{notification_id}.job_ids has unknown values: {', '.join(unknown_job_ids)}")
    url = notification.get("url")
    if not isinstance(url, str) or not url:
        raise ConfigError(f"notifications.{notification_id}.url is required")
    if provider == "ntfy":
        topic = notification.get("topic")
        if not isinstance(topic, str) or not topic:
            raise ConfigError(f"notifications.{notification_id}.topic is required for ntfy")
        token_env = notification.get("token_env")
        if token_env is not None and not isinstance(token_env, str):
            raise ConfigError(f"notifications.{notification_id}.token_env must be a string when set")
        tags = notification.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
            raise ConfigError(f"notifications.{notification_id}.tags must be a string array when set")
    if provider == "webhook":
        headers = notification.get("headers", {})
        if not isinstance(headers, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in headers.items()):
            raise ConfigError(f"notifications.{notification_id}.headers must be a string table when set")


def state_dir(config: dict[str, Any], config_path: Path) -> Path:
    raw = str(config["settings"]["state_dir"])
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path


def load_state(path: Path) -> dict[str, Any]:
    state_path = path / "state.json"
    if not state_path.exists():
        return {"jobs": {}}
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except json.JSONDecodeError:
        return {"jobs": {}}
    if not isinstance(state, dict):
        return {"jobs": {}}
    state.setdefault("jobs", {})
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    tmp = path / "state.json.tmp"
    final = path / "state.json"
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(final)


def append_log(path: Path, record: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def append_command_log(command: dict[str, Any], record: dict[str, Any]) -> None:
    raw_log_path = command.get("log_path")
    if not raw_log_path:
        return
    log_path = Path(str(raw_log_path)).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== {record['job_id']} {record['status']} {record['started_at']} -> {record['finished_at']} ===\n")
        if "returncode" in record:
            handle.write(f"returncode: {record['returncode']}\n")
        if "timeout_seconds" in record:
            handle.write(f"timeout_seconds: {record['timeout_seconds']}\n")
        stdout = record.get("stdout_for_log", "")
        stderr = record.get("stderr_for_log", "")
        if stdout:
            handle.write("--- stdout ---\n")
            handle.write(stdout)
            if not stdout.endswith("\n"):
                handle.write("\n")
        if stderr:
            handle.write("--- stderr ---\n")
            handle.write(stderr)
            if not stderr.endswith("\n"):
                handle.write("\n")


def notification_matches(notification: dict[str, Any], record: dict[str, Any]) -> bool:
    job_ids = set(notification.get("job_ids", []))
    if job_ids and record["job_id"] not in job_ids:
        return False
    status = str(record["status"])
    event = str(record.get("event", ""))
    events = set(notification.get("events", ["failed", "timeout"]))
    if status in events or event in events:
        return True
    if "failure" in events and status in {"failed", "timeout"}:
        return True
    if "completion" in events and status in {"success", "failed", "timeout"}:
        return True
    return False


def notification_payload(job: dict[str, Any], record: dict[str, Any]) -> tuple[str, str]:
    title = str(record.get("title") or job.get("title") or record["job_id"])
    status = str(record["status"])
    outcome = str(record.get("event", status))
    notification_title = str(record.get("event_title") or f"Skill Scheduler: {title} {outcome}")
    lines = [
        f"Job: {record['job_id']}",
        f"Status: {status}",
        f"Started: {record['started_at']}",
        f"Finished: {record['finished_at']}",
    ]
    if "returncode" in record:
        lines.append(f"Return code: {record['returncode']}")
    if "timeout_seconds" in record:
        lines.append(f"Timeout: {record['timeout_seconds']} seconds")
    if record.get("event_message"):
        lines.extend(["", str(record["event_message"])])
    stderr_tail = str(record.get("stderr_tail", "")).strip()
    if stderr_tail:
        lines.append("")
        lines.append(stderr_tail[-1200:])
    return notification_title, "\n".join(lines)


def send_ntfy_notification(notification: dict[str, Any], title: str, message: str, status: str) -> None:
    base_url = str(notification["url"]).rstrip("/")
    topic = urllib.parse.quote(str(notification["topic"]).strip("/"), safe="")
    url = f"{base_url}/{topic}"
    headers = {
        "Title": title,
        "Priority": str(notification.get("priority", "high" if status in {"failed", "timeout"} else "default")),
    }
    tags = notification.get("tags", [])
    if tags:
        headers["Tags"] = ",".join(str(tag) for tag in tags)
    token_env = notification.get("token_env")
    if token_env:
        token = os.environ.get(str(token_env))
        if not token:
            raise RuntimeError(f"environment variable {token_env} is not set")
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=int(notification.get("timeout_seconds", 10))) as response:
        response.read()


def send_webhook_notification(notification: dict[str, Any], title: str, message: str, record: dict[str, Any]) -> None:
    headers = {"Content-Type": "application/json"}
    headers.update(notification.get("headers", {}))
    payload = {
        "title": title,
        "message": message,
        "record": {key: value for key, value in record.items() if key not in {"stdout_for_log", "stderr_for_log"}},
    }
    request = urllib.request.Request(
        str(notification["url"]),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=int(notification.get("timeout_seconds", 10))) as response:
        response.read()


def send_notifications(config: dict[str, Any], job: dict[str, Any], record: dict[str, Any]) -> None:
    for notification in config.get("notifications", []):
        if notification.get("enabled") is False or not notification_matches(notification, record):
            continue
        title, message = notification_payload(job, record)
        try:
            if notification["provider"] == "ntfy":
                send_ntfy_notification(notification, title, message, str(record["status"]))
            elif notification["provider"] == "webhook":
                send_webhook_notification(notification, title, message, record)
        except (OSError, RuntimeError, urllib.error.URLError, TimeoutError) as exc:
            print(f"NOTIFY FAILED {record['job_id']} {notification['id']}: {exc}", file=sys.stderr)


def read_command_result(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 65536:
            raise ValueError("result exceeds 65536 bytes")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("unsupported result schema")
        event = value.get("event")
        if event not in COMMAND_EVENTS:
            raise ValueError(f"unknown event {event!r}")
        title = value.get("title", "")
        message = value.get("message", "")
        details = value.get("details", {})
        if not isinstance(title, str) or not isinstance(message, str) or not isinstance(details, dict):
            raise ValueError("title, message, or details has invalid type")
        encoded_details = json.dumps(details, sort_keys=True)
        if len(encoded_details.encode("utf-8")) > 50000:
            details = {"truncated": True}
        return {
            "event": event,
            "event_title": title[:200],
            "event_message": message[:4000],
            "event_details": details,
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"RESULT IGNORED {path.name}: {exc}", file=sys.stderr)
        return None
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


@contextlib.contextmanager
def lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LockHeld(str(path)) from exc
    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def parse_weekly(value: str) -> tuple[list[int], dt.time]:
    parts = value.strip().split()
    if len(parts) != 2:
        raise ConfigError(f"Invalid weekly schedule {value!r}; use 'mon,thu 05:00'")
    day_tokens = [item.strip().lower() for item in parts[0].split(",") if item.strip()]
    if not day_tokens:
        raise ConfigError(f"Invalid weekly schedule {value!r}; no weekdays found")
    days: list[int] = []
    for token in day_tokens:
        if token not in WEEKDAYS:
            raise ConfigError(f"Invalid weekday {token!r} in weekly schedule {value!r}")
        days.append(WEEKDAYS[token])
    return sorted(set(days)), parse_time(parts[1])


def previous_daily_occurrence(now: dt.datetime, when: dt.time) -> dt.datetime:
    candidate = dt.datetime.combine(now.date(), when, tzinfo=now.tzinfo)
    if candidate > now:
        candidate -= dt.timedelta(days=1)
    return candidate


def previous_weekly_occurrence(now: dt.datetime, days: list[int], when: dt.time) -> dt.datetime:
    candidates: list[dt.datetime] = []
    for day in days:
        days_back = (now.weekday() - day) % 7
        candidate_date = now.date() - dt.timedelta(days=days_back)
        candidate = dt.datetime.combine(candidate_date, when, tzinfo=now.tzinfo)
        if candidate <= now:
            candidates.append(candidate)
        else:
            candidates.append(candidate - dt.timedelta(days=7))
    return max(candidates)


def is_due(job: dict[str, Any], job_state: dict[str, Any], now: dt.datetime) -> tuple[bool, str]:
    if job.get("enabled") is False:
        return False, "disabled"
    schedule = job["schedule"]
    last_attempt = parse_iso(job_state.get("last_attempt_at"))
    if "every" in schedule:
        interval = parse_duration(str(schedule["every"]))
        if last_attempt is None:
            return True, "never-run"
        due_at = last_attempt + interval
        return now >= due_at, f"next-at {iso(due_at)}"
    if "daily_at" in schedule:
        previous = previous_daily_occurrence(now, parse_time(str(schedule["daily_at"])))
        return last_attempt is None or last_attempt < previous, f"slot {iso(previous)}"
    days, when = parse_weekly(str(schedule["weekly"]))
    previous = previous_weekly_occurrence(now, days, when)
    return last_attempt is None or last_attempt < previous, f"slot {iso(previous)}"


def command_for_job(config: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    return config["commands"][job["command_id"]]


def run_job(
    config: dict[str, Any],
    job: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    dry_run: bool,
) -> int:
    job_id = job["id"]
    command = command_for_job(config, job)
    now = now_local()
    job_state = state.setdefault("jobs", {}).setdefault(job_id, {})
    if dry_run:
        print(f"DRY RUN {job_id}: {' '.join(command['argv'])}")
        return 0
    lock_path = state_path / "locks" / f"{job_id}.lock"
    try:
        with lock(lock_path):
            job_state["last_attempt_at"] = iso(now)
            job_state["last_status"] = "running"
            job_state.pop("last_event", None)
            save_state(state_path, state)
            started = now_local()
            result_path = state_path / "results" / f"{job_id}-{uuid.uuid4().hex}.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            command_env = os.environ.copy()
            command_env["SKILL_SCHEDULER_RESULT_FILE"] = str(result_path)
            result = subprocess.run(
                command["argv"],
                env=command_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(command.get("timeout_seconds", 3600)),
                check=False,
            )
            finished = now_local()
            status = "success" if result.returncode == 0 else "failed"
            job_state["last_finished_at"] = iso(finished)
            job_state["last_status"] = status
            job_state["last_returncode"] = result.returncode
            if status == "success":
                job_state["last_success_at"] = iso(finished)
                job_state["failure_count"] = 0
            else:
                job_state["failure_count"] = int(job_state.get("failure_count", 0)) + 1
            record = {
                "job_id": job_id,
                "title": job.get("title", job_id),
                "command_id": job["command_id"],
                "started_at": iso(started),
                "finished_at": iso(finished),
                "status": status,
                "returncode": result.returncode,
                "stdout_for_log": result.stdout,
                "stderr_for_log": result.stderr,
                "stdout_tail": result.stdout[-4000:],
                "stderr_tail": result.stderr[-4000:],
            }
            if status == "success":
                command_result = read_command_result(result_path)
                if command_result:
                    record.update(command_result)
                    job_state["last_event"] = command_result["event"]
            else:
                with contextlib.suppress(FileNotFoundError):
                    result_path.unlink()
            append_command_log(command, record)
            send_notifications(config, job, record)
            record.pop("stdout_for_log", None)
            record.pop("stderr_for_log", None)
            append_log(state_path, record)
            save_state(state_path, state)
            print(f"{status.upper()} {job_id} rc={result.returncode}")
            return result.returncode
    except LockHeld:
        print(f"SKIP {job_id}: lock held")
        return 0
    except subprocess.TimeoutExpired as exc:
        with contextlib.suppress(UnboundLocalError, FileNotFoundError):
            result_path.unlink()
        finished = now_local()
        job_state["last_finished_at"] = iso(finished)
        job_state["last_status"] = "timeout"
        job_state["failure_count"] = int(job_state.get("failure_count", 0)) + 1
        record = {
            "job_id": job_id,
            "title": job.get("title", job_id),
            "command_id": job["command_id"],
            "started_at": iso(now),
            "finished_at": iso(finished),
            "status": "timeout",
            "timeout_seconds": command.get("timeout_seconds", 3600),
            "stdout_for_log": exc.stdout or "" if isinstance(exc.stdout, str) else "",
            "stderr_for_log": exc.stderr or "" if isinstance(exc.stderr, str) else "",
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
        }
        append_command_log(command, record)
        send_notifications(config, job, record)
        record.pop("stdout_for_log", None)
        record.pop("stderr_for_log", None)
        append_log(state_path, record)
        save_state(state_path, state)
        print(f"TIMEOUT {job_id}")
        return 124
    except OSError as exc:
        with contextlib.suppress(UnboundLocalError, FileNotFoundError):
            result_path.unlink()
        finished = now_local()
        job_state["last_finished_at"] = iso(finished)
        job_state["last_status"] = "failed"
        job_state["last_returncode"] = 127
        job_state["failure_count"] = int(job_state.get("failure_count", 0)) + 1
        record = {
            "job_id": job_id,
            "title": job.get("title", job_id),
            "command_id": job["command_id"],
            "started_at": iso(now),
            "finished_at": iso(finished),
            "status": "failed",
            "returncode": 127,
            "stdout_for_log": "",
            "stderr_for_log": str(exc),
            "stderr_tail": str(exc),
        }
        append_command_log(command, record)
        send_notifications(config, job, record)
        record.pop("stdout_for_log", None)
        record.pop("stderr_for_log", None)
        append_log(state_path, record)
        save_state(state_path, state)
        print(f"FAILED {job_id} rc=127")
        return 127


def cmd_doctor(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    path = state_dir(config, config_path)
    path.mkdir(parents=True, exist_ok=True)
    (path / "locks").mkdir(parents=True, exist_ok=True)
    print(f"config: {config_path}")
    print(f"state_dir: {path}")
    print(f"commands: {len(config.get('commands', {}))}")
    print(f"jobs: {len(config.get('jobs', []))}")
    print("ok")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    path = state_dir(config, config_path)
    state = load_state(path)
    now = now_local()
    for job in config.get("jobs", []):
        job_state = state.get("jobs", {}).get(job["id"], {})
        due, reason = is_due(job, job_state, now)
        status = job_state.get("last_status", "never-run")
        enabled = "enabled" if job.get("enabled") is not False else "disabled"
        marker = "due" if due else "not-due"
        print(f"{job['id']}\t{enabled}\t{marker}\t{status}\t{reason}")
    return 0


def cmd_tick(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    path = state_dir(config, config_path)
    state = load_state(path)
    max_jobs = int(config.get("settings", {}).get("max_jobs_per_tick", 9999))
    ran = 0
    rc = 0
    try:
        with lock(path / "locks" / "scheduler.lock"):
            now = now_local()
            for job in config.get("jobs", []):
                if ran >= max_jobs:
                    break
                job_state = state.get("jobs", {}).get(job["id"], {})
                due, reason = is_due(job, job_state, now)
                if not due:
                    continue
                print(f"DUE {job['id']}: {reason}")
                job_rc = run_job(config, job, state, path, args.dry_run)
                ran += 1
                if job_rc != 0 and rc == 0:
                    rc = job_rc
    except LockHeld:
        if not args.quiet:
            print("SKIP scheduler: lock held")
        return 0
    if not args.quiet or ran > 0:
        print(f"tick complete: {ran} job(s) selected")
    return rc


def cmd_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    path = state_dir(config, config_path)
    state = load_state(path)
    for job in config.get("jobs", []):
        if job["id"] == args.job_id:
            return run_job(config, job, state, path, args.dry_run)
    raise ConfigError(f"Unknown job id: {args.job_id}")


def build_parser() -> argparse.ArgumentParser:
    default_config = Path(__file__).with_name("skill_cron.toml")
    parser = argparse.ArgumentParser(description="Run recurring skill and script jobs from TOML config")
    parser.add_argument("--config", default=str(default_config), help="Path to skill_cron.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Validate config and state directory")
    doctor.add_argument("--config", default=argparse.SUPPRESS, help="Path to skill_cron.toml")
    doctor.set_defaults(func=cmd_doctor)

    list_parser = subparsers.add_parser("list", help="List jobs and due status")
    list_parser.add_argument("--config", default=argparse.SUPPRESS, help="Path to skill_cron.toml")
    list_parser.set_defaults(func=cmd_list)

    tick = subparsers.add_parser("tick", help="Run all due jobs")
    tick.add_argument("--config", default=argparse.SUPPRESS, help="Path to skill_cron.toml")
    tick.add_argument("--dry-run", action="store_true", help="Print selected jobs without executing")
    tick.add_argument("--quiet", action="store_true", help="Suppress output when no jobs are selected")
    tick.set_defaults(func=cmd_tick)

    run = subparsers.add_parser("run", help="Force one job by id")
    run.add_argument("job_id")
    run.add_argument("--config", default=argparse.SUPPRESS, help="Path to skill_cron.toml")
    run.add_argument("--dry-run", action="store_true", help="Print command without executing")
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
