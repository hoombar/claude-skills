---
name: mermaid-from-code
description: Generate verified mermaid diagrams from codebases using adversarial generator+critic agents. Use when the user wants to create a mermaid diagram that represents code structure, flows, or relationships.
---

# Mermaid From Code

Generate accurate mermaid diagrams from codebases using a generator+critic adversarial pipeline. The critic independently explores the code and verifies the diagram, catching errors the generator missed.

---

## Step 0: Decision Gate

Determine whether this is a **code-based** or **conceptual** diagram request.

**Code-based signals** (use the full adversarial pipeline):
- User references specific files, directories, repos, or modules
- User says "from the code", "show me how X works", "diagram the flow of..."
- The request implies tracing actual code relationships

**Conceptual signals** (skip to Step 6 — generate directly, no adversarial pipeline):
- User describes an abstract concept with no code references
- User says "diagram the concept of...", "visualise the idea of..."
- No codebase exploration is needed

**If ambiguous:** Ask one clarifying question — "Should I generate this from the actual code, or is this a conceptual diagram?"

---

## Step 1: Explorer Agent

Spawn an **Explore** agent to map the relevant code surface area.

**Agent prompt must include:**
- The user's exact scope/request (verbatim)
- The target directory or files to explore
- Instruction to produce a structured summary containing:
  - Key components/classes/functions found
  - Relationships between them (calls, imports, extends, emits)
  - Entry points and exit points
  - File paths and line numbers for everything discovered

**Agent config:**
- `subagent_type: Explore`
- Thoroughness: `very thorough`

Store the explorer's output — it feeds into the generator.

---

## Step 2: Generator Agent

Determine the appropriate mermaid diagram type based on the user's request:
- **flowchart** — for processes, pipelines, decision flows
- **sequence** — for call chains, request/response flows, temporal ordering
- **classDiagram** — for class hierarchies, interfaces, type relationships
- **stateDiagram** — for state machines, lifecycle stages
- **erDiagram** — for data models, schema relationships

Spawn a **general-purpose** agent with the explorer's output and the evidence log format.

**Agent prompt must include:**
- The explorer's full structured summary
- The user's original request/scope
- The chosen diagram type
- The full content of `references/evidence-log-format.md`
- The full content of `references/renderer-compatibility.md` — this is non-negotiable. Generator output that violates the compatibility rules will fail Step 3 validation and force a retry, wasting tokens.
- Instruction to produce:
  1. A mermaid diagram in a code block
  2. An evidence log following the format exactly
  3. A list of deliberate omissions with reasons
- **Mermaid readability rules** (include these in the generator prompt):
  - Keep edge labels to 3-4 words max — mermaid's layout engine does not avoid label collisions, so long labels will overlap and become unreadable
  - Prefer a single edge over bidirectional edges between the same nodes — two edges with labels will almost always collide
  - Use node text and comments for detail; edges should only carry short annotations
  - Avoid `\n` in edge labels where possible — multi-line edge labels worsen collisions
- **Renderer-compatibility rules** (summary — full rationale in `references/renderer-compatibility.md`):
  - Do NOT use `subgraph` blocks. Convey grouping via `:::className` + `classDef` on a flat node structure.
  - Put a blank line between every statement.
  - Flush-left all content (no indentation inside the mermaid block).
  - Quote every non-alphanumeric label: `(["text"])`, `["text"]`, `[/"text"/]`, `|"edge"|`.
  - Apply classes inline at node definition (`A["foo"]:::myClass`), not via separate `class X,Y myClass` statements.
  - Put `classDef` statements at the bottom, one per line, with blank lines between them.
  - No `<br/>`, no `%%` comments, no `&` (use "and"), no semicolons, no `direction TB` inside subgraphs.

**Agent config:**
- `subagent_type: general-purpose`

Store both the mermaid source and the evidence log.

---

## Step 3: Syntax Validation (dual-form)

This is a mechanical check — no agent needed. Both the original AND a collapsed form must pass `mmdc`, because the collapsed form simulates stricter real-world renderers that `mmdc` alone will not catch.

### 3a. Original form

1. Write the mermaid source to `/tmp/mermaid_temp.mmd`.
2. Run: `mmdc -i /tmp/mermaid_temp.mmd -o /tmp/mermaid_test.png -b transparent -s 2`.
3. If `mmdc` fails: read the error, fix the syntax, retry (max 3 attempts).
4. If still failing after 3 attempts: show the error to the user and ask for guidance.

### 3b. Collapsed form (renderer-compatibility check)

