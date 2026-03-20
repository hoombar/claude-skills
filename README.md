# Claude Skills Marketplace

A collection of reusable [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills.

## Available Skills

| Skill | Description |
|-------|-------------|
| [mermaid-to-png](skills/mermaid-to-png/) | Saves a Mermaid diagram as a PNG image |
| [promote-permissions](skills/promote-permissions/) | Find permissions Claude requested during a session and offer to add them permanently |

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
