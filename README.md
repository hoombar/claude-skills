# Claude Skills Marketplace

A collection of reusable [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills.

## Available Skills

| Skill | Description |
|-------|-------------|
| [kobo-epub-pipeline](skills/kobo-epub-pipeline/) | Generate and deliver Kobo deep-dive EPUBs with queueing, critic pass, and Google Drive pull sync |
| [mermaid-from-code](skills/mermaid-from-code/) | Generate verified mermaid diagrams from codebases using adversarial generator+critic agents |
| [mermaid-to-png](skills/mermaid-to-png/) | Saves a Mermaid diagram as a PNG image |
| [promote-permissions](skills/promote-permissions/) | Find permissions Claude requested during a session and offer to add them permanently |
| [todoist](skills/todoist/) | Manage Todoist tasks via the CLI |
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
