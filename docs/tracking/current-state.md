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
  `agent ask <text>` now emits structured intent, trace output, and append-only
  audit records.

## Next Action

Continue Milestone 1 by turning the prototype into a fuller agent loop:
message/action/observation types, a mock model adapter boundary, stop
conditions, cancellation/timeouts, and budget placeholders.

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
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --trace-dir /tmp/afs-traces-312 --audit-log /tmp/afs-audit-312.jsonl
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m agent_runtime ask "고객 테이블에서 오래된 데이터를 삭제해줘" --trace-dir /tmp/afs-traces-block --audit-log /tmp/afs-audit-block.jsonl
```

All commands passed.

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
