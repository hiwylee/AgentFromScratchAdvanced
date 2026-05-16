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

## Next Action

Milestone 1 runtime controls are now in place: stop conditions, timeout checks,
cancellation token support, budget placeholders, message/action/observation
types, mock model adapter boundary, and monitorable run status.

Next implementation focus: finish Milestone 2 tool loop integration into
`AgentLoop`, wire workflow pause/resume records into the generic trace schema,
and design the remaining Milestone 4 SQLcl execution/provisioning apply path.
Persistent workflow
approval/resume and real target-system writes must remain closed until signed
or hashed checkpoint persistence, approval authorization, idempotency, and
replay protection are designed. Real ADW execution must remain closed until
SQLcl credential passing, timeouts, result limits, and audit redaction are
specified and tested. Real admin provisioning apply must also remain closed
until idempotency checks, compensation behavior, and redacted audit events are
implemented.

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
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest tests.test_oracle_adw
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest tests/test_eval_runner.py
UV_CACHE_DIR=.uv-cache uv run --python 3.12 python -m unittest discover -s tests
bin/agent workflow "이번달 특허자산 대체 등록 진행해줘" --run-dir /tmp/afs-workflow-final2 --audit-log /tmp/afs-workflow-final2.jsonl
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --run-dir /tmp/afs-runs-1 --audit-log /tmp/afs-audit-1.jsonl
bin/agent ask "고객 테이블에서 오래된 데이터를 삭제해줘" --run-dir /tmp/afs-runs-2 --audit-log /tmp/afs-audit-2.jsonl
bin/agent ask "이번달 특허자산 대체 등록 진행해줘" --run-dir /tmp/afs-workflow-intent2 --audit-log /tmp/afs-workflow-intent2.jsonl
bin/agent status --run-dir /tmp/afs-runs-1
bin/agent status --run-dir /tmp/afs-runs-2
bin/agent status --run-dir /tmp/afs-workflow-intent2
```

The latest full test run covered 67 tests and passed. The latest focused
Oracle ADW test run covered 19 tests and passed. The latest workflow smoke returned
`checkpoint_required` and blocked target-system D loading.

## Open Questions

- Should the first implementation be Rust-only, or Rust core plus a TypeScript
  or Python helper layer? Decided: Python 3.12+ prototype first through `uv`.
- Should Oracle ADW execution use SQLcl subprocesses first or a direct Oracle
  driver?
- Which read-only schema introspection queries are safe enough for the first
  connector milestone? Initial constants now cover tables, columns, and comments
  through Oracle data dictionary views.
- Which schema retrieval strategy should be used first for compact Oracle ADW
  context?
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
- For Oracle ADW work, open `agent_runtime/oracle_adw.py` and
  `tests/test_oracle_adw.py` first.
- Check local git state with:

```bash
git --git-dir=/tmp/AgentFromScrach.git --work-tree=/home/opc/work/AgentFromScrach status
```

The workspace currently uses `/tmp/AgentFromScrach.git` as the git metadata
directory because `.git` in the worktree is a read-only mount.
