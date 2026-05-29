"""Fake result-explanation artifacts for planned query plans.

This module keeps real SQL execution closed. It only accepts query plans that
already crossed the deterministic planning boundary and still declare execution
as disabled/not_executed, then runs them through the fake SQL adapter protocol.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping

from .query_plan import QueryPlanArtifact
from .redaction import redact
from .sql_execution import SqlExecutionAdapter, SqlExecutionRequest, SqlExecutionResponse


RESULT_EXPLANATION_SCHEMA_VERSION = "agent-runtime.result-explanation.v1"


ResultExplanationStatus = Literal["succeeded", "blocked", "rejected"]


@dataclass(frozen=True)
class ResultExplanationArtifact:
    schema_version: str
    query_plan_schema_version: str
    profile_id: str
    status: ResultExplanationStatus
    source: str
    real_database_execution: bool
    sql_execution_backend: str
    request_text: str
    proposed_sql: str | None
    adapter_response_metadata: Mapping[str, object] = field(default_factory=dict)
    columns: tuple[str, ...] = ()
    rows: tuple[Mapping[str, Any], ...] = ()
    row_count: int = 0
    summary: str = ""
    explanation: str = ""
    query_plan: Mapping[str, object] = field(default_factory=dict)
    execution_response: Mapping[str, object] = field(default_factory=dict)
    refusal_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


def build_fake_result_explanation(
    query_plan: QueryPlanArtifact,
    adapter: SqlExecutionAdapter,
) -> ResultExplanationArtifact:
    """Build a deterministic fake result explanation from a closed query plan."""

    backend = getattr(adapter, "backend", "unknown")
    if backend != "fake":
        return _blocked_artifact(
            query_plan,
            backend=backend,
            reason="Only the fake SQL execution backend may produce result explanations.",
        )

    if not _is_fake_executable_plan(query_plan):
        return _blocked_artifact(
            query_plan,
            backend=backend,
            reason=_blocked_plan_reason(query_plan),
        )

    response = adapter.execute(
        SqlExecutionRequest(
            sql=query_plan.proposed_sql or "",
            purpose="fake_result_explanation",
            metadata={
                "query_plan_schema_version": query_plan.schema_version,
                "profile_id": query_plan.profile_id,
                "request_text": query_plan.request_text,
            },
        )
    )
    if not response.ok:
        return _rejected_artifact(query_plan, response)

    return ResultExplanationArtifact(
        schema_version=RESULT_EXPLANATION_SCHEMA_VERSION,
        query_plan_schema_version=query_plan.schema_version,
        profile_id=query_plan.profile_id,
        status="succeeded",
        source="fake/deterministic",
        real_database_execution=False,
        sql_execution_backend=response.backend,
        request_text=query_plan.request_text,
        proposed_sql=query_plan.proposed_sql,
        adapter_response_metadata=response.backend_metadata,
        columns=response.columns,
        rows=response.rows,
        row_count=response.row_count,
        summary=_success_summary(response),
        explanation=_success_explanation(query_plan, response),
        query_plan=_query_plan_snapshot(query_plan),
        execution_response=_response_snapshot(response),
    )


def _is_fake_executable_plan(query_plan: QueryPlanArtifact) -> bool:
    return (
        query_plan.status == "planned"
        and bool(query_plan.proposed_sql)
        and query_plan.execution.get("enabled") is False
        and query_plan.execution.get("status") == "not_executed"
    )


def _blocked_plan_reason(query_plan: QueryPlanArtifact) -> str:
    if query_plan.status in {"blocked", "clarification_required"}:
        return query_plan.refusal_reason or f"Query plan status is {query_plan.status}."
    if not query_plan.proposed_sql:
        return "Query plan has no proposed SQL."
    if query_plan.execution.get("enabled") is not False:
        return "Query plan does not declare execution as disabled."
    if query_plan.execution.get("status") != "not_executed":
        return "Query plan execution status is not not_executed."
    return "Query plan is not eligible for fake result explanation."


def _blocked_artifact(
    query_plan: QueryPlanArtifact,
    *,
    backend: str,
    reason: str,
) -> ResultExplanationArtifact:
    return ResultExplanationArtifact(
        schema_version=RESULT_EXPLANATION_SCHEMA_VERSION,
        query_plan_schema_version=query_plan.schema_version,
        profile_id=query_plan.profile_id,
        status="blocked",
        source="fake/deterministic",
        real_database_execution=False,
        sql_execution_backend=backend,
        request_text=query_plan.request_text,
        proposed_sql=None,
        summary="No result rows were produced because the query plan was not eligible for fake execution.",
        explanation=reason,
        query_plan=_query_plan_snapshot(query_plan),
        refusal_reason=reason,
    )


def _rejected_artifact(
    query_plan: QueryPlanArtifact,
    response: SqlExecutionResponse,
) -> ResultExplanationArtifact:
    error = response.error.to_redacted_dict() if response.error else {}
    reason = str(error.get("message") or error.get("code") or "Fake SQL adapter rejected the request.")
    return ResultExplanationArtifact(
        schema_version=RESULT_EXPLANATION_SCHEMA_VERSION,
        query_plan_schema_version=query_plan.schema_version,
        profile_id=query_plan.profile_id,
        status="rejected",
        source="fake/deterministic",
        real_database_execution=False,
        sql_execution_backend=response.backend,
        request_text=query_plan.request_text,
        proposed_sql=None,
        adapter_response_metadata=response.backend_metadata,
        summary="No result rows were produced because the fake SQL adapter rejected the proposed SQL.",
        explanation=reason,
        query_plan=_query_plan_snapshot(query_plan),
        execution_response=_response_snapshot(response),
        refusal_reason=reason,
    )


def _success_summary(response: SqlExecutionResponse) -> str:
    if response.row_count == 1:
        return "Fake deterministic execution returned 1 row."
    return f"Fake deterministic execution returned {response.row_count} rows."


def _success_explanation(
    query_plan: QueryPlanArtifact,
    response: SqlExecutionResponse,
) -> str:
    dimensions = ", ".join(str(item.get("alias")) for item in query_plan.dimensions if item.get("alias"))
    measures = ", ".join(str(item.get("alias")) for item in query_plan.measures if item.get("alias"))
    parts = ["The rows come from the fake deterministic SQL adapter, not from Oracle ADW."]
    if dimensions:
        parts.append(f"Grouped dimensions: {dimensions}.")
    if measures:
        parts.append(f"Measures: {measures}.")
    parts.append(f"Returned columns: {', '.join(response.columns) if response.columns else 'none'}.")
    return " ".join(parts)


def _query_plan_snapshot(query_plan: QueryPlanArtifact) -> dict[str, object]:
    return {
        "schema_version": query_plan.schema_version,
        "status": query_plan.status,
        "profile_id": query_plan.profile_id,
        "selected_table_ids": list(query_plan.selected_table_ids),
        "policy_validation": query_plan.policy_validation,
        "execution": query_plan.execution,
        "refusal_reason": query_plan.refusal_reason,
    }


def _response_snapshot(response: SqlExecutionResponse) -> dict[str, object]:
    return {
        "ok": response.ok,
        "status": response.status,
        "backend": response.backend,
        "mode": response.mode,
        "row_count": response.row_count,
        "error": response.error.to_redacted_dict() if response.error else None,
        "backend_metadata": response.backend_metadata,
        "audit_metadata": response.audit_metadata,
    }


def build_real_result_explanation(
    query_plan: QueryPlanArtifact,
    *,
    adw_output: dict[str, Any],
) -> ResultExplanationArtifact:
    """Build a result explanation from actual ADW query output.

    adw_output is the output dict from _handle_adw_query in tools.py.
    Does not require FakeSqlExecutionAdapter.
    """
    result_schema_version = "agent-runtime.result-explanation.v1"
    status_val = str(adw_output.get("status") or "")
    real_db = bool(adw_output.get("real_database_execution"))
    backend = str(adw_output.get("backend") or "sqlcl")
    row_count = int(adw_output.get("row_count") or 0)
    rows = list(adw_output.get("rows") or [])
    columns: list[str] = []
    if rows:
        columns = list(rows[0].keys())

    # Guard: row_count > 0 but rows is empty → inconsistent state; reject
    if status_val == "succeeded" and real_db and row_count > 0 and not rows:
        return ResultExplanationArtifact(
            schema_version="agent-runtime.result-explanation.v1",
            query_plan_schema_version=query_plan.schema_version,
            profile_id=query_plan.profile_id,
            status="rejected",
            source="real/oracle_adw",
            real_database_execution=real_db,
            sql_execution_backend=backend,
            request_text=query_plan.request_text,
            proposed_sql=query_plan.proposed_sql or "",
            adapter_response_metadata={"backend": backend, "status": status_val, "row_count": row_count},
            columns=(),
            rows=(),
            row_count=0,
            summary="Real ADW execution reported rows but returned no row data.",
            explanation="",
            query_plan=query_plan.to_dict(),
            refusal_reason="row_data_missing_despite_row_count",
        )

    if not real_db or status_val != "succeeded":
        return ResultExplanationArtifact(
            schema_version=result_schema_version,
            query_plan_schema_version=query_plan.schema_version,
            profile_id=query_plan.profile_id,
            status="rejected",
            source="real/oracle_adw",
            real_database_execution=real_db,
            sql_execution_backend=backend,
            request_text=query_plan.request_text,
            proposed_sql=query_plan.proposed_sql or "",
            adapter_response_metadata={
                "backend": backend,
                "status": status_val,
                "real_database_execution": real_db,
            },
            columns=tuple(columns),
            rows=tuple(dict(r) for r in rows),
            row_count=row_count,
            summary="Real ADW execution did not return a successful result.",
            explanation="",
            query_plan=query_plan.to_dict(),
            refusal_reason=f"adw_query status={status_val!r}",
        )

    # Build summary from actual rows
    summary_parts = [
        f"Query returned {row_count} row(s) from Oracle ADW (real execution).",
    ]
    if columns:
        summary_parts.append(f"Columns: {', '.join(columns)}.")
    if rows:
        sample = rows[0]
        sample_text = ", ".join(f"{k}={v}" for k, v in list(sample.items())[:3])
        summary_parts.append(f"First row: {sample_text}.")

    explanation_lines = [
        "This result was produced by executing the proposed SQL against Oracle ADW.",
        "The data reflects actual database contents at query time.",
        "Source: real Oracle ADW execution via SQLcl read-only adapter.",
        f"Row count: {row_count}.",
    ]
    if row_count >= 10:
        explanation_lines.append(
            "Note: rows are bounded to the first 10 for this explanation."
        )

    return ResultExplanationArtifact(
        schema_version=result_schema_version,
        query_plan_schema_version=query_plan.schema_version,
        profile_id=query_plan.profile_id,
        status="succeeded",
        source="real/oracle_adw",
        real_database_execution=True,
        sql_execution_backend=backend,
        request_text=query_plan.request_text,
        proposed_sql=query_plan.proposed_sql or "",
        adapter_response_metadata={
            "backend": backend,
            "oracle_adw_execution": adw_output.get("oracle_adw_execution", True),
            "sqlcl_execution": adw_output.get("sqlcl_execution", True),
            "query_plan_id": adw_output.get("query_plan_id", ""),
            "row_count": row_count,
            "real_database_execution": True,
        },
        columns=tuple(columns),
        rows=tuple(dict(r) for r in rows),
        row_count=row_count,
        summary=" ".join(summary_parts),
        explanation=" ".join(explanation_lines),
        query_plan=query_plan.to_dict(),
        execution_response={
            "status": status_val,
            "backend": backend,
            "real_database_execution": True,
        },
    )


__all__ = [
    "RESULT_EXPLANATION_SCHEMA_VERSION",
    "ResultExplanationArtifact",
    "build_fake_result_explanation",
    "build_real_result_explanation",
]
