# AgentFromScratch

A production-quality agent runtime with a Next.js web UI. Built from scratch with intent-first architecture, capability-tagged planning, human-gate verification, tacit knowledge capture, and Oracle ADW natural-language data access — all with append-only audit, secret redaction, and self-evolution controls closed by default.

**559 tests passing.**

---

## Repository Structure

```
AgentFromScratchAdvanced/
  agent_runtime/     # Python backend — agent loop, tools, workflow, tacit knowledge
  tests/             # Python test suite (559 tests)
  bin/               # CLI entrypoint (bin/agent)
  artifacts/         # Versioned schemas, evals, prompts, policies, verification episodes
  frontend/          # Next.js 14 UI — chat, audit, workflow, schema, memory pages
  docs/              # Design docs, runbooks, tracking
  feat/              # Feature design docs
```

---

## Frontend (Next.js UI)

Dark terminal-aesthetic UI. All API routes spawn `bin/agent` subprocess — no direct Python/DB connection from the browser layer.

### Setup

```bash
cd frontend
cp .env.local.example .env.local   # update AGENT_BIN_PATH and AGENT_PROJECT_DIR
npm install
npm run dev                         # http://localhost:3000
npm run build                       # production build check
```

### Pages

| Page | URL | Description |
|---|---|---|
| Chat | `/` | Natural-language agent queries |
| Status | `/status` | Live run status monitor |
| Audit | `/audit` | Audit log viewer (JSONL table) |
| Workflow | `/workflow` | Patent asset workflow runner + human gate |
| Memory | `/memory` | Memory record viewer |
| Operator | `/operator` | Operator controls |
| Schema | `/schema` | Oracle ADW schema inspector |

### Environment Variables (`frontend/.env.local`)

| Variable | Description |
|---|---|
| `AGENT_BIN_PATH` | Absolute path to `bin/agent` in this repo |
| `AGENT_PROJECT_DIR` | Absolute path to repo root |
| `AGENT_RUN_DIR` | Run-dir for `agent ask` (default `/tmp/afs-runs`) |
| `AGENT_AUDIT_LOG` | Audit log for `agent ask` |
| `AGENT_WORKFLOW_RUN_DIR` | Run-dir for `agent workflow` |
| `AGENT_WORKFLOW_AUDIT_LOG` | Audit log for `agent workflow` |
| `AGENT_MEMORY_DIR` | Path to `artifacts/memory` |

### Frontend Architecture

```
frontend/
  app/
    page.tsx                      # Chat interface — agent ask
    status/page.tsx               # Run status monitor (live polling)
    audit/page.tsx                # Audit log viewer
    workflow/page.tsx             # Workflow runner + human gate approve/reject
    memory/page.tsx               # Memory record viewer
    operator/page.tsx             # Operator controls
    schema/page.tsx               # Oracle ADW schema inspector
    api/agent/
      ask/route.ts                # POST → spawns bin/agent ask
      status/route.ts             # GET  → reads run status JSON
      audit/route.ts              # GET  → reads audit JSONL
      workflow/route.ts           # POST → spawns bin/agent workflow
      workflow/approve/route.ts   # POST → workflow resume with human decision
      memory/route.ts             # GET  → reads artifacts/memory
      operator/route.ts           # POST → operator commands
  components/                     # Sidebar, StatusBadge, shadcn/ui components
  lib/                            # TypeScript utilities (types, auditColors, errors)
```

---

## Backend (Python Agent Runtime)

### Commands

```bash
# Natural-language query (mock mode default)
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --run-dir /tmp/afs-runs --audit-log /tmp/afs.jsonl

# With real ADW query execution (operator flag — enables real Oracle ADW execution via adw_query tool;
# requires .env credentials and SQLcl)
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --allow-real-query --run-dir /tmp/afs-runs --audit-log /tmp/afs.jsonl

# With a live LLM provider
bin/agent ask "채널별 매출 비교해줘" --model-provider openai --run-dir /tmp/afs-runs
bin/agent ask "채널별 매출 비교해줘" --model-provider oci   --run-dir /tmp/afs-runs

# Check latest run status
bin/agent status --run-dir /tmp/afs-runs

# Run a workflow request
bin/agent workflow "이번달 특허자산 대체 등록 진행해줘" --run-dir /tmp/afs-wf --audit-log /tmp/afs-wf.jsonl

# Resume a paused workflow (human-gate decision)
bin/agent workflow resume \
  --run-id <run-id> \
  --decision approve_load \
  --actor "reviewer-name" \
  --reasoning "reconciliation verified manually" \
  --confidence 0.9 \
  --reason "approved" \
  --run-dir /tmp/afs-wf \
  --audit-log /tmp/afs-wf.jsonl

# Tacit knowledge — human verification memory
bin/agent tacit list
bin/agent tacit reflect --episode-id <uuid>
bin/agent tacit heuristics

# Operator-only live ADW commands (require explicit --confirm-* flag)
bin/agent operator adw-smoke --confirm-live-adw-smoke
bin/agent operator adw-query --sql "select count(*) from sales" --confirm-live-adw-query
bin/agent operator adw-provision-working-user --grant-profile prototype-any-table-read --confirm-live-adw-admin-provision
bin/agent operator adw-provision-working-user --grant-profile production-sh-read --confirm-live-adw-admin-provision

# Self-evolution improvement candidates (operator-only, never auto-applied)
bin/agent operator propose-improvement --candidate-id <id> --candidate-type prompt \
  --trigger-type manual --summary "..." --proposed-change "..." \
  --affected-artifact artifacts/prompts/... --source-type manual --source-id reviewer

bin/agent operator review-candidate list --candidates-dir artifacts/improvement-candidates
bin/agent operator review-candidate list --status pending --candidates-dir artifacts/improvement-candidates
bin/agent operator review-candidate approve --candidate-id <id> --reviewer <name>
bin/agent operator review-candidate reject  --candidate-id <id> --reviewer <name> --notes "..."

# Run all tests
UV_CACHE_DIR=.uv-cache uv run --python 3.13 python -m unittest discover -s tests
# or
uv run --python 3.13 python -m pytest -q
```

