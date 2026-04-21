# Renderer Compatibility Rules

Mermaid is rendered by many tools: `mmdc` CLI, GitHub's in-browser renderer, VS Code previews, JetBrains previews, mermaid.live, third-party markdown viewers. They do not all behave identically. A diagram that parses cleanly in `mmdc` can fail in a stricter renderer — usually because the stricter renderer collapses or reformats whitespace in ways `mmdc` doesn't.

The generator agent MUST follow these rules, and the validation step MUST check for them, so the output renders reliably across tools.

---

## Rule 1: No `subgraph` blocks by default

**Why:** At least one real-world renderer merges `subgraph X ["Label"]` with the first statement of the subgraph body — regardless of blank lines, indentation, or semicolons between them. The merged line `subgraph X ["Label"]    <next statement>` is an unrecoverable parse error. `mmdc` does NOT reproduce this bug, so `mmdc` validation will not catch it.

**What to do instead:** Convey grouping through colour classes (`:::className` + `classDef`) on a flat node structure. Visual proximity in the layout will communicate the grouping without risking the renderer bug.

**When subgraphs are unavoidable:** Only if the user explicitly requires them AND confirms the target renderer handles them. In that case, put the subgraph opener and first body item on separate statements with a blank line between them, and expect some renderers to still fail.

---

## Rule 2: Blank line between every top-level statement

Put a blank line between every top-level statement — node definition, edge, classDef, class application. This is unusual formatting but it is the only layout that survives renderers that strip single newlines but preserve blank lines.

```
flowchart LR

A["foo"]

B["bar"]

A --> B

classDef myClass fill:#7ed321
```

Not:

```
flowchart LR
A["foo"]
B["bar"]
A --> B
classDef myClass fill:#7ed321
```

The compact form renders in `mmdc` but can produce `Expecting 'SEMI', 'NEWLINE', 'EOF', got 'SPACE'` errors in stricter renderers.

---

## Rule 3: Flush-left content — no indentation

Do not indent content inside the mermaid code block. Renderers that strip newlines preserve indentation as literal whitespace, which merges with previous content to produce parse errors.

```
flowchart LR

A["foo"]
```

Not:

```
flowchart LR

    A["foo"]
```

---

## Rule 4: Quote every non-alphanumeric label

Every node label, edge label, and stadium/parallelogram content containing anything other than `[A-Za-z0-9_]` must be quoted.

```
tagTrigger(["Tag m*.*.*"])
fad[/"Firebase App Distribution"/]
A -->|"edge with label"| B
```

Not:

```
tagTrigger([Tag m*.*.*])
fad[/Firebase App Distribution/]
A -->|edge with label| B
```

Unquoted special characters (`*`, `.`, `·`, `@`, `/`, `+`) cause parse errors in some renderers.

---

## Rule 5: Inline `:::className` at node definition

Apply class styling inline at node definition time, NOT with separate `class X,Y className` statements at the bottom.

```
A["foo"]:::myClass
B["bar"]:::myClass
classDef myClass fill:#7ed321
```

Not:

```
A["foo"]
B["bar"]
classDef myClass fill:#7ed321
class A,B myClass
```

The `class X,Y className` form is more brittle when newlines are stripped — the comma-separated node list can be misparsed as a node definition.

---

## Rule 6: `classDef` statements at the bottom, one per line, with blank lines between

`classDef` values contain colons (`fill:#hex`, `color:#hex`). If two `classDef` statements are joined (e.g. by newline-stripping), the color-value parser gets confused and parsing dies in place. Semicolons do not help — the parser consumes the semicolon as part of the value.

Place `classDef` statements at the bottom of the diagram, each on its own line, with a blank line between each, and with a blank line between them and the previous statement:

```
A["foo"]:::myClass

B["bar"]:::otherClass

A --> B

classDef myClass fill:#7ed321,color:#000,stroke:#5a9a17

classDef otherClass fill:#f5a623,color:#000,stroke:#d4891c
```

---

## Rule 7: Avoid disallowed tokens

Do not include any of the following in generated mermaid:

- `<br/>` in node labels — renders in `mmdc` and on GitHub, but triggers different parse paths in some renderers. Prefer shorter labels or multiple separate nodes.
- `%%` comments — stripped by some renderers, kept by others. Leave them out; put rationale in the evidence log instead.
- `&` ampersand in labels — use "and".
- Semicolons at statement ends — experimentation showed they cause spurious errors in at least one renderer and do not help in any renderer we tested.
- `direction TB` / `direction LR` inside subgraphs — this specific sequence (`subgraph X [Label]` followed by `direction TB`) triggers the subgraph-merge bug described in Rule 1 most reliably. Even if subgraphs are permitted, omit `direction` and rely on the flowchart's top-level direction.

---

## Rule 8: Subgraph syntax (when unavoidable)

If a subgraph is truly required (see Rule 1 — strongly prefer avoidance):

- Use `subgraph ID ["Label"]` with a space between the ID and the bracket. `subgraph ID["Label"]` (no space) is rejected by some renderers.
- Put a blank line between the subgraph opener and the first body item, AND between each body item, AND between the last body item and `end`.
- Do NOT put `direction TB` inside the subgraph.

---

## Validation — beyond mmdc

`mmdc` passing is necessary but not sufficient. For every generated diagram, the validation step MUST also test a synthetically-collapsed form that simulates the worst common renderer behaviour: stripping single newlines but preserving blank lines. If the collapsed form also passes `mmdc`, confidence is higher that the diagram will render in stricter tools.

### Python transform for the collapsed form

```python
def collapse_for_strict_renderer(mermaid_source: str) -> str:
    """Simulate a renderer that joins consecutive non-blank lines with a space
    and preserves blank lines as newlines. Produces the input that stricter
    renderers effectively see."""
    lines = mermaid_source.split('\n')
    out = []
    current = []
    for line in lines:
        if line.strip() == '':
            if current:
                out.append(' '.join(current))
                current = []
            if out and out[-1] != '':
                out.append('')
        else:
            current.append(line)
    if current:
        out.append(' '.join(current))
    return '\n'.join(out)
```

### Validation loop (used in Step 3)

1. Write original mermaid to `/tmp/mermaid_temp.mmd`; run `mmdc -i ... -o /tmp/test.png`.
2. Write collapsed form to `/tmp/mermaid_collapsed.mmd`; run `mmdc` on it too.
3. Both must succeed. If the original passes but the collapsed form fails, apply the rules above (most commonly: remove subgraphs, add blank lines, flush-left, quote labels) and retry. Max 3 attempts.
4. If after 3 attempts the collapsed form still fails, flag it to the user — the diagram is at risk of rendering badly in some of their tooling.

---

## When in doubt

Prefer fewer features. Mermaid accepts a very lean subset: `flowchart LR/TD`, rectangle and stadium node shapes, simple arrows with quoted edge labels, and `classDef` + `:::className` for colour. That subset renders near-universally. Every additional feature (subgraphs, `<br/>`, `direction`, comments) is a renderer-compatibility risk.
