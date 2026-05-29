# Change Log

This is a human-written project change log. It tracks meaningful project
direction and implementation changes, not every tiny edit.

## 2026-05-29

- **M8 bug fix**: `SqlclReadOnlyAdapter` in `_handle_adw_query` was passing `settings`
  as a positional argument but the constructor requires it as keyword-only (after `*`).
  Fixed to `settings=settings`. Live smoke confirmed: `adw_query` returns 240 rows
  from real Oracle ADW.

- **Phase 5 (CP5) — Milestone 8: real ADW query tool**: `adw_query` ToolSpec
  with `risk_level="high"`, `read_only=True` registered in `default_tool_registry()`.
  `_handle_adw_query` handler validates SQL policy → loads `OracleAdwConfig` →
  runs `SqlclReadOnlyAdapter(allow_real_execution=True)` → returns bounded rows.
  `AgentLoop` gains `allow_real_query: bool = False`; when `True` and a planned
  query plan exists, a second `adw_query` tool call fires with
  `approved_high_risk_tools=("adw_query",)`. CLI `--allow-real-query` operator flag
  threads through `_ask()`. 6 new tests; 555 tests / 109 subtests pass.

- **Phase 4 (CP4) — M7 rollback design + review CLI**: `ImprovementCandidateRecord`
  gains immutable `review_records: tuple[ReviewRecord, ...]` audit trail.
  `approve_candidate()` / `reject_candidate()` pure functions append `ReviewRecord`
  and update `CandidateReview` atomically. `RollbackExecutor` class with
  `validate_rollback_plan()` and `execute_rollback(dry_run=True)` (live execution
  permanently closed). `review-candidate list --status` filter; approve/reject
  delegate to new functions. 5 new tests.

- **Phase 3 (CP3) — SSB artifacts + QUERY_PATTERN_REGISTRY + M7 hash tamper
  detection**: SSB Star Schema Benchmark artifacts created
  (`oracle_adw_ssb.schema-metadata.v1.json`, `oracle_adw_ssb.curated-seed.v1.json`).
  `artifact-manifest.v1.json` gains `oracle_adw_ssb.v1` profile.
  `QUERY_PATTERN_REGISTRY` in `query_plan.py` blocks unknown schema profiles with
  `unsupported_schema_profile`. `ReviewRecord` dataclass added to `self_evolution.py`.
  `evaluate_self_evolution_gate()` re-computes SHA-256 and blocks on hash mismatch.

- **Phase 2 (CP2) — Schema Registry infrastructure**: Hardcoded `oracle_adw_sh`
  file paths replaced with `artifact-manifest.v1.json` registry lookup.
  `SchemaProfileConfig` dataclass + `load_schema_profile_from_manifest()` in
  `schema_context.py`. `tools.py` and `loop.py` use `_load_schema_profile()`.
  `SCHEMA_REQUIRED_TABLES` dict in `oracle_adw.py`.

- **Phase 1 (CP1) — Production DB permission hardening**: Added `production-sh-read`
  grant profile to `adw-provision-working-user`. The new profile grants only
  `CREATE SESSION` (system) + `GRANT SELECT ON SH.{table}` for the five core SH
  tables (CHANNELS, CUSTOMERS, PRODUCTS, SALES, TIMES) plus private synonyms, replacing
  the broad prototype `SELECT ANY TABLE` + `DWROLE`. Drift detection now rejects
  `SELECT ANY TABLE` and `DWROLE` when the production profile is active.
  New helpers: `_admin_required_object_grants`, `_admin_drift_roles`,
  `_admin_drift_sys_privileges`. `_admin_account_state` extended with
  `required_object_grants`, `drift_roles_set`, `drift_sys_privileges_set` params;
  `dba_tab_privs` inspection query added. Updated runbook with production section,
  drift-revoke guidance, and object-grant verification SQL. 3 new tests added;
  544 tests / 109 subtests pass.

## 2026-05-16

- Created the initial harness structure for building an agent runtime from
  scratch.
- Created a private GitHub repository at `hiwylee/AgentFromScratch`.
- Added product, architecture, harness engineering, and reference-map docs.
- Chose Oracle ADW as the first database specialization target.
- Added secret-handling rules for `.env`, wallet files, passwords, API keys,
  and connection strings.
- Confirmed local SQLcl installation at
  `/home/opc/.local/share/sqlcl/sqlcl/bin/sql`.
