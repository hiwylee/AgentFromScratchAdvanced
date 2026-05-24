# Next Work Queue

This file is the durable handoff queue for the next implementation wave. Read
it after `docs/tracking/current-state.md` and before starting new work.

## Execution Rules

- Use uv-managed Python 3.13+ for all local verification.
- Keep `.env`, wallet files, passwords, and rendered credential strings out of
  logs, tests, docs, commits, and worker messages.
- Run parallel workers only on disjoint write scopes.
- Keep real ADW execution, real admin provisioning apply, and real
  target-system writes closed until the listed safety gates pass.
- Before commit, get a senior-review pass and run focused plus full tests.

## Completed Parallel Wave: 2026-05-16

### Worker A: Tool Loop Integration

Status: completed.

Primary scope:

- `agent_runtime/loop.py`
- `agent_runtime/tools.py`
- `tests/test_runtime_controls.py`
- `tests/test_tools.py`

Goal:

- Wire `ToolRegistry` and `ToolRunner` into `AgentLoop` without enabling any
  write or high-risk tool by default.
- Preserve current mock-model behavior for existing CLI paths.
- Add a low-risk read-only mock tool path that records observation events.
- Ensure retry/max-step behavior remains explicit and test-covered.

Acceptance:

- Existing runtime and tool tests pass.
- Full `python -m unittest discover -s tests` passes.
- Audit and monitor events redact tool arguments and outputs.

### Worker B: Workflow Trace And Resume Safety Design

Status: completed.

Primary scope:

- `agent_runtime/workflow.py`
- `agent_runtime/trace.py`
- `tests/test_workflow_engine.py`
- `tests/test_eval_runner.py`
- `docs/design-docs/workflow-orchestration.md`

Goal:

- Promote workflow pause/resume/checkpoint events into the generic trace
  schema.
- Design and, where narrow enough, implement the first trusted checkpoint
  identity/hash boundary for resume.
- Keep `approve-workflow` unable to load target system D from caller-supplied
  arbitrary JSON alone.

Acceptance:

- Human decisions and load attempts have durable trace/audit records.
- Resume validation rejects mismatched, missing, or fabricated checkpoint data.
- Real target writes remain closed unless the checkpoint boundary is trusted.

### Worker C: Oracle ADW SQLcl Execution Design

Status: completed.

Primary scope:

- `agent_runtime/oracle_adw.py`
- `tests/test_oracle_adw.py`
- `docs/design-docs/oracle-adw-connection.md`

Goal:

- Design the working-user read-only SQLcl execution boundary before enabling
  real execution.
- Specify credential passing without command-line password exposure.
- Specify timeout, row limit, output parsing, redacted audit, and error
  handling behavior.
- Keep admin provisioning apply as a separate design until idempotency and
  compensation behavior are testable.

Acceptance:

- Focused Oracle ADW tests prove no passwords appear in argv, result dicts,
  errors, audit records, or docs.
- Read-only query execution remains closed unless all safety gates are covered.
- Admin apply remains closed and documented as separate from read-only
  execution.

### Worker D: Compact Schema Context Plan

Status: completed.

Primary scope:

- `docs/design-docs/database-natural-language.md`
- `docs/design-docs/oracle-adw-connection.md`
- `docs/tracking/decisions.md`
- `docs/tracking/todo.md`

Goal:

- Choose the first compact schema retrieval strategy for Oracle ADW.
- Define schema metadata JSON shape, curated table/glossary seed format,
  sample-value masking policy, and context recording requirements.
- Prefer SH-first business analysis semantics and leave SSB for stress tests.

Acceptance:

- A concrete Milestone 5 plan exists with file formats and testable acceptance
  criteria.
- Any open decision is explicit and narrow.

## Completed Milestone 5 Fixture/Retrieval Wave

Milestone 5 should start with data artifacts and validation before any
NL-to-SQL generation:

1. Add SH schema metadata and curated seed JSON fixtures under
   `docs/generated/schema-context/`.
2. Add seed-to-metadata validation for missing table and column references.
3. Add deterministic lexical table/column retrieval with ambiguity handling.
4. Add sample-value masking and allowlist enforcement.
5. Record compact schema context evidence in trace/audit output.

