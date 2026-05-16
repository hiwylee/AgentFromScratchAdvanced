# Todo

## Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Done
- `[?]` Needs decision

## Project Setup

- `[x]` Create private GitHub repository.
- `[x]` Add root `AGENTS.md` guidance.
- `[x]` Add initial README.
- `[x]` Add product spec and architecture notes.
- `[x]` Add Oracle ADW connection design.
- `[x]` Add `.gitignore` and `.env.example`.
- `[x]` Add continuity tracking files.
- `[x]` Add planner/developer review and PM reflection.
- `[ ]` Resolve normal worktree `.git` setup if the read-only mount is removed.

## Implementation Decisions

- `[x]` Choose primary runtime language: uv-managed Python 3.12+ prototype first,
  Rust hardening later if needed.
- `[x]` Choose first CLI command shape: `agent ask <text>`.
- `[x]` Choose mock-model-first versus API-model-first sequencing.
- `[?]` Choose first Oracle ADW execution backend: SQLcl subprocess or direct
  driver.
- `[x]` Choose initial test framework: Python `unittest`.
- `[x]` Choose initial prompt, policy, memory, and eval artifact formats:
  Markdown and JSON.
- `[?]` Choose schema retrieval strategy for compact Oracle ADW context.
- `[x]` Choose workflow template format and human-gate review packet format:
  JSON artifacts validated by JSON Schema.

## Milestone 1: Minimal Agent Loop

- `[x]` Create the first executable package.
- `[x]` Define message, action, observation, and final-answer types.
- `[x]` Define structured user intent types.
- `[x]` Implement a mock model adapter.
- `[x]` Implement the basic agent loop and stop conditions.
- `[x]` Add append-only audit event recording.
- `[x]` Add cancellation and timeout primitives.
- `[x]` Add token, cost, row, and latency budget placeholders.
- `[x]` Add focused tests for intent and redaction behavior.
- `[x]` Add a CLI entry point for structured intent analysis.
- `[x]` Verify the prototype through `uv run --python 3.12`.
- `[x]` Add monitorable run status via `agent status`.

Acceptance criteria:

- `agent ask <text>` runs with no network dependency in mock mode.
- The command outputs structured intent and next action.
- A trace file and append-only audit record are created.
- Secret redaction tests pass.
- Unit tests cover at least one DB-analysis intent and one non-DB intent.

## Milestone 2: Tool Loop

- `[ ]` Define a structured tool interface.
- `[ ]` Add tool registry and validation.
- `[ ]` Add retry and max-step limits.
- `[ ]` Add observable progress reporting.

## Milestone 2A: Workflow Orchestration Skeleton

- `[x]` Define first-pass workflow intent fields.
- `[x]` Define workflow template artifact format.
- `[x]` Define workflow step graph data model.
- `[x]` Add mock connector interface for systems A/B/C/D.
- `[x]` Add deterministic reconciliation rule interface.
- `[x]` Add human-gate pause state and review packet format.
- `[x]` Add workflow status and audit events.
- `[x]` Reflect senior architect/developer review blockers for checkpoint
  closure, connector mutation, resume monitoring, and mock rule enforcement.

Acceptance criteria:

- A natural-language workflow request maps to a structured workflow intent.
- A mock workflow can run A/B lookups in parallel and join for reconciliation.
- The workflow can branch to C enrichment when required data is missing.
- The workflow pauses at a human gate when reconciliation is unresolved.
- No target-system load step can run without an explicit policy checkpoint.
- Rejected checkpoints cannot later be approved.
- Target connectors cannot mutate trusted checkpoint records through aliases.

## Milestone 3: Observability And Eval Skeleton

- `[ ]` Add structured trace output for agent steps.
- `[ ]` Add eval fixture file format.
- `[ ]` Add frozen golden eval set location.
- `[ ]` Add eval runner skeleton with mock-model fixtures.
- `[ ]` Add prompt, policy, and memory version fields to traces.
- `[ ]` Add redaction tests for secrets.
- `[ ]` Promote workflow pause/resume monitor events into generic trace schema.

Acceptance criteria:

- A frozen golden eval directory exists.
- Mock evals can run locally without credentials.
- Redaction tests fail if known secret-shaped values appear in traces.
- Trace records include artifact versions.

## Milestone 4: Oracle ADW Read-Only Foundation

- `[ ]` Load Oracle ADW config from environment variables.
- `[ ]` Verify SQLcl exists without printing secrets.
- `[ ]` Verify wallet paths without printing wallet contents.
- `[ ]` Implement working-user read-only query execution.
- `[ ]` Add database least-privilege expectations for the working user.
- `[ ]` Add query policy that blocks writes, DDL, `SELECT ... FOR UPDATE`,
  procedural blocks, database links, resource-heavy hints, and unsafe
  multi-statement input.
- `[ ]` Add schema introspection queries.
- `[ ]` Add tests with fixtures that do not require real credentials.

Acceptance criteria:

- SQLcl version check succeeds.
- Wallet path checks never print wallet contents.
- Working-user smoke query can run read-only.
- Admin credentials are not used by default.
- Query execution logs contain no passwords, wallet passwords, or full
  secret-bearing connection strings.

## Milestone 5: Compact Schema Context

- `[ ]` Define schema metadata storage format.
- `[ ]` Add curated table and glossary seed format.
- `[ ]` Add table/column retrieval over names, comments, and business terms.
- `[ ]` Add on-demand table expansion.
- `[ ]` Add sample-value masking policy.
- `[ ]` Record schema context used for each answer.

## Milestone 6: Natural Language To SQL

- `[ ]` Build compact schema context.
- `[ ]` Generate candidate query plans.
- `[ ]` Validate generated SQL before execution.
- `[ ]` Explain query assumptions and results.
- `[ ]` Add NL-to-SQL evaluation fixtures.

## Milestone 7: Self-Evolution Controls

- `[ ]` Add improvement candidate records.
- `[ ]` Add memory provenance fields.
- `[ ]` Add prompt, policy, and memory rollback path.
- `[ ]` Add drift detection fixtures for repeated questions.
- `[ ]` Require frozen eval pass before accepting behavior-shaping changes.

## Ongoing Harness Work

- `[ ]` Move completed exec plans to `docs/exec-plans/completed/`.
- `[ ]` Record durable decisions in `docs/tracking/decisions.md`.
- `[ ]` Update `docs/tracking/change-log.md` after meaningful changes.
- `[ ]` Keep `docs/tracking/current-state.md` accurate before ending sessions.
