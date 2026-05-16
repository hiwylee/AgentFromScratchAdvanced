"""Structured user intent analysis for the first agent milestone."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List


WRITE_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "merge",
    "삭제",
    "수정",
    "변경",
    "추가",
    "생성",
)

DB_KEYWORDS = (
    "adw",
    "oracle",
    "sql",
    "query",
    "schema",
    "table",
    "column",
    "database",
    "db",
    "데이터",
    "테이블",
    "컬럼",
    "스키마",
    "쿼리",
    "매출",
    "고객",
    "상품",
)

METRIC_KEYWORDS = {
    "revenue": ("매출", "revenue", "sales", "amount"),
    "count": ("건수", "수", "count", "number"),
}

DIMENSION_KEYWORDS = {
    "customer": ("고객", "customer", "client"),
    "product": ("상품", "제품", "product", "item"),
    "region": ("지역", "region", "area"),
}

TIME_RANGE_KEYWORDS = {
    "previous_month": ("지난달", "전월", "previous month", "last month"),
    "monthly": ("월별", "monthly", "month by month"),
    "daily": ("일별", "daily", "day by day"),
}

TREND_KEYWORDS = ("추이", "trend", "변화", "증감")
COMPARE_KEYWORDS = ("비교", "compare", "versus", "vs")
AGGREGATE_KEYWORDS = ("상위", "합계", "평균", "sum", "avg", "average", "top")


@dataclass(frozen=True)
class UserIntent:
    intent_type: str
    task_type: str
    safety_level: str
    requires_oracle_adw_context: bool
    entities: Dict[str, List[str]] = field(default_factory=dict)
    required_context: List[str] = field(default_factory=list)
    ambiguities: List[str] = field(default_factory=list)
    next_action: str = "answer_directly"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def analyze_user_intent(text: str) -> UserIntent:
    normalized = text.casefold()
    requires_db = any(keyword in normalized for keyword in DB_KEYWORDS)
    unsafe_write = any(keyword in normalized for keyword in WRITE_KEYWORDS)

    if not requires_db:
        return UserIntent(
            intent_type="general",
            task_type="general_request",
            safety_level="normal",
            requires_oracle_adw_context=False,
            entities={},
            required_context=[],
            ambiguities=[],
            next_action="answer_directly",
        )

    metrics = _matches(normalized, METRIC_KEYWORDS)
    dimensions = _matches(normalized, DIMENSION_KEYWORDS)
    time_ranges = _matches(normalized, TIME_RANGE_KEYWORDS)
    task_type = _db_task_type(normalized)

    required_context = ["oracle_adw_schema"]
    ambiguities: List[str] = []

    if metrics:
        required_context.append("business_glossary")
        ambiguities.append("metric_definition")
    if dimensions:
        ambiguities.append("dimension_table_mapping")
    if not metrics and task_type in {"aggregation", "trend_analysis", "comparison"}:
        ambiguities.append("metric_not_identified")
    if not dimensions and task_type in {"aggregation", "trend_analysis", "comparison"}:
        ambiguities.append("dimension_not_identified")

    safety_level = "blocked_write_request" if unsafe_write else "read_only"
    if unsafe_write:
        next_action = "refuse_or_request_explicit_safe_alternative"
    elif ambiguities:
        next_action = "inspect_schema_then_clarify"
    else:
        next_action = "inspect_schema"

    return UserIntent(
        intent_type="database_analysis",
        task_type=task_type,
        safety_level=safety_level,
        requires_oracle_adw_context=True,
        entities={
            "metrics": metrics,
            "dimensions": dimensions,
            "time_ranges": time_ranges,
        },
        required_context=sorted(set(required_context)),
        ambiguities=sorted(set(ambiguities)),
        next_action=next_action,
    )


def _matches(text: str, groups: Dict[str, tuple[str, ...]]) -> List[str]:
    found = []
    for name, keywords in groups.items():
        if any(keyword in text for keyword in keywords):
            found.append(name)
    return found


def _db_task_type(text: str) -> str:
    if any(keyword in text for keyword in TREND_KEYWORDS):
        return "trend_analysis"
    if any(keyword in text for keyword in COMPARE_KEYWORDS):
        return "comparison"
    if any(keyword in text for keyword in AGGREGATE_KEYWORDS):
        return "aggregation"
    if any(keyword in text for keyword in ("스키마", "schema", "테이블", "table")):
        return "metadata_exploration"
    return "lookup"