Items 1-4 are complete. Item 5 remains open as the next integration step.

## Completed Runtime Context And Adapter Wave

Integrate compact schema context into the runtime without enabling SQL
generation:

1. Wire `mock_schema_context` or a replacement low-risk read-only tool to load
   the generated SH artifacts and return a redacted compact context result.
2. Record schema context evidence in monitor, audit, and trace records,
   including selected/rejected tables, scores, glossary matches, masking
   decisions, and artifact ids.
3. Add CLI smoke tests for sales/product/month prompts that prove context is
   selected but SQL generation remains closed.
4. Decide whether context records should be separate trace events or embedded
   observations before Milestone 6 query planning begins.

Items 1-3 are complete. Context evidence currently flows through tool
observations, audit records, and normalized trace events. A separate dedicated
schema-context trace event can be added later if review tools need that shape.

The SQL execution boundary now uses a backend-neutral adapter. SQLcl is an
implementation behind `SqlclReadOnlyAdapter`, not an agent-facing tool
contract. Real SQL execution remains closed.

## Completed Milestone 6 Query-Plan Runtime Wave

Plan Milestone 6 NL-to-SQL without enabling real execution:

1. Define query-plan artifact shape for compact-context-backed SQL proposals.
2. Generate deterministic draft query plans for the SH revenue/product/month
   prompt from selected schema context.
3. Validate proposed SQL with the existing Oracle read-only policy and closed
   SQL execution adapter.
4. Record query-plan assumptions, selected schema evidence, and refusal or
   clarification reasons in trace/audit output.

Items 1-4 are implemented. Query-plan artifacts now flow through the runtime
schema-context tool observation/audit/trace path for supported prompts.

## Completed Query-Plan Eval And Pattern-Expansion Wave

Expanded query planning and eval coverage without enabling execution:

1. Add stable golden eval assertions for query-plan fields once trace-event
   subset matching is tuned for nested observation payloads.
2. Add refusal/clarification eval cases for unsupported or ambiguous
   NL-to-SQL prompts.
3. Add more SH query-plan patterns only when selected compact schema context is
   unambiguous.
4. Keep live SQL execution closed; use `SqlclReadOnlyAdapter` only as a closed
   validation boundary until the execution runner safety gates pass.

Items 1-4 are complete for the current Milestone 6 slice.

## Completed Fake Result Explanation Wave

Planned and implemented fake result explanation without enabling real ADW
execution:

1. Define `agent-runtime.result-explanation.v1` artifact fields for query-plan
   provenance, fake adapter metadata, fixture identity, row summaries,
   explanation text, caveats, and `real_database_execution: false`.
2. Consume an existing `planned` query-plan artifact for the supported SH
   revenue/product/month pattern. Do not regenerate SQL from the original
   prompt in the explanation step.
3. Route fixture execution through `FakeSqlExecutionAdapter` only. Record
   adapter name, adapter version, deterministic scenario id, fixture id,
   column names, row count, and fixture limits in trace/audit output.
4. Write cautious explanation behavior: describe only what the fake fixture
   rows show, label the output as non-real database output, and avoid wording
   that implies current Oracle ADW facts, production records, or live SQLcl
   success.
5. Add eval coverage for the happy path and safety gates: blocked, ambiguous,
   unsupported, or policy-rejected query plans must not produce or explain fake
   rows.
6. Keep wording and contracts generic enough that Worker A can change internal
   implementation details without changing the design intent.

Safety gates for this wave:

- No code path may call `SqlclReadOnlyAdapter` or any real ADW connection while
  producing fake explanations.
- Every fake-result artifact, audit record, and trace observation must include
  `real_database_execution: false`.
- Fake rows must come from deterministic fixtures, not from a live database,
  SQLcl subprocess, environment-derived connection, or ad hoc generated data.
- Explanation text must be testable for non-real-output caveats and must never
  present fixture rows as actual business facts.
- Real ADW execution, admin apply, and persistent workflow target writes remain
  closed until their separate safety gates are implemented and reviewed.

