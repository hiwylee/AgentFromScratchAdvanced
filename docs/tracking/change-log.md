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