- Updated local `.env` `SQLCL_PATH` to the installed SQLcl path.
- Added `.gitignore` and `.env.example`.
- Added continuity tracking files for interrupted-session recovery.
- Incorporated design-review feedback into the roadmap:
  prompt-as-data, append-only audit logs, observability, eval skeleton, frozen
  golden fixtures, memory provenance, drift detection, DB least privilege, and
  compact schema context design.
- Added planner/developer review notes and PM decisions. The MVP is now
  intent-first with traceability and minimal Oracle ADW read-only connectivity;
  full NL-to-SQL is explicitly later.
- Started Milestone 1 with a uv-managed Python 3.13+ prototype. Added `agent ask`,
  structured intent analysis, trace/audit output, redaction helpers, artifact
  files, and initial `unittest` coverage.
- Expanded Milestone 1 with core message/action/observation/final-answer types,
  a mock model adapter, an `AgentLoop`, budget placeholders, run status files,
  and `agent status` for local monitoring.
- Added workflow orchestration design for multi-system natural-language business
  processes, including A/B source comparison, C-system enrichment, D-system
  loading, reconciliation checkpoints, and human-in-the-loop gates.
- Completed Milestone 1 runtime controls with max-step stopping, timeout checks,
  cancellation token support, and focused runtime-control tests.
- Added first-pass workflow intent recognition for patent asset replacement
  registration requests, returning workflow template selection as the next
  safe action.
- Added the first JSON workflow template artifact and JSON Schema for the mock
  patent asset replacement registration workflow, including review packet
  fields and target-load checkpoint expectations.
- Implemented the Milestone 2A workflow skeleton with template-backed metadata,
  mock A/B/C/D connectors, parallel A/B lookup, C enrichment, deterministic
  reconciliation, human-gate checkpoint packets, monitor/audit events, and
  tests for forged checkpoint attempts.
- Reflected senior architect/developer review feedback into the workflow
  skeleton: rejected checkpoints now close trusted resume state, target loads
  receive copied checkpoint records, paused/resumed workflows update monitor
  files, CLI workflow output is redacted, empty result sets close without D
  loading, and declared mock rules for asset status and duplicate registration
  are enforced.
- Added CLI workflow tests so unsupported natural-language workflow requests do
  not silently run the patent workflow, while supported patent requests still
  pause at the target-load checkpoint.
- Added the Milestone 4 Oracle ADW read-only foundation skeleton with
  environment config loading, redacted SQLcl status checks, wallet path metadata
  checks, read-only SQL policy validation, schema introspection query constants,
  and fixture-only unit tests. Real database execution remains intentionally
  closed.
- Added the Milestone 2 tool registry skeleton with typed tool specs, argument
  validation, retry-aware execution results, progress event hooks, and
  redacted tool outputs.
- Added the Milestone 3 observability/eval skeleton with versioned trace
  records, frozen mock intent/workflow golden fixtures, a credential-free local
  eval runner, and tests that fail on unredacted known secret values.
- Reflected senior review blockers for Milestones 2-4: tool execution now
  requires an auditable execution context and blocks high-risk/write tools
  without explicit approval; Oracle read-only policy now blocks line hints,
  package/unallowlisted function calls, and SQLcl timeout escapes; eval secret
  checks ignore low-signal common values to avoid false positives.
- Tightened Oracle SQL policy after repeated senior review: quoted identifiers,
  mixed quoted/unquoted package calls, comment-separated calls, and
  non-alias dotted references are now blocked until a real Oracle parser and
  safe function allowlist exist.
- Added a conservative parser-less guard that blocks nested query shapes with
  dotted references, preventing subquery aliases from whitelisting package-like
  references in another SQL scope.
- Added the same conservative dotted-reference guard for compound queries
  (`UNION`, `INTERSECT`, `MINUS`) to prevent later query-block aliases from
  whitelisting earlier package-like references.
- Blocked multi-part dotted references such as `a.b.c` until a real Oracle SQL
  parser can distinguish schema/table/column references from package/member
  calls safely.
- Fixed SQL comment stripping for callable analysis so comment markers inside
  double-quoted Oracle identifiers are not mistaken for real comments.
- Blocked SQLcl slash lines with trailing comments, sequence `NEXTVAL`
  references, and `PARALLEL_INDEX` optimizer hints.
- Blocked SQLcl blank-line script breaks and SQLcl command lines such as
  `HOST`, `CONNECT`, `@script`, and shell escapes in read-only SQL text.
- Blocked SQLcl `.` buffer terminators and accepted command abbreviations such
  as `hos` and `conne`.
- Treated any slash-starting SQLcl buffer execution line as procedural,
  including slash lines with trailing text or block comments.
