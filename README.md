# Agent Skills

A harness-neutral collection of reusable [Agent Skills](https://agentskills.io).
The canonical source for every skill is `skills/<skill-name>/`; harness-specific
directories are installation targets, not separate copies maintained in this
repository.

## Compatibility

Each skill uses the open `SKILL.md` format shared by OpenCode, Codex, and Claude
Code. Individual skills can still depend on a particular CLI or harness feature;
check their frontmatter and README before using them elsewhere.

| Harness | User skill directory | Project skill directory |
|---------|----------------------|-------------------------|
| OpenCode | `~/.agents/skills/` or `~/.config/opencode/skills/` | `.agents/skills/` or `.opencode/skills/` |
| Codex | `~/.agents/skills/` | `.agents/skills/` |
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |

`~/.agents/skills/` is the preferred user-level target because both OpenCode and
Codex discover it. Claude Code currently requires its own discovery path.

## Available Skills

| Skill | Description |
|-------|-------------|
| [benpearson-dev-blog](skills/benpearson-dev-blog/) | Generate draft Hugo blog posts for benpearson.dev with the correct page bundle, frontmatter, draft workflow, and writing voice |
| [kobo-epub-pipeline](skills/kobo-epub-pipeline/) | Generate and deliver Kobo deep-dive EPUBs with queueing, critic pass, and Google Drive pull sync |
| [obsidian-braindump-retro](skills/obsidian-braindump-retro/) | Review marked Obsidian daily-note braindumps, connect recurring ideas, and produce structured retros |
| [mermaid-from-code](skills/mermaid-from-code/) | Generate verified mermaid diagrams from codebases using adversarial generator+critic agents |
| [mermaid-to-png](skills/mermaid-to-png/) | Save a Mermaid diagram as a PNG image |
| [pr-monitor](skills/pr-monitor/) | Autonomously monitor a GitHub PR, fix failing CI, process review feedback, and repeat until green and clean |
| [promote-permissions](skills/promote-permissions/) | Find permissions requested during an agent session and offer to add them permanently |
| [skill-scheduler](skills/skill-scheduler/) | Run one cron-invoked scheduler that dispatches recurring skills and scripts from local config |
| [todoist](skills/todoist/) | Manage Todoist tasks via the CLI |
| [website-monitor](skills/website-monitor/) | Monitor website documents and paginated listings with deterministic diffs and optional semantic relevance evaluation |
| [youtube-podcast-generator](skills/youtube-podcast-generator/) | Generate NotebookLM audio podcasts from curated YouTube channels |

## Installation

Symlink all skills into the shared OpenCode and Codex location:

```bash
./scripts/install-skills agents
```

Install only selected skills:

```bash
./scripts/install-skills agents todoist website-monitor
```

Use `opencode` or `claude` instead of `agents` to target their native user
directories. Run the command again after adding a skill; existing links that
already point into this repository are refreshed safely.

For a project-local installation, symlink the required skill into the harness's
project directory. For example:

```bash
mkdir -p /path/to/project/.agents/skills
ln -s "$PWD/skills/website-monitor" /path/to/project/.agents/skills/website-monitor
```

## Skills And Plugins

Agent Skills are the portable workflow layer. Plugins are harness-specific
distribution and extension packages:

- Claude Code plugins use `.claude-plugin/plugin.json`.
- Codex plugins use `.codex-plugin/plugin.json`.
- OpenCode plugins are JavaScript or TypeScript modules and use a different API.

Do not duplicate every skill into those formats. Add a harness adapter only when
a skill needs plugin-only capabilities such as hooks, custom tools, agents, or
MCP configuration. Keep the underlying skill in `skills/` so other harnesses can
still use it.

## Contributing

Each skill lives in `skills/<skill-name>/` and must contain a `SKILL.md` with
Agent Skills-compatible YAML frontmatter. At minimum:

```markdown
---
name: skill-name
description: What the skill does and when an agent should use it.
---
```

Keep the folder name and frontmatter `name` identical. Prefer standard fields
(`name`, `description`, `license`, `compatibility`, `metadata`, and
`allowed-tools`) over harness-specific extensions.
