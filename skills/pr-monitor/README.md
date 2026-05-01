# PR Monitor

Autonomously monitor a GitHub PR — fix failing CI, process Copilot review feedback, push, and repeat until the PR is green and clean. Hands-off PR babysitting.

You point Claude at a PR (`/pr-monitor <url-or-number>`). Each tick it pulls the PR's check status and unresolved Copilot threads, fixes one thing, commits, pushes, and schedules the next tick via `ScheduleWakeup`. It halts and asks for help if a fix doesn't stick after two attempts, if cycle count exceeds a safety cap, or if it can't parse a failure.

**Hard rule:** only Copilot review threads are auto-processed. Comments from human reviewers are always left for the user.

## How It Works

```mermaid
flowchart TD
    Start([Invoke /pr-monitor PR]) --> Resolve[Resolve PR<br/>owner/repo/number/headOid]
    Resolve --> Sanity{Head == base<br/>or base is main/master?}
    Sanity -- yes --> Refuse[Refuse, exit]
    Sanity -- no --> LoadState[Load state file]
    LoadState --> HeadChange{HEAD oid changed<br/>since last cycle?}
    HeadChange -- yes --> Reset[Reset attempt counters]
    HeadChange -- no --> Fetch
    Reset --> Fetch[Fetch in parallel:<br/>gh pr checks +<br/>GraphQL reviewThreads]
    Fetch --> FilterCopilot[Filter threads:<br/>Copilot author only<br/>human comments ignored]
    FilterCopilot --> Limits{Stop limits hit?<br/>attempts >= 2 OR cycle >= 50}
    Limits -- yes --> Halt[Post summary comment<br/>AskUserQuestion, exit]
    Limits -- no --> Decide{What's the state?}

    Decide -- all green +<br/>no unresolved threads --> Done([DONE<br/>delete state, exit])
    Decide -- only pending --> Schedule
    Decide -- failures present --> FixFailure[Pick one failure]
    Decide -- only Copilot threads --> ProcessCopilot[Pick one thread]

    FixFailure --> Kind{Kind?}
    Kind -- lint/style --> FixCode[Parse log, edit file,<br/>verify with project's<br/>local check task]
    Kind -- compile/build --> FixCode
    Kind -- failing test --> FixCode
    Kind -- flaky/infra --> FlakyCheck{Already retried<br/>this check?}
    FlakyCheck -- no --> Rerun[gh run rerun --failed<br/>mark flaky_retried=true]
    FlakyCheck -- yes --> FixCode

    ProcessCopilot --> Judge{Comment valid?}
    Judge -- yes, applicable --> ApplyFix[Apply fix,<br/>verify locally]
    Judge -- disagree --> ReplyDisagree[Reply with reasoning]
    ApplyFix --> ReplyAgree[Reply: applied summary]
    ReplyAgree --> Resolve2[Resolve thread]
    ReplyDisagree --> Resolve2
    Resolve2 --> Commit

    FixCode --> Commit[Commit:<br/>match repo convention]
    Commit --> Push{Push to feature branch}
    Push -- success --> IncCycle
    Push -- non-fast-forward --> Rebase[Fetch + rebase, retry once]
    Rebase -- success --> IncCycle
    Rebase -- still fails --> Halt
    Push -- denied --> Halt

    Rerun --> IncCycle
    IncCycle[Increment counters,<br/>persist state] --> Schedule[ScheduleWakeup<br/>cadence by situation]
    Schedule --> Wake([Sleep until next tick])
    Wake -.next invocation.-> Resolve

    classDef done fill:#1f5d2f,stroke:#2e8b57,color:#fff
    classDef halt fill:#5d1f1f,stroke:#8b2e2e,color:#fff
    classDef sleep fill:#1f3d5d,stroke:#2e5a8b,color:#fff
    class Done done
    class Refuse,Halt halt
    class Wake sleep
```

Green = terminal success. Red = halt-and-ask. Blue = sleeping until the next scheduled tick.

## Installation

```bash
cp -r skills/pr-monitor ~/.claude/skills/
```

Then in Claude Code, invoke as `/pr-monitor <pr-url-or-number>`.

## Prerequisites

- **`gh` CLI** authenticated against the repo (`gh auth status` should show write access).
- **`git push` not blocked.** A common Claude Code setting is `"Bash(git push *)"` in the `deny` list, which is a hard block that per-call approval cannot override. Narrow it before running this skill, e.g.:
  ```json
  "deny": [
    "Bash(git push *--force*)",
    "Bash(git push *-f *)",
    "Bash(git push * origin main*)",
    "Bash(git push * origin master*)"
  ]
  ```
  This still blocks force-pushes and pushes to default branches but allows feature-branch pushes (always reversible).

## State

Per-PR state lives at `~/.claude/skills/pr-monitor/state/<owner>-<repo>-<pr>.json` — tracks attempt counts per check and per Copilot thread, the last-seen HEAD SHA (so a manual push from the user resets counters), and a cycle counter. Deleted when the PR reaches a clean green state.

## Stop conditions

The loop halts and asks the user via `AskUserQuestion` when:
- A fix has been attempted twice for the same check or Copilot thread
- The cycle counter exceeds 50 (safety cap)
- A push fails after one rebase retry
- A failure can't be parsed from CI logs
- A check is failing with no associated workflow run

A `[Claude]` summary comment is posted to the PR before halting, so all review surface lives in one place.
