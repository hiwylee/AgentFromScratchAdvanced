"""Closed query-plan artifacts built from compact schema context."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .oracle_adw import validate_read_only_sql
from .redaction import redact
from .schema_context import CompactSchemaResult


QUERY_PLAN_SCHEMA_VERSION = "agent-runtime.query-plan.v1"


QueryPlanStatus = Literal["planned", "clarification_required", "blocked"]


@dataclass(frozen=True)
class QueryPlanArtifact:
    schema_version: str
    profile_id: str
    status: QueryPlanStatus
    request_text: str
    selected_table_ids: tuple[str, ...]
    proposed_sql: str | None
    policy_validation: dict[str, Any]
    assumptions: tuple[str, ...]
    dimensions: tuple[dict[str, str], ...] = ()
    measures: tuple[dict[str, str], ...] = ()
    joins: tuple[dict[str, str], ...] = ()
    schema_context: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    refusal_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return redact(asdict(self))


def build_query_plan_from_context(
    compact_context: CompactSchemaResult,
    *,
    request_text: str = "",
) -> QueryPlanArtifact:
    """Create a proposed query plan without executing SQL.

    The Milestone 6 slice supports a small set of deterministic SH revenue
    analysis patterns only. Broader NL-to-SQL generation should add plan
    candidates behind this artifact shape rather than bypassing it.
    """

    context_refs = _schema_context_refs(compact_context)
    execution = _closed_execution_boundary()
    if compact_context.clarification.get("required"):
        return QueryPlanArtifact(
            schema_version=QUERY_PLAN_SCHEMA_VERSION,
            profile_id=compact_context.profile_id,
            status="clarification_required",
            request_text=request_text,
            selected_table_ids=tuple(compact_context.selected_table_ids),
            proposed_sql=None,
            policy_validation=_not_evaluated_policy("clarification_required"),
            assumptions=(
                "Schema retrieval requires clarification before a query plan can be proposed.",
            ),
            schema_context=context_refs,
            execution=execution,
            refusal_reason=str(compact_context.clarification.get("reason")),
        )

    pattern = _select_query_pattern(compact_context, request_text)
    if pattern is None:
        return QueryPlanArtifact(
            schema_version=QUERY_PLAN_SCHEMA_VERSION,
            profile_id=compact_context.profile_id,
            status="blocked",
            request_text=request_text,
            selected_table_ids=tuple(compact_context.selected_table_ids),
            proposed_sql=None,
            policy_validation=_not_evaluated_policy("unsupported_query_pattern"),
            assumptions=(
                "The request did not confidently match a supported query-plan pattern.",
                "Supported patterns are revenue by product by month, revenue by channel by month, and revenue by promotion by month.",
            ),
            schema_context=context_refs,
            execution=execution,
            refusal_reason="unsupported query-plan pattern",
        )

    required_tables = pattern["required_tables"]
    selected = set(compact_context.selected_table_ids)
    missing_tables = sorted(required_tables - selected)
    if missing_tables:
        return QueryPlanArtifact(
            schema_version=QUERY_PLAN_SCHEMA_VERSION,
            profile_id=compact_context.profile_id,
            status="blocked",
            request_text=request_text,
            selected_table_ids=tuple(compact_context.selected_table_ids),
            proposed_sql=None,
            policy_validation=_not_evaluated_policy("missing_required_schema_context"),
            assumptions=(
                f"The {pattern['label']} query pattern requires "
                f"{_required_table_names(required_tables)} context.",
            ),
            schema_context=context_refs,
            execution=execution,
            refusal_reason=f"missing required table context: {', '.join(missing_tables)}",
        )

    sql = pattern["sql"]
    policy = validate_query_plan_sql(sql)
    status: QueryPlanStatus = "planned" if policy["allowed"] else "blocked"
    refusal_reason = None if policy["allowed"] else str(policy["code"])
    return QueryPlanArtifact(
        schema_version=QUERY_PLAN_SCHEMA_VERSION,
        profile_id=compact_context.profile_id,
        status=status,
        request_text=request_text,
        selected_table_ids=tuple(compact_context.selected_table_ids),
        proposed_sql=sql if policy["allowed"] else None,
        policy_validation=policy,
        assumptions=pattern["assumptions"],
        dimensions=pattern["dimensions"],
        measures=pattern["measures"],
        joins=pattern["joins"],
        schema_context=context_refs,
        execution=execution,
        refusal_reason=refusal_reason,
    )


def validate_query_plan_sql(sql: str) -> dict[str, Any]:
    policy = validate_read_only_sql(sql)
    return {
        "validator": "oracle_adw.read_only_sql_policy",
        "allowed": policy.allowed,
        "code": policy.code,
        "reason": policy.reason,
    }


def _select_query_pattern(
    compact_context: CompactSchemaResult,
    request_text: str,
) -> dict[str, Any] | None:
    terms = _normalized_request_terms(compact_context, request_text)
    if _has_any_term(
        terms,
        (
            "country",
            "countries",
            "region",
            "regions",
            "customer",
            "customers",
        ),
    ):
        return None
    has_day = _has_day_term(terms)
    has_month = _has_month_term(terms)
    if _has_promotion_term(terms):
        if _has_revenue_term(terms):
            if has_day:
                return _revenue_by_promotion_day_pattern(
                    use_subcategory=_has_promotion_subcategory_term(terms)
                )
            if has_month:
                return _revenue_by_promotion_month_pattern(
                    use_subcategory=_has_promotion_subcategory_term(terms)
                )
        return None
    if _has_any_term(terms, ("channel", "channels", "sales channel", "route to market")):
        if _has_revenue_term(terms):
            if has_day:
                return _revenue_by_channel_day_pattern()
            if has_month:
                return _revenue_by_channel_month_pattern()
        return None
    if _has_any_term(terms, ("product", "products", "product category", "category")):
        if _has_revenue_term(terms):
            if has_day:
                return _revenue_by_product_day_pattern()
            if has_month:
                return _revenue_by_product_month_pattern()
        return None
    return None


def _normalized_request_terms(
    compact_context: CompactSchemaResult,
    request_text: str,
) -> set[str]:
    terms = {str(term).strip().lower() for term in compact_context.request_terms if str(term).strip()}
    terms.update(_words(request_text))
    for match in compact_context.glossary_matches:
        term = str(match.get("term", "")).strip().lower()
        if term:
            terms.add(term)
        for alias in match.get("aliases", []):
            alias_text = str(alias).strip().lower()
            if alias_text:
                terms.add(alias_text)
    return terms


def _words(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[A-Za-z0-9]+", text)}


def _has_any_term(terms: set[str], candidates: tuple[str, ...]) -> bool:
    return any(candidate in terms for candidate in candidates)


def _has_revenue_term(terms: set[str]) -> bool:
    return _has_any_term(terms, ("revenue", "sales", "sales amount", "amount sold"))


def _has_month_term(terms: set[str]) -> bool:
    return _has_any_term(terms, ("month", "monthly", "calendar month"))


def _has_day_term(terms: set[str]) -> bool:
    return _has_any_term(terms, ("day", "daily", "calendar date", "일별", "일"))


def _has_promotion_term(terms: set[str]) -> bool:
    return _has_any_term(
        terms,
        (
            "promotion",
            "promotions",
            "promo",
            "promos",
            "campaign",
            "campaigns",
            "offer",
            "offers",
            "promotion category",
            "promo category",
            "promotion subcategory",
            "promo subcategory",
        ),
    )


def _has_promotion_subcategory_term(terms: set[str]) -> bool:
    return _has_any_term(terms, ("promotion subcategory", "promo subcategory"))


def _revenue_by_product_month_pattern() -> dict[str, Any]:
    return {
        "label": "revenue/product/month",
        "required_tables": {"SH.SALES", "SH.PRODUCTS", "SH.TIMES"},
        "sql": _revenue_by_product_month_sql(),
        "assumptions": (
            "Revenue maps to SUM(SALES.AMOUNT_SOLD) from the curated SH glossary.",
            "Product grouping uses PRODUCTS.PROD_CATEGORY until a more specific product grain is requested.",
            "Month grouping uses TIMES.CALENDAR_MONTH_DESC.",
            "No date filter is applied until the request supplies a concrete period.",
            "The proposed SQL is not executed in this milestone.",
        ),
        "dimensions": (
            {"table_id": "SH.TIMES", "column": "CALENDAR_MONTH_DESC", "alias": "month"},
            {"table_id": "SH.PRODUCTS", "column": "PROD_CATEGORY", "alias": "product_category"},
        ),
        "measures": (_revenue_measure(),),
        "joins": (
            {
                "from_table_id": "SH.SALES",
                "from_column": "PROD_ID",
                "to_table_id": "SH.PRODUCTS",
                "to_column": "PROD_ID",
            },
            _sales_time_join(),
        ),
    }


def _revenue_by_channel_month_pattern() -> dict[str, Any]:
    return {
        "label": "revenue/channel/month",
        "required_tables": {"SH.SALES", "SH.CHANNELS", "SH.TIMES"},
        "sql": _revenue_by_channel_month_sql(),
        "assumptions": (
            "Revenue maps to SUM(SALES.AMOUNT_SOLD) from the curated SH glossary.",
            "Channel grouping uses CHANNELS.CHANNEL_DESC from the curated SH glossary.",
            "Month grouping uses TIMES.CALENDAR_MONTH_DESC.",
            "No date filter is applied until the request supplies a concrete period.",
            "The proposed SQL is not executed in this milestone.",
        ),
        "dimensions": (
            {"table_id": "SH.TIMES", "column": "CALENDAR_MONTH_DESC", "alias": "month"},
            {"table_id": "SH.CHANNELS", "column": "CHANNEL_DESC", "alias": "channel"},
        ),
        "measures": (_revenue_measure(),),
        "joins": (
            {
                "from_table_id": "SH.SALES",
                "from_column": "CHANNEL_ID",
                "to_table_id": "SH.CHANNELS",
                "to_column": "CHANNEL_ID",
            },
            _sales_time_join(),
        ),
    }


def _revenue_by_promotion_month_pattern(*, use_subcategory: bool = False) -> dict[str, Any]:
    promo_column = "PROMO_SUBCATEGORY" if use_subcategory else "PROMO_CATEGORY"
    promo_alias = "promotion_subcategory" if use_subcategory else "promotion_category"
    promo_grain = "subcategory" if use_subcategory else "category"
    return {
        "label": "revenue/promotion/month",
        "required_tables": {"SH.SALES", "SH.PROMOTIONS", "SH.TIMES"},
        "sql": _revenue_by_promotion_month_sql(
            promo_column=promo_column,
            promo_alias=promo_alias,
        ),
        "assumptions": (
            "Revenue maps to SUM(SALES.AMOUNT_SOLD) from the curated SH glossary.",
            f"Promotion grouping uses PROMOTIONS.{promo_column} because the request asks for promotion {promo_grain}.",
            "Month grouping uses TIMES.CALENDAR_MONTH_DESC.",
            "No date filter is applied until the request supplies a concrete period.",
            "The proposed SQL is not executed in this milestone.",
        ),
        "dimensions": (
            {"table_id": "SH.TIMES", "column": "CALENDAR_MONTH_DESC", "alias": "month"},
            {"table_id": "SH.PROMOTIONS", "column": promo_column, "alias": promo_alias},
        ),
        "measures": (_revenue_measure(),),
        "joins": (
            {
                "from_table_id": "SH.SALES",
                "from_column": "PROMO_ID",
                "to_table_id": "SH.PROMOTIONS",
                "to_column": "PROMO_ID",
            },
            _sales_time_join(),
        ),
    }


def _revenue_by_product_day_pattern() -> dict[str, Any]:
    return {
        "label": "revenue/product/day",
        "required_tables": {"SH.SALES", "SH.PRODUCTS", "SH.TIMES"},
        "sql": _revenue_by_product_day_sql(),
        "assumptions": (
            "Revenue maps to SUM(SALES.AMOUNT_SOLD) from the curated SH glossary.",
            "Product grouping uses PRODUCTS.PROD_CATEGORY.",
            "Day grouping uses TIMES.TIME_ID (DATE).",
            "No date filter is applied until the request supplies a concrete period.",
            "The proposed SQL is not executed in this milestone.",
        ),
        "dimensions": (
            {"table_id": "SH.TIMES", "column": "TIME_ID", "alias": "day"},
            {"table_id": "SH.PRODUCTS", "column": "PROD_CATEGORY", "alias": "product_category"},
        ),
        "measures": (_revenue_measure(),),
        "joins": (
            {"from_table_id": "SH.SALES", "from_column": "PROD_ID", "to_table_id": "SH.PRODUCTS", "to_column": "PROD_ID"},
            _sales_time_join(),
        ),
    }


def _revenue_by_channel_day_pattern() -> dict[str, Any]:
    return {
        "label": "revenue/channel/day",
        "required_tables": {"SH.SALES", "SH.CHANNELS", "SH.TIMES"},
        "sql": _revenue_by_channel_day_sql(),
        "assumptions": (
            "Revenue maps to SUM(SALES.AMOUNT_SOLD) from the curated SH glossary.",
            "Channel grouping uses CHANNELS.CHANNEL_DESC.",
            "Day grouping uses TIMES.TIME_ID (DATE).",
            "No date filter is applied until the request supplies a concrete period.",
            "The proposed SQL is not executed in this milestone.",
        ),
        "dimensions": (
            {"table_id": "SH.TIMES", "column": "TIME_ID", "alias": "day"},
            {"table_id": "SH.CHANNELS", "column": "CHANNEL_DESC", "alias": "channel"},
        ),
        "measures": (_revenue_measure(),),
        "joins": (
            {"from_table_id": "SH.SALES", "from_column": "CHANNEL_ID", "to_table_id": "SH.CHANNELS", "to_column": "CHANNEL_ID"},
            _sales_time_join(),
        ),
    }


def _revenue_by_promotion_day_pattern(*, use_subcategory: bool = False) -> dict[str, Any]:
    promo_column = "PROMO_SUBCATEGORY" if use_subcategory else "PROMO_CATEGORY"
    promo_alias = "promotion_subcategory" if use_subcategory else "promotion_category"
    promo_grain = "subcategory" if use_subcategory else "category"
    return {
        "label": "revenue/promotion/day",
        "required_tables": {"SH.SALES", "SH.PROMOTIONS", "SH.TIMES"},
        "sql": _revenue_by_promotion_day_sql(promo_column=promo_column, promo_alias=promo_alias),
        "assumptions": (
            "Revenue maps to SUM(SALES.AMOUNT_SOLD) from the curated SH glossary.",
            f"Promotion grouping uses PROMOTIONS.{promo_column} because the request asks for promotion {promo_grain}.",
            "Day grouping uses TIMES.TIME_ID (DATE).",
            "No date filter is applied until the request supplies a concrete period.",
            "The proposed SQL is not executed in this milestone.",
        ),
        "dimensions": (
            {"table_id": "SH.TIMES", "column": "TIME_ID", "alias": "day"},
            {"table_id": "SH.PROMOTIONS", "column": promo_column, "alias": promo_alias},
        ),
        "measures": (_revenue_measure(),),
        "joins": (
            {"from_table_id": "SH.SALES", "from_column": "PROMO_ID", "to_table_id": "SH.PROMOTIONS", "to_column": "PROMO_ID"},
            _sales_time_join(),
        ),
    }


def _revenue_by_product_month_sql() -> str:
    return "\n".join(
        (
            "SELECT",
            "  t.CALENDAR_MONTH_DESC AS month,",
            "  p.PROD_CATEGORY AS product_category,",
            "  SUM(s.AMOUNT_SOLD) AS revenue",
            "FROM SALES s",
            "JOIN PRODUCTS p ON s.PROD_ID = p.PROD_ID",
            "JOIN TIMES t ON s.TIME_ID = t.TIME_ID",
            "GROUP BY t.CALENDAR_MONTH_DESC, p.PROD_CATEGORY",
            "ORDER BY t.CALENDAR_MONTH_DESC, p.PROD_CATEGORY",
        )
    )


def _revenue_by_channel_month_sql() -> str:
    return "\n".join(
        (
            "SELECT",
            "  t.CALENDAR_MONTH_DESC AS month,",
            "  c.CHANNEL_DESC AS channel,",
            "  SUM(s.AMOUNT_SOLD) AS revenue",
            "FROM SALES s",
            "JOIN CHANNELS c ON s.CHANNEL_ID = c.CHANNEL_ID",
            "JOIN TIMES t ON s.TIME_ID = t.TIME_ID",
            "GROUP BY t.CALENDAR_MONTH_DESC, c.CHANNEL_DESC",
            "ORDER BY t.CALENDAR_MONTH_DESC, c.CHANNEL_DESC",
        )
    )


def _revenue_by_promotion_month_sql(*, promo_column: str, promo_alias: str) -> str:
    return "\n".join(
        (
            "SELECT",
            "  t.CALENDAR_MONTH_DESC AS month,",
            f"  pr.{promo_column} AS {promo_alias},",
            "  SUM(s.AMOUNT_SOLD) AS revenue",
            "FROM SALES s",
            "JOIN PROMOTIONS pr ON s.PROMO_ID = pr.PROMO_ID",
            "JOIN TIMES t ON s.TIME_ID = t.TIME_ID",
            f"GROUP BY t.CALENDAR_MONTH_DESC, pr.{promo_column}",
            f"ORDER BY t.CALENDAR_MONTH_DESC, pr.{promo_column}",
        )
    )


def _revenue_by_product_day_sql() -> str:
    return "\n".join((
        "SELECT",
        "  t.TIME_ID AS day,",
        "  p.PROD_CATEGORY AS product_category,",
        "  SUM(s.AMOUNT_SOLD) AS revenue",
        "FROM SALES s",
        "JOIN PRODUCTS p ON s.PROD_ID = p.PROD_ID",
        "JOIN TIMES t ON s.TIME_ID = t.TIME_ID",
        "GROUP BY t.TIME_ID, p.PROD_CATEGORY",
        "ORDER BY t.TIME_ID, p.PROD_CATEGORY",
    ))


def _revenue_by_channel_day_sql() -> str:
    return "\n".join((
        "SELECT",
        "  t.TIME_ID AS day,",
        "  c.CHANNEL_DESC AS channel,",
        "  SUM(s.AMOUNT_SOLD) AS revenue",
        "FROM SALES s",
        "JOIN CHANNELS c ON s.CHANNEL_ID = c.CHANNEL_ID",
        "JOIN TIMES t ON s.TIME_ID = t.TIME_ID",
        "GROUP BY t.TIME_ID, c.CHANNEL_DESC",
        "ORDER BY t.TIME_ID, c.CHANNEL_DESC",
    ))


def _revenue_by_promotion_day_sql(*, promo_column: str, promo_alias: str) -> str:
    return "\n".join((
        "SELECT",
        "  t.TIME_ID AS day,",
        f"  pr.{promo_column} AS {promo_alias},",
        "  SUM(s.AMOUNT_SOLD) AS revenue",
        "FROM SALES s",
        "JOIN PROMOTIONS pr ON s.PROMO_ID = pr.PROMO_ID",
        "JOIN TIMES t ON s.TIME_ID = t.TIME_ID",
        f"GROUP BY t.TIME_ID, pr.{promo_column}",
        f"ORDER BY t.TIME_ID, pr.{promo_column}",
    ))


def _revenue_measure() -> dict[str, str]:
    return {
        "table_id": "SH.SALES",
        "column": "AMOUNT_SOLD",
        "expression": "SUM(s.AMOUNT_SOLD)",
        "alias": "revenue",
    }


def _sales_time_join() -> dict[str, str]:
    return {
        "from_table_id": "SH.SALES",
        "from_column": "TIME_ID",
        "to_table_id": "SH.TIMES",
        "to_column": "TIME_ID",
    }


def _required_table_names(table_ids: set[str]) -> str:
    return ", ".join(table_id.removeprefix("SH.") for table_id in sorted(table_ids))


def _schema_context_refs(compact_context: CompactSchemaResult) -> dict[str, Any]:
    return {
        "profile_id": compact_context.profile_id,
        "schema_metadata_artifact_id": compact_context.schema_metadata_artifact_id,
        "curated_seed_artifact_id": compact_context.curated_seed_artifact_id,
        "schema_metadata_version": compact_context.schema_metadata_version,
        "curated_seed_version": compact_context.curated_seed_version,
        "masking_policy_version": compact_context.masking_policy_version,
        "request_terms": list(compact_context.request_terms),
        "selected_table_ids": list(compact_context.selected_table_ids),
        "glossary_matches": compact_context.glossary_matches,
        "considered_tables": compact_context.considered_tables,
        "rejected_tables": compact_context.rejected_tables,
    }


def _closed_execution_boundary() -> dict[str, Any]:
    return {
        "enabled": False,
        "status": "not_executed",
        "reason": "Milestone 6 query plans are proposed and policy-validated only.",
    }


def _not_evaluated_policy(reason: str) -> dict[str, Any]:
    return {
        "validator": "oracle_adw.read_only_sql_policy",
        "allowed": False,
        "code": "not_evaluated",
        "reason": reason,
    }


__all__ = [
    "QUERY_PLAN_SCHEMA_VERSION",
    "QueryPlanArtifact",
    "build_query_plan_from_context",
    "validate_query_plan_sql",
]
