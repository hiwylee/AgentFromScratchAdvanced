# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run a user request
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --run-dir /tmp/afs-runs --audit-log /tmp/afs.jsonl

# Check latest run status
bin/agent status --run-dir /tmp/afs-runs

# Run a workflow request
bin/agent workflow "이번달 특허자산 대체 등록 진행해줘" --run-dir /tmp/afs-wf --audit-log /tmp/afs-wf.jsonl

# Run all tests
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest discover -s tests

# Run a single test module
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest tests.test_tools

# Operator-only live ADW commands (require explicit --confirm-* flag)
bin/agent operator adw-smoke --confirm-live-adw-smoke
bin/agent operator adw-query --sql "select count(*) from sales" --confirm-live-adw-query
bin/agent operator adw-provision-working-user --grant-profile prototype-any-table-read --confirm-live-adw-admin-provision
```

## Resume

Start every session by checking repository freshness before editing:

```bash
git fetch --prune origin
git status --short --branch
git log --oneline @{u}..HEAD
git log --oneline HEAD..@{u}
```

If `git fetch` cannot reach the repo server, state that the remote freshness
check is blocked and use `git status --short --branch` as the local baseline.
Do not reset, overwrite, or discard local changes unless the user explicitly
requests it.

Then read:
1. `docs/tracking/current-state.md`
2. `docs/tracking/todo.md`
3. `docs/tracking/change-log.md`

## Architecture

The runtime is an intent-first agent loop with optional multi-step plan execution: **user text → intent → model action → tool call (optional) → observation → final answer**. The `claude/general` branch adds capability-tagged planning, real tool execution, reflection, and session-scoped context (P1–P10).

```
agent_runtime/
  types.py               # Core dataclasses: Message, Action, Observation, FinalAnswer, Budget, CancellationToken
  intent.py              # Deterministic heuristic intent classifier → ActionKind
  model.py               # MockModel + OpenAI/OCI Responses API adapters
  loop.py                # AgentLoop: orchestrates the full loop; optional plan execution + SelfEvaluator wiring
  tools.py               # ToolRegistry, ToolRunner, ToolSpec — mock_schema_context + mock_data_query wired
  planner.py             # PlanStep + ExecutionPlan with Kahn topological sort; capability-tagged steps
  executor.py            # StepExecutor: run_plan() with retry/skip/abort/clarify; approval_callback gate
  verifier.py            # ToolResultVerifier: FailureReason taxonomy, suggested_action
  session.py             # SessionContext, BudgetTracker, ConversationSlot; recent_history(n=20)
  hooks.py               # HookRegistry: per-event handlers with redact() enforcement
  skills.py              # SkillRegistry: composable skill lookup
  self_evaluator.py      # SelfEvaluator: 5-check deterministic answer quality → EvalResult
  session_summarizer.py  # SessionSummarizer: failure-pattern extraction → proposed MemoryRecord (never auto-applied)
  workflow.py            # WorkflowEngine: mock multi-system patent workflow (A/B/C/D connectors)
  schema_context.py      # Artifact-first lexical schema retriever for Oracle SH tables
  query_plan.py          # Deterministic query-plan builder for supported SH revenue patterns
  result_explanation.py  # Fake result explanations using FakeSqlExecutionAdapter
  sql_execution.py       # Backend-neutral adapter boundary; SqlclReadOnlyAdapter closed by default
  sqlcl_runner.py        # SQLcl subprocess boundary: stdin-only credentials, stream-capped output
  oracle_adw.py          # Config loading, SQL policy validation, SQLcl/wallet verification
  self_evolution.py      # Gate-only self-evolution boundary — no automatic modifications allowed
  audit.py               # Append-only JSONL audit records (all secrets redacted)
  monitor.py             # Per-run status and event files under run_root/
  redaction.py           # Strips secrets from any dict/str before output or audit
  trace.py               # Versioned trace event normalization
  eval_runner.py         # Golden fixture eval runner for regression checks
  cli.py                 # argparse entrypoint: ask / status / workflow / operator subcommands
```

**Artifacts** under `artifacts/` are versioned data files (JSON schemas, prompts, eval fixtures, schema metadata). The artifact manifest at `artifacts/artifact-manifest.v1.json` is the single rollback source for prompt/policy/memory/eval versions.

**Design docs** at `docs/design-docs/` explain every major tradeoff. **Exec plans** at `docs/exec-plans/active/` are the current implementation roadmap.

## Key Invariants

- `.env`, Oracle wallet files, passwords, and API keys must never be committed or printed.
- All output and audit records must pass through `redact()` before being written.
- `SqlclReadOnlyAdapter` requires `allow_real_execution=True` to run live SQL; it is closed by default.
- Operator ADW commands (`adw-smoke`, `adw-query`, `adw-provision-working-user`) require an explicit `--confirm-*` flag and are never registered as agent tools.
- SQL execution is validated through `validate_read_only_sql()` before any SQLcl subprocess call.
- The self-evolution gate (`self_evolution.py`) never applies changes automatically.
- Golden eval fixtures live in `artifacts/evals/golden/` and must not be hand-edited without updating the artifact manifest.
- The current working DB user is `AIAGENT` (working user); admin credentials use `ADMIN_USER`/`ADMIN_USER_PASS`.
- `SH` is the first sample schema; `SSB` is reserved for later benchmarks.