- Moved SQLcl slash, blank-line, and command-line gates to raw input lines so
  unterminated strings or quoted identifiers cannot hide SQLcl commands.
- Added dry-run admin provisioning plan generation for creating the working
  `DB_USER` from `ADMIN_USER`, with validated identifiers, symbolic password
  placeholders, object-level SH/SSB grants, and private synonyms for sample
  tables.
- Tightened the provisioning plan to require admin setup configuration, reject
  protected working usernames, use SSB `DWDATE`, and accept Oracle-style
  uppercase result keys from schema profile rows.
- Chose `SH` as the first natural-language DB analysis dataset and `SSB` as
  the later benchmark/stress dataset.
- Added `docs/tracking/next-work-queue.md` as the durable handoff queue for the
  next parallel implementation wave, with worker scopes, safety gates, and
  verification commands.
- Completed the first tool-loop integration into `AgentLoop` with the
  low-risk read-only `mock_schema_context` tool, explicit retry/max-step
  behavior, and redacted tool monitor/audit output.
- Promoted workflow monitor events into the generic trace-event shape and added
  a local trusted checkpoint identity/hash boundary so mock workflow resume no
  longer relies on caller-supplied JSON alone before target-system D loading.
- Designed the Oracle ADW SQLcl read-only execution boundary as a still-closed
  execution plan with private stdin credentials, row/time/output limits, JSON
  result parsing, redacted errors, and redacted audit records.
- Defined the Milestone 5 compact schema context plan: artifact-first lexical
  retrieval over SH metadata and curated seeds, sample values deny-by-default,
  and required trace/audit context records.
- Verified the current workspace with focused tool/runtime, workflow/eval, and
  Oracle ADW tests plus the full test suite. The full suite covered 81 tests
  and passed.
- Added generated SH compact schema artifacts under
  `docs/generated/schema-context/`: schema metadata for SALES, PRODUCTS,
  CUSTOMERS, CHANNELS, TIMES, PROMOTIONS, and COUNTRIES, plus a curated table
  and glossary seed with low-risk sample value allowlists.
- Narrowed `.gitignore` so versioned schema-context generated JSON artifacts
  can be tracked while other generated output stays ignored.
- Added `agent_runtime.schema_context`, a dependency-free compact schema
  context layer that loads and validates metadata/seed artifacts, rejects
  missing seed table or column references, retrieves tables through
  deterministic lexical scoring, handles ambiguity with clarification, expands
  only selected relationship candidates, and enforces deny-by-default sample
  masking.
- Added focused schema context tests and verified the full suite again. The
  full suite now covers 86 tests and passed.
- Integrated compact schema context into the default low-risk schema tool.
  Schema-inspection runs now load the generated SH artifacts, return selected
  and rejected table evidence, glossary matches, masking decisions, artifact
  ids, and explicit markers that SQL generation and execution remain disabled.
- Added the backend-neutral SQL execution adapter boundary with
  `SqlExecutionAdapter`, request/response/error records,
  `FakeSqlExecutionAdapter`, and a closed `SqlclReadOnlyAdapter` that builds
  redacted SQLcl dry-run metadata without invoking a subprocess.
- Documented the adapter-vs-tool boundary and why MCP/server exposure should
  remain optional above the adapter rather than replacing it.
- Verified the full suite again after adapter integration. The full suite now
  covers 95 tests and passed.
- Started Milestone 6 by adding `agent_runtime.query_plan` and focused tests.
  Compact schema context can now produce a versioned query-plan artifact for
  SH revenue by product by month, with proposed SQL, assumptions, schema
  provenance, read-only policy validation, and explicit `not_executed`
  execution metadata.
- Verified the full suite after the query-plan slice. The full suite now
  covers 99 tests and passed.
- Integrated query-plan artifacts into the runtime schema-context tool output
  so supported prompts record proposed SQL plans, policy validation, schema
  provenance, and `not_executed` execution metadata in monitor/audit/trace
  events.
- Expanded deterministic query planning to support both SH revenue by product
  by month and SH revenue by channel by month, while blocking unsupported
  country/customer/promotion-style patterns instead of guessing.
- Added a golden eval case for an SH monthly revenue-by-product prompt and
  extended the eval runner with ordered trace-event subset matching.
- Verified the full suite after the runtime/eval/query-plan wave. The full
  suite now covers 103 tests and passed.
- Strengthened golden eval query-plan coverage with recursive nested subset
  matching and `$absent` assertions so stable query-plan fields can be checked
  without matching volatile trace payloads.
