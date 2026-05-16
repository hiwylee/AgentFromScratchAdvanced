# Current State

## Purpose

This file is the first resume point after an interrupted session. Keep it short
and current.

## Current Focus

Bootstrap the project harness for an agent runtime built from scratch, with
Oracle ADW natural-language data access as the first domain specialization.

## Last Completed Work

- Created the private GitHub repository `hiwylee/AgentFromScrach`.
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
- Started Milestone 1 implementation as a uv-managed Python 3.12+ prototype:
  `agent ask <text>` now emits structured intent, monitorable run status,
  event output, and append-only audit records.
- Added workflow orchestration architecture for natural-language business
  requests that span A/B/C/D systems, reconciliation, enrichment, target-system
  loading, and human-in-the-loop review.
- Added first-pass workflow intent recognition for requests like
  `이번달 특허자산 대체 등록 진행해줘`, returning `workflow_execution` and
  `select_workflow_template` as the next action.

## Next Action

Milestone 1 runtime controls are now in place: stop conditions, timeout checks,
cancellation token support, budget placeholders, message/action/observation
types, mock model adapter boundary, and monitorable run status.

Next implementation focus: prepare Milestone 2A workflow orchestration skeleton
with mock connectors and human-gate state, while keeping Milestone 2 tool
registry design aligned.

Recommended starting point:

- uv-managed Python 3.12+ prototype first, with Rust hardening later if needed.
- Mock-model-first agent loop and deterministic intent heuristics for the
  initial slice.
- Prompt, policy, memory, and eval artifacts stored as data files.
- Append-only audit events from the first executable milestone.
- `agent ask <text>` should first prove structured intent analysis and next
  action selection.
- Oracle ADW connector design kept behind an interface until the core loop is
  testable.

## Last Verification

```bash
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest discover -s tests
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --run-dir /tmp/afs-runs-1 --audit-log /tmp/afs-audit-1.jsonl
bin/agent ask "고객 테이블에서 오래된 데이터를 삭제해줘" --run-dir /tmp/afs-runs-2 --audit-log /tmp/afs-audit-2.jsonl
bin/agent ask "이번달 특허자산 대체 등록 진행해줘" --run-dir /tmp/afs-workflow-intent2 --audit-log /tmp/afs-workflow-intent2.jsonl
bin/agent status --run-dir /tmp/afs-runs-1
bin/agent status --run-dir /tmp/afs-runs-2
bin/agent status --run-dir /tmp/afs-workflow-intent2
```

The latest full test run covered 13 tests and passed.

## Open Questions

- Should the first implementation be Rust-only, or Rust core plus a TypeScript
  or Python helper layer? Decided: Python 3.12+ prototype first through `uv`.
- Should Oracle ADW execution use SQLcl subprocesses first or a direct Oracle
  driver?
- Which read-only schema introspection queries are safe enough for the first
  connector milestone?
- Which schema retrieval strategy should be used first for compact Oracle ADW
  context?
- Which eval fixture format should become the frozen golden set?
- Which artifact format should be used first for intent schemas and mock model
  fixtures? Initial decision: JSON schemas and Markdown prompts.
- Which workflow template format and review packet format should be used first?

## Resume Checklist

- Read `AGENTS.md`.
- Read this file.
- Read `docs/tracking/todo.md`.
- Check local git state with:

```bash
git --git-dir=/tmp/AgentFromScrach.git --work-tree=/home/opc/work/AgentFromScrach status
```

The workspace currently uses `/tmp/AgentFromScrach.git` as the git metadata
directory because `.git` in the worktree is a read-only mount.
