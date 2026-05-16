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
