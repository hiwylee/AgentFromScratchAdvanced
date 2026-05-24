# Current State

## Purpose

This file is the first resume point after an interrupted session. Keep it short
and current.

## Current Focus

Bootstrap the project harness for an agent runtime built from scratch, with
Oracle ADW natural-language data access as the first domain specialization.

## Last Completed Work

- Created the private GitHub repository `hiwylee/AgentFromScratch`.
- Added initial harness documents, architecture notes, and product spec.
- Fixed local `SQLCL_PATH` in `.env` to the installed SQLcl executable.
- Added `.gitignore` rules so `.env`, Oracle wallet files, and local secret
  material are not committed.
- Added Oracle ADW connection design and secret-handling rules.
- Added continuity tracking files so work can resume after interruption.
- Reviewed design feedback and promoted key risks into the roadmap:
  observability, eval gates, prompt-as-data, append-only audit logs, compact
  schema context, DB least privilege, memory provenance, drift detection, and
  SQL safety edge cases.
- Ran a planner/developer review and PM reflection. The MVP is now scoped as an
  intent-first agent foundation with audit traces and minimal Oracle ADW
  read-only connectivity, not full autonomous NL-to-SQL.
- Started Milestone 1 implementation as a uv-managed Python 3.13+ prototype:
  `agent ask <text>` now emits structured intent, monitorable run status,
  event output, and append-only audit records.
- Added workflow orchestration architecture for natural-language business
  requests that span A/B/C/D systems, reconciliation, enrichment, target-system
  loading, and human-in-the-loop review.
- Added first-pass workflow intent recognition for requests like
  `이번달 특허자산 대체 등록 진행해줘`, returning `workflow_execution` and
  `select_workflow_template` as the next action.
- Added the first JSON workflow template and JSON Schema for the mock patent
  asset replacement registration workflow. JSON is now the initial workflow
  template and human-gate review packet format.
- Implemented the Milestone 2A workflow skeleton with mock A/B/C/D connectors,
  parallel A/B lookup, C enrichment, deterministic reconciliation, human review
  packets, monitor/audit events, and checkpoint-required D loading.
- Ran senior architect and senior developer reviews over the workflow skeleton
  and reflected blocking feedback. The mock workflow now closes rejected
  checkpoints, copies checkpoint records before target connector calls, records
  pause/resume status, redacts CLI workflow output, blocks invalid asset status
  and duplicate registration rules, and treats empty source results as
  `closed/no_records_to_load`.
- Started Milestone 2 tool loop implementation with structured tool specs,
  registry validation, retry-aware tool execution results, progress event hooks,
  redacted tool outputs, auditable execution context, and approval gates for
  high-risk/write tools.
- Added the Milestone 3 observability/eval skeleton in a disjoint runtime
  layer: versioned trace records, frozen golden mock intent/workflow fixtures,
  a local AgentLoop/mock-model eval runner, and secret-leak checks for trace
  and eval output.
- Added the Milestone 4 Oracle ADW read-only foundation skeleton:
  environment configuration loading, redacted SQLcl status verification, wallet
  path metadata checks, read-only SQL policy validation, schema introspection
  query constants, and fixture-only tests. Real ADW execution is still closed.
- Added a dry-run admin provisioning plan for creating the working `DB_USER`
  from `ADMIN_USER`. The plan requires admin setup configuration, validates the
  working username, rejects protected account/schema names, keeps the real
  password out of generated statements, grants object-level read access to the
  selected sample schema, and creates private synonyms so read-only queries can
  avoid schema-qualified dotted references.
- Chose `SH` as the first sample dataset for natural-language database
  analysis, with `SSB` reserved for later benchmark and stress tests.
- Reflected senior review blockers for the parallel Milestone 2-4 work:
  Oracle policy now blocks `--+` line hints, package/unallowlisted function
  calls, and SQLcl timeout escapes; eval secret checks filter low-signal common
  env values.
