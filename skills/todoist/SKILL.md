---
name: todoist
description: Manage Todoist tasks via the CLI. Use when the user wants to add a task, list tasks, check today's tasks, complete tasks, delete tasks, update tasks, or manage projects/labels in Todoist. Triggers on phrases like "add a task", "todoist", "what's due today", "my tasks".
allowed-tools: Bash(td *)
---

# Todoist CLI Skill

You help the user manage their Todoist tasks using the `td` CLI.

## Command Reference

| Action | Command |
|--------|---------|
| **Add task** (structured) | `td task add "content" --due "date" --priority p1-p4 --project "name" --labels "a,b"` |
| **Quick add** (natural language) | `td add "Buy milk tomorrow p1 #Shopping"` |
| **Today's tasks** | `td today` |
| **Upcoming tasks** | `td upcoming` |
| **Inbox** | `td inbox` |
| **List tasks** | `td task list` |
| **View task** | `td task view <ref>` |
| **Complete task** | `td task complete <ref>` |
| **Update task** | `td task update <ref> --content "new" --due "date"` |
| **Delete task** | `td task delete <ref>` |
| **List projects** | `td project list` |
| **List labels** | `td label list` |

Use `--json` or `--ndjson` flags when you need to parse output programmatically.

## Safety Rules

### Adding tasks — NO confirmation needed (usually)
When the user asks to add a task, proceed immediately. Use `td task add` with structured flags (preferred for agents over `td add`).

**Exception — shared tasks:** If the task sounds like something the user's wife might need to see (e.g., household errands, family events, shared shopping, appointments involving both of them, kid-related tasks), ask: "Want me to add this to the Shared project so your wife can see it?" before running the command. If they say no (or the task is clearly personal/work-related), use the default project.

### Destructive actions — ALWAYS confirm with the user BEFORE executing
The following actions are destructive and require explicit user confirmation:
- `td task delete` — deleting a task
- `td project delete` — deleting a project
- `td label delete` — deleting a label
- `td task uncomplete` — reopening a completed task

Before running any of these, tell the user exactly what will be affected and ask for confirmation.

### Editing/updating actions — verify current state FIRST
Before running any update command, ALWAYS:
1. Fetch and display the current state of the item (e.g., `td task view <ref> --json`)
2. Show the user what will change (old value → new value)
3. Then execute the update

This applies to:
- `td task update`
- `td task move`
- `td task reschedule`
- `td project update`
- `td label update`

### Completing tasks — show task first
Before completing a task, run `td task view <ref>` to confirm you have the right task, then complete it.

## Defaults & Conventions

- When the user says "add a task" without other context, they mean Todoist.
- Prefer `td task add` over `td add` for structured, unambiguous task creation.
- Use `--dry-run` when available if you're unsure about the effect of a command.
- For date inputs, use natural language (e.g., "tomorrow", "next Monday", "March 25") — the CLI supports it.
- Default priority is p4 (lowest) if not specified by the user.

### Default due date: today
If the user does not specify a due date, ALWAYS set `--due "today"`. The user schedules tasks for today and reschedules as needed. A task without a date will vanish into the void.

### Default project: Inbox (or Shared)
Do not specify `--project` unless the user asks for one or the task is a candidate for Shared. Inbox is the default landing spot.

### Projects
| Project | When to use |
|---------|-------------|
| **Inbox** | Default. No `--project` flag needed. |
| **Shared** | Tasks the user's wife should see — household errands, family events, shared shopping, joint appointments. ASK before using this. |
| **Home** | Only when the user explicitly wants something on their dashboard. Never use as a default. |
