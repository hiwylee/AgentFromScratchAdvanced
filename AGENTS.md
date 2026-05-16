# AgentFromScrach

This repository is for building an agent runtime from scratch while using
`../codex` as a reference implementation, not as code to copy blindly.

## Project Intent

- Build the smallest useful agent first, then add planning, tools, memory,
  sandboxing, and complex task orchestration in deliberate stages.
- Treat harness engineering as part of the product: instructions, docs, tests,
  constraints, and workflow checks should make the agent easier to steer.
- Prefer explicit design notes over implicit decisions. When a decision changes,
  update the relevant doc before or with the code.

## Harness Map

- `docs/product-specs/`: user-facing goals, scenarios, and non-goals.
- `docs/design-docs/`: architecture notes and technical tradeoffs.
- `docs/exec-plans/active/`: current implementation plans.
- `docs/exec-plans/completed/`: finished plans with outcomes.
- `docs/references/`: distilled notes from `../codex` or external material.
- `docs/generated/`: generated artifacts only; do not hand-edit unless noted.

## Working Rules

- Keep early implementations boring and observable.
- Do not introduce a framework until the plain version exposes real pressure.
- Every milestone should have a runnable command and a focused verification path.
- Treat `.env`, Oracle wallet files, passwords, API keys, and connection strings
  as secrets. Never print them, commit them, or include them in logs.
- For Oracle ADW work, use environment variables for credentials and prefer the
  working DB user over admin credentials unless the task explicitly requires
  admin access.
- When referencing `../codex`, document the concept being borrowed and why it
  fits this project before implementing it.
- Put stable project instructions here. Put detailed, evolving work plans in
  `docs/exec-plans/active/`.

## Current Starting Point

Read these first:

1. `docs/product-specs/agent-runtime.md`
2. `docs/design-docs/harness-engineering.md`
3. `docs/design-docs/architecture.md`
4. `docs/design-docs/database-natural-language.md`
5. `docs/design-docs/oracle-adw-connection.md`
6. `docs/exec-plans/active/0001-project-bootstrap.md`
