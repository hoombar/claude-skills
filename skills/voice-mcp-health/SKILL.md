---
name: voice-mcp-health
description: Run a deterministic, read-only health check for the Minibot voice MCP services and their Obsidian, Todoist, Gmail, Drive, Calendar, and OAuth integrations. Use when checking whether the voice assistant is ready or diagnosing expired credentials.
allowed-tools: Bash(node *), Bash(systemctl *), Bash(curl *), Bash(git *)
---

# Voice MCP Health

This skill is implemented as a deterministic command, not an LLM workflow. The command is intended to run from the shared skill scheduler so the host needs only one cron heartbeat.

## What It Checks

- Minibot MCP SSE and HTTP bridge systemd services.
- Public bridge and SSE health endpoints.
- OAuth metadata and expected SSE authentication protection.
- Obsidian read access through the real MCP stdio server.
- Todoist task-list read access through the real MCP tool.
- Personal-profile Gmail, Drive, and Calendar read access through `gws` and the real MCP tools.
- Remote MCP client-credentials authentication when the configured runtime environment contains the credential.

The check is read-only. It never creates tasks, writes notes, sends mail, changes Drive, or changes calendar data.

## Safety

- Do not print MCP runtime environment values.
- Do not log note, task, email, Drive, or calendar contents.
- Summaries contain only check names and sanitized error categories.
- A valid empty result from a read operation is still a successful authentication check.

## Scheduler

The live job is registered as the deterministic `voice_mcp_health` command in the machine-local scheduler configuration. It runs once daily and notifies ntfy only when the check fails or times out.

Run it manually with:

```bash
node /home/ben/dev/minibot-voice-mcp/scripts/health-check.js
```

The command exits zero only when every required check passes.