Simulate the worst common renderer behaviour: non-blank lines within a paragraph joined by spaces, blank lines preserved. The transform is documented in `references/renderer-compatibility.md` (section "Python transform for the collapsed form"). Use the same transform, or equivalent shell logic.

1. Produce the collapsed form from `/tmp/mermaid_temp.mmd`, write it to `/tmp/mermaid_collapsed.mmd`.
2. Run: `mmdc -i /tmp/mermaid_collapsed.mmd -o /tmp/mermaid_collapsed_test.png -b transparent -s 2`.
3. If the collapsed form fails: the diagram violates a renderer-compatibility rule. Apply the rules in `references/renderer-compatibility.md` (remove subgraphs, add blank lines, flush-left content, quote labels, etc.) and retry both 3a and 3b. Max 3 attempts.
4. If the collapsed form still fails after 3 attempts: flag it to the user — the diagram is at risk of failing in some of their tooling — and surface the specific rule violation.

Clean up the test PNG files after validation.

**Do not skip step 3b.** `mmdc` is more permissive than GitHub's in-browser renderer, which is more permissive than some third-party previews. The collapsed form catches the class of errors that `mmdc` alone will not.

---

## Step 4: Critic Agent

This is the core quality gate. The critic must verify the diagram independently.

### 4a. Read the reference files

Read these files before constructing the critic prompt:
- `references/critic-prompt-mutations.md` — the four mutation strategies
- `references/critic-checklists.md` — the verification checklists

### 4b. Select the relevant checklist

From `critic-checklists.md`, take the **General** checklist AND the checklist matching the diagram type from Step 2.

### 4c. Construct the mutated critic prompt

Follow the assembly pattern in `critic-prompt-mutations.md` to combine all four strategies:

1. **Strategy 2 (Adversarial Persona)** — set the tone
2. **Strategy 1 (Reversed Reasoning)** — the core verification approach
3. **Strategy 3 (Forced Search)** — the effort requirement
4. **Strategy 4 (Type-Specific Audit)** — use the section matching the diagram type

Then append:
- The mermaid source (in a code block)
- The user's original scope description
- The combined checklist items
- The expected output format (PASS / REVISE / REJECT)

### 4d. What the critic receives

- The mermaid diagram source
- The user's original scope/request
- The diagram type
- Access to the full codebase for independent exploration

**CRITICAL: The critic does NOT receive the evidence log.** It must verify independently. Giving it the generator's citations would bias it toward the same conclusions.

### 4e. Spawn the critic

**Agent config:**
- `subagent_type: general-purpose`
- The fully assembled mutated prompt from 4c

### 4f. Interpret the critic's output

- **PASS** — proceed to Step 6 (render)
- **REVISE** — proceed to Step 5 (one revision pass)
- **REJECT** — surface the critic's explanation to the user, ask how to proceed

---

## Step 5: Revision (Conditional)

Only runs if the critic returned **REVISE**.

Spawn a **general-purpose** agent with:
- The original mermaid source
- The original evidence log from Step 2
- The critic's list of concrete corrections (with file:line evidence)
- Instruction to:
  1. Address each correction
  2. Produce a revised mermaid diagram
  3. Produce an updated evidence log

After revision:
- Re-run syntax validation (Step 3)
- Do NOT run the critic again — one revision is the cap

---

## Step 6: Render to PNG

Follow the `mermaid-to-png` skill procedure:

1. Write the final mermaid source to `/tmp/mermaid_temp.mmd`
2. Generate a random filename: short descriptive prefix + random suffix (e.g., `auth-flow-a3f9b2`)
3. Copy the `.mmd` source file:
   ```
   cp /tmp/mermaid_temp.mmd "$HOME/Desktop/mermaid diagrams/<filename>.mmd"
   ```
4. Render to PNG:
   ```
   mmdc -i /tmp/mermaid_temp.mmd -o "$HOME/Desktop/mermaid diagrams/<filename>.png" -b transparent -s 2
   ```
5. Verify both files were created
6. Clean up the temp file

---

## Step 7: Present to User

1. Show the final mermaid source in a fenced code block
2. Show the rendered PNG image
3. Provide a clickable link: `[Open folder](file:///Users/ben.pearson/Desktop/mermaid%20diagrams)`
4. Briefly note the critic's verdict:
   - If PASS: "The critic verified this diagram against the code and found no issues."
   - If REVISE: "The critic found [N] issues which were corrected: [brief summary]."
   - This transparency helps the user trust (or question) the output.
