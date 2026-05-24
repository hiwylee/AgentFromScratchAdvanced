# AgentFromScratch

A production-quality agent runtime built from scratch: intent-first architecture,
capability-tagged planning, multi-step tool execution, session context, self-evaluation,
and Oracle ADW natural-language data access — all with append-only audit, secret
redaction, and self-evolution controls closed by default.

Branch: **`claude/general`** — 493 tests passing.

## What This Is

The project builds an agent loop incrementally, applying harness engineering
(observability, eval fixtures, security gates) from the first commit. The first
domain specialization is natural-language access to Oracle Autonomous Data
Warehouse: schema-aware query planning, safe SQL generation, result explanation,
and frozen golden eval coverage.

The general-purpose agent layer (P1–P11) adds capability-tagged planning,
real tool execution with retry/fallback, session-scoped context, LLM
self-evaluation, and a human-gate approval callback.

## Architecture

```
agent_runtime/
  types.py               # Core dataclasses: Message, Action, Observation, FinalAnswer, Budget
  intent.py              # Deterministic heuristic intent classifier → ActionKind
  model.py               # MockModel + OpenAI/OCI Responses API adapters
  loop.py                # AgentLoop: intent → plan → tool → eval → answer
  tools.py               # ToolRegistry, ToolRunner, ToolSpec
  planner.py             # PlanStep + ExecutionPlan with topological sort
  executor.py            # StepExecutor: run_plan() with retry/skip/abort/clarify
  verifier.py            # ToolResultVerifier: FailureReason taxonomy
  session.py             # SessionContext, BudgetTracker, ConversationSlot
  hooks.py               # HookRegistry: per-event handlers with redact() enforcement
  skills.py              # SkillRegistry: composable skill lookup
  self_evaluator.py      # SelfEvaluator: 5-check answer quality + optional LLM critique
  session_summarizer.py  # SessionSummarizer: failure-pattern extraction → proposed MemoryRecord
  workflow.py            # WorkflowEngine: mock multi-system patent workflow (A/B/C/D)
  schema_context.py      # Artifact-first lexical schema retriever for Oracle SH tables
  query_plan.py          # Deterministic query-plan builder for SH revenue patterns
  result_explanation.py  # Fake result explanations using FakeSqlExecutionAdapter
  sql_execution.py       # Backend-neutral adapter boundary; real execution closed by default
  sqlcl_runner.py        # SQLcl subprocess boundary: stdin-only credentials, stream caps
  oracle_adw.py          # Config loading, SQL policy, SQLcl/wallet verification
  self_evolution.py      # Gate-only self-evolution boundary — no automatic modifications
  audit.py               # Append-only JSONL audit records (all secrets redacted)
  monitor.py             # Per-run status and event files
  redaction.py           # Strips secrets from any dict/str before output or audit
  trace.py               # Versioned trace event normalization
  eval_runner.py         # Golden fixture eval runner for regression checks
  cli.py                 # argparse entrypoint: ask / status / workflow / operator
```

**Artifacts** under `artifacts/` are versioned data files (JSON schemas, prompts,
eval fixtures, schema metadata). The artifact manifest at
`artifacts/artifact-manifest.v1.json` is the single rollback source for all
prompt/policy/memory/eval versions.

## Commands

```bash
# Natural-language query (mock mode default)
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --run-dir /tmp/afs-runs --audit-log /tmp/afs.jsonl

# With a live LLM provider
bin/agent ask "채널별 매출 비교해줘" --model-provider openai --run-dir /tmp/afs-runs
bin/agent ask "채널별 매출 비교해줘" --model-provider oci   --run-dir /tmp/afs-runs

# Check latest run status
bin/agent status --run-dir /tmp/afs-runs

# Run a workflow request
bin/agent workflow "이번달 특허자산 대체 등록 진행해줘" --run-dir /tmp/afs-wf --audit-log /tmp/afs-wf.jsonl

# Resume a paused workflow (human-gate decision)
bin/agent workflow resume \
  --run-id <run-id-from-paused-run> \
  --decision approve_load \
  --actor "reviewer-name" \
  --reason "reconciliation verified" \
  --run-dir /tmp/afs-wf \
  --audit-log /tmp/afs-wf.jsonl

# Operator-only live ADW commands (require explicit --confirm-* flag)
bin/agent operator adw-smoke --confirm-live-adw-smoke
bin/agent operator adw-query --sql "select count(*) from sales" --confirm-live-adw-query
bin/agent operator adw-provision-working-user --grant-profile prototype-any-table-read --confirm-live-adw-admin-provision

# Self-evolution improvement candidates (operator-only, never auto-applied)
bin/agent operator propose-improvement --candidate-id <id> --candidate-type prompt \
  --trigger-type manual --summary "..." --proposed-change "..." \
  --affected-artifact artifacts/prompts/... --source-type manual --source-id reviewer

bin/agent operator review-candidate list --candidates-dir artifacts/improvement-candidates
bin/agent operator review-candidate show   --candidate-id <id>
bin/agent operator review-candidate approve --candidate-id <id> --reviewer <name>
bin/agent operator review-candidate reject  --candidate-id <id> --reviewer <name> --notes "..."

# Run all tests
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest discover -s tests
# or
uv run --python 3.13 python -m pytest -q
```

