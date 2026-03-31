# Critic Prompt Mutations

These four mutation strategies seed the critic agent in a different reasoning space from the generator. The orchestrator combines ALL FOUR into a single critic prompt, adjusting emphasis based on diagram type.

Placeholders:
- `{{diagram_type}}` — flowchart, sequence, classDiagram, stateDiagram, erDiagram
- `{{scope}}` — the user's original request/scope description
- `{{mermaid_source}}` — the generated mermaid diagram
- `{{checklist}}` — the relevant items from critic-checklists.md

---

## Strategy 1: Reversed Reasoning

**What it does:** Forces the critic to reason from diagram to code, instead of code to diagram. This inverts the generator's reasoning direction and surfaces different assumptions.

**Especially valuable for:** Sequence diagrams (where ordering matters) and flowcharts (where branching matters).

**Prompt fragment:**

> You are given a mermaid {{diagram_type}} diagram. Your task is to work BACKWARDS from the diagram to the code.
>
> For every relationship/arrow in this diagram, find the exact line of code that implements it. If you cannot find it, flag it as unsupported.
>
> For every node/entity in this diagram, find the code entity it represents. If the label doesn't match the actual code name, flag it.
>
> Then, independently explore the codebase within the stated scope and check: are there components or relationships that SHOULD be in this diagram but are MISSING?

---

## Strategy 2: Adversarial Persona

**What it does:** Shifts the model toward skepticism and thoroughness by raising the stakes of errors. Counteracts the default tendency to approve.

**Especially valuable for:** All diagram types, but particularly architecture and class diagrams where errors propagate to team understanding.

**Prompt fragment:**

> You are a staff engineer reviewing this diagram before it is published as official documentation. Every incorrect relationship in this diagram will mislead engineers during incident response. Every missing component will create a blind spot in the team's mental model.
>
> Your reputation depends on catching errors. Assume the diagram contains mistakes until you have verified otherwise. Do not give the benefit of the doubt — verify every claim against the code.

---

## Strategy 3: Forced Search

**What it does:** Counteracts the model's tendency to quickly pattern-match and approve. Forces deeper investigation even when the diagram looks correct at first glance.

**Especially valuable for:** Complex diagrams with many relationships, where surface-level checking might miss subtle errors.

**Prompt fragment:**

> Your goal is to find at least 3 errors or omissions in this diagram. These could be:
> - Relationships that don't exist in the code
> - Relationships that exist in the code but are missing from the diagram
> - Nodes that are mislabelled or don't match their code counterparts
> - Incorrect direction of dependencies
> - Missing error/exception paths
> - Scope violations (too much or too little included)
>
> If after thorough investigation you find fewer than 3 genuine issues, that is acceptable — but you MUST demonstrate that you searched thoroughly. For each area you checked and found correct, briefly note what you verified and how.

---

## Strategy 4: Type-Specific Structural Audit

**What it does:** Applies formal structural rules specific to the diagram type. Catches category-specific errors that generic review misses.

**Emphasis varies by type — use the matching section below.**

### For Flowcharts:
> Trace every conditional branch in the code within scope. For each `if/else`, `switch/case`, `try/catch`, or ternary, verify that ALL branches appear in the diagram — not just the happy path. Check that loop constructs have corresponding loop-back edges.

### For Sequence Diagrams:
> Trace the actual call sequence by reading the code top-to-bottom. Verify that the message ordering in the diagram matches the execution order. Check that every intermediate participant in a call chain is shown (no skipped hops). Verify async boundaries are correctly marked.

### For Class Diagrams:
> Check every inheritance arrow against actual `extends`/`implements` in code. Verify composition vs association: does the parent CONTAIN the child (composition) or merely REFERENCE it (association)? Check that interfaces are not labelled as classes.

### For State Diagrams:
> Find the state enum, status field, or equivalent in code. Verify every value is represented. Trace every state transition by finding the code that changes state — verify triggers and guards match.

### For ER Diagrams:
> Read the actual schema definitions (migrations, models, or DDL). Verify every entity maps to a real table/model. Check cardinality by examining foreign keys and join tables. Verify that optional vs required matches nullable/NOT NULL constraints.

---

## Combining the Strategies

The orchestrator assembles the critic prompt as follows:

```
[Strategy 2: Adversarial Persona — always first, sets the tone]

[Strategy 1: Reversed Reasoning — the core verification approach]

[Strategy 3: Forced Search — the effort requirement]

[Strategy 4: Type-Specific Audit for {{diagram_type}}]

Here is the diagram to verify:

\`\`\`mermaid
{{mermaid_source}}
\`\`\`

The user's original request/scope: {{scope}}

Apply the following verification checklist:
{{checklist}}

## Your Output

Respond with one of:

### PASS
No issues found. For each checklist item, briefly note what you verified.

### REVISE
List each issue as:
- **Issue**: [description]
- **Evidence**: [file:line that supports your finding]
- **Suggested fix**: [concrete change to the mermaid source]

### REJECT
The diagram is fundamentally wrong (e.g., diagrams the wrong system, entirely wrong scope). Explain why and what the diagram should actually represent.
```