- Added an ambiguous SH revenue-by-region/month eval that requires
  clarification and verifies no SQL is proposed or executed.
- Expanded deterministic query planning to support SH revenue by promotion by
  month, including promotion subcategory when explicitly requested, while
  keeping customer/country/region and campaign-cost promotion prompts blocked.
- Verified the full suite after the query-plan eval and pattern-expansion wave.
  The full suite now covers 108 tests and passed.
- Added `agent_runtime.result_explanation`, a fake deterministic
  result-explanation boundary for planned query artifacts. It consumes
  `FakeSqlExecutionAdapter` output only, marks `real_database_execution` as
  false, preserves query-plan provenance, and blocks non-planned or rejected
  plans without adapter calls.
- Integrated fake result explanations into the schema-context tool for the SH
  revenue/product/month plan using small deterministic demo rows and explicit
  fake backend metadata.
- Extended golden evals to assert fake result explanation markers and absence
  of real database/SQLcl row fields.
- Verified the full suite after the fake result explanation wave. The full
  suite now covers 114 tests and passed.

## 2026-05-17

- Added `agent_runtime.sqlcl_runner`, a standalone SQLcl subprocess runner
  boundary that accepts prebuilt SQLcl plans, keeps credentials and SQL text
  out of argv, sends connect/query text through private stdin, allowlists plan
  environment keys, bounds captured output, redacts secrets, and returns
  structured timeout and stream-limit statuses.
- Integrated the SQLcl runner path into `SqlclReadOnlyAdapter` only behind the
  explicit `allow_real_execution=True` gate. The adapter remains closed by
  default, rejects unsafe SQL before runner calls, classifies runner output
  through the Oracle ADW helper layer, and keeps audit metadata redacted.
- Added golden eval coverage for fake result-explanation refusal paths so
  ambiguous, unsupported, and blocked-write prompts do not emit fake rows, real
  database markers, or SQLcl row fields.
- Hardened the SQLcl adapter path before live ADW smoke: adapter tests now
  cover stream-limit statuses, pre-output runner errors, and direct timeout
  exceptions; audit metadata includes a redacted runner summary; SQLcl
  connect-line echoes are redacted as a unit; and SQLcl plan construction
  rejects newline/control characters in `DB_DSN` and `DB_USER_PASS`.
- Added a senior-review document for the SQLcl runner/adapter path. Live ADW
  smoke remains blocked until an explicit operator-only command path and smoke
  SQL contract are defined.
- Fixed the SQLcl runner live subprocess path so stdout and stderr limits are
  enforced while streams are read, not after `subprocess.run(capture_output=True)`
  buffers the full output. The default runner now terminates the process as
  soon as either stream crosses its configured byte cap, while injected test
  runners keep the existing callable contract.
- Added `bin/agent operator adw-smoke --confirm-live-adw-smoke`, an
  operator-only live ADW smoke command that runs only the fixed
  `select 1 as smoke_check from dual` query through the SQLcl adapter live gate.
  It requires working-user env config, absolute `SQLCL_PATH`, wallet-directory
  `DB_WALLET_PATH`, wallet TNS alias `DB_DSN`, and successful SQLcl
  verification before constructing `SqlclReadOnlyAdapter` with
  `allow_real_execution=True`; it writes redacted `operator.adw_smoke` audit
  records and is not exposed through the agent tool registry.
- Reflected senior security feedback on the smoke path: SQLcl version checks
  now use a minimal allowlisted environment, CLI smoke limits are validated
  before verification or adapter construction, operator audit events include
  non-secret local context, and smoke output separates requested, attempted,
  and succeeded live execution states.
- Added `bin/agent operator adw-query --confirm-live-adw-query`, an
  operator-only working-user read-only ADW query command. It accepts one SQL
  source from `--sql-file`, `--sql-stdin`, or convenience `--sql`, validates
  read-only SQL before SQLcl verification, reuses the smoke live-execution
  gates, and constructs the SQLcl adapter with `allow_real_execution=True` only
  after preflight succeeds. Durable `operator.adw_query` audit records omit
  arbitrary result rows and avoid raw SQL text.
- Tested the operator ADW smoke path with local `.env` values. The checked-in
  code reached live SQLcl execution after overriding stale wallet paths to
  `/home/opc/wallet`, but the database rejected the configured working-user
  login with `ORA-01017`. The adapter now passes a minimal runtime environment
  (`PATH`, `JAVA_HOME`, `HOME`, locale keys) to SQLcl execution so SQLcl can
  find Java without inheriting credential variables.
