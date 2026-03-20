---
name: promote-permissions
description: Find permissions that Claude requested during this session but aren't allowlisted, and offer to add them permanently.
disable-model-invocation: true
---

# Promote Permissions

Find permissions that Claude requested during this session that aren't covered by any settings file, and interactively add them to permanent settings.

## Goal

During a session, Claude requests many tool permissions. Some get approved transiently (one-off), some via "don't ask again" (saved to `settings.local.json`), and some are already allowlisted. The goal of this skill is to identify permissions the user keeps having to approve and offer to allowlist them permanently.

## Steps

### Phase 1: Identify Permission Gaps

1. Read the three settings files:
   - **Local:** `.claude/settings.local.json` in the current project root
   - **Project:** `.claude/settings.json` in the current project root
   - **User:** `~/.claude/settings.json`
2. Extract the `permissions.allow` arrays from each file (treat missing files/keys as empty arrays).
3. Review the current conversation for any tool calls that required user approval — these are permissions Claude needed but didn't have. Look for:
   - Tool calls the user was prompted to approve
   - `Edit`, `Write`, `Read`, `Bash`, `WebFetch`, `WebSearch`, MCP tool calls, etc.
   - Pay attention to the tool name AND the arguments (paths, domains, commands) to construct the correct permission rule
4. Also check `settings.local.json` for any permissions that aren't already in Project or User settings — these were saved via "don't ask again" in prior sessions but haven't been promoted.
5. Build the **candidate list**: all permissions from steps 3 and 4 that aren't already covered by Project or User settings. A permission is "covered" if an identical rule or a broader wildcard rule exists.

If the candidate list is empty, tell the user everything is already covered and stop.

### Phase 2: Classify by Risk

Classify each candidate by risk level. **Never group permissions of different risk levels together in the same question.**

#### Read-only / Safe (low risk)
These observe state but don't change anything:
- `Read(...)` — reading files
- `Bash(ls *)`, `Bash(cat *)`, `Bash(which *)`, `Bash(file *)`, `Bash(wc *)` — inspecting
- `Bash(grep *)`, `Bash(rg *)`, `Bash(find *)` — searching
- `Bash(git log*)`, `Bash(git status*)`, `Bash(git diff*)`, `Bash(git branch*)`, `Bash(git show*)`, `Bash(git blame*)` — read-only git
- `WebSearch`, `WebFetch(...)` — web reads
- MCP tools that only read data (e.g., `get_*`, `list_*`, `Get-*`, `List-*`)

#### Mutating / Creative (medium risk)
These create or modify state but are generally reversible:
- `Edit(...)`, `Write(...)` — modifying/creating files
- `Bash(mkdir *)` — creating directories
- `Bash(git add*)`, `Bash(git commit*)`, `Bash(git stash*)`, `Bash(git checkout*)` — local git mutations
- `Bash(python3:*)`, `Bash(javap:*)` — running interpreters/tools
- MCP tools that create or modify (e.g., `create_*`, `update_*`, `push_*`)

#### Destructive / Remote (high risk)
These are hard to reverse or affect systems beyond the local machine:
- `Bash(rm *)`, `Bash(rmdir *)` — deleting files/dirs
- `Bash(git push*)`, `Bash(git reset*)` — remote git / history rewriting
- MCP tools that delete, merge, or post (e.g., `delete_*`, `merge_*`, `add_*_comment`)

### Phase 3: Interactive Review

Present candidates one risk level at a time, starting with **read-only**, then **mutating**, then **destructive**. Within each level, group by category (Bash, File access, MCP, Web). **Each permission gets its own question** — never bundle unrelated permissions into a single question. Use batches of up to 4 questions per `AskUserQuestion` call.

For each permission, the options are:

- **Project settings** — add to `.claude/settings.json` (shared with team via git)
- **User settings** — add to `~/.claude/settings.json` (personal, all projects)
- **Skip** — don't add anywhere, leave as-is

When constructing permission rules to suggest, use appropriate wildcards:
- For file paths: suggest patterns like `Edit(.claude/*)` rather than exact paths when a group of related files is involved
- For Bash commands: use the command name with wildcard, e.g. `Bash(npm *)`
- For MCP tools: use the exact tool name
- For WebFetch: use domain patterns, e.g. `WebFetch(domain:github.com)`

### Phase 4: Apply Changes

1. Re-read the current content of each settings file that needs changes (to avoid stale data).
2. Add chosen permissions to the appropriate `permissions.allow` arrays.
3. Write back only the files that changed.
4. Summarize: how many added to project settings, how many to user settings, how many skipped.

## Notes

- This skill only adds permissions — it never removes existing ones from any settings file.
- Preserve existing JSON formatting and key ordering when writing files.
- If a settings file doesn't have a `permissions.allow` array yet, create the structure.
- When suggesting permission rules, prefer slightly broader patterns over exact paths when it's clear the user will need the same type of access again (e.g., `Edit(.claude/*)` instead of `Edit(.claude/settings.local.json)`).
- If the user selects "Other", ask them to clarify what they want.