Design reference: `docs/design-docs/database-natural-language.md`, section
"Fake Result Explanation Artifacts After Query Planning".

## Completed SQLcl Runner And Adapter-Gate Wave

Implemented the SQLcl subprocess runner safety gates behind the existing
backend-neutral adapter while keeping normal runtime ADW execution closed:

1. Add a runner-level abstraction that accepts a SQLcl execution plan and
   invokes SQLcl with an argv list shaped as `sql -S -L -nolog`. Keep
   credentials, DSNs, rendered connect strings, wallet passwords, and SQL text
   out of argv.
2. Implement minimal base environment construction plus plan environment
   merging. Permit only reviewed SQLcl keys such as `TNS_ADMIN`; reject or
   ignore unexpected keys and prove credential variables do not leak into the
   child process.
3. Pass the SQLcl connect command, session setup, and query through private
   stdin only. Exclude stdin from reprs, responses, traces, audit records, and
   test failure output.
4. Implement hard timeout handling that kills and waits for the SQLcl process,
   then returns a structured timeout outcome through the existing Oracle ADW
   classification helpers.
5. Capture stdout and stderr separately with configured byte limits. Classify
   oversized streams as `output_too_large` or `error_output_too_large` and
   expose only bounded, redacted stderr tails.
6. Keep JSON parsing, row-limit checks, credential redaction, and result/error
   classification in the `oracle_adw` helper layer. The subprocess runner
   should collect process output and status, not duplicate backend parsing
   rules.
7. Add redacted audit metadata for backend, mode, SQL hash, argv, working user,
   timeout, row limit, stream limits, return-code class, and structured
   outcome. Do not record stdin, raw SQL, DSN, passwords, wallet secrets, wallet
   contents, or unredacted SQLcl output.
8. Add adapter integration tests proving `SqlclReadOnlyAdapter` remains closed
   by default, normal planning/fake-result flows cannot reach real execution,
   and `allow_real_execution` is not enabled until the runner gates have a
   senior-review pass.

SQLcl MCP or server-based integration remains optional and is not part of this
wave. This wave is only the local subprocess runner boundary behind
`SqlclReadOnlyAdapter`; real SQL execution, real admin apply, and target-system
writes remain closed.

Items 1-8 are complete for the local runner and adapter-gated integration
slice. `SqlclReadOnlyAdapter` calls a runner only when
`allow_real_execution=True`; all normal planning and fake-result flows keep
real execution disabled.

## Completed SQLcl Adapter Hardening Wave

Hardened the SQLcl adapter path before any live ADW smoke test:

1. Add adapter tests for standalone `SqlclRunnerResult` stream-limit statuses
   and runner pre-output failures.
2. Decide whether `SqlExecutionResponse.audit_metadata` should include
   redacted runner metadata such as bounded byte counts, env keys, and
   return-code class, or keep those details only in lower-level runner tests.
3. Add a senior-review pass over `agent_runtime.sqlcl_runner`,
   `agent_runtime.sql_execution`, and the Oracle ADW classification helpers.
4. Define the explicit operator command or fixture-only smoke path that may set
   `allow_real_execution=True`; do not enable it from agent-facing tools.
5. Keep admin provisioning apply and persistent workflow target-system writes
   closed on their separate review tracks.

Items 1-4 are complete. The adapter now records a redacted runner summary in
audit metadata, covers runner stream-limit and pre-output failure statuses, and
redacts SQLcl connect-line echoes as a unit. SQLcl plan construction also
rejects newline/control characters in `DB_DSN` and `DB_USER_PASS` before
rendering private stdin. The operator-only smoke and read-only query paths now
own the only reviewed runtime routes that may set `allow_real_execution=True`.

## Completed Operator-Only ADW Command Wave

Defined and implemented the operator-only live ADW paths without enabling them
from normal runtime flows:

1. Add an explicit command or harness entry point for a manual read-only smoke
   query that constructs `SqlclReadOnlyAdapter(allow_real_execution=True)`.
2. Require reviewed environment configuration and fail closed when SQLcl path,
   wallet path, working user, DSN, password, or row/time limits are missing or
   unsafe.
