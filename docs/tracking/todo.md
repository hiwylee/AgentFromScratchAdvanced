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
- `[x]` Choose first Oracle ADW execution backend: SQLcl subprocess behind the
  backend-neutral adapter first; direct driver or MCP/server exposure later if
  needed.
  driver.
- `[x]` Choose initial test framework: Python `unittest`.
- `[x]` Choose initial prompt, policy, memory, and eval artifact formats:
  Markdown and JSON.
- `[x]` Choose schema retrieval strategy for compact Oracle ADW context:
  artifact-first deterministic lexical retrieval over metadata and curated SH
  seeds.
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

- `[x]` Define a structured tool interface.
- `[x]` Add tool registry and validation.
- `[x]` Add retry and max-step limits.
- `[x]` Add observable progress reporting.
- `[x]` Require auditable tool execution context and block high-risk/write tools
  without explicit approval.

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

- `[x]` Add structured trace output for agent steps.
- `[x]` Add eval fixture file format.
- `[x]` Add frozen golden eval set location.
- `[x]` Add eval runner skeleton with mock-model fixtures.
- `[x]` Add prompt, policy, and memory version fields to traces.
- `[x]` Add redaction tests for secrets.
- `[x]` Promote workflow pause/resume monitor events into generic trace schema.

Acceptance criteria:

- A frozen golden eval directory exists.
- Mock evals can run locally without credentials.
- Redaction tests fail if known secret-shaped values appear in traces.
- Trace records include artifact versions.

## Milestone 4: Oracle ADW Read-Only Foundation

- `[x]` Load Oracle ADW config from environment variables.
- `[x]` Verify SQLcl exists without printing secrets.
- `[x]` Verify wallet paths without printing wallet contents.
- `[x]` Add dry-run admin provisioning plan for the working user.
- `[x]` Choose first sample dataset: SH first, SSB later.
- `[x]` Design working-user SQLcl read-only execution boundary with private
  stdin credentials, row/output/time limits, JSON parsing, redacted audit, and
  real execution still closed.
- `[x]` Add backend-neutral read-only SQL execution adapter boundary with fake
  and SQLcl-backed closed implementations.
- `[x]` Add standalone SQLcl subprocess runner safety boundary.
- `[x]` Integrate SQLcl runner into `SqlclReadOnlyAdapter` behind the explicit
  closed-by-default `allow_real_execution` gate.
- `[x]` Harden SQLcl adapter runner-status, timeout, audit metadata, and
  connect-component redaction before live smoke.
- `[x]` Define explicit operator-only live ADW read-only smoke path.
- `[x]` Implement operator-only working-user read-only query execution.
- `[x]` Implement explicit admin provisioning apply with bounded SQLcl capture,
  redacted audit, first-pass rerunnable grants, and structured idempotency
  classification for created/already-compliant/granted-missing/rejected-drift.
- `[x]` Add database least-privilege expectations for the working user.
- `[x]` Add query policy that blocks writes, DDL, `SELECT ... FOR UPDATE`,
  procedural blocks, database links, resource-heavy hints, and unsafe
  multi-statement input.
- `[x]` Add schema introspection queries.
- `[x]` Add tests with fixtures that do not require real credentials.

Acceptance criteria:

- SQLcl version check succeeds.
- Wallet path checks never print wallet contents.
- Working-user smoke query can run read-only.
- Admin credentials are not used by default.
- Query execution logs contain no passwords, wallet passwords, or full
  secret-bearing connection strings.

## Milestone 5: Compact Schema Context

- `[x]` Define schema metadata storage format in
  `docs/design-docs/database-natural-language.md`.
- `[x]` Add curated table and glossary seed format in
  `docs/design-docs/database-natural-language.md`.
- `[x]` Add generated SH schema metadata fixture using
  `agent-runtime.schema-metadata.v1`.
- `[x]` Add curated SH table/glossary seed fixture using
  `agent-runtime.curated-schema-seed.v1`.
- `[x]` Add seed-to-metadata validation for missing table and column
  references.
- `[x]` Add table/column retrieval over names, comments, aliases, and business
  terms.
- `[x]` Add deterministic scoring and ambiguity handling for compact schema
  retrieval.
- `[x]` Add on-demand table expansion for selected table candidates only.
- `[x]` Define sample-value masking policy in
  `docs/design-docs/database-natural-language.md`.
- `[x]` Implement sample-value masking and allowlist enforcement.
- `[x]` Define schema context recording requirements in
  `docs/design-docs/database-natural-language.md`.
- `[x]` Record schema context used for each answer.
- `[x]` Add Milestone 5 test fixtures for SH-first business analysis prompts and
  sensitive-sample masking.

## Milestone 6: Natural Language To SQL

- `[x]` Build compact schema context.
- `[x]` Define query-plan artifact shape before execution.
- `[x]` Generate first candidate query plan for SH revenue by product by month.
- `[x]` Validate generated SQL before execution.
- `[x]` Explain query assumptions for the first query-plan artifact.
- `[x]` Integrate query-plan artifact into `AgentLoop` or a read-only planning
  tool.
- `[x]` Record query-plan artifacts in trace/audit output.
- `[x]` Explain query results after real or fake execution is explicitly
  enabled.
- `[x]` Add NL-to-SQL evaluation fixtures.
- `[x]` Add stable golden eval assertions for query-plan fields.
- `[x]` Add unsupported or ambiguous NL-to-SQL eval coverage.
- `[x]` Add SH revenue by promotion by month query-plan pattern.
- `[x]` Define fake result explanation artifact shape.
- `[x]` Add fake result explanation over `FakeSqlExecutionAdapter` for one
  planned SH query pattern.
- `[x]` Add golden eval assertions for fake result explanation markers.
- `[x]` Add eval coverage for fake explanation refusal paths.

## Milestone 7: Self-Evolution Controls

- `[ ]` Add improvement candidate records.
- `[ ]` Add memory provenance fields.
- `[ ]` Add prompt, policy, and memory rollback path.
- `[ ]` Add drift detection fixtures for repeated questions.
- `[ ]` Require frozen eval pass before accepting behavior-shaping changes.

## Ongoing Harness Work

- `[x]` Execute the 2026-05-16 active parallel wave in
  `docs/tracking/next-work-queue.md`.
- `[x]` Define the next implementation wave for Milestone 5 compact schema
  context fixtures and retrieval.
- `[x]` Execute the compact schema context runtime integration and SQL adapter
  boundary wave.
- `[x]` Execute the Milestone 6 query-plan eval and pattern-expansion wave.
- `[x]` Execute the fake result explanation wave.
- `[x]` Execute the SQLcl subprocess runner boundary and adapter-gated
  integration wave.
- `[x]` Resolve SQLcl runner live stream-limit enforcement review.
- `[x]` Implement and review the operator-only ADW smoke command path.
- `[x]` Implement and review the operator-only ADW read-only query command path.
- `[x]` Extend fake result explanations across supported SH revenue
  product/channel/promotion month query-plan patterns.
- `[ ]` Move completed exec plans to `docs/exec-plans/completed/`.
- `[ ]` Record durable decisions in `docs/tracking/decisions.md`.
- `[ ]` Update `docs/tracking/change-log.md` after meaningful changes.
- `[ ]` Keep `docs/tracking/current-state.md` accurate before ending sessions.