- Further tightened the Oracle SQL policy for the parser-less foundation:
  quoted identifiers, mixed quoted/unquoted package calls, comment-separated
  function calls, and dotted references that do not use visible FROM/JOIN table
  names or aliases are blocked conservatively. Nested query shapes with dotted
  references and compound query shapes with dotted references are also blocked
  until a real Oracle SQL parser can enforce scope correctly. Multi-part dotted
  references are blocked for the same reason. Comment stripping for callable
  analysis now preserves comment markers inside double-quoted identifiers.
  SQLcl slash lines with trailing comments, sequence `NEXTVAL`, and
  `PARALLEL_INDEX` hints are also blocked. SQLcl blank-line script breaks and
  command lines such as `HOST`, `CONNECT`, `@script`, and shell escapes are
  blocked before SQL validation, including `.` buffer terminators and command
  abbreviations such as `hos` and `conne`. Any slash-starting SQLcl buffer
  execution line is treated as procedural, even with trailing text. SQLcl
  line-level gates now inspect raw input lines before literal masking.
- Completed the 2026-05-16 active parallel wave:
  - Tool loop integration now wires the default low-risk read-only
    `mock_schema_context` tool into `AgentLoop` for schema inspection actions,
    with retry/max-step coverage and redacted monitor/audit events.
  - Workflow pause/resume/checkpoint events now normalize into the generic
    trace-event shape, and mock workflow resume requires an engine-created
    checkpoint identity and SHA-256 hash before target-system D loading.
  - Oracle ADW SQLcl read-only execution is now designed as a closed execution
    plan: credentials stay out of argv, stdin is redacted, timeout/row/output
    limits are specified, JSON output parsing is bounded, and failure/audit
    records are redacted. Real execution is still intentionally disabled.
  - Milestone 5 compact schema context now has a documented artifact-first
    lexical retrieval plan, schema metadata JSON shape, curated SH seed shape,
    sample-value masking policy, context recording requirements, and durable
    decisions.
- Completed the first Milestone 5 compact schema context implementation wave:
  added generated SH metadata and curated seed artifacts, a dependency-free
  `agent_runtime.schema_context` loader/validator/retriever, deterministic
  lexical scoring with ambiguity handling, relationship-limited table
  expansion, and deny-by-default sample-value masking with allowlist
  enforcement.
- Integrated compact schema context into the low-risk `mock_schema_context`
  tool path. Runtime schema-inspection observations now include selected and
  rejected SH tables, scores, glossary matches, masking decisions, artifact ids,
  and explicit `sql_generation_enabled: false` and
  `sql_execution_enabled: false` markers.
- Added the backend-neutral SQL execution adapter boundary in
  `agent_runtime.sql_execution`. The first implementations are a deterministic
  `FakeSqlExecutionAdapter` for tests and a `SqlclReadOnlyAdapter` that uses
  the existing SQLcl plan/redaction helpers but keeps real execution closed by
  default.
- Started Milestone 6 with `agent_runtime.query_plan`: compact schema context
  can now produce a versioned `agent-runtime.query-plan.v1` artifact for the SH
  revenue/product/month pattern. The artifact contains proposed SQL,
  assumptions, selected schema evidence, read-only policy validation, and an
  explicit `not_executed` execution boundary.
- Integrated query-plan artifacts into runtime observability through the
  low-risk schema context tool. Supported schema prompts now record a
  `query_plan` artifact in tool observations, audit records, and normalized
  trace events while keeping SQL execution disabled.
- Expanded deterministic query-plan coverage to a second SH pattern: revenue
  by channel by month. Unsupported country/customer/promotion patterns block
  instead of guessing.
- Added golden eval coverage for an SH monthly revenue-by-product prompt and
  trace-event subset assertions for schema context output.
- Strengthened golden eval query-plan assertions with nested list subset
  matching and `$absent` checks. The SH revenue/product/month eval now verifies
  stable `query_plan` fields, disabled execution, allowed policy validation,
  and absence of result rows.
