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

Decision: Implement the first intent-first runtime slice as a Python 3.13+
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

## 2026-05-16: Admin Creates The Working User Through A Separate Setup Boundary

Decision: `ADMIN_USER` may provision `DB_USER`, but this must be implemented as
an explicit admin setup workflow, separate from the normal read-only connector.
The read-only connector must never fall back to admin credentials. Dry-run setup
plan generation requires admin setup configuration to be present, but still does
not embed or print admin passwords.

Rationale: Admin credentials are powerful enough to change the database. Setup
needs stricter validation, audit, redaction, idempotency, and approval controls
than natural-language read-only analysis.

## 2026-05-16: Use SH Before SSB For First DB Analysis Dataset

Decision: Prefer Oracle `SH` sample data first, and keep `SSB` as the later
benchmark/stress dataset.

Rationale: `SH` has richer business semantics for natural-language analysis:
sales, products, customers, channels, and time. `SSB` is useful later for
larger star-schema benchmark tests.

## 2026-05-16: Start Compact Schema Context With Artifact-First Lexical Retrieval

Decision: Milestone 5 starts with deterministic lexical retrieval over a
generated Oracle ADW schema metadata JSON artifact plus a curated SH table and
glossary seed JSON artifact. Embedding retrieval is deferred until the lexical
path has fixtures, trace records, and golden eval pressure showing it is not
enough.

Rationale: The first compact schema context needs to be inspectable,
dependency-light, and easy to test. SH business semantics are small enough for
curated seeds to cover early sales, product, customer, channel, and time
questions, while SSB remains reserved for later benchmark and stress coverage.

## 2026-05-16: Sample Values Are Deny-By-Default In Schema Context

Decision: Compact schema context excludes raw sample values by default. Only
explicitly allowlisted low-cardinality business category values may appear, and
sensitive or high-cardinality columns must be omitted or represented with
masked placeholders and masking reasons.

Rationale: Sample values can leak personal, secret, or operational data. Early
NL-to-SQL accuracy should rely first on schema names, comments, curated
glossary entries, relationships, and aggregate profiles rather than raw rows.

## 2026-05-17: SQLcl Runs Behind Adapter-Gated Execution Only

Decision: SQLcl subprocess execution is implemented as a runner behind
`SqlclReadOnlyAdapter`, and the adapter calls it only when
`allow_real_execution=True`. Agent-facing planning, schema context, and fake
result explanation paths must not enable this flag.

Rationale: The project needs a tested local SQLcl boundary, but live ADW access
is still a privileged operator action. Keeping SQLcl behind the adapter
preserves backend neutrality, lets fake and real execution share response
contracts, and prevents MCP/server or subprocess details from becoming the
agent-facing tool contract.

## 2026-05-17: Runner Metadata Is Audit-Only

Decision: SQLcl runner details such as bounded byte counts, environment key
names, timeout, command shape, and return status may be recorded as redacted
audit metadata. Backend metadata exposed to callers should keep only generic
execution state and `runner_status`.

Rationale: Operators need enough process context to review failures and prove
limits were enforced, but agent-facing responses should not depend on
subprocess internals or receive stdout/stderr details. Stdin, raw SQL text,
DSNs, passwords, wallet secrets, and unredacted SQLcl output remain excluded.

## 2026-05-17: SQLcl Stream Limits Are Enforced During Capture

Decision: The default SQLcl runner reads stdout and stderr through bounded live
pipe readers and terminates the subprocess as soon as either stream exceeds its
configured byte cap. Injected runner callables remain compatible with the
existing `subprocess.run`-style test boundary.

Rationale: Post-processing captured output does not protect the runtime from a
large SQLcl result or noisy SQLcl error because `capture_output=True` buffers
the full stream before limits are checked. Live bounded reads keep memory usage
tied to configured caps before operator-only ADW smoke work begins.

## 2026-05-17: Live ADW Smoke Is Operator-Only And Fixed-SQL

Decision: The first live ADW execution path is
`bin/agent operator adw-smoke --confirm-live-adw-smoke`. It runs only
`select 1 as smoke_check from dual`, requires working-user credentials,
absolute `SQLCL_PATH`, wallet-directory `DB_WALLET_PATH`, wallet TNS alias
`DB_DSN`, and successful SQLcl verification, then constructs
`SqlclReadOnlyAdapter(..., allow_real_execution=True)`.

Rationale: A fixed, manually confirmed smoke command proves the live SQLcl
boundary without turning natural-language requests or agent tools into live
database execution paths. Requiring wallet/TNS alias form and working-user
credentials keeps the first live check narrow, reviewable, and separated from
admin setup or general query execution.

## 2026-05-17: SQLcl Version Checks Use Minimal Environment

Decision: The default SQLcl version check passes only a minimal allowlisted
environment (`PATH`, `HOME`, `LANG`, and `LC_ALL`) to the subprocess.

Rationale: SQLcl version checks do not need database credentials. Avoiding full
process environment inheritance reduces the chance that credential variables
are exposed to subprocesses before live ADW smoke execution begins.

## 2026-05-17: SQLcl Execution Uses Minimal Runtime Environment

Decision: Live SQLcl execution receives only the plan environment plus a
minimal allowlisted runtime environment (`PATH`, `JAVA_HOME`, `HOME`, and locale
keys) from `SqlclReadOnlyAdapter`.

Rationale: SQLcl needs Java and basic runtime paths to execute, but it should
not inherit database passwords, DSNs, admin credentials, or unrelated process
environment values. Passing only runtime keys lets SQLcl find Java while
keeping credential flow inside the redacted stdin plan.