- Created the `AIAGENT` working user through an explicit admin SQLcl operation
  at operator request, granting `CREATE SESSION`, `DWROLE`, and
  `SELECT ANY TABLE`. Verified the account is `OPEN` and those grants are
  present. Fixed SQLcl read-only stdin rendering so wrapped queries terminate
  with a semicolon before `exit`, then verified both `operator adw-smoke` and
  `operator adw-query` succeed against ADW as `AIAGENT`.
- Formalized admin provisioning as
  `bin/agent operator adw-provision-working-user --grant-profile prototype-any-table-read --confirm-live-adw-admin-provision`.
  The command stays outside agent tools and read-only adapters, uses admin
  SQLcl only through private stdin, does not rotate an existing working-user
  password by default, reapplies the explicit prototype grants, redacts audit
  output, and was verified successfully against ADW before rerunning smoke and
  read-only query checks.
- Reflected expert review feedback on the SQLcl subprocess family. The admin
  provisioning path now uses bounded live stream capture instead of
  `subprocess.run(capture_output=True)`, rejects unsafe working-user password
  characters before rendering setup SQL, and records runner status/byte counts
  in redacted operator output. The SQLcl runner also waits for wrapper child
  process output to drain within the configured timeout.
- Extended the `prototype-any-table-read` provisioning profile to create
  private `AIAGENT` synonyms for SH core tables. This lets operator SQL keep
  using unqualified table names while the read-only policy continues blocking
  schema-qualified dotted references. Live verification succeeded for
  `operator adw-smoke` and `select count(*) as row_count from sales`, returning
  `row_count = 918843`.
- Tightened operator-only ADW admin provisioning with structured idempotency
  classification. The command now prechecks metadata, skips DDL for
  `already_compliant`, rejects `rejected_drift` before unlocking or granting,
  repairs only expected profile grants/synonyms for
  `granted_missing_privileges`, postchecks created or repaired accounts, and
  records redacted structured classification state.
- Added `docs/runbooks/operator-adw.md` covering env preflight, provisioning
  classifications, smoke, reviewed query execution, common failures, and
  rollback/revoke guidance.

## 2026-05-18

- Updated the work queue so completed operator-only ADW smoke/query/provisioning
  work no longer appears as the next implementation wave.
- Extended fake result explanations across all currently supported SH monthly
  revenue query-plan patterns: product category, channel, promotion category,
  and promotion subcategory. The runtime still uses only deterministic
  `FakeSqlExecutionAdapter` fixtures and keeps real ADW/SQLcl execution closed
  for normal agent flows.
- Added focused tool coverage and golden eval cases for channel/month and
  promotion/month fake result explanations, including fake source markers,
  disabled real execution markers, and absence of Oracle ADW or SQLcl row
  fields.
- Reflected expert review feedback by requiring revenue and month terms before
  product or channel query-plan patterns can emit proposed SQL, adding negative
  coverage for bare product/channel prompts, and recording fake adapter
  version plus scenario id in result-explanation provenance.
- Recorded the next implementation wave as Milestone 7 self-evolution
  controls: improvement-candidate records, memory provenance, rollback,
  drift-detection fixtures, and eval/review gates.
- Added the Milestone 7 self-evolution control boundary. New data models and
  tests cover improvement candidates, memory provenance, rollback plans,
  acceptance-gate reports, artifact manifest loading, and repeated-prompt drift
  fixtures without applying prompt, policy, memory, eval, or code changes.
- Added `artifacts/artifact-manifest.v1.json`,
  `artifacts/memory/runtime-memory.v1.json`, and
  `artifacts/evals/drift/self-evolution-drift-v1.json`. Trace artifact versions
  now load from the manifest, and runtime memory is explicitly versioned as a
  reviewed closed-by-default policy.
- Tightened redaction so status fields such as `passed` are not mistaken for
  password fields while `DB_USER_PASS`, wallet password, token, API key, and
  private-key shaped fields remain redacted.
- Reflected expert review feedback on the self-evolution gate. Acceptance now
  also requires approved candidate provenance, reviewer identity and timestamp
  for approved reviews, frozen evals from `artifacts/evals/golden` with
  manifest artifact versions matching candidate current versions, rollback
  artifact type and version alignment, and finer drift signatures that include
  query-plan details and result-explanation hashes.
- Reflected follow-up review feedback by rejecting synthetic eval and drift
  results at the self-evolution gate. Eval results must include the manifest
  `golden_fixture` version and every frozen case id; drift results must include
  the configured drift fixture id, path, SHA-256 hash, and every drift case id.

## 2026-05-19