- Added golden eval coverage for an ambiguous revenue-by-region/month prompt.
  It verifies schema context remains read-only, query planning requires
  clarification, no SQL is proposed, and execution remains disabled.
- Expanded deterministic query planning to a third supported SH pattern:
  revenue by promotion by month, using `PROMOTIONS.PROMO_CATEGORY` by default
  and `PROMO_SUBCATEGORY` when explicitly requested. Customer/country/region
  rollups and campaign-cost promotion prompts remain blocked.
- Added `agent_runtime.result_explanation` with
  `agent-runtime.result-explanation.v1` artifacts. Planned query plans can now
  be explained using `FakeSqlExecutionAdapter` rows while explicitly marking
  `source: fake/deterministic`, `real_database_execution: false`, and backend
  `fake`.
- Integrated fake result explanations into the schema-context tool for
  supported SH monthly revenue plans. The explanations use deterministic demo
  rows, record fake adapter metadata, and remain separate from real SQLcl or
  ADW execution.
- Strengthened golden evals to assert fake result explanation markers and
  absence of real/SQLcl row fields.
- Added the standalone SQLcl subprocess runner boundary in
  `agent_runtime.sqlcl_runner`. It accepts a prebuilt SQLcl plan, uses argv
  only from the plan, allowlists plan environment keys, passes connect/query
  text through private stdin, bounds/redacts stdout and stderr, and returns
  structured timeout and stream-limit statuses.
- Integrated the SQLcl runner path into `SqlclReadOnlyAdapter` only behind the
  explicit `allow_real_execution=True` gate. The adapter remains closed by
  default, unsafe SQL is rejected before runner calls, injected runner results
  are classified through Oracle ADW helpers, and audit metadata keeps stdin and
  secrets redacted.
- Added fake result-explanation refusal-path eval coverage. Ambiguous,
  unsupported, and blocked-write cases now assert no fake result explanation,
  result rows, real database markers, or SQLcl row fields are present.
- Hardened the still-closed SQLcl adapter path before live ADW use:
  adapter tests now cover runner stream-limit statuses, pre-output `OSError`,
  and direct `TimeoutExpired`; audit metadata includes a redacted runner
  summary; SQLcl connect-line echoes are redacted as a unit; and SQLcl plan
  construction rejects newline/control characters in `DB_DSN` and
  `DB_USER_PASS` before private stdin rendering.
- Added a senior review document for the SQLcl runner/adapter path. The review
  keeps live ADW smoke blocked until an explicit operator path is defined and
  reviewed, but the identified runner-metadata, config-injection, and adapter
  edge-status test gaps are now resolved in the workspace.
- Fixed the SQLcl runner live subprocess capture path so stdout and stderr byte
  limits are enforced while pipes are read. The default runner now stops the
  process as soon as a stream crosses its cap instead of buffering all SQLcl
  output first; injected test runners remain compatible with the existing
  `subprocess.run`-style contract.
- Added the explicit operator-only live ADW smoke command:
  `bin/agent operator adw-smoke --confirm-live-adw-smoke`. It runs only the
  fixed `select 1 as smoke_check from dual` query through
  `SqlclReadOnlyAdapter(..., allow_real_execution=True)` after absolute
  `SQLCL_PATH`, wallet-directory `DB_WALLET_PATH`, wallet TNS alias `DB_DSN`,
  working-user credentials, and `verify_sqlcl(...)` checks pass. The command is
  not registered as an agent tool and records redacted `operator.adw_smoke`
  audit events for confirmation-required, rejected, and executed outcomes.
  Senior-review feedback is reflected: SQLcl version checks use a minimal
  allowlisted environment, smoke limits are prevalidated, operator audit events
  include non-secret local context, and output separates requested, attempted,
  and succeeded live execution states.
