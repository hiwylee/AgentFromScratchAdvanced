# Decisions

Record durable decisions here. Keep entries short and include rationale.

## 2026-05-16: Use Harness Documents As The Project Memory

Decision: Keep stable instructions in `AGENTS.md`, evolving plans in
`docs/exec-plans/`, and session continuity in `docs/tracking/`.

Rationale: The project is being built through iterative agent sessions, so the
next session needs a reliable resume point that does not depend on chat history.

## 2026-05-16: Oracle ADW Is The First Database Target

Decision: Specialize the first database workflow for Oracle Autonomous Data
Warehouse.

Rationale: The target credentials and wallet configuration already exist in
local environment variables, and the project goal includes natural-language
processing over database data.

## 2026-05-16: Secrets Stay In Environment Variables

Decision: Passwords, wallet passwords, API keys, wallet files, and
secret-bearing connection strings must not be printed, committed, or stored in
agent state.

Rationale: Oracle ADW workflows require real credentials. The harness must make
secret handling a default constraint before code exists.
