# Decisions

Record durable decisions here. Keep entries short and include rationale.

## 2026-05-16: Use Harness Documents As The Project Memory

Decision: Keep stable instructions in `AGENTS.md`, evolving plans in
`docs/exec-plans/`, and session continuity in `docs/tracking/`.

Rationale: The project is being built through iterative agent sessions, so the
next session needs a reliable resume point that does not depend on chat history.

## 2026-05-16: Oracle ADW Is The First Database Target

Decision: Specialize the first database workflow for Oracle Autonomous Data
Warehouse.

Rationale: The target credentials and wallet configuration already exist in
local environment variables, and the project goal includes natural-language
processing over database data.

## 2026-05-16: Secrets Stay In Environment Variables

Decision: Passwords, wallet passwords, API keys, wallet files, and
secret-bearing connection strings must not be printed, committed, or stored in
agent state.

Rationale: Oracle ADW workflows require real credentials. The harness must make
secret handling a default constraint before code exists.

## 2026-05-16: Prompt And Policy Are Data

Decision: Keep prompts, policies, memory, eval fixtures, and tool schemas as
versioned data artifacts where practical instead of burying them in compiled
runtime code.

Rationale: Early agent development requires frequent iteration. External data
artifacts keep Rust viable without slowing prompt and policy experiments.

## 2026-05-16: Record Self-Evolution Data Before Enabling Self-Evolution

Decision: Add append-only audit and trace records early, but defer automated
self-improvement until eval gates, provenance, and rollback exist.

Rationale: Self-improvement is useful but risky. The project needs historical
data for later improvement while preventing silent behavior drift.

## 2026-05-16: Add Observability And Eval Before Oracle NL-to-SQL

Decision: Insert an observability and eval skeleton before deeper Oracle ADW
workflows and natural-language-to-SQL.

Rationale: Schema retrieval and prompt changes will regress without structured
traces, frozen evals, and redaction tests.

## 2026-05-16: Database Least Privilege Is The Primary SQL Safety Boundary

Decision: The Oracle ADW working user should be read-only and least-privileged;
application-level SQL validation is a second layer.

Rationale: Regex or parser validation can miss edge cases. DB permissions must
make unsafe operations fail even if generated SQL slips through validation.

## 2026-05-16: MVP Is Intent-First, Not Full NL-To-SQL

Decision: The MVP should prove the agent runtime, structured user intent,
auditable traces, and minimal Oracle ADW read-only connectivity before full
natural-language-to-SQL.

Rationale: NL-to-SQL accuracy depends on schema context, eval gates, and safety
policy. Shipping intent analysis first creates a smaller, testable product
slice.

## 2026-05-16: SQLcl Is Hidden Behind An Oracle Connector Interface

Decision: Use SQLcl first for Oracle ADW execution, but keep subprocess details
behind a connector interface.

Rationale: SQLcl is available locally and matches the immediate environment,
while an interface keeps the option open for a direct Oracle driver later.

## 2026-05-16: Use A uv-Managed Python Prototype Before Rust Hardening

Decision: Implement the first intent-first runtime slice as a Python 3.12+
prototype executed through `uv`, with no external runtime dependencies.

Rationale: Rust is not installed in the current environment, and the earliest
phase needs fast iteration over intent schemas, prompts, traces, and artifact
formats. The design still keeps interfaces and artifacts separate so the core
can be hardened or ported later.
