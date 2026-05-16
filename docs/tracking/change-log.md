# Change Log

This is a human-written project change log. It tracks meaningful project
direction and implementation changes, not every tiny edit.

## 2026-05-16

- Created the initial harness structure for building an agent runtime from
  scratch.
- Created a private GitHub repository at `hiwylee/AgentFromScrach`.
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
- Started Milestone 1 with a uv-managed Python 3.12+ prototype. Added `agent ask`,
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
