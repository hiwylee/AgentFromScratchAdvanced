"""Structured tool interface and registry for the agent runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Literal, Protocol

from .audit import RunRecord, append_audit
from .query_plan import QueryPlanArtifact, build_query_plan_from_context
from .redaction import redact
from .result_explanation import build_fake_result_explanation
from .schema_context import build_compact_schema_context, load_schema_artifacts
from .sql_execution import FakeSqlExecutionAdapter


ToolState = Literal["completed", "failed", "invalid", "blocked"]
ToolArgType = Literal["string", "integer", "number", "boolean", "object", "array"]
ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_METADATA_PATH = (
    _PROJECT_ROOT / "docs/generated/schema-context/oracle_adw_sh.schema-metadata.v1.json"
)
_CURATED_SEED_PATH = (
    _PROJECT_ROOT / "docs/generated/schema-context/oracle_adw_sh.curated-seed.v1.json"
)


class ToolEventSink(Protocol):
    def __call__(self, event: str, data: dict[str, Any]) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: ToolArgType
    required: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: tuple[ToolParameter, ...] = ()
    risk_level: Literal["low", "medium", "high"] = "low"
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "risk_level": self.risk_level,
            "read_only": self.read_only,
        }


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": redact(self.arguments)}


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    state: ToolState
    attempts: int
    latency_ms: int
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler


@dataclass(frozen=True)
class ToolExecutionContext:
    run_id: str
    audit_path: Path
    approved_high_risk_tools: tuple[str, ...] = ()
    approved_write_tools: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "audit_path": str(self.audit_path),
            "approved_high_risk_tools": list(self.approved_high_risk_tools),
            "approved_write_tools": list(self.approved_write_tools),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if not spec.name or not spec.name.replace("_", "").replace("-", "").isalnum():
            raise ValueError("tool name must be non-empty and alphanumeric with '-' or '_'")
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def specs(self) -> list[dict[str, Any]]:
        return [registered.spec.to_dict() for registered in self._tools.values()]

    def validate_call(self, call: ToolCall) -> list[str]:
        try:
            registered = self.get(call.name)
        except KeyError as exc:
            return [str(exc)]

        errors: list[str] = []
        parameters = {parameter.name: parameter for parameter in registered.spec.parameters}
        for parameter in registered.spec.parameters:
            if parameter.required and parameter.name not in call.arguments:
                errors.append(f"missing required argument: {parameter.name}")
        for name, value in call.arguments.items():
            parameter = parameters.get(name)
            if parameter is None:
                errors.append(f"unknown argument: {name}")
                continue
            if not _matches_type(value, parameter.type):
                errors.append(f"argument {name} must be {parameter.type}")
        return errors


def default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="mock_schema_context",
            description="Return compact read-only Oracle ADW schema context without external access.",
            parameters=(
                ToolParameter(
                    name="required_context",
                    type="array",
                    required=False,
                    description="Context artifacts requested by intent analysis.",
                ),
                ToolParameter(
                    name="request_text",
                    type="string",
                    required=False,
                    description="Original user request text used for deterministic schema retrieval.",
                ),
                ToolParameter(
                    name="request_terms",
                    type="array",
                    required=False,
                    description="Optional normalized request terms used for schema retrieval.",
                ),
            ),
            risk_level="low",
            read_only=True,
        ),
        _mock_schema_context,
    )
    return registry


class ToolRunner:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        context: ToolExecutionContext,
        event_sink: ToolEventSink | None = None,
    ) -> None:
        self.registry = registry
        self.context = context
        self.event_sink = event_sink

    def run(self, call: ToolCall, *, max_attempts: int = 1) -> ToolResult:
        started = monotonic()
        attempts = max(1, max_attempts)
        errors = self.registry.validate_call(call)
        if errors:
            result = ToolResult(
                tool_name=call.name,
                state="invalid",
                attempts=0,
                latency_ms=_elapsed_ms(started),
                error="; ".join(errors),
            )
            self._event("tool_invalid", {"call": call.to_dict(), "result": result.to_dict()})
            return result

        registered = self.registry.get(call.name)
        policy_error = _policy_error(registered.spec, self.context)
        if policy_error:
            result = ToolResult(
                tool_name=call.name,
                state="blocked",
                attempts=0,
                latency_ms=_elapsed_ms(started),
                error=policy_error,
            )
            self._event(
                "tool_blocked",
                {
                    "call": call.to_dict(),
                    "tool": registered.spec.to_dict(),
                    "policy": self.context.to_dict(),
                    "result": result.to_dict(),
                },
            )
            return result

        self._event("tool_started", {"call": call.to_dict(), "tool": registered.spec.to_dict()})
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                output = registered.handler(dict(call.arguments))
            except Exception as exc:  # noqa: BLE001 - tool boundary captures handler failure.
                last_error = f"{type(exc).__name__}: {exc}"
                self._event(
                    "tool_attempt_failed",
                    {"tool_name": call.name, "attempt": attempt, "error": last_error},
                )
                continue
            result = ToolResult(
                tool_name=call.name,
                state="completed",
                attempts=attempt,
                latency_ms=_elapsed_ms(started),
                output=output,
            )
            self._event("tool_completed", {"result": result.to_dict()})
            return result

        result = ToolResult(
            tool_name=call.name,
            state="failed",
            attempts=attempts,
            latency_ms=_elapsed_ms(started),
            error=last_error,
        )
        self._event("tool_failed", {"result": result.to_dict()})
        return result

    def _event(self, event: str, data: dict[str, Any]) -> None:
        append_audit(
            RunRecord.create(event=event, data=redact(data), run_id=self.context.run_id),
            self.context.audit_path,
        )
        if self.event_sink is not None:
            self.event_sink(event, redact(data))


def _policy_error(spec: ToolSpec, context: ToolExecutionContext) -> str:
    if not spec.read_only and spec.name not in set(context.approved_write_tools):
        return "write_tool_requires_explicit_approval"
    if spec.risk_level == "high" and spec.name not in set(context.approved_high_risk_tools):
        return "high_risk_tool_requires_explicit_approval"
    return ""


def _matches_type(value: Any, expected: ToolArgType) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int | float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return False


def _elapsed_ms(started: float) -> int:
    return max(0, round((monotonic() - started) * 1000))


def _mock_schema_context(args: dict[str, Any]) -> dict[str, Any]:
    requested = args.get("required_context", [])
    request_text = args.get("request_text", "")
    request_terms = args.get("request_terms", [])
    if not isinstance(requested, list):
        requested = []
    if not isinstance(request_text, str):
        request_text = ""
    if not isinstance(request_terms, list):
        request_terms = []

    artifacts = load_schema_artifacts(
        _SCHEMA_METADATA_PATH,
        _CURATED_SEED_PATH,
        expected_profile_id="oracle_adw_sh.v1",
    )
    compact = build_compact_schema_context(
        artifacts,
        request_text=request_text,
        request_terms=[str(term) for term in request_terms],
    )
    context = compact.to_dict()
    output = {
        "mode": "compact_schema_context_read_only",
        "external_access": False,
        "sql_generation_enabled": False,
        "sql_execution_enabled": False,
        "requested_context": requested,
        "available_context": ["oracle_adw_schema", "business_glossary", "sample_masking_policy"],
        "profile_id": context["profile_id"],
        "schema_metadata_artifact_id": context["schema_metadata_artifact_id"],
        "curated_seed_artifact_id": context["curated_seed_artifact_id"],
        "schema_metadata_version": context["schema_metadata_version"],
        "curated_seed_version": context["curated_seed_version"],
        "selected_table_ids": context["selected_table_ids"],
        "considered_tables": context["considered_tables"],
        "rejected_tables": context["rejected_tables"],
        "glossary_matches": context["glossary_matches"],
        "clarification": context["clarification"],
        "masking": {
            "policy_version": context["masking_policy_version"],
            "sample_values": context["sample_values"],
        },
        "context": context["context"],
        "next_action": "SQL generation remains closed; use this context only for schema inspection or clarification.",
    }
    query_plan = build_query_plan_from_context(
        compact,
        request_text=request_text,
    )
    query_plan_output = query_plan.to_dict()
    if query_plan.status != "blocked":
        output["query_plan"] = query_plan_output
        fake_adapter = _fake_result_explanation_adapter(query_plan)
        if fake_adapter is not None:
            output["result_explanation"] = build_fake_result_explanation(
                query_plan,
                fake_adapter,
            ).to_dict()
    return output


def _fake_result_explanation_adapter(query_plan: QueryPlanArtifact) -> FakeSqlExecutionAdapter | None:
    if query_plan.status != "planned":
        return None
    aliases = {
        str(item.get("alias"))
        for item in (*query_plan.dimensions, *query_plan.measures)
        if item.get("alias")
    }
    for required_aliases, fixture in _FAKE_RESULT_EXPLANATION_FIXTURES.items():
        if set(required_aliases).issubset(aliases):
            return FakeSqlExecutionAdapter(
                rows=fixture["rows"],
                columns=fixture["columns"],
                metadata={
                    "fixture_id": fixture["fixture_id"],
                    "scenario_id": fixture["scenario_id"],
                    "adapter_version": "fake-sql-execution-adapter.v1",
                    "execution_state": "fake_only",
                    "oracle_adw_execution": False,
                    "sqlcl_execution": False,
                },
            )
    return None


_FAKE_RESULT_EXPLANATION_FIXTURES: dict[tuple[str, ...], dict[str, Any]] = {
    ("month", "product_category", "revenue"): {
        "fixture_id": "schema-context-product-month-fake-results",
        "scenario_id": "sh-revenue-product-month-demo",
        "columns": ("month", "product_category", "revenue"),
        "rows": (
            {
                "month": "demo_month_01",
                "product_category": "demo_category_alpha",
                "revenue": 1000,
            },
            {
                "month": "demo_month_02",
                "product_category": "demo_category_beta",
                "revenue": 1250,
            },
        ),
    },
    ("month", "channel", "revenue"): {
        "fixture_id": "schema-context-channel-month-fake-results",
        "scenario_id": "sh-revenue-channel-month-demo",
        "columns": ("month", "channel", "revenue"),
        "rows": (
            {
                "month": "demo_month_01",
                "channel": "demo_channel_direct",
                "revenue": 2100,
            },
            {
                "month": "demo_month_02",
                "channel": "demo_channel_partner",
                "revenue": 1980,
            },
        ),
    },
    ("month", "promotion_category", "revenue"): {
        "fixture_id": "schema-context-promotion-category-month-fake-results",
        "scenario_id": "sh-revenue-promotion-category-month-demo",
        "columns": ("month", "promotion_category", "revenue"),
        "rows": (
            {
                "month": "demo_month_01",
                "promotion_category": "demo_promo_category_alpha",
                "revenue": 760,
            },
            {
                "month": "demo_month_02",
                "promotion_category": "demo_promo_category_beta",
                "revenue": 930,
            },
        ),
    },
    ("month", "promotion_subcategory", "revenue"): {
        "fixture_id": "schema-context-promotion-subcategory-month-fake-results",
        "scenario_id": "sh-revenue-promotion-subcategory-month-demo",
        "columns": ("month", "promotion_subcategory", "revenue"),
        "rows": (
            {
                "month": "demo_month_01",
                "promotion_subcategory": "demo_promo_subcategory_alpha",
                "revenue": 410,
            },
            {
                "month": "demo_month_02",
                "promotion_subcategory": "demo_promo_subcategory_beta",
                "revenue": 530,
            },
        ),
    },
}