- Added the operator-only working-user read-only ADW query command:
  `bin/agent operator adw-query --sql-file query.sql --confirm-live-adw-query`.
  It accepts exactly one SQL source from `--sql-file`, `--sql-stdin`, or
  convenience `--sql`, validates the SQL through the read-only policy before
  SQLcl verification, reuses the smoke preflight gates, and constructs
  `SqlclReadOnlyAdapter(..., allow_real_execution=True)` only after those gates
  pass. Stdout may return bounded redacted rows to the operator, but durable
  `operator.adw_query` audit records omit arbitrary result rows and keep SQL
  text out of audit.
- Tested operator ADW smoke using the local `.env` without printing secrets.
  The `.env` wallet path currently points at a missing directory; overriding
  `DB_WALLET_PATH=/home/opc/wallet` and matching `DB_WALLET_FILE` reaches
  live SQLcl execution. SQLcl can now find Java through the minimal runtime
  environment passed by `SqlclReadOnlyAdapter`, but ADW rejects the configured
  working-user login with `ORA-01017`.
- At operator request, created ADW working user `AIAGENT` via admin SQLcl and
  granted `CREATE SESSION`, `DWROLE`, and `SELECT ANY TABLE`. Verified
  `AIAGENT` is `OPEN` and the requested grants are present. Fixed SQLcl
  read-only stdin rendering so wrapped SQL is terminated before `exit`, then
  verified `bin/agent operator adw-smoke --confirm-live-adw-smoke` and
  `bin/agent operator adw-query --sql-file ... --confirm-live-adw-query`
  both succeed as `AIAGENT`.
- Formalized that admin setup as
  `bin/agent operator adw-provision-working-user --grant-profile prototype-any-table-read --confirm-live-adw-admin-provision`.
  The command is separate from read-only adapters and agent tools, uses admin
  SQLcl with private stdin, keeps audit output redacted, does not rotate an
  existing working-user password by default, and was verified successfully
  against ADW before rerunning smoke/query checks.
- Reflected expert review feedback on the SQLcl runner family: the read-only
  runner already enforces stream caps during live capture, and admin
  provisioning now uses the same bounded SQLcl subprocess boundary instead of
  `subprocess.run(capture_output=True)`. The runner also waits for SQLcl
  wrapper child output to drain within the configured timeout.
- Re-ran live ADW verification with network access enabled. The local `.env`
  wallet paths now resolve without command-line overrides. `operator adw-smoke`
  succeeds as `AIAGENT`, admin provisioning reapplies `CREATE SESSION`,
  `DWROLE`, `SELECT ANY TABLE`, and SH private synonyms, and
  `operator adw-query --sql 'select count(*) as row_count from sales'` succeeds
  with `row_count = 918843`.
- Tightened operator-only ADW admin provisioning after expert review. The
  command now prechecks metadata, skips DDL for `already_compliant`, rejects
  `rejected_drift` before unlocking or granting, repairs only expected profile
  grants/synonyms, postchecks created/repaired accounts, and records redacted
  structured provisioning state. Added `docs/runbooks/operator-adw.md` for env
  preflight, provisioning classifications, smoke, reviewed query execution,
  common failures, and rollback/revoke guidance.
- Updated the stale next-work queue and closed the remaining Milestone 6 fake
  result-explanation gap across supported SH monthly revenue patterns. Product,
  channel, promotion category, and promotion subcategory plans now route to
  explicit deterministic `FakeSqlExecutionAdapter` fixtures, with golden evals
  asserting fake-only markers and absence of Oracle ADW/SQLcl row fields.
- Reflected expert review feedback: product and channel query-plan patterns now
  require revenue and month terms before proposing SQL, bare channel/product
  prompts have negative coverage, and fake result-explanation provenance
  includes fixture id, scenario id, and adapter version.
- Added the Milestone 7 self-evolution control boundary:
  `agent_runtime.self_evolution` now validates improvement candidate records,
  reviewed memory provenance, rollback plans, drift fixtures, and acceptance
  gate reports. The gate can pass only when review is approved, frozen evals
  pass, drift checks pass, rollback covers every affected artifact path, and
  behavior-shaping candidates touch one artifact type at a time. No code path
  applies prompt, policy, memory, eval, schema, or code changes automatically.
