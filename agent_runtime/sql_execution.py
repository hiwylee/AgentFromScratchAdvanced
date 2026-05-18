"""Read-only SQL execution adapter boundary.

The adapter API is intentionally backend-neutral. SQLcl is currently only one
implementation detail behind the boundary, and real SQLcl execution remains
closed until subprocess execution is separately designed and tested.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
import subprocess
from typing import Any, Callable, Mapping, Protocol

from agent_runtime.oracle_adw import (
    OracleAdwConfig,
    SqlclExecutionError as OracleSqlclExecutionError,
    SqlclExecutionOutcome,
    SqlclReadOnlyExecutionPlan,
    SqlclReadOnlyExecutionSettings,
    SqlclRunResult,
    build_read_only_sqlcl_execution_plan,
    build_redacted_sqlcl_audit_record,
    classify_sqlcl_read_only_result,
    classify_sqlcl_timeout,
    validate_read_only_sql,
)
from agent_runtime.redaction import redact
from agent_runtime.sqlcl_runner import SqlclRunnerResult, run_sqlcl_plan


@dataclass(frozen=True)
class SqlExecutionRequest:
    """Backend-neutral read-only SQL execution request."""

    sql: str
    purpose: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


@dataclass(frozen=True)
class SqlExecutionError:
    code: str
    message: str
    detail: Mapping[str, object] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


@dataclass(frozen=True)
class SqlExecutionResponse:
    """Backend-neutral execution result.

    `backend_metadata` is safe for agent/tool callers. Backend-specific audit
    details, such as SQLcl argv shape, belong in `audit_metadata`.
    """

    ok: bool
    status: str
    backend: str
    mode: str = "read_only"
    columns: tuple[str, ...] = ()
    rows: tuple[Mapping[str, Any], ...] = ()
    row_count: int = 0
    error: SqlExecutionError | None = None
    backend_metadata: Mapping[str, object] = field(default_factory=dict)
    audit_metadata: Mapping[str, object] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return redact(asdict(self))


class SqlExecutionAdapter(Protocol):
    """Protocol for future read-only SQL execution backends."""

    backend: str

    def execute(self, request: SqlExecutionRequest) -> SqlExecutionResponse:
        """Validate and execute, or return a structured closed/rejected result."""


class FakeSqlExecutionAdapter:
    """Deterministic adapter for tests and closed-loop development."""

    backend = "fake"

    def __init__(
        self,
        *,
        rows: tuple[Mapping[str, Any], ...] = (),
        columns: tuple[str, ...] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self._rows = rows
        self._columns = columns
        self._metadata = metadata or {}

    def execute(self, request: SqlExecutionRequest) -> SqlExecutionResponse:
        policy = validate_read_only_sql(request.sql)
        metadata = {
            "backend": self.backend,
            "adapter": self.__class__.__name__,
            "mode": "read_only",
            "policy_code": policy.code,
            **self._metadata,
        }
        if not policy.allowed:
            return SqlExecutionResponse(
                ok=False,
                status="rejected",
                backend=self.backend,
                error=SqlExecutionError(
                    code=policy.code,
                    message=policy.reason,
                ),
                backend_metadata=metadata,
            )

        columns = self._columns or _columns_from_rows(self._rows)
        return SqlExecutionResponse(
            ok=True,
            status="succeeded",
            backend=self.backend,
            columns=columns,
            rows=self._rows,
            row_count=len(self._rows),
            backend_metadata=metadata,
            audit_metadata={
                "backend": self.backend,
                "mode": "read_only",
                "status": "succeeded",
                "row_count": len(self._rows),
            },
        )


class SqlclReadOnlyAdapter:
    """SQLcl-backed adapter with real execution intentionally closed."""

    backend = "sqlcl"

    def __init__(
        self,
        config: OracleAdwConfig,
        *,
        settings: SqlclReadOnlyExecutionSettings | None = None,
        allow_real_execution: bool = False,
        runner: Callable[
            [SqlclReadOnlyExecutionPlan],
            SqlclRunResult | SqlclRunnerResult,
        ]
        | None = None,
    ) -> None:
        self.config = config
        self.settings = settings
        self.allow_real_execution = allow_real_execution
        self._runner = runner

    def execute(self, request: SqlExecutionRequest) -> SqlExecutionResponse:
        try:
            plan = build_read_only_sqlcl_execution_plan(
                self.config,
                request.sql,
                settings=self.settings,
            )
        except ValueError as exc:
            return SqlExecutionResponse(
                ok=False,
                status="rejected",
                backend=self.backend,
                error=SqlExecutionError(
                    code=_error_code_from_value_error(exc),
                    message=str(exc),
                ),
                backend_metadata={
                    "backend": self.backend,
                    "adapter": self.__class__.__name__,
                    "mode": "read_only",
                    "execution_state": "rejected",
                    "allow_real_execution": self.allow_real_execution,
                },
            )

        metadata = _generic_sqlcl_metadata(
            plan,
            allow_real_execution=self.allow_real_execution,
            execution_state="closed",
            adapter_name=self.__class__.__name__,
        )
        audit_metadata = build_redacted_sqlcl_audit_record(
            "sql_execution.read_only.closed",
            plan,
        )

        if not self.allow_real_execution:
            return SqlExecutionResponse(
                ok=False,
                status="closed",
                backend=self.backend,
                error=SqlExecutionError(
                    code="real_execution_closed",
                    message="Real SQL execution is disabled for this adapter.",
                ),
                backend_metadata=metadata,
                audit_metadata=audit_metadata,
            )

        try:
            if self._runner is None:
                run_result = run_sqlcl_plan(
                    plan,
                    base_env=_minimal_sqlcl_execution_env(),
                )
            else:
                run_result = self._runner(plan)
        except subprocess.TimeoutExpired as exc:
            outcome = classify_sqlcl_timeout(plan, exc)
            runner_metadata: Mapping[str, object] = {"status": "timeout"}
        except OSError as exc:
            outcome = SqlclExecutionOutcome(
                ok=False,
                error=OracleSqlclExecutionError(
                    code="runner_error",
                    message=f"SQLcl runner failed before returning output: {exc.__class__.__name__}.",
                ),
            )
            runner_metadata = {"status": "runner_error"}
        else:
            outcome, runner_metadata = _classify_runner_result(plan, run_result)

        return _response_from_sqlcl_outcome(
            plan,
            outcome,
            metadata={
                **metadata,
                "execution_state": "executed",
                "runner_status": runner_metadata.get("status"),
            },
            runner_metadata=runner_metadata,
            audit_event="sql_execution.read_only.executed",
        )


def _generic_sqlcl_metadata(
    plan: SqlclReadOnlyExecutionPlan,
    *,
    allow_real_execution: bool,
    execution_state: str,
    adapter_name: str,
) -> dict[str, object]:
    return {
        "backend": "sqlcl",
        "adapter": adapter_name,
        "mode": "read_only",
        "execution_state": execution_state,
        "allow_real_execution": allow_real_execution,
        "sql_sha256": plan.sql_sha256,
        "working_user": plan.working_user,
        "limits": {
            "timeout_seconds": plan.timeout_seconds,
            "row_limit": plan.row_limit,
            "max_output_bytes": plan.max_output_bytes,
            "max_error_bytes": plan.max_error_bytes,
        },
    }


def _classify_runner_result(
    plan: SqlclReadOnlyExecutionPlan,
    run_result: SqlclRunResult | SqlclRunnerResult,
) -> tuple[SqlclExecutionOutcome, Mapping[str, object]]:
    if isinstance(run_result, SqlclRunnerResult):
        runner_metadata = run_result.to_redacted_dict()
        if run_result.timed_out:
            return (
                SqlclExecutionOutcome(
                    ok=False,
                    error=OracleSqlclExecutionError(
                        code="timeout",
                        message=(
                            "SQLcl read-only query exceeded "
                            f"{plan.timeout_seconds} seconds."
                        ),
                        returncode=run_result.returncode,
                        stderr=plan.redact_text(run_result.stderr) or None,
                    ),
                ),
                runner_metadata,
            )
        if run_result.stdout_too_large:
            return (
                SqlclExecutionOutcome(
                    ok=False,
                    error=OracleSqlclExecutionError(
                        code="output_too_large",
                        message="SQLcl stdout exceeded the configured capture limit.",
                        returncode=run_result.returncode,
                    ),
                ),
                runner_metadata,
            )
        if run_result.stderr_too_large:
            return (
                SqlclExecutionOutcome(
                    ok=False,
                    error=OracleSqlclExecutionError(
                        code="error_output_too_large",
                        message="SQLcl stderr exceeded the configured capture limit.",
                        returncode=run_result.returncode,
                    ),
                ),
                runner_metadata,
            )
        return (
            classify_sqlcl_read_only_result(plan, run_result.to_sqlcl_run_result()),
            runner_metadata,
        )

    return (
        classify_sqlcl_read_only_result(plan, run_result),
        {"status": "completed" if run_result.returncode == 0 else "failed"},
    )


def _response_from_sqlcl_outcome(
    plan: SqlclReadOnlyExecutionPlan,
    outcome: SqlclExecutionOutcome,
    *,
    metadata: Mapping[str, object],
    runner_metadata: Mapping[str, object],
    audit_event: str,
) -> SqlExecutionResponse:
    audit_metadata = build_redacted_sqlcl_audit_record(audit_event, plan, outcome)
    audit_metadata["runner"] = redact(dict(runner_metadata))
    if outcome.ok and outcome.result is not None:
        return SqlExecutionResponse(
            ok=True,
            status="succeeded",
            backend="sqlcl",
            columns=outcome.result.columns,
            rows=outcome.result.rows,
            row_count=outcome.result.row_count,
            backend_metadata=metadata,
            audit_metadata=audit_metadata,
        )

    error = outcome.error or OracleSqlclExecutionError(
        code="unknown_sqlcl_error",
        message="SQLcl execution failed without a structured error.",
    )
    return SqlExecutionResponse(
        ok=False,
        status=_sql_execution_status_from_error(error.code),
        backend="sqlcl",
        error=SqlExecutionError(
            code=error.code,
            message=error.message,
            detail=_sqlcl_error_detail(error),
        ),
        backend_metadata=metadata,
        audit_metadata=audit_metadata,
    )


def _sqlcl_error_detail(error: OracleSqlclExecutionError) -> dict[str, object]:
    detail: dict[str, object] = {}
    if error.returncode is not None:
        detail["returncode"] = error.returncode
    if error.stderr:
        detail["stderr"] = error.stderr
    return detail


def _sql_execution_status_from_error(code: str) -> str:
    if code == "timeout":
        return "timeout"
    return "failed"


def _minimal_sqlcl_execution_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("PATH", "JAVA_HOME", "HOME", "LANG", "LC_ALL"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _columns_from_rows(rows: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
    if not rows:
        return ()
    return tuple(str(key) for key in rows[0].keys())


def _error_code_from_value_error(exc: ValueError) -> str:
    text = str(exc)
    if ":" in text:
        prefix = text.split(":", 1)[0].strip()
        if prefix:
            return prefix
    return "invalid_execution_request"


__all__ = [
    "FakeSqlExecutionAdapter",
    "SqlExecutionAdapter",
    "SqlExecutionError",
    "SqlExecutionRequest",
    "SqlExecutionResponse",
    "SqlclReadOnlyAdapter",
]
