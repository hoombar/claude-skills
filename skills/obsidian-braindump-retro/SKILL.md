---
name: obsidian-braindump-retro
description: Review marked braindump blocks from Obsidian daily notes, route captures into existing durable notes, and produce a short next-action checklist plus a slim retro receipt. Use when the user wants to process captured thoughts from daily notes, run a weekly retro, or turn fragmented notes into organized follow-up.
---

# Obsidian Braindump Retro

Process low-friction thought captures from Obsidian daily notes into routed notes and a small action checklist without making capture itself heavy or formal.

## When To Use This Skill

Use this skill when the user wants to:

- review daily note braindumps
- run a weekly or periodic retrospective
- connect related thoughts captured across multiple days
- separate fleeting thoughts from durable ideas
- promote captures into actions, project notes, or idea threads

## Vault Prerequisites

This skill works best when the vault has:

1. A daily note template with a dedicated marker block for braindumps
2. A single AI-managed folder for action checklists, retro receipts, and thread notes
3. A clear adoption date after which the marker pattern is considered active

The inline cursor requires editing the marked braindump block in each source daily note. Confirm that the user permits this narrow workflow edit; do not make other changes in a human-owned area without explicit permission.

## Daily Note Template

The skill only extracts captures from notes that contain both of these exact markers:

```md
## 🤖 Braindump
<!-- BRAIN_DUMP:START -->

- one fragment per bullet when possible

<!-- BRAIN_DUMP:END -->
```

Rules:

- Only parse content between `<!-- BRAIN_DUMP:START -->` and `<!-- BRAIN_DUMP:END -->`
- If a note does not contain both markers, skip it entirely
- Do not fall back to heading-based parsing for old notes
- Prefer one top-level bullet per thought, but tolerate messy paragraphs

## Suggested Vault Layout

Adapt the paths to the user's vault. A simple default is:

```text
Templates/
  Daily Note.md

Daily notes/
  YYYY-MM-DD.md

AI/
  Braindump Retro/
    runtime/
      retros/
      actions/
      threads/
      state/
```

Recommended runtime files:

- `AI/Braindump Retro/runtime/retros/braindump-retro-YYYY-MM-DD.md`
- `AI/Braindump Retro/runtime/actions/braindump-retro-actions-YYYY-MM-DD.md`
- `AI/Braindump Retro/runtime/threads/<thread-slug>.md`
- `AI/Braindump Retro/runtime/state/active-threads.md`

The runtime area is AI-managed state. Keep it separate from the daily notes themselves.

## Action Checklist Triage State

Every action checklist created by this workflow must include this exact control near the top of the note:

```md
- [ ] **Triage complete**
```

This checkbox records whether the user has manually reviewed the checklist as a batch. It is independent of the completion state of the individual actions below it.

Before routing a run, inspect every Markdown file under `runtime/actions/`, including files that do not follow the preferred filename pattern, and count the checklists containing an unchecked `Triage complete` control. The active checklist filename must match the date of the retro run.

- Exactly one unchecked checklist dated today: update it in place for an additional same-day run.
- Exactly one unchecked checklist from an earlier date: roll it forward. Copy its actions, headings, clarifying questions, links, notes, and individual checkbox states into a new `braindump-retro-actions-YYYY-MM-DD.md` for today's run; check `Triage complete` in the previous file and add a `Rolled forward to [[new-checklist]]` note.
- No unchecked checklist: create `braindump-retro-actions-YYYY-MM-DD.md` with an unchecked `Triage complete` control.
- More than one unchecked checklist: do not choose or combine them automatically. Ask the user which checklist should remain active.
- A legacy checklist with no `Triage complete` control is historical and closed for rollover purposes, but still load it when needed for semantic duplicate detection.

Normally only the user marks `Triage complete`. The workflow may check it automatically only when rolling that checklist into a new run-dated file. Never infer triage state from individual action checkboxes or reopen a checked checklist.

When rolling forward or updating a same-day checklist:

- preserve all existing action checkbox states, headings, questions, links, and notes
- semantically deduplicate new actions against existing checklist content and durable destination notes
- append actions under an existing matching heading when practical, creating a concise heading only when needed
- use the current run date for the new checklist's filename, title, `captured`, and `updated` values
- record only the current file's retro runs and link a rolled checklist back to its predecessor with `Rolled forward from [[previous-checklist]]`
- keep a separate retro receipt for the new run and point it at the current run-dated checklist

## Core Model

Treat these as two different things:

1. Raw captures
2. Idea threads

A raw capture is a single fragment from a daily note. An idea thread is a higher-level concept that may accumulate signals across several days or weeks.

### Raw capture lifecycle

- `new`: extracted but not yet reviewed
- `linked`: connected to a thread or related note
- `actioned`: converted into a concrete task or next step
- `question`: reviewed but blocked on user clarification
- `discarded`: reviewed and intentionally ignored

### Idea thread lifecycle

- `emerging`: early cluster of related captures
- `incubating`: interesting and worth watching
- `active`: currently being explored or built
- `parked`: intentionally paused
- `done`: resolved or no longer active

Repeated thoughts across different days are a signal, not noise. Do not deduplicate them away by default.

## Inline Processing Cursor

Processed state lives inside each braindump block so it travels with the Markdown note through Obsidian Sync. Do not maintain a separate ledger or checkpoint.

The cursor has this exact shape:

```md
<!-- BRAIN_DUMP_RETRO:PROCESSED at="YYYY-MM-DDTHH:MM:SSZ" retro="AI/Braindump Retro/runtime/retros/braindump-retro-YYYY-MM-DD.md" -->
```

For every daily note dated on or after the user-defined adoption date:

1. Find the content between `BRAIN_DUMP:START` and `BRAIN_DUMP:END`
2. Find the last valid `BRAIN_DUMP_RETRO:PROCESSED` cursor inside that block, if present
3. Treat only substantive content after that cursor and before `BRAIN_DUMP:END` as unprocessed
4. If no cursor exists, treat the whole marked block as unprocessed
5. Ignore blank space and cursor comments when deciding whether work exists

After every capture from a note has been routed successfully, remove any older processed cursor from that block and insert one updated cursor after the processed content, immediately before `BRAIN_DUMP:END`. If routing or required output writes fail, do not advance that note's cursor. This allows new captures to be appended after the cursor later without reprocessing older material.

## Extraction Rules

For each note in scope:

1. Confirm the note contains both markers
2. Extract all content between the markers
3. Split into captures using top-level bullets first
4. If there are no bullets, split by paragraph blocks
5. Preserve the raw wording as much as possible

## Retro Workflow

1. Scan daily notes in all configured active and archive locations from the adoption date onward
2. Extract only content after each note's last processed cursor
3. Load all action checklists under `runtime/actions/`, identify and roll forward any older active checklist using the exact `Triage complete` control, and inspect current and recent checklists for semantic duplicates
4. Load the active thread index
5. Load only the thread notes that appear relevant
6. Classify each remaining capture:
   - action
   - idea
   - project-related
   - workflow improvement
   - research topic
   - fleeting thought
   - question
7. Decide whether to:
   - file into an existing AI-managed note
   - append to an existing history, plan, ideas, or next-steps note
   - create a short action in the run action checklist
   - add a clarifying question in the run action checklist when the correct destination or interpretation is ambiguous
   - link to an existing thread only when no better durable note exists yet
   - create a new thread only for repeated or genuinely emerging themes with no existing destination
   - discard
8. Apply safe AI-managed filings immediately. Examples:
   - workout logs go into an existing training history note
   - workout workflow questions, such as whether a separate training log should exist or whether weekly retro should update it, should become clarifying questions unless the user has already established the rule
   - project ideas go into that project's existing ideas, plan, or next-steps note
   - one-off follow-ups go into the run action checklist
9. Create a slim retro receipt
10. Update the current run-dated unchecked checklist with new unique actions and clarifying questions
11. Update thread notes and the active thread index
12. Advance the inline cursor in each successfully processed daily note
13. Propose any other edits to user-owned notes before making them

## Duplicate Handling

Duplicates are possible in two ways:

- already processed source: content appears before a daily note's latest inline cursor
- semantic duplicate: the same task or idea already appears in an existing action checklist or durable destination note

Rules:

- Never route content before the latest inline cursor.
- For semantic duplicates, do not add a second action. Link to the existing action or note in the retro receipt if useful.
- If a repeated thought adds new detail, strengthen the existing durable note rather than creating another action.
- If unsure whether something is duplicate or new, add it to clarifying questions instead of silently routing it.

## Output Shape

The retro note is a routing receipt, not the product. Keep it extremely slim.

Include only:

- retro run time
- daily notes with non-empty marked braindumps
- routing summary: destination notes and action checklist
- skipped duplicate summary when applicable
- clarifying questions when any capture was ambiguous
- explicit statement when user-owned notes were not modified

Do not include long reasoning, long raw captures, thread essays, or broad synthesis in the retro receipt. Put durable detail where it belongs:

- project-related ideas go into existing project ideas, plans, or next-steps notes
- logs go into existing history notes
- concrete follow-ups go into `runtime/actions/braindump-retro-actions-YYYY-MM-DD.md`
- thread notes are only for items that need incubation and have no existing destination

The action checklist is the main user-facing output. Keep it short, high signal, and directly triageable:

- include the exact `- [ ] **Triage complete**` control near the top of every new checklist
- one checkbox per action
- link the relevant destination note when useful
- avoid explanation unless needed to make the action executable
- include a `Clarifying Questions` section when captures were ambiguous or when routing required an assumption
- record every retro run routed into the checklist; use a short `Retro runs` list when a checklist contains more than one run

## Thread Notes

Keep thread notes short and current. Suggested sections:

- `What this thread is`
- `Why it matters`
- `Signals so far`
- `Related notes and projects`
- `Open questions`
- `Next experiment`

Do not copy every raw capture into the thread note. Summarize the pattern; the source daily note and retro receipt provide the processing history.

Use `question` when a capture is understandable but the correct routing decision is unclear, such as whether to create a new durable note or update an existing workflow. Record the item in the current action checklist's clarifying questions section so it is not silently lost.

## Retrieval Rules

To keep context small:

1. Scan configured daily-note locations from the adoption date onward
2. Load only substantive content after each note's latest processed cursor
3. Load current and recent action checklists to catch semantic duplicates before creating new actions
4. Load the active thread index
5. Load only likely-matching thread notes
6. Load older retro summaries only when needed for a specific thread

The main memory surfaces should be:

- the active thread index
- the current unprocessed daily-note captures
- routed project/history notes
- action checklists
- concise thread notes
- slim retro receipts

## What Success Looks Like

After running this skill, the user should be able to scan the action checklist and answer:

- What needs action now?
- Where did the captured material get filed?
- Which items can be ignored because they were already handled?