- Added an artifact manifest and reviewed closed-by-default runtime memory
  artifact. Trace artifact versions now load from
  `artifacts/artifact-manifest.v1.json`, so prompt, policy, memory, and eval
  version rollback has a single data source.
- Added repeated-prompt drift fixtures for SH monthly product revenue planning
  and patent workflow selection. Drift checks compare stable semantic
  signatures and ignore volatile run ids.
- Reflected expert review feedback on the Milestone 7 gate: approved
  candidates now require approved provenance, reviewer identity/timestamp,
  frozen evals from `artifacts/evals/golden` with manifest versions matching
  candidate current versions, rollback artifact type and before/after version
  alignment, drift fixture path provenance, and finer query-plan/result
  explanation signatures.
- Reflected follow-up review feedback by making gate inputs prove fixture
  provenance. Frozen eval results must include the manifest `golden_fixture`
  version and every frozen case id. Drift results must include the configured
  drift fixture id, path, SHA-256 hash, and every drift case id before the gate
  can pass.
- Renamed the GitHub repository to `hiwylee/AgentFromScratch`, updated the
  local `origin` remote and temporary git metadata directory, and corrected
  visible project title/link references.
- Added optional live LLM action planning through OpenAI Responses API. The
  default remains deterministic mock mode; `agent ask --model-provider openai`
  requires `OPENAI_API_KEY`, uses `OPENAI_MODEL` or `gpt-5.2`, validates returned
  action kinds against the local safety baseline, and does not enable live ADW
  execution or workflow writes.
- Added `oci` as a separate OpenAI-compatible provider. `agent ask` can now use
  `--model-provider oci` or `LLM=oci`, reading `OCI_BASE_URL`, `OCI_API_KEY` or
  `OCI_API_KEY_2`, and `OCI_MODEL`. The local `.env` is configured for OCI
  provider selection and `xai.grok-4-1-fast-non-reasoning` without printing key
  values.
- OCI live smoke now reaches the configured endpoint with the `OpenAI-Project`
  header derived from `OCI_PROJECT_OCID`, but both configured OCI API keys
  return `404 Authorization failed or requested resource not found`. This
  suggests project OCID, endpoint region, model availability, or API-key
  authorization mismatch rather than missing local env wiring.
- Reflected Oracle docs by keeping the documented OCI `/openai/v1` Responses
  API path and adding an API-key fallback to `/20231130/actions/v1/responses`
  after OCI 404 responses. The OCI live smoke now succeeds with
  `xai.grok-4-1-fast-non-reasoning`, returning a locally validated
  `final_answer` action with `model_provider: oci`.
- Added `docs/runbooks/oci-responses-api.md` as the operator runbook for OCI
  Responses API setup, smoke testing, fallback behavior, and troubleshooting.
- Added non-secret OpenAI configuration placeholders to local `.env` and
  tracked `.env.example`; the real `OPENAI_API_KEY` value remains operator
  supplied and ignored by git.
- Corrected the Python project package name to `agent-from-scratch` and
  refreshed `uv.lock`.
- Normalized Python command examples and tracking references to Python 3.13 so
  documentation matches `pyproject.toml`.
- Added startup repository freshness checks to `AGENTS.md` and `CLAUDE.md` so
  future sessions must compare repo-server state, upstream commits, and local
  worktree changes before implementation.
- Added `bin/agent operator propose-improvement` for operator-only recording
  of self-evolution improvement candidates. It writes proposed candidate JSON,
  records audit, leaves review/provenance pending, and does not run gates or
  apply behavior changes.
- Moved the completed bootstrap execution plan from
  `docs/exec-plans/active/` to `docs/exec-plans/completed/`.
- Reflected the latest whole-code review and expert/PM feedback. Operator ADW
  audit records now omit arbitrary response rows consistently, SQLcl process
  cleanup keeps a captured process-group id for timeout/output-limit cleanup,
  SQL file/stdin reads are byte-bounded, non-finite self-evolution confidence
  values are rejected, behavior-shaping candidate type checks are stricter, and
  pytest can run from the repository root through `pyproject.toml`.

