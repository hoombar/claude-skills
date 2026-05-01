---
name: pr-monitor
description: Autonomously monitor a GitHub PR — fix failing CI, process Copilot review feedback, push, repeat until green and clean. Use when the user wants hands-off PR babysitting on a specific PR.
argument-hint: <pr-url-or-number>
disable-model-invocation: true
---

# pr-monitor — autonomous PR babysitter

You are running one cycle ("tick") of an autonomous PR-shepherding loop. The user wants you to: fix failing CI, process unresolved **Copilot** review comments (only Copilot — never humans), push, and re-check, until the PR is green and has no unresolved Copilot threads. The user's only involvement is reviewing the final result.

Each invocation does **one cycle** then either declares the PR done, halts and asks for help, or schedules itself via `ScheduleWakeup` to run again. Be idempotent: state lives in a per-PR JSON file; nothing in your context is required to survive between ticks.

## Hard rules

- **Copilot only.** Process review comments authored by `Copilot` or `copilot-pull-request-reviewer` only. **Never** auto-fix, reply to, or resolve threads from human reviewers — they remain for the user. Drop human-authored threads from the unresolved list before any decision logic.
- **Never push to `main` or `master`.** Refuse before invoking `git push` if the head branch equals the base branch or is `main`/`master`.
- **Never `--force` push.** Not `--force`, not `-f`, not `--force-with-lease`.
- **Never skip hooks.** No `--no-verify`, `--no-gpg-sign`.
- **Never silently retry the same fix.** Every counter that hits its limit halts the loop and asks the user.
- **Commit messages follow the repo's existing convention.** Inspect `git log --oneline -10` to detect the format (e.g. `TICKET-123 Description`, conventional commits, etc.) and match it. If the head branch contains a ticket prefix like `TICKET-123-…`, include the ticket.

## Setup (first run only)

The user's `~/.claude/settings.json` may have `"Bash(git push *)"` in the `deny` list. A `deny` rule is a hard block that per-call approval cannot override. If you find pushing is denied, **stop and tell the user** to narrow the deny rule to:

```json
"deny": [
  "Bash(git push *--force*)",
  "Bash(git push *-f *)",
  "Bash(git push * origin main*)",
  "Bash(git push * origin master*)"
]
```

Don't edit settings.json yourself. Wait for the user to make the change and re-invoke.

## Cycle procedure

### 1. Resolve the PR

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
gh pr view "<input>" --json number,headRefName,baseRefName,headRefOid,title
```

Save: `OWNER`, `REPO`, `PR_NUMBER`, `HEAD_BRANCH`, `BASE_BRANCH`, `HEAD_OID`, `TITLE`.

### 2. Sanity check

If `HEAD_BRANCH == BASE_BRANCH`, or `HEAD_BRANCH ∈ {main, master}`, refuse and exit with a message to the user.

### 3. Load state

State file: `~/.claude/skills/pr-monitor/state/<OWNER>-<REPO>-<PR_NUMBER>.json`

Schema:
```json
{
  "attempts_by_check": { "<checkName>": <count> },
  "flaky_retried": { "<checkName>": true },
  "attempts_by_thread": { "<threadId>": <count> },
  "last_head_oid": "<sha>",
  "cycle_count": <int>
}
```

If the file doesn't exist, treat as `{ attempts_by_check: {}, flaky_retried: {}, attempts_by_thread: {}, last_head_oid: null, cycle_count: 0 }`.

### 4. Detect HEAD change

If `state.last_head_oid` is set and differs from current `HEAD_OID`: reset `attempts_by_check`, `attempts_by_thread`, and `flaky_retried` to `{}` (someone made progress; previous failures may no longer apply).

Increment `cycle_count`. Update `last_head_oid = HEAD_OID`.

### 5. Stop-limit guard

Halt immediately (do not fetch more, do not try to fix) if any of:
- `cycle_count >= 50`
- `max(attempts_by_check.values()) >= 2`
- `max(attempts_by_thread.values()) >= 2`

When halting: post a `[Claude]` PR-level comment summarising what was tried (which check name / thread, how many attempts), use `AskUserQuestion` to ask the user how to proceed, then exit.

### 6. Fetch live state (parallel)

```bash
# All checks
gh pr checks <PR_NUMBER> --json name,state,bucket,link

