# 2026-05-17 SQLcl Runner Adapter Review

Reviewer: Worker H

Scope: `agent_runtime/sqlcl_runner.py`, `agent_runtime/sql_execution.py`, and
Oracle ADW SQLcl/read-only policy helpers in `agent_runtime/oracle_adw.py`.

## Gate Decision

Block live ADW smoke for now. Real ADW execution remains closed unless an
explicit operator path constructs `SqlclReadOnlyAdapter` with
`allow_real_execution=True`; the normal runtime path must continue to return
`real_execution_closed`.

## Findings

### Resolved High: Enabled SQLcl adapter path raised before returning a structured response

`SqlclReadOnlyAdapter.execute()` classifies the runner result and builds
`runner_metadata`, then calls `_response_from_sqlcl_outcome(...)` without the
required `runner_metadata` argument. This affects every
`allow_real_execution=True` path after the runner returns or after the adapter
catches `TimeoutExpired`/`OSError`, so the operator path can raise `TypeError`
instead of returning the intended redacted `SqlExecutionResponse`.

Evidence:

- `agent_runtime/sql_execution.py:211-238` creates `runner_metadata` but does
  not pass it to `_response_from_sqlcl_outcome`.
- `agent_runtime/sql_execution.py:323-330` requires `runner_metadata`.
- Existing tests in `tests/test_sql_execution.py:115-216` appear intended to
  cover enabled success/failure/timeout paths, but this branch needs to be run
  and fixed before any live smoke.

Recommendation: pass the redacted runner metadata into
`_response_from_sqlcl_outcome`, then run the SQL execution and SQLcl runner
test modules before considering a live smoke.

Resolution: fixed in the current workspace. The adapter now passes
`runner_metadata` into `_response_from_sqlcl_outcome`, stores a redacted runner
summary in audit metadata, and `tests.test_sql_execution` covers enabled
success, failure, timeout-result, stream-limit, and pre-output runner-error
paths.

### Resolved Medium: SQLcl stdin construction trusted DSN/password shape too much

The plan builder validates the working username but embeds `DB_DSN` and
`DB_USER_PASS` directly into a SQLcl `connect` line. The password only doubles
double quotes, and the DSN is unquoted. If an operator-supplied env value
contains newlines or SQLcl command separators, it could corrupt the private
stdin script before SQL validation is relevant. This is not an agent prompt
bypass, but it is a configuration/injection hardening gap in the explicit
operator path.

Evidence:

- `agent_runtime/oracle_adw.py:532-586` requires config values but does not
  validate them as single-line SQLcl-safe connection components.
- `agent_runtime/oracle_adw.py:963-986` renders `connect
  {working_user}/"{escaped_password}"@{dsn}` into stdin.

Recommendation: reject newline/control characters in DSN and password before
building the plan, and define the accepted DSN shape for wallet aliases versus
full connect descriptors. Keep all rejected values redacted.

Resolution: fixed in the current workspace for newline and ASCII control
characters. The plan builder rejects unsafe `DB_DSN` and `DB_USER_PASS`
connection components before rendering private stdin, and error messages name
the variable without echoing the rejected value.

### Resolved Low: Adapter coverage is thinner than the runner coverage for live-path edge statuses

`SqlclRunnerResult` has explicit timeout, stdout-too-large, and
stderr-too-large statuses, and `SqlclReadOnlyAdapter` maps those into execution
errors. The standalone runner has tests for oversized streams, but the adapter
needs direct tests that injected `SqlclRunnerResult(stdout_too_large=True)` and
`SqlclRunnerResult(stderr_too_large=True)` become structured redacted adapter
responses with audit runner metadata. It should also cover pre-output
`OSError` and `subprocess.TimeoutExpired` from an injected runner.

Evidence:

- `agent_runtime/sqlcl_runner.py:51-60` defines distinct runner statuses.
- `agent_runtime/sql_execution.py:265-315` maps runner statuses to outcomes.
- `tests/test_sqlcl_runner.py:86-105` covers standalone stream limits, while
  `tests/test_sql_execution.py:188-216` covers only adapter timeout result
  handling for `SqlclRunnerResult`.

Recommendation: add focused adapter tests after fixing the high-severity bug.
No live database is needed; injected runner results are sufficient.

Resolution: fixed in the current workspace. Adapter tests now cover injected
`SqlclRunnerResult` stdout and stderr stream-limit statuses plus pre-output
`OSError`; a direct `subprocess.TimeoutExpired` runner test is being added.

## Open Questions

- Should backend metadata include more redacted runner context than
  `runner_status`, or should process-shape details remain audit-only?
- What exact DSN forms are allowed for the first smoke: wallet alias only, easy
  connect string, or full descriptor? The validation rule should match that
  operator contract.
- Should SQLcl command-line hardening explicitly reject additional SQLcl-only
  commands such as `REM`, `REMARK`, and `SET` in user SQL text, even if Oracle
  would likely reject them inside the wrapped query?

## Verification

No tests were run for this review pass.