### Architecture

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
  workflow.py            # WorkflowEngine: patent workflow (A/B/C/D connectors) + human gate
  tacit_knowledge.py     # VerificationEpisode, CorrectionDiff, ReflectionAgent, TacitSignalExtractor
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
  cli.py                 # argparse entrypoint: ask / status / workflow / operator / tacit
```

### Tacit Knowledge Layer

When a human approves or overrides at a workflow gate, the system captures:
- `correction_diff` — semantic diff between AI output and human revision
- `reasoning` — why the human made this decision
- `consultation_trace` — who was consulted and why
- `reason_tags` — classification tags (tone mismatch, policy risk, etc.)

Episodes are stored at `artifacts/verification-episodes/{session_id}.jsonl`. The `ReflectionAgent` analyzes episodes deterministically to extract reusable heuristics and policy proposals.

### Workflow Resume

When a workflow pauses at a human gate (`state: checkpoint_required`), resume with:

```bash
bin/agent workflow resume \
  --run-id <run_id> \
  --decision approve_load \
  --actor reviewer-name \
  --reasoning "reconciliation verified" \
  --confidence 0.9 \
  --reason "approved after review" \
  --run-dir /tmp/afs-wf
```

The checkpoint persists to `{run-dir}/{run-id}/checkpoint.json` and is deleted after resume.

### Live LLM Providers

| Variable | Default | Description |
|---|---|---|
| `AGENT_MODEL_PROVIDER` / `LLM` | `mock` | `mock` \| `openai` \| `oci` |
| `OPENAI_API_KEY` | — | required for openai |
| `OPENAI_MODEL` | `gpt-5.2` | model name |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | endpoint |
| `OCI_BASE_URL` | — | OCI Generative AI endpoint |
| `OCI_API_KEY` / `OCI_API_KEY_2` | — | API key (fallback) |
| `OCI_MODEL` | `xai.grok-4-1-fast-non-reasoning` | model name |

OCI-specific setup: `docs/runbooks/oci-responses-api.md`.

### Oracle ADW

Credentials are read from `.env` (git-ignored). The working DB user is `AIAGENT`. All SQL is validated through `validate_read_only_sql()` before any SQLcl call. See `docs/runbooks/operator-adw.md`.

### Security Invariants

- `.env`, Oracle wallet files, passwords, and API keys must never be committed or printed.
- All output and audit records pass through `redact()` before being written.
- `SqlclReadOnlyAdapter` requires `allow_real_execution=True`; closed by default.
- Operator ADW commands require an explicit `--confirm-*` flag.
- The self-evolution gate never applies changes automatically.
- `SecretLeakError` (from `trace.py`) must never be silenced.
- Episode store failures are best-effort telemetry and must never abort approved workflow resumes.

---

## Repository Map

| Path | Contents |
|---|---|
| `frontend/` | Next.js 14 UI (app router, API routes, components, lib) |
| `agent_runtime/` | Python backend runtime (29 modules) |
| `tests/` | Unit and integration tests (559 passing) |
| `bin/` | CLI entry point (`bin/agent`) |
| `artifacts/schemas/` | JSON Schema files for all artifact types |
| `artifacts/evals/golden/` | Frozen golden eval fixtures (do not hand-edit) |
| `artifacts/verification-episodes/` | Human verification tacit knowledge (JSONL) |
| `artifacts/improvement-candidates/` | Self-evolution candidate records |
| `docs/design-docs/` | Architecture and tradeoff decisions |
| `docs/runbooks/` | Operator runbooks (ADW, OCI) |
| `docs/tracking/` | current-state, todo, decisions, change-log |
| `feat/` | Feature design docs (e.g. `feat/self_evolve.md`) |

---

## Resume Point

Start every session with:

1. `git fetch --prune origin && git status --short --branch`
2. [docs/tracking/current-state.md](docs/tracking/current-state.md)
3. [docs/tracking/todo.md](docs/tracking/todo.md)
4. [docs/tracking/change-log.md](docs/tracking/change-log.md)
