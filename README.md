# Claude Skills Marketplace

A collection of reusable [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills.

## Available Skills

| Skill | Description |
|-------|-------------|
| [benpearson-dev-blog](skills/benpearson-dev-blog/) | Generate draft Hugo blog posts for benpearson.dev with the correct page bundle, frontmatter, draft workflow, and writing voice |
| [kobo-epub-pipeline](skills/kobo-epub-pipeline/) | Generate and deliver Kobo deep-dive EPUBs with queueing, critic pass, and Google Drive pull sync |
| [obsidian-braindump-retro](skills/obsidian-braindump-retro/) | Review marked Obsidian daily-note braindumps, connect recurring ideas, and produce structured retros |
| [mermaid-from-code](skills/mermaid-from-code/) | Generate verified mermaid diagrams from codebases using adversarial generator+critic agents |
| [mermaid-to-png](skills/mermaid-to-png/) | Saves a Mermaid diagram as a PNG image |
| [pr-monitor](skills/pr-monitor/) | Autonomously monitor a GitHub PR — fix failing CI, process Copilot review feedback, push, repeat until green and clean |
| [promote-permissions](skills/promote-permissions/) | Find permissions Claude requested during a session and offer to add them permanently |
| [skill-scheduler](skills/skill-scheduler/) | Run one cron-invoked scheduler that dispatches recurring skills and scripts from local config |
| [todoist](skills/todoist/) | Manage Todoist tasks via the CLI |
| [website-monitor](skills/website-monitor/) | Monitor website documents and paginated listings with deterministic diffs and optional semantic relevance evaluation |
| [youtube-podcast-generator](skills/youtube-podcast-generator/) | Generate NotebookLM audio podcasts from curated YouTube channels |

## Installation

To use a skill, copy its folder into your Claude Code skills directory:

**Per-project** (shared via git):
```bash
cp -r skills/<skill-name> /path/to/project/.claude/skills/
```

**Per-user** (available in all projects):
```bash
cp -r skills/<skill-name> ~/.claude/skills/
```

## Contributing

Each skill lives in its own folder under `skills/` and must contain a `SKILL.md` file with YAML frontmatter (`name`, `description`) followed by the skill instructions.