- Renamed the GitHub repository to `hiwylee/AgentFromScratch`, updated the
  local `origin` URL and temporary git metadata directory, and corrected
  visible project title/link references.

## 2026-05-20

- Added optional OpenAI Responses API action planning for `agent ask` through
  `--model-provider openai` or `AGENT_MODEL_PROVIDER=openai`. Mock mode remains
  the default, and the live model can choose only locally allowed action kinds.
- Added `oci` as a separate OpenAI-compatible Responses API provider for
  `agent ask`, using `OCI_BASE_URL`, `OCI_API_KEY` / `OCI_API_KEY_2`, and
  `OCI_MODEL=xai.grok-4-1-fast-non-reasoning`.
- OCI live smoke reached the configured endpoint with `OCI_PROJECT_OCID` mapped
  to the `OpenAI-Project` header, but both configured OCI API keys returned
  `404 Authorization failed or requested resource not found`.
- Reflected Oracle's OCI Generative AI OpenAI-compatible API docs by retaining
  `/openai/v1` as the documented base path and adding an API-key fallback to
  `/20231130/actions/v1/responses` after OCI 404 responses. OCI live smoke now
  succeeds and returns a locally validated `final_answer` action through the
  `oci` provider.
- Added `docs/runbooks/oci-responses-api.md` with OCI Responses API setup,
  `.env` variables, smoke commands, endpoint fallback behavior, and common
  failure diagnostics.
- Added OpenAI model environment documentation in `.env.example` and `README`,
  kept API keys out of request payload traces, and added tests for provider
  configuration, action validation, and Responses API output parsing.
- Corrected the Python project package name to `agent-from-scratch` and
  refreshed `uv.lock`.
- Pinned Python to 3.13 and added `pytest` as a dev dependency.
- Normalized remaining documentation, runbook, tracking, and self-evolution
  validation command references to `uv run --python 3.13`.
- Added mandatory startup repository freshness checks to `AGENTS.md` and
  `CLAUDE.md`: fetch remote refs when possible, compare local and upstream
  commits, inspect local working-tree changes, and do not discard local work
  without explicit user instruction.
- Wired `query_plan` into `AgentLoop`: after `inspect_schema` tool succeeds,
  `_build_query_plan` is called and the result is attached to `AgentResult`;
  `_final_answer` returns the proposed SQL when `query_plan.status == "planned"`.
- Fixed intent classifier to recognize English metric+dimension/time patterns
  ("show last month revenue by product") by also matching against
  `METRIC_KEYWORDS` and `DIMENSION_KEYWORDS` values, not just `DB_KEYWORDS`.
- Added Korean query support: `_english_terms_from_intent` extracts English
  synonyms from intent entities and passes them as `request_terms` to the schema
  retriever. Multi-word time terms ("previous month") are split so "month" matches
  `_has_month_term`. Both `inspect_schema` and `ask_clarification` actions now
  trigger query plan generation.
- Updated golden eval fixtures for `korean_database_trend` and
  `sh_revenue_product_month_schema_context` to expect SQL output instead of
  clarification-only responses. 183 tests pass.
- Expanded Korean keyword coverage in `intent.py`:
  - `DIMENSION_KEYWORDS["product"]`: added `"카테고리"`, `"category"`
  - `TIME_RANGE_KEYWORDS`: added `current_month` entry (`"이번달"`, `"금월"`,
    `"this month"`, `"current month"`)
- Added trend-implied month injection in `_english_terms_from_intent`: when
  `task_type` is `trend_analysis` or `comparison` and no time range is specified,
  `"month"` and `"monthly"` are injected so pattern matching succeeds for
  queries like "추이 분석해줘".
- Added `CLAUDE.md` with project guidance and added `.omc/` to `.gitignore`.
- Added daily (일별) query patterns to `query_plan.py`: revenue by product/day,
  revenue by channel/day, and revenue by promotion(category/subcategory)/day.
  Day grouping uses `TIMES.TIME_ID`. Added `_has_day_term()` helper and updated
  `_select_query_pattern` to prefer daily over monthly when "day"/"daily"/"일별"
  is detected. Supported pattern matrix is now 4 dimensions × 2 time grains.
- Added `bin/agent operator propose-improvement`, an operator-only path for
  recording self-evolution improvement candidates as versioned JSON artifacts
  under `artifacts/improvement-candidates/` by default. The command records an
  audit event and leaves the candidate in `proposed` / review-pending state; it
  does not run acceptance gates or apply behavior changes.