3. Permit only a narrow first smoke SQL shape, such as `select 1 from dual` or
   a bounded dictionary-view query, and continue to run read-only policy
   validation before execution.
4. Write redacted audit output with SQL hash, working user, runner status,
   limits, and structured outcome. Do not record raw SQL text, stdin, DSN,
   passwords, wallet secrets, or unredacted SQLcl output.
5. Keep agent-facing tools, schema context, query planning, fake explanations,
   admin provisioning apply, and persistent workflow target-system writes
   unable to enable live execution.

Items 1-5 are complete for smoke and reviewed read-only query execution.
Admin provisioning is also formalized as a separate operator-only command with
structured idempotency classification; it remains outside agent tools and
read-only adapter defaults.

## Completed Fake Explanation Pattern Expansion Wave

Closed the remaining Milestone 6 fake-explanation gap across the currently
supported SH query-plan patterns:

1. Keep result explanations on the `FakeSqlExecutionAdapter` only.
2. Route product/month, channel/month, promotion category/month, and promotion
   subcategory/month plans to explicit deterministic demo fixtures.
3. Preserve `source: fake/deterministic`, `real_database_execution: false`,
   backend `fake`, and `oracle_adw_execution: false` / `sqlcl_execution: false`
   metadata in every result-explanation artifact.
4. Add focused tool tests and golden eval coverage for channel/month and
   promotion/month traces.
5. Preserve refusal behavior for ambiguous, unsupported, blocked, and write
   prompts: no result explanation and no row fields.
6. Require revenue and month terms before product/channel/promotion patterns
   may propose SQL or attach fake rows, and record fixture id, scenario id, and
   adapter version in fake-explanation provenance.

## Completed Milestone 7 Self-Evolution Control Boundary

Started Milestone 7 self-evolution controls without enabling automatic
self-modification:

1. Define `agent-runtime.improvement-candidate.v1` records for observed misses,
   operator notes, eval failures, and review feedback.
2. Add memory provenance fields so any future remembered instruction or
   behavior-shaping fact records source, scope, confidence, timestamp, and
   expiration/review state.
3. Define a rollback path for prompt, policy, memory, and eval artifact changes
   before any behavior-shaping update can be accepted.
4. Add drift-detection fixtures for repeated database-analysis and workflow
   prompts.
5. Require frozen eval pass and explicit review status before accepting any
   self-evolution candidate.

Items 1-5 are complete for the first control boundary. The runtime now has
validators and tests for candidate records, reviewed memory provenance,
rollback plans, drift fixtures, and acceptance gates. The gate does not apply
changes; it only reports `passed` or `blocked`.

Expert review hardening is reflected: accepted candidates require approved
candidate provenance, reviewer identity and timestamp, frozen evals from
`artifacts/evals/golden` with manifest versions matching candidate current
versions, rollback type/version alignment, drift fixture path provenance, and
semantic drift signatures that include query-plan and result-explanation
details.

Follow-up review hardening is also reflected: the gate rejects synthetic eval
or drift result objects unless they cover every configured frozen case, include
the manifest `golden_fixture` version, and include the configured drift fixture
id, path, SHA-256 hash, and case ids.

## Completed Operator Candidate Recording And Safety Hardening Wave

Added the first operator-only candidate recording path and reflected whole-code
review findings without opening automatic self-modification:

1. `bin/agent operator propose-improvement` records proposed improvement
   candidates under the configured artifact directory and writes an operator
   audit event.
2. Candidate artifacts stay in `proposed` / review-pending state. The command
   does not run acceptance gates, approve reviews, edit behavior artifacts, or
   apply changes.
3. Candidate confidence rejects non-finite values such as `NaN` and infinity.
4. Candidate type checks now block behavior-shaping artifact changes from
   hiding behind `docs` candidates, and gate reports reject mismatched drift
   schema versions.
5. Operator ADW audit payloads omit arbitrary response rows on query and smoke
   paths; durable audit keeps row counts and summary fields instead.
6. SQL file and stdin inputs are bounded before decoding, and invalid UTF-8 is
   rejected explicitly.
