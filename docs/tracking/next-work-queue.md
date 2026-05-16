# Next Work Queue

This file is the durable handoff queue for the next implementation wave. Read
it after `docs/tracking/current-state.md` and before starting new work.

## Execution Rules

- Use uv-managed Python 3.12+ for all local verification.
- Keep `.env`, wallet files, passwords, and rendered credential strings out of
  logs, tests, docs, commits, and worker messages.
- Run parallel workers only on disjoint write scopes.
- Keep real ADW execution, real admin provisioning apply, and real
  target-system writes closed until the listed safety gates pass.
- Before commit, get a senior-review pass and run focused plus full tests.

## Active Parallel Wave: 2026-05-16

### Worker A: Tool Loop Integration

Status: ready for background worker.

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

Status: ready for background worker.

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

Status: ready for background worker.

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

Status: ready for background worker.

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

## Recommended Start Order

1. Worker A and Worker D can run immediately in parallel.
2. Worker B can run in parallel if it limits changes to trace/workflow files.
3. Worker C should start as design/tests first; real execution stays closed.
4. Integrate worker outputs in this order: D, A, B, C.

## Verification Commands

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest tests.test_tools tests.test_runtime_controls
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest tests.test_workflow_engine tests.test_eval_runner
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest tests.test_oracle_adw
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest discover -s tests
```