- Moved the stale bootstrap execution plan from
  `docs/exec-plans/active/0001-project-bootstrap.md` to
  `docs/exec-plans/completed/0001-project-bootstrap.md` and marked its outcome
  complete.
- Reflected whole-code review and expert feedback across the operator and
  self-evolution safety boundary: ADW query/smoke durable audit records omit
  arbitrary response rows, SQL file/stdin inputs are byte-bounded before decode,
  SQLcl process cleanup keeps a captured process-group id for child cleanup,
  wallet/DSN/TNS/connection-string redaction is stricter while status booleans
  remain readable, non-finite candidate confidence values are rejected, and
  behavior-shaping candidate type checks cannot be hidden behind docs-only
  candidates.
- Switched the documented verification path to pytest from the repository root
  and added `pyproject.toml` pytest pythonpath configuration. Latest checks
  passed: focused pytest 96 tests / 84 subtests, full pytest 207 tests / 103
  subtests, root `uv run pytest -q`, compileall, and `git diff --check`.
- Completed final security/code, QA, and PM reviews for this hardening pass.
  The reviews found no blocking code issues; PM verdict was conditional ship
  after updating tracking and handoff documentation.

## 2026-05-24

- Implemented the general-purpose agent design (P1–P10) on branch
  `claude/general`. All work merged into `main` via PR #1.

### P1–P7 — General Agent Foundation

- Added `agent_runtime.planner`: `PlanStep` and `ExecutionPlan` with Kahn
  topological sort. Plan steps carry `required_capabilities`, `depends_on`,
  `success_criteria`, `retry_policy`, `risk_level`, `requires_approval`, and
  `fallback_strategy`.
- Added `agent_runtime.executor`: `StepExecutor` with `run_plan_shadow()` for
  plan artifact capture without execution side effects.
- Added `agent_runtime.verifier`: `ToolResultVerifier` and `FailureReason`
  taxonomy (`missing_context`, `ambiguous_request`, `tool_error`,
  `policy_denied`, `data_mismatch`, `timeout`, `external_unavailable`,
  `budget_exceeded`, `unsafe_side_effect`, `schema_or_contract_mismatch`).
- Added `agent_runtime.session`: `SessionContext`, `BudgetTracker`, and
  `ConversationSlot`. Session state persists to `{run_dir}/{session_id}/`
  as `messages.jsonl` + `state.json` (permissions `0o600`).
- Added `agent_runtime.hooks`: `HookRegistry` with per-handler redact()
  enforcement and per-handler exception isolation.
- Added `agent_runtime.skills`: `SkillRegistry` and `default_skill_registry()`
  composition.
- Extended `ToolSpec` with `capabilities` list and `cost_estimate`; registered
  `mock_data_query` as a second wired tool. `ToolRunner` events now fire
  `tool_started` / `tool_completed` through `HookRegistry`.
- Added `artifacts/schemas/plan.schema.v1.json` and
  `artifacts/schemas/session-context.schema.v1.json`.

### P8 — Real Plan Execution

- Extended `StepExecutor` with `run_plan()`: real tool calls in topological
  groups with `approval_callback` gate for `requires_approval=True` steps.
  Fallback strategies `retry`, `skip`, `abort`, `clarify`, and
  `use_alternative` are wired to `FailureReason` outcomes.
- Added `AgentLoop(use_plan_execution=False)` flag and
  `AgentResult.plan_execution` field. Shadow mode records `plan_shadow` in
  trace without changing execution flow.

### P9 — Reflection Loop

- Added `agent_runtime.self_evaluator`: `SelfEvaluator` runs five deterministic
  answer-quality checks (non-empty, no error prefix, no refusal-only, lexical
  overlap informational, length ≥ 20 chars) and returns `EvalResult` with
  `passed`, `score`, `issues`, and `suggestions`.
- Added `agent_runtime.session_summarizer`: `SessionSummarizer` scans run
  results for failed verifications, groups by `failure_reason`, and writes one
  `MemoryRecord` per distinct reason. Records always use `status="proposed"` and
  `review_status="pending"` — never auto-applied.

### P10 — Agentic Engineering Wiring

- Wired `SelfEvaluator` into `AgentLoop.run()` after `_final_answer()`. Result
  stored in `AgentResult.eval_result`; `answer_evaluated` hook fires with
  `passed`, `score`, and `issues`.
- Added `AgentLoop.summarize_session()` so the CLI can call `SessionSummarizer`
  after a run and report proposed memory paths.
- Added `SessionContext.recent_history(n=20)` for LLM context windowing; avoids
  context explosion in multi-turn sessions.