## General Agent Architecture (claude/general branch — P1–P10 complete, 2026-05-24)

Implemented P1–P10 of the general-purpose agent design on branch `claude/general`.
All tests pass; Codex adversarial review + QA PASSED; PR #1 open (claude/general → main).

### P1–P7 (initial implementation)
- `agent_runtime/planner.py` — PlanStep + ExecutionPlan with Kahn topological sort
- `agent_runtime/executor.py` — StepExecutor + run_plan_shadow()
- `agent_runtime/verifier.py` — ToolResultVerifier, FailureReason taxonomy
- `agent_runtime/session.py` — SessionContext, BudgetTracker, ConversationSlot
- `agent_runtime/hooks.py` — HookRegistry (redact enforced, per-handler isolation)
- `agent_runtime/skills.py` — SkillRegistry + default_skill_registry()
- `artifacts/schemas/plan.schema.v1.json`, `session-context.schema.v1.json`

### P8 — Real Plan Execution (2026-05-24)
- `executor.py`: `StepExecutor.run_plan()` — real tool calls, retry/skip/abort/clarify/use_alternative
- `executor.py`: `approval_callback` gate for `requires_approval=True` steps
- `loop.py`: `AgentLoop(use_plan_execution=False)` flag + `AgentResult.plan_execution`

### P9 — Reflection Loop (2026-05-24)
- `agent_runtime/self_evaluator.py` — deterministic 5-check answer quality (SelfEvaluator)
- `agent_runtime/session_summarizer.py` — failure-pattern extraction → proposed MemoryRecord

### P10 — Agentic Engineering Wiring (2026-05-24)
Closed gaps identified by 12-principle Agentic Engineering review:
- `loop.py`: SelfEvaluator wired after final_answer → `AgentResult.eval_result`
- `loop.py`: `AgentLoop.summarize_session()` — calls SessionSummarizer after run
- `session.py`: `SessionContext.recent_history(n=20)` — context windowing
- `cli.py`: `--memory-dir` arg → calls summarize_session after ask subcommand
- Hook event `answer_evaluated` fires with passed/score/issues

### Agentic Engineering 12-principle coverage
✅ Goal-driven, Planning, Tool Use, Infinite Loop Prevention, Tool Reliability, Observability
⚠️ Memory (windowing added, compression future), Reflection (structural only, LLM critique future)
⚠️ Human Gate (approval_callback exists, real interrupt P11), Evaluation (offline only)
❌ Context compression/retrieval (P11+)

## Next Action

Next implementation focus moves past the first Milestone 7 operator recording
and hardening boundary:

- optionally run a live LLM smoke after setting `OPENAI_API_KEY`:

```bash
bin/agent ask "hello" --model-provider openai --run-dir /tmp/afs-llm-smoke --audit-log /tmp/afs-llm-smoke.jsonl
```

- add JSON Schema files for the self-evolution artifacts if external producers
  will write them directly;
- define candidate artifact hash/signature and reviewer identity fields before
  persisted candidates can feed an apply workflow;
- design candidate review/approval and rollback execution flows before opening
  any behavior-change apply path;
- define the next active execution plan before starting another implementation
  wave;
- broaden drift fixtures only after a concrete prompt, policy, or memory change
  candidate needs coverage;
- keep automatic self-modification closed until reviewer identity, artifact
  signing or hashes, and rollback execution are designed.

Persistent workflow approval/resume and real target-system writes must remain
closed until signed or hashed checkpoint persistence, approval authorization,
idempotency, and replay protection are designed. Admin provisioning apply
remains operator-only and live; production hardening should still replace the
prototype `SELECT ANY TABLE` profile with narrower object-level grants.
Operator ADW smoke, read-only query, and provisioning commands remain explicit
operator checks only; normal `agent ask`, schema context, query planning, fake
explanations, and default tools must not enable live execution.

Recommended starting point:

