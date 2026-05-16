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

## 2026-05-16: Business Workflows Are First-Class Plan Graphs

Decision: Multi-system business requests should be modeled as versioned
workflow templates executed as checkpointed plan graphs, not as ad hoc tool
chains.

Rationale: Requests like patent asset replacement registration require source
lookups, comparison, reconciliation, enrichment, target-system loading, and
human review. Graph-based workflows make parallelism, checkpoints, human gates,
and auditability explicit.

## 2026-05-16: Workflow Templates And Review Packets Start As JSON

Decision: Use JSON workflow templates validated by JSON Schema, and use JSON as
the first human-gate review packet format.

Rationale: The first workflow slice needs versioned, inspectable artifacts that
can describe graph nodes, mock connectors, reconciliation rules, approval
checkpoints, review packet fields, and audit expectations before runtime code
exists.

## 2026-05-16: Persistent Workflow Approval Stays Closed Until Checkpoints Are Tamper-Proof

Decision: Do not expose CLI approval from caller-editable workflow result JSON.
For now, approval can only resume from a trusted in-memory checkpoint in the
same engine instance.

Rationale: Result JSON can be forged. Persistent workflow approval requires a
signed or hashed checkpoint store before target-system loading is safe.

## 2026-05-16: Senior Review Gates Must Be Reflected Before Commit

Decision: Workflow implementation changes should pass a senior architect review
and a senior developer review before commit. Blocking feedback must be fixed or
explicitly scoped out as mock-only before push.

Rationale: The project is intentionally building an agent harness with workflow
execution and database access. Review gates catch safety, checkpoint, audit,
and connector risks before they become architectural defaults.

## 2026-05-16: Empty Workflow Result Sets Close Without Target Loading

Decision: A workflow with no reconciled records should close with
`no_records_to_load`, not request a target-system D checkpoint.

Rationale: Loading zero records is operationally ambiguous and makes monitoring
look like a pending write. A no-op close is clearer and safer.

## 2026-05-16: Oracle ADW Execution Starts Closed

Decision: Milestone 4 implements Oracle ADW configuration checks, SQLcl
verification, wallet metadata checks, read-only SQL validation, and schema
query constants before enabling real database execution.

Rationale: Secrets, wallet handling, SQL safety, audit records, timeouts, row
limits, and SQLcl subprocess behavior need tests before the runtime can safely
connect to ADW.