7. SQLcl timeout/output-limit cleanup stores the process-group id at launch so
   child processes can still be terminated if the group leader exits first.
8. Wallet, DSN, TNS, and connection-string redaction is stricter while boolean
   configuration status fields remain readable.

Expert and PM review status: latest security/code and QA reviews found no
blocking issues after this hardening pass. PM verdict was conditional ship after
updating tracking docs and next-work guidance.

## Completed General Agent Wave (P1–P10, 2026-05-24)

Implemented the general-purpose agent design on branch `claude/general`
(merged to `main` via PR #1). 450 tests / 109 subtests pass.

Modules added: `planner.py`, `executor.py`, `verifier.py`, `session.py`,
`hooks.py`, `skills.py`, `self_evaluator.py`, `session_summarizer.py`.
New artifacts: `artifacts/schemas/plan.schema.v1.json`,
`artifacts/schemas/session-context.schema.v1.json`.

See `docs/tracking/change-log.md` § 2026-05-24 for full detail.

## Next Implementation Wave — P11 (General Agent)

Three open P11 items on branch `claude/general`:

### P11-A: Human Gate Real Interrupt

Scope: `agent_runtime/executor.py`, `agent_runtime/cli.py`

- Replace the `approval_callback: Callable[[PlanStep], bool] | None` stub with
  a real interrupt path: pause execution at `requires_approval=True` steps,
  emit a CLI prompt or webhook event, and resume or abort based on operator
  response.
- Audit records must capture approval decision, timestamp, and operator id.
- Keep the existing `approval_callback` protocol so tests remain compatible.

Acceptance:
- `run_plan()` blocks and waits for operator input when `requires_approval=True`.
- Approval and rejection are both audited.
- Timeout results in abort, not silent skip.

### P11-B: Context Compression / Retrieval

Scope: `agent_runtime/session.py`, `agent_runtime/loop.py`,
`agent_runtime/session_summarizer.py`

- Wire `SessionContext.recent_history(n=20)` into `AgentLoop` so only the last
  20 messages are injected into model context on each turn.
- Add a compression step that summarizes turns beyond the window into a
  `MemoryRecord(status="proposed", review_status="pending")`.
- Keep full history in `messages.jsonl`; inject only the compressed window.

Acceptance:
- Multi-turn sessions do not inject unbounded history into model context.
- Compressed summaries are proposed, never auto-applied.
- Existing single-turn tests continue to pass.

### P11-C: LLM-Based Semantic Self-Evaluation

Scope: `agent_runtime/self_evaluator.py`

- Add an optional LLM-critique path to `SelfEvaluator` when a model provider
  is configured (`model_provider != "mock"`).
- Structural checks (P9) remain as the fast fallback when no provider is set.
- LLM critique output is recorded in `AgentResult.eval_result` alongside the
  structural score.
- Never block answer delivery on LLM critique failure; log and proceed.

Acceptance:
- Mock mode still uses structural-only checks.
- LLM critique result is audited.
- `test_loop_eval.py` continues to pass in mock mode.

## Milestone 7 Hardening — Secondary Wave

Not yet started. Choose when P11 is complete:

1. Add JSON Schema files for self-evolution artifacts if external tools will
   produce candidates, memory records, rollback plans, or drift fixtures.
2. Add candidate hash/signature fields before any persisted candidate can
   become an input to an apply workflow.
3. Define candidate review/approval CLI or workflow states, including reviewer
   identity, timestamps, reject/change-request states, and audit records.
4. Add rollback execution design only after artifact hashes and reviewer
   identity are defined.
5. Keep automatic self-modification, prompt rewrites, policy rewrites, memory
   activation, and eval fixture rewrites closed.

## Verification Commands

```bash
uv run --python 3.13 python -m pytest tests/test_cli.py tests/test_oracle_adw.py tests/test_self_evolution.py tests/test_sql_execution.py tests/test_sqlcl_runner.py -q
uv run --python 3.13 python -m pytest -q
uv run pytest -q
uv run --python 3.13 python -m compileall -q agent_runtime tests
git diff --check
```