- Open `agent_runtime/self_evolution.py`, `agent_runtime/cli.py`,
  `agent_runtime/sqlcl_runner.py`, and `tests/test_cli.py` before continuing
  self-evolution or operator safety hardening.
- If adding external candidate producers, create JSON Schema files for
  improvement candidates, rollback plans, memory records, drift fixtures, and
  gate reports.
- Keep `agent ask`, schema context, query planning, and fake result explanation
  paths non-live unless a future reviewed plan explicitly changes that boundary.

## Last Verification

Most recent focused and full checks after the expert/PM hardening pass:

```bash
uv run --python 3.13 python -m pytest tests/test_cli.py tests/test_oracle_adw.py tests/test_self_evolution.py tests/test_sql_execution.py tests/test_sqlcl_runner.py -q
uv run --python 3.13 python -m pytest -q
uv run pytest -q
uv run --python 3.13 python -m compileall -q agent_runtime tests
git diff --check
```

Result: focused tests passed 96 tests and 84 subtests; the full pytest suite
passed 207 tests and 103 subtests; root `uv run pytest -q` passed; compileall
and whitespace checks passed.

Latest review status: independent security/code and QA reviews found no
blocking issues after the hardening pass. The PM verdict was conditional ship:
code is shippable, with documentation/tracking updated here before handoff.

Previous Python 3.13 normalization check:

```bash
UV_CACHE_DIR=.uv-cache uv run --no-dev --python 3.13 python -m unittest tests.test_self_evolution
```