- Added `--memory-dir` CLI flag to `agent ask`; loads approved memories into
  `AgentLoop` and writes proposed memories from `summarize_session()`.
- Codex adversarial review + independent security, code, and QA reviews passed.
  Full test suite: 450 tests / 109 subtests passed.
- PR #1 (`claude/general` → `main`) opened and merged.

### Agentic Engineering 12-principle coverage after P10

- Covered: Goal-driven, Planning, Tool Use, Infinite Loop Prevention,
  Tool Reliability, Observability.
- Partially covered: Memory (windowing added; compression is P11+), Reflection
  (structural checks only; LLM critique is P11+).
- Partially covered: Human Gate (approval_callback exists; real interrupt is
  P11), Evaluation (offline golden evals only).
- Not yet covered: Context compression/retrieval (P11+).

### P11 — Human Gate, Context Compression, LLM Self-Evaluation (2026-05-24)

- Added `make_cli_approval_callback(timeout_seconds=30.0)` to `executor.py`.
  Returns a callback that prompts stdin with step info (id, description,
  risk level, capabilities) and waits up to 30 s for y/n. Non-interactive
  stdin returns False immediately (abort-safe default). Uses
  `concurrent.futures.ThreadPoolExecutor` for the timeout.
- Added `SessionContext.compress_history(threshold=40)` to `session.py`.
  Summarizes turns older than the recent window into a proposed `MemoryRecord`
  (status="proposed", review_status="pending"). Applies `redact()` to summary
  text, uses timestamp-suffixed `memory_id`, guards `window=0`. Never
  auto-applies compressed memories.
- Wired `session_ctx` into `AgentLoop.__init__` and `run()`. Each user
  message is added to the session; `recent_history(n=20)` is injected into
  model context (with `redact()`); `compress_history()` is called after each
  run (returns [] when under threshold — no redundant outer guard needed).
- Added optional `llm_critic: Callable[[str, str], str] | None` to
  `SelfEvaluator`. Runs after 5 structural checks; false-positive bare
  `"issue"` substring removed from detection markers; `SecretLeakError`
  re-raised (project invariant); other exceptions degrade gracefully.
- Security review fixes: `SecretLeakError` explicitly re-raised in LLM
  critique except block; `redact()` applied to history injection and
  compress_history summary.
- Added 28 new tests across `test_executor_approval.py`,
  `test_context_compression.py`, and `test_self_evaluator_llm.py`.
  Full suite: 478 tests / 109 subtests passed.

### Agentic Engineering 12-principle coverage after P11

All 12 principles now have at least partial coverage:
- Fully covered: Goal-driven, Planning, Tool Use, Infinite Loop Prevention,
  Tool Reliability, Observability.
- Covered: Memory (windowing + compression), Reflection (structural + optional
  LLM critique), Human Gate (CLI interrupt), Evaluation (offline golden evals).
- Deferred: Context compression to LLM-driven summary (future).

### M7 Hardening — JSON Schemas, Content Hash, Review CLI (2026-05-24)

Secondary Milestone 7 hardening wave completed on branch `claude/general`:

- Added 4 JSON Schema files (`improvement-candidate.schema.v1.json`,
  `memory-record.schema.v1.json`, `rollback-plan.schema.v1.json`,
  `gate-report.schema.v1.json`) with `additionalProperties: false` at every
  level; all property names match the Python dataclass `to_dict()` output.
- Added `ImprovementCandidateRecord.content_hash` — SHA-256 over a compact
  canonical JSON of stable fields (candidate_id, candidate_type, summary,
  proposed_change, affected_artifacts, trigger_type). Auto-computed in
  `build_improvement_candidate()`; verified via `verify_candidate_hash()`.
  Canonical field key `"artifact_path"` intentionally differs from the
  serialized `"path"` key — do not change without re-hashing all candidates.
- Added `operator review-candidate` CLI (list / show / approve / reject):
  - `review.decision != "pending"` guard prevents double-approve or
    double-reject (the correct check — `status` stays "proposed" after a review).
  - Non-empty `--reviewer` enforced before any write.
  - `_find_candidate_path()` validates candidate_id via
    `re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", ...)` — path traversal
    rejected before file lookup.
  - All print and audit output passes through `redact()`.
- Security fixes from expert review:
  - `SecretLeakError` re-raised in drift check (was silently caught).
  - `utc_now` moved to module-level import.
  - Path traversal validation added to `_find_candidate_path()`.
- Added 9 tests: hash round-trip, guard enforcement, path traversal rejection,
  double-approve / double-reject guard, audit path wiring.
- Full suite: **493 tests passed**.
