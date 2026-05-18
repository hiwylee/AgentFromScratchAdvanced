from dataclasses import replace
import os
import unittest

from agent_runtime.query_plan import QUERY_PLAN_SCHEMA_VERSION, QueryPlanArtifact
from agent_runtime.redaction import REDACTION
from agent_runtime.result_explanation import (
    RESULT_EXPLANATION_SCHEMA_VERSION,
    build_fake_result_explanation,
)
from agent_runtime.sql_execution import FakeSqlExecutionAdapter, SqlExecutionRequest


class ResultExplanationTests(unittest.TestCase):
    def test_builds_successful_fake_result_explanation(self):
        adapter = FakeSqlExecutionAdapter(
            rows=(
                {"MONTH": "1998-01", "PRODUCT_CATEGORY": "Hardware", "REVENUE": 1250},
                {"MONTH": "1998-02", "PRODUCT_CATEGORY": "Hardware", "REVENUE": 1410},
            ),
            metadata={"fixture_id": "unit-fake-results"},
        )

        artifact = build_fake_result_explanation(_planned_query_plan(), adapter)
        payload = artifact.to_dict()

        self.assertEqual(RESULT_EXPLANATION_SCHEMA_VERSION, artifact.schema_version)
        self.assertEqual(QUERY_PLAN_SCHEMA_VERSION, artifact.query_plan_schema_version)
        self.assertEqual("succeeded", artifact.status)
        self.assertEqual("fake/deterministic", artifact.source)
        self.assertFalse(artifact.real_database_execution)
        self.assertEqual("fake", artifact.sql_execution_backend)
        self.assertEqual(("MONTH", "PRODUCT_CATEGORY", "REVENUE"), artifact.columns)
        self.assertEqual(2, artifact.row_count)
        self.assertEqual("unit-fake-results", artifact.adapter_response_metadata["fixture_id"])
        self.assertIn("Fake deterministic execution returned 2 rows", artifact.summary)
        self.assertIn("not from Oracle ADW", artifact.explanation)
        self.assertEqual("not_executed", payload["query_plan"]["execution"]["status"])

    def test_blocked_query_plan_does_not_call_adapter(self):
        adapter = RecordingAdapter()
        blocked_plan = replace(
            _planned_query_plan(),
            status="blocked",
            proposed_sql=None,
            policy_validation={
                "validator": "oracle_adw.read_only_sql_policy",
                "allowed": False,
                "code": "not_evaluated",
                "reason": "unsupported_query_pattern",
            },
            refusal_reason="unsupported query-plan pattern",
        )

        artifact = build_fake_result_explanation(blocked_plan, adapter)

        self.assertEqual("blocked", artifact.status)
        self.assertEqual(0, adapter.call_count)
        self.assertEqual((), artifact.rows)
        self.assertFalse(artifact.real_database_execution)
        self.assertIsNone(artifact.proposed_sql)
        self.assertIn("unsupported query-plan pattern", artifact.explanation)

    def test_fake_adapter_rejection_blocks_and_redacts_sql(self):
        unsafe_plan = replace(
            _planned_query_plan(),
            proposed_sql="delete from customers",
        )

        artifact = build_fake_result_explanation(unsafe_plan, FakeSqlExecutionAdapter())
        payload = artifact.to_dict()

        self.assertEqual("rejected", artifact.status)
        self.assertEqual("fake", artifact.sql_execution_backend)
        self.assertFalse(artifact.real_database_execution)
        self.assertIsNone(artifact.proposed_sql)
        self.assertEqual((), artifact.rows)
        self.assertEqual(0, artifact.row_count)
        self.assertEqual("write_or_admin_sql", payload["execution_response"]["error"]["code"])
        self.assertNotIn("delete from customers", str(payload).lower())

    def test_redaction_and_no_real_execution_marker(self):
        os.environ["RESULT_EXPLANATION_TEST_PASSWORD"] = "db-secret-value"
        try:
            adapter = FakeSqlExecutionAdapter(
                rows=({"MONTH": "1998-01", "REVENUE": 100},),
                metadata={
                    "password": "db-secret-value",
                    "source_note": "fixture contains db-secret-value marker",
                },
            )
            plan = replace(
                _planned_query_plan(),
                request_text="show revenue by month using db-secret-value",
            )

            payload = build_fake_result_explanation(plan, adapter).to_dict()
            rendered = str(payload)

            self.assertEqual("fake/deterministic", payload["source"])
            self.assertFalse(payload["real_database_execution"])
            self.assertEqual("fake", payload["sql_execution_backend"])
            self.assertEqual(REDACTION, payload["adapter_response_metadata"]["password"])
            self.assertNotIn("db-secret-value", rendered)
            self.assertIn(REDACTION, rendered)
        finally:
            os.environ.pop("RESULT_EXPLANATION_TEST_PASSWORD", None)


class RecordingAdapter:
    backend = "fake"

    def __init__(self) -> None:
        self.call_count = 0

    def execute(self, request: SqlExecutionRequest):
        self.call_count += 1
        raise AssertionError(f"adapter should not be called for {request.sql}")


def _planned_query_plan() -> QueryPlanArtifact:
    return QueryPlanArtifact(
        schema_version=QUERY_PLAN_SCHEMA_VERSION,
        profile_id="oracle_adw_sh.v1",
        status="planned",
        request_text="show revenue by product by month",
        selected_table_ids=("SH.SALES", "SH.PRODUCTS", "SH.TIMES"),
        proposed_sql="\n".join(
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
        ),
        policy_validation={
            "validator": "oracle_adw.read_only_sql_policy",
            "allowed": True,
            "code": "allowed",
            "reason": "read-only select statement",
        },
        assumptions=("The proposed SQL is not executed in this milestone.",),
        dimensions=(
            {"table_id": "SH.TIMES", "column": "CALENDAR_MONTH_DESC", "alias": "month"},
            {"table_id": "SH.PRODUCTS", "column": "PROD_CATEGORY", "alias": "product_category"},
        ),
        measures=(
            {
                "table_id": "SH.SALES",
                "column": "AMOUNT_SOLD",
                "expression": "SUM(s.AMOUNT_SOLD)",
                "alias": "revenue",
            },
        ),
        joins=(
            {
                "from_table_id": "SH.SALES",
                "from_column": "PROD_ID",
                "to_table_id": "SH.PRODUCTS",
                "to_column": "PROD_ID",
            },
        ),
        execution={
            "enabled": False,
            "status": "not_executed",
            "reason": "Milestone 6 query plans are proposed and policy-validated only.",
        },
    )


if __name__ == "__main__":
    unittest.main()