Result: passed 15 tests. A default dev-dependency run attempted to fetch
`pluggy==1.6.0` for `pytest` and was blocked by DNS/network access.

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_tools tests.test_runtime_controls
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_workflow_engine tests.test_eval_runner
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_oracle_adw
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_schema_context
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_sql_execution
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_sqlcl_runner
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_runtime_controls tests.test_sql_execution tests.test_sqlcl_runner tests.test_tools tests.test_oracle_adw
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m py_compile agent_runtime/cli.py agent_runtime/sqlcl_runner.py tests/test_runtime_controls.py tests/test_sqlcl_runner.py
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m py_compile agent_runtime/sqlcl_runner.py tests/test_sqlcl_runner.py
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_query_plan
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_query_plan tests.test_tools tests.test_eval_runner tests.test_result_explanation
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_model tests.test_cli tests.test_intent tests.test_runtime_controls
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest discover -s tests
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m py_compile agent_runtime/model.py agent_runtime/cli.py agent_runtime/loop.py tests/test_model.py tests/test_cli.py
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python - <<'PY'
from pathlib import Path
from agent_runtime.schema_context import load_schema_artifacts, build_compact_schema_context
root = Path('docs/generated/schema-context')
artifacts = load_schema_artifacts(root / 'oracle_adw_sh.schema-metadata.v1.json', root / 'oracle_adw_sh.curated-seed.v1.json', expected_profile_id='oracle_adw_sh.v1')
result = build_compact_schema_context(artifacts, request_text='show revenue by product month trend', request_terms=['revenue','product','month','trend'])
print(result.profile_id)
print(result.selected_table_ids)
print(result.clarification)
PY
bin/agent ask "inspect oracle schema" --run-dir /tmp/afs-tool-smoke --audit-log /tmp/afs-tool-smoke.jsonl
bin/agent workflow "이번달 특허자산 대체 등록 진행해줘" --run-dir /tmp/afs-workflow-final2 --audit-log /tmp/afs-workflow-final2.jsonl
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --run-dir /tmp/afs-runs-1 --audit-log /tmp/afs-audit-1.jsonl
bin/agent ask "고객 테이블에서 오래된 데이터를 삭제해줘" --run-dir /tmp/afs-runs-2 --audit-log /tmp/afs-audit-2.jsonl
bin/agent ask "이번달 특허자산 대체 등록 진행해줘" --run-dir /tmp/afs-workflow-intent2 --audit-log /tmp/afs-workflow-intent2.jsonl
bin/agent ask "Show channels from the Oracle ADW SH schema." --run-dir /tmp/afs-channel-negative --audit-log /tmp/afs-channel-negative.jsonl
bin/agent ask "hello" --model-provider mock --run-dir /tmp/afs-llm-mock-smoke --audit-log /tmp/afs-llm-mock-smoke.jsonl
env -u OPENAI_API_KEY bin/agent ask "hello" --model-provider openai --run-dir /tmp/afs-llm-config-smoke --audit-log /tmp/afs-llm-config-smoke.jsonl
bin/agent ask "hello" --model-provider oci --run-dir /tmp/afs-oci-doc-fallback --audit-log /tmp/afs-oci-doc-fallback.jsonl
OCI_API_KEY= bin/agent ask "hello" --model-provider oci --run-dir /tmp/afs-oci-llm-smoke-key2 --audit-log /tmp/afs-oci-llm-smoke-key2.jsonl
bin/agent status --run-dir /tmp/afs-runs-1
bin/agent status --run-dir /tmp/afs-runs-2
bin/agent status --run-dir /tmp/afs-workflow-intent2
```

The latest full test run covered 183 tests and passed. Focused model, CLI,
intent, runtime-control, query-plan, tool, eval-runner, and result-explanation
tests pass. The reviewed negative channel prompt no longer emits proposed SQL,
fake result rows, or real execution markers. Focused runtime, SQL execution,
SQLcl runner, tool, and Oracle ADW tests pass. The mock `agent ask` smoke
works, and the OpenAI provider path fails closed with `configuration_required`
when `OPENAI_API_KEY` is not set. OCI provider live smoke now succeeds through
the API-key fallback route after the documented `/openai/v1` route returns
OCI 404.
Query-plan artifacts still propose SQL only after read-only policy validation
and mark execution as `not_executed`. Fake result explanations are marked as
deterministic non-real output and use only `FakeSqlExecutionAdapter`.

## Open Questions

- Should the first implementation be Rust-only, or Rust core plus a TypeScript
  or Python helper layer? Decided: Python 3.13+ prototype first through `uv`.
- Should Oracle ADW execution use SQLcl subprocesses first or a direct Oracle
  driver? Current design path: backend-neutral SQL execution adapter first,
  with SQLcl as the first adapter-gated subprocess implementation. Direct
  driver or MCP exposure can be added later behind the same adapter boundary.
- Which read-only schema introspection queries are safe enough for the first
  connector milestone? Initial constants now cover tables, columns, and comments
  through Oracle data dictionary views.
- Which schema retrieval strategy should be used first for compact Oracle ADW
  context? Decided: artifact-first deterministic lexical retrieval over
  working-user-visible metadata plus curated SH seeds.
- Which eval fixture format should become the frozen golden set? Initial
  decision: JSON files under `artifacts/evals/golden/` using
  `agent-runtime.eval-fixture.v1`.
- Which artifact format should be used first for intent schemas and mock model
  fixtures? Initial decision: JSON schemas and Markdown prompts.
- Which workflow template format and review packet format should be used first?
  Decided: JSON artifacts validated by JSON Schema.

## Resume Checklist

- Read `AGENTS.md`.
- Read this file.
- Read `docs/tracking/todo.md`.
- Read `docs/tracking/next-work-queue.md`.
- For Milestone 5 work, open `docs/design-docs/database-natural-language.md`
  and `docs/tracking/todo.md` first.
- For Oracle ADW execution work, open `agent_runtime/oracle_adw.py` and
  `tests/test_oracle_adw.py` first.
- For OCI Responses API LLM work, open `docs/runbooks/oci-responses-api.md`,
  `agent_runtime/model.py`, and `tests/test_model.py` first.
- Check local git state with:

```bash
git --git-dir=/tmp/AgentFromScratch.git --work-tree="$PWD" status
```

The workspace currently uses `/tmp/AgentFromScratch.git` as the git metadata
directory because `.git` in the worktree is a read-only mount.