## 2026-05-18: Fake Result Explanations Stay Fixture-Scoped

Decision: Runtime result explanations may be emitted for supported SH query
plans only through explicit deterministic fake fixtures. Each explanation must
keep `source: fake/deterministic`, `real_database_execution: false`, backend
`fake`, fixture id, scenario id, adapter version, and no SQLcl or Oracle ADW row
fields.

Rationale: The project needs explainable end-to-end NL-to-SQL behavior before
live execution is generally available. Fixture-scoped explanations exercise the
trace, audit, and eval contracts without presenting demo rows as real database
facts or opening a live execution path.

## 2026-05-18: Self-Evolution Starts As A Gate, Not An Apply Path

Decision: Milestone 7 records and validates self-evolution candidates, memory
provenance, rollback plans, drift fixtures, and gate reports, but does not
apply prompt, policy, memory, eval, schema, or code changes automatically.

Rationale: Behavior-shaping changes can silently degrade safety and accuracy.
The first useful boundary is a reviewable acceptance gate requiring approved
review, passing frozen evals, passing drift checks, rollback coverage for every
affected artifact, and one behavior-shaping artifact type per candidate.

## 2026-05-18: Artifact Versions Come From A Manifest

Decision: Trace artifact versions should load from
`artifacts/artifact-manifest.v1.json`, including the closed-by-default runtime
memory artifact.

Rationale: Rollback and drift review need a single version source for prompt,
policy, memory, and eval artifacts. Hard-coded trace versions are easy to
forget when behavior-shaping artifacts change.

## 2026-05-17: General Live ADW Queries Stay Operator-Only

Decision: General working-user live read-only queries are exposed only through
`bin/agent operator adw-query --confirm-live-adw-query`, with SQL supplied from
one of `--sql-file`, `--sql-stdin`, or convenience `--sql`. The command
validates read-only SQL before SQLcl verification, reuses the smoke preflight
gates, and constructs `SqlclReadOnlyAdapter(..., allow_real_execution=True)`
only after those gates pass.

Rationale: Operators need a manual read-only query path after smoke, but normal
agent, schema context, query planning, fake explanation, and tool paths should
remain non-live. Keeping arbitrary SQL out of audit and omitting result rows
from durable audit records reduces leakage risk while still giving operators a
bounded redacted stdout result for manual verification.

## 2026-05-17: AIAGENT Was Provisioned With Broad Read Privileges By Operator Request

Decision: At explicit operator request, the ADW working user `AIAGENT` was
created with `CREATE SESSION`, `DWROLE`, and `SELECT ANY TABLE`.

Rationale: This is broader than the earlier least-privilege SH object-grant
plan, but it was requested to unblock live database smoke and read-only query
verification. Future production hardening should revisit this grant shape and
prefer object-level grants where feasible.

## 2026-05-17: Admin SQLcl Uses Bounded Subprocess Capture

Decision: Operator-only admin provisioning uses the bounded SQLcl subprocess
runner boundary instead of `subprocess.run(capture_output=True)`.

Rationale: Admin setup can produce noisy SQLcl output just like read-only query
execution. Enforcing stdout/stderr byte caps during live capture keeps memory
usage tied to configured limits before redaction and audit serialization.

## 2026-05-17: Prototype Broad Grant Profile Creates SH Private Synonyms

Decision: The temporary `prototype-any-table-read` profile also creates
private synonyms in the working schema for the SH core tables.

Rationale: The current parser-less read-only SQL policy blocks schema-qualified
dotted references, while the generated and operator-reviewed SH SQL uses
unqualified business table names. Private synonyms let `AIAGENT` read SH data
through names such as `sales` without loosening the SQL policy.

## 2026-05-17: Admin Provisioning Classifies Before Applying DDL

Decision: Operator-only ADW admin provisioning runs a metadata precheck before
DDL, skips apply for `already_compliant`, rejects `rejected_drift` before
unlocking or granting anything, and postchecks `created` or
`granted_missing_privileges` repairs.

Rationale: Re-running setup must not normalize a manually broadened or
compromised working account. The operator needs a structured result that says
whether the command created, repaired, skipped, or refused the account without
relying on raw SQLcl output.

## 2026-05-20: Live LLM Planning Is Explicit And Locally Validated

Decision: Keep `agent ask` on the deterministic mock model by default, and add
OpenAI Responses API planning only when `--model-provider openai` or
`AGENT_MODEL_PROVIDER=openai` is set. The live model may choose only from
locally allowed action kinds, and invalid or unsafe kinds fall back to the
deterministic baseline.

Rationale: A live LLM is useful for model-backed planning, but it must not be
the authority that opens Oracle ADW execution, workflow writes, or destructive
database operations. Local policy validation preserves the current safety
boundary while enabling real provider smoke tests and future prompt iteration.

## 2026-05-20: OCI Uses A Separate OpenAI-Compatible Provider

Decision: Add `oci` as its own model provider instead of overloading OpenAI
environment variables. OCI uses `OCI_BASE_URL`, `OCI_API_KEY` or
`OCI_API_KEY_2`, and `OCI_MODEL`, while reusing the same Responses API adapter
and local action-kind validation. The provider first uses Oracle's documented
OpenAI-compatible `/openai/v1` base path and then falls back to the API-key
`/20231130/actions/v1/responses` path after OCI 404 responses.

Rationale: OCI Generative AI is OpenAI-compatible at the HTTP boundary, but its
endpoint, key rotation, and model identifiers are operationally separate from
OpenAI. A provider split avoids mixing credentials and keeps fallback models
such as `xai.grok-4-1-fast-non-reasoning` explicit.