## Workflow Resume

When a workflow pauses at a human gate (`state: checkpoint_required`), the
run-id is printed in the result JSON. Operators resume it with:

```bash
bin/agent workflow resume \
  --run-id <run_id> \
  --decision approve_load          # or reject_workflow / request_manual_correction
  --actor reviewer-name \
  --reason "approved after review" \
  --run-dir /tmp/afs-wf
```

The checkpoint (identity + hash + record ids) is persisted to
`{run-dir}/{run-id}/checkpoint.json` and loaded automatically on resume.
The checkpoint file is deleted after resume (approved or rejected).

## Live LLM Providers

The default action model is deterministic mock mode. Route through an
OpenAI-compatible Responses API provider with `--model-provider`:

```bash
# OpenAI
bin/agent ask "..." --model-provider openai
# OCI Generative AI
bin/agent ask "..." --model-provider oci
```

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `AGENT_MODEL_PROVIDER` / `LLM` | `mock` | `mock` \| `openai` \| `oci` |
| `OPENAI_API_KEY` | — | required for openai |
| `OPENAI_MODEL` | `gpt-5.2` | model name |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | endpoint |
| `OPENAI_TIMEOUT_SECONDS` | `30` | request timeout |
| `OCI_BASE_URL` | — | OCI Generative AI endpoint |
| `OCI_API_KEY` / `OCI_API_KEY_2` | — | API key (fallback) |
| `OCI_MODEL` | `xai.grok-4-1-fast-non-reasoning` | model name |
| `OCI_TIMEOUT_SECONDS` | `30` | request timeout |

Live LLM planning does not enable live Oracle ADW execution or workflow writes.
OCI-specific setup: `docs/runbooks/oci-responses-api.md`.

## Oracle ADW

Local Oracle ADW credentials are read from `.env` (git-ignored). Passwords,
wallet files, wallet passwords, API keys, and secret-bearing connection strings
must never be printed or committed.

SQLcl is expected at:
```
/home/opc/.local/share/sqlcl/sqlcl/bin/sql
```

The working DB user is `AIAGENT`. Admin commands use `ADMIN_USER`/`ADMIN_USER_PASS`.
All SQL is validated through `validate_read_only_sql()` before any SQLcl call.
See `docs/runbooks/operator-adw.md` for preflight, provisioning, and rollback.

## Security Invariants

- `.env`, Oracle wallet files, passwords, and API keys must never be committed or printed.
- All output and audit records pass through `redact()` before being written.
- `SqlclReadOnlyAdapter` requires `allow_real_execution=True`; closed by default.
- Operator ADW commands require an explicit `--confirm-*` flag.
- SQL execution is validated through `validate_read_only_sql()` before any SQLcl call.
- The self-evolution gate never applies changes automatically.
- `SecretLeakError` (from `trace.py`) must never be silenced.
- Improvement candidates are `proposed` / `review_status=pending` until an operator
  explicitly approves via `review-candidate approve`.

## Repository Map

| Path | Contents |
|---|---|
| `AGENTS.md` | Root harness instructions and session-start checklist |
| `CLAUDE.md` | Claude Code project guidance and key invariants |
| `agent_runtime/` | All runtime modules (28 files) |
| `artifacts/` | Versioned data files: schemas, prompts, evals, schema metadata |
| `artifacts/schemas/` | JSON Schema files for all major artifact types |
| `artifacts/evals/golden/` | Frozen golden eval fixtures (do not hand-edit) |
| `artifacts/improvement-candidates/` | Proposed self-evolution candidate records |
| `bin/` | CLI entry points |
| `docs/design-docs/` | Architecture and tradeoff decisions |
| `docs/exec-plans/active/` | Current implementation plans |
| `docs/exec-plans/completed/` | Completed plans and outcomes |
| `docs/runbooks/` | Operator runbooks (ADW, OCI) |
| `docs/tracking/` | current-state, todo, decisions, change-log |
| `tests/` | Unit and integration tests (493 passing) |

## Resume Point

Start every session with:

1. `git fetch --prune origin && git status --short --branch`
2. [docs/tracking/current-state.md](docs/tracking/current-state.md)
3. [docs/tracking/todo.md](docs/tracking/todo.md)
4. [docs/tracking/change-log.md](docs/tracking/change-log.md)