# Unresolved Copilot threads
gh api graphql -f query='
query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner, name:$repo){
    pullRequest(number:$number){
      reviewThreads(first:100){
        nodes{
          id isResolved
          comments(first:5){
            nodes{
              databaseId
              author{login}
              body path line
            }
          }
        }
      }
    }
  }
}' -F owner=<OWNER> -F repo=<REPO> -F number=<PR_NUMBER>
```

Categorise checks by `bucket`: `pass` / `fail` / `pending` / `skipping` / `cancel`.

Filter threads: keep only those where `isResolved == false` **and** the first comment's `author.login ∈ {Copilot, copilot-pull-request-reviewer}`. Drop everything else.

### 7. Decide action

| State | Action |
|---|---|
| All checks pass + zero Copilot threads | **DONE** — post a brief `[Claude]` summary comment, delete the state file, exit. |
| Some pending, no failures, no threads | `ScheduleWakeup` (see cadence) and exit. |
| Failures present | Pick **one** failure (highest-priority kind: build > test > lint/style > flaky). Fix it this cycle. |
| Only unresolved Copilot threads | Pick **one** thread. Process this cycle. |

One issue per cycle keeps commits small and the diff easy to review.

### 8a. Fix a failed check

```bash
# Get the run ID from the check link, then:
gh run view <run-id> --log-failed
```

By kind:
- **Lint / style / static analysis** — parse `file:line: rule` from log, edit, verify by running the project's appropriate module/package-scoped lint task locally.
- **Compile / build** — parse the error, edit, verify with the project's appropriate build task scoped to the affected module/package.
- **Failing unit test** — read the failure, judge whether the test or production code is wrong (production-bug or test-needs-update), fix, verify by running just the affected test scope locally.
- **Flaky / infra** — only if `state.flaky_retried[<checkName>]` is not `true`:
  - `gh run rerun <run-id> --failed`
  - Set `state.flaky_retried[<checkName>] = true`
  - Skip increment of `attempts_by_check` (this isn't a fix attempt)
  - Schedule wakeup (long — 600s) and exit
  - **If `flaky_retried` is already `true`, treat as real failure** — do not retry, attempt to fix as a real failure.

After a non-flaky fix: increment `state.attempts_by_check[<checkName>]` by 1, then proceed to commit.

> Discover the project's verification commands by reading its README, `CLAUDE.md`, `package.json`/`Makefile`/`build.gradle`/etc. — don't assume Gradle, npm, or any specific tool. The point is to verify the fix locally before pushing, using whatever the project uses.

### 8b. Process a Copilot thread

For the picked thread:
1. Read the comment body, file `path`, `line`. Open the file at that line.
2. Decide: is the comment valid?
   - **Valid + applicable** → apply the fix. Run project-appropriate local checks for the touched module/package.
   - **Disagree** (intentional, false positive, etc.) → don't change code; prepare a reply explaining why.
3. Reply on the thread:
   ```bash
   # Use the databaseId of the FIRST comment in the thread (root comment)
   gh api -X POST repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/comments/<COMMENT_ID>/replies \
     -f body='[Claude] <one-line summary of fix or reasoning>'
   ```
4. Resolve the thread:
   ```bash
   gh api graphql -F threadId='<THREAD_NODE_ID>' -f query='
   mutation($threadId:ID!){
     resolveReviewThread(input:{threadId:$threadId}){ reviewThread{ id isResolved } }
   }'
   ```
5. Increment `state.attempts_by_thread[<threadId>]` by 1.

If you applied a code change, proceed to commit. If you only replied (disagreement, no code change), persist state and either schedule a wakeup or process the next thread next cycle — but don't commit.

### 9. Commit + push

```bash
git add <changed-files>     # specific files only, never -A or .
git commit -m "<message in repo's existing convention>"
git push origin <HEAD_BRANCH>
```

If push fails with non-fast-forward:
```bash
git fetch origin
git rebase origin/<HEAD_BRANCH>
git push origin <HEAD_BRANCH>
```
If still failing, halt, post a comment, ask the user.

### 10. Persist state and schedule next tick

Write the updated state file. Then `ScheduleWakeup` with cadence:

| Situation | Sleep |
|---|---|
| CI just kicked off, big jobs running | 270s |
| CI mostly green, one check left | 60–90s |
| Fix just pushed, waiting for checks to start | 120s |
| Nothing pending, only Copilot threads remain | (process immediately, don't sleep) |
| Long-running flaky retry just issued | 600s |

The `ScheduleWakeup` `prompt` field should re-invoke this skill with the same PR argument so the next tick starts fresh.

## Stop conditions (recap)

Halt and `AskUserQuestion` when:
- `cycle_count >= 50` (safety cap)
- Any `attempts_by_check[name] >= 2`
- Any `attempts_by_thread[id] >= 2`
- Push fails after one rebase retry
- Failure can't be parsed from logs (no actionable info)
- A check is in `failure` state with no associated workflow run

Always post a `[Claude]` PR-level summary comment when halting, so the user has a single review surface (the PR conversation).

## Things to NOT do

- Don't reply to or resolve threads authored by humans.
- Don't fix the same check more than twice in the same SHA without asking.
- Don't push to `main`/`master` or with `--force`.
- Don't bundle multiple unrelated fixes in one commit.
- Don't `git add -A` or `git add .` — stage specific files.
- Don't edit `~/.claude/settings.json`.
- Don't continue the loop silently when something unexpected happens — halt and ask.
