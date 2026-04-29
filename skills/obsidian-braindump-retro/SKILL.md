---
name: obsidian-braindump-retro
description: Review marked braindump blocks from Obsidian daily notes, connect recurring ideas across days, and distill them into actions, idea threads, and retrospective notes. Use when the user wants to process captured thoughts from daily notes, run a weekly retro, or turn fragmented notes into organized follow-up.
---

# Obsidian Braindump Retro

Process low-friction thought captures from Obsidian daily notes into structured outputs without making capture itself heavy or formal.

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
2. A single AI-managed folder for runtime state and retro notes
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
      threads/
      state/
```

Recommended runtime files:

- `AI/Braindump Retro/runtime/logs/YYYY-MM.jsonl`
- `AI/Braindump Retro/runtime/retros/braindump-retro-YYYY-MM-DD.md`
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

The review window must be driven by a checkpoint file, not by the ledger partition.

1. Read `runtime/state/latest-checkpoint.json` if it exists
2. If it exists, use its timestamp as the exclusive lower bound
3. If it does not exist, use the user-defined adoption date as the initial lower bound
4. Set the upper bound to the current retro run time
5. Load every daily note and every monthly log partition touched by that time range

Monthly partitioning is only a storage optimization. It must never limit the retrospective window.

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
4. Load the active thread index
5. Load only the thread notes that appear relevant
6. Classify each capture:
   - action
   - idea
   - project-related
   - workflow improvement
   - research topic
   - fleeting thought
   - question
7. Decide whether to:
   - link to an existing thread
   - create a new thread
   - promote to an action
   - merge into an existing note
   - discard
8. Create a retro summary note
9. Update the monthly log, thread notes, and checkpoint state
10. Propose any edits to user-owned notes before making them

## Output Shape

A good retro output should include:

- `New threads`
- `Existing threads strengthened`
- `Actions for today or this week`
- `Note candidates`
- `Discarded or low-signal items`
- `Open questions`

For each promoted or linked item, include:

- source note
- raw capture id
- target thread or note
- short reasoning

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

## Retrieval Rules

To keep context small:

1. Load daily note captures only for the active review window
2. Load only the monthly ledger files that overlap the window
3. Load the active thread index
4. Load only likely-matching thread notes
5. Load older retro summaries only when needed for a specific thread

The main memory surfaces should be:

- the active thread index
- the current retro window
- concise thread notes
- recent retro summaries

## What Success Looks Like

After running this skill, the user should be able to answer:

- What new ideas appeared?
- What keeps resurfacing?
- What needs action now?
- Which captures should become proper notes or projects?
- What can be safely discarded?
