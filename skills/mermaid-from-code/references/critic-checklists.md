# Critic Verification Checklists

Apply the **General** checklist to every diagram, then apply the **type-specific** checklist that matches the diagram type.

---

## General (All Diagram Types)

- [ ] Every node label matches an actual code entity (not paraphrased or renamed)
- [ ] No phantom nodes — every entity in the diagram exists in the codebase
- [ ] No missing nodes — every relevant entity in scope is represented
- [ ] Direction of arrows is correct (caller to callee, not reversed)
- [ ] No duplicate representations of the same entity under different names
- [ ] Scope matches the user's original request (no creep, no gaps)
- [ ] Diagram is self-consistent (no contradictory paths or relationships)

---

## Flowchart

- [ ] All conditional branches represented (not just the happy path)
- [ ] Error and exception paths included where they exist in code
- [ ] Loop-back paths shown where the code loops or retries
- [ ] Terminal nodes are actually terminal (no missing continuations)
- [ ] Decision node labels match actual conditions in code (not paraphrased)
- [ ] Node ordering reflects actual execution flow

## Sequence

- [ ] Call ordering matches actual execution order in code
- [ ] Return values and responses shown where the code returns them
- [ ] Async vs sync interactions correctly distinguished
- [ ] No missing participants in a call chain (if A calls B calls C, B must appear)
- [ ] Activation bars (if used) correctly reflect when participants are active
- [ ] Alt/opt/loop fragments match actual conditional/loop structures in code

## Class Diagram

- [ ] Inheritance direction correct (child points to parent)
- [ ] Interface vs class vs abstract correctly distinguished
- [ ] Composition vs aggregation vs association correctly represented
- [ ] Access modifiers accurate if shown (public, private, protected)
- [ ] Method signatures match actual code (parameter types, return types)
- [ ] No missing key methods or properties that are part of the public API

## State Diagram

- [ ] All reachable states in the code are represented
- [ ] Transitions have correct triggers and guard conditions
- [ ] Initial state is marked and matches the code's default/constructor state
- [ ] Terminal/final states are marked where the code has them
- [ ] No orphan states that can't be reached from the initial state
- [ ] State names match actual enum values, constants, or status fields in code

## ER Diagram

- [ ] Cardinality is correct (1:1, 1:N, M:N) based on actual schema/model
- [ ] Required vs optional relationships correctly distinguished
- [ ] Entity attributes match actual schema fields, model properties, or column definitions
- [ ] Primary keys and foreign keys correctly represented if shown
- [ ] Junction/join tables shown for M:N relationships where they exist
- [ ] Entity names match actual table names, model names, or class names in code
