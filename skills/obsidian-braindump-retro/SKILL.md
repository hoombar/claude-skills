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
2. A single AI-managed folder for runtime state, action checklists, and retro receipts
3. A clear adoption date after which the marker pattern is considered active

If the vault separates human-owned notes from AI-managed notes, do not write into the human-owned area without explicit permission.

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
      logs/
      retros/
      actions/
      threads/
      state/
```

Recommended runtime files:

- `AI/Braindump Retro/runtime/logs/YYYY-MM.jsonl`
- `AI/Braindump Retro/runtime/retros/braindump-retro-YYYY-MM-DD.md`
- `AI/Braindump Retro/runtime/actions/braindump-retro-actions-YYYY-MM-DD.md`
- `AI/Braindump Retro/runtime/threads/<thread-slug>.md`
- `AI/Braindump Retro/runtime/state/latest-checkpoint.json`
- `AI/Braindump Retro/runtime/state/active-threads.md`

The runtime area is AI-managed state. Keep it separate from the daily notes themselves.

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

## Review Window

Never use the current month as the review boundary.

The checkpoint and ledger are mandatory runtime state. Do not run this workflow by simply grepping all daily notes and routing whatever is found.

The review window must be driven by a checkpoint file, not by the ledger partition.

1. Read `runtime/state/latest-checkpoint.json` if it exists
2. If it exists, use its timestamp as the exclusive lower bound
3. If it does not exist, use the user-defined adoption date as the initial lower bound
4. Set the upper bound to the current retro run time
5. Load every daily note and every monthly log partition touched by that time range

Monthly partitioning is only a storage optimization. It must never limit the retrospective window.

Before routing anything, build a set of already-ledgered `capture_id` values from every loaded monthly log. If a capture id already exists, skip it unless the user explicitly asks for a reprocess.

## Extraction Rules

For each note in scope:

1. Confirm the note contains both markers
2. Extract all content between the markers
3. Split into captures using top-level bullets first
4. If there are no bullets, split by paragraph blocks
5. Preserve the raw wording as much as possible

Assign each capture a stable id using the note date plus ordinal position.

## Retro Workflow

1. Determine the review window from the checkpoint
2. Load marked daily-note captures in that window
3. Load only the monthly log partitions touched by that window
4. Load current and recent action checklists under `runtime/actions/` to detect semantic duplicates before adding new actions
5. Load the active thread index
6. Load only the thread notes that appear relevant
7. Assign stable ids using note date plus ordinal position
8. Drop any capture whose stable id is already present in the loaded ledger partitions, unless the user explicitly requested reprocessing
9. Classify each remaining capture:
   - action
   - idea
   - project-related
   - workflow improvement
   - research topic
   - fleeting thought
   - question
10. Decide whether to:
   - file into an existing AI-managed note
   - append to an existing history, plan, ideas, or next-steps note
   - create a short action in the run action checklist
   - add a clarifying question in the run action checklist when the correct destination or interpretation is ambiguous
   - link to an existing thread only when no better durable note exists yet
   - create a new thread only for repeated or genuinely emerging themes with no existing destination
   - discard
11. Apply safe AI-managed filings immediately. Examples:
   - workout logs go into an existing training history note
   - workout workflow questions, such as whether a separate training log should exist or whether weekly retro should update it, should become clarifying questions unless the user has already established the rule
   - project ideas go into that project's existing ideas, plan, or next-steps note
   - one-off follow-ups go into the run action checklist
12. Create a slim retro receipt
13. Create or update a high-signal action checklist
14. Update the monthly log, thread notes, and checkpoint state
15. Propose any edits to user-owned notes before making them

## Duplicate Handling

Duplicates are possible in two ways:

- exact duplicate: the same stable `capture_id` already appears in the ledger
- semantic duplicate: the same task or idea already appears in an existing action checklist or durable destination note

Rules:

- Never route an exact duplicate.
- For semantic duplicates, do not add a second action. Link to the existing action or note in the retro receipt if useful.
- If a repeated thought adds new detail, strengthen the existing durable note rather than creating another action.
- If unsure whether something is duplicate or new, add it to clarifying questions instead of silently routing it.

## Output Shape

The retro note is a routing receipt, not the product. Keep it extremely slim.

Include only:

- review window
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

- one checkbox per action
- link the relevant destination note when useful
- avoid explanation unless needed to make the action executable
- include a `Clarifying Questions` section when captures were ambiguous or when routing required an assumption

## Thread Notes

Keep thread notes short and current. Suggested sections:

- `What this thread is`
- `Why it matters`
- `Signals so far`
- `Related notes and projects`
- `Open questions`
- `Next experiment`

Do not copy every raw capture into the thread note. Summarize the pattern and keep the full history in the ledger.

## Ledger Guidance

Use one JSON object per line in the monthly log. Example fields:

- `capture_id`
- `source_note`
- `source_date`
- `ordinal`
- `raw_text`
- `normalized_hash`
- `raw_status`
- `thread_slug`
- `retro_note`
- `routed_to`
- `updated_at`

The ledger is state, not prompt context. Do not load the full history by default.

Use `question` when a capture is understandable but the correct routing decision is unclear, such as whether to create a new durable note or update an existing workflow. Record the item in the current action checklist's clarifying questions section so it is not silently lost.

## Retrieval Rules

To keep context small:

1. Load daily note captures only for the active review window
2. Load only the monthly ledger files that overlap the window
3. Build a set of already-ledgered `capture_id` values and skip exact duplicates
4. Load current and recent action checklists to catch semantic duplicates before creating new actions
5. Load the active thread index
6. Load only likely-matching thread notes
7. Load older retro summaries only when needed for a specific thread

The main memory surfaces should be:

- the active thread index
- the current retro window
- routed project/history notes
- action checklists
- concise thread notes
- slim retro receipts

## What Success Looks Like

After running this skill, the user should be able to scan the action checklist and answer:

- What needs action now?
- Where did the captured material get filed?
- Which items can be ignored because they were already handled?
