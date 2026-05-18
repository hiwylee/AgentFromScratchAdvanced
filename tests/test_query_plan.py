from dataclasses import replace
from pathlib import Path
import unittest

from agent_runtime.query_plan import (
    QUERY_PLAN_SCHEMA_VERSION,
    build_query_plan_from_context,
    validate_query_plan_sql,
)
from agent_runtime.schema_context import (
    build_compact_schema_context,
    load_schema_artifacts,
)


SCHEMA_CONTEXT_ROOT = Path("docs/generated/schema-context")


class QueryPlanTests(unittest.TestCase):
    def test_builds_policy_validated_revenue_product_month_plan_without_execution(self):
        compact = _compact_context()

        plan = build_query_plan_from_context(
            compact,
            request_text="show revenue by product by month",
        )
        payload = plan.to_dict()

        self.assertEqual(QUERY_PLAN_SCHEMA_VERSION, plan.schema_version)
        self.assertEqual("planned", plan.status)
        self.assertEqual("oracle_adw_sh.v1", plan.profile_id)
        self.assertFalse(plan.execution["enabled"])
        self.assertEqual("not_executed", plan.execution["status"])
        self.assertTrue(plan.policy_validation["allowed"])
        self.assertEqual("allowed", plan.policy_validation["code"])
        self.assertIn("SUM(s.AMOUNT_SOLD)", plan.proposed_sql)
        self.assertIn("JOIN PRODUCTS p ON s.PROD_ID = p.PROD_ID", plan.proposed_sql)
        self.assertIn("JOIN TIMES t ON s.TIME_ID = t.TIME_ID", plan.proposed_sql)
        self.assertIn("SH.SALES", plan.selected_table_ids)
        self.assertIn("SH.PRODUCTS", plan.selected_table_ids)
        self.assertIn("SH.TIMES", plan.selected_table_ids)
        self.assertEqual("SH.SALES", plan.measures[0]["table_id"])
        self.assertIn("schema_metadata_artifact_id", payload["schema_context"])

    def test_builds_policy_validated_revenue_channel_month_plan_without_execution(self):
        compact = _compact_context(
            request_text="show revenue by channel by month",
            request_terms=["revenue", "channel", "month"],
        )

        plan = build_query_plan_from_context(
            compact,
            request_text="show revenue by channel by month",
        )

        self.assertEqual("planned", plan.status)
        self.assertFalse(plan.execution["enabled"])
        self.assertEqual("not_executed", plan.execution["status"])
        self.assertTrue(plan.policy_validation["allowed"])
        self.assertIn("SUM(s.AMOUNT_SOLD)", plan.proposed_sql)
        self.assertIn("JOIN CHANNELS c ON s.CHANNEL_ID = c.CHANNEL_ID", plan.proposed_sql)
        self.assertIn("JOIN TIMES t ON s.TIME_ID = t.TIME_ID", plan.proposed_sql)
        self.assertIn("SH.SALES", plan.selected_table_ids)
        self.assertIn("SH.CHANNELS", plan.selected_table_ids)
        self.assertIn("SH.TIMES", plan.selected_table_ids)
        self.assertEqual(
            {"table_id": "SH.CHANNELS", "column": "CHANNEL_DESC", "alias": "channel"},
            plan.dimensions[1],
        )

    def test_builds_policy_validated_revenue_promotion_month_plan_without_execution(self):
        compact = _compact_context(
            request_text="show revenue by promotion by month",
            request_terms=["revenue", "promotion", "month"],
        )

        plan = build_query_plan_from_context(
            compact,
            request_text="show revenue by promotion by month",
        )

        self.assertEqual("planned", plan.status)
        self.assertFalse(plan.execution["enabled"])
        self.assertEqual("not_executed", plan.execution["status"])
        self.assertTrue(plan.policy_validation["allowed"])
        self.assertIn("SUM(s.AMOUNT_SOLD)", plan.proposed_sql)
        self.assertIn("JOIN PROMOTIONS pr ON s.PROMO_ID = pr.PROMO_ID", plan.proposed_sql)
        self.assertIn("JOIN TIMES t ON s.TIME_ID = t.TIME_ID", plan.proposed_sql)
        self.assertIn("SH.SALES", plan.selected_table_ids)
        self.assertIn("SH.PROMOTIONS", plan.selected_table_ids)
        self.assertIn("SH.TIMES", plan.selected_table_ids)
        self.assertEqual(
            {
                "table_id": "SH.PROMOTIONS",
                "column": "PROMO_CATEGORY",
                "alias": "promotion_category",
            },
            plan.dimensions[1],
        )

    def test_promotion_subcategory_request_uses_subcategory_dimension(self):
        compact = _compact_context(
            request_text="show revenue by promotion subcategory by month",
            request_terms=["revenue", "promotion subcategory", "month"],
        )

        plan = build_query_plan_from_context(
            compact,
            request_text="show revenue by promotion subcategory by month",
        )

        self.assertEqual("planned", plan.status)
        self.assertTrue(plan.policy_validation["allowed"])
        self.assertIn("pr.PROMO_SUBCATEGORY AS promotion_subcategory", plan.proposed_sql)
        self.assertEqual(
            {
                "table_id": "SH.PROMOTIONS",
                "column": "PROMO_SUBCATEGORY",
                "alias": "promotion_subcategory",
            },
            plan.dimensions[1],
        )

    def test_clarification_context_does_not_propose_sql(self):
        compact = replace(
            _compact_context(),
            selected_table_ids=[],
            clarification={
                "required": True,
                "reason": "ambiguous_schema_match",
                "candidate_table_ids": ["SH.PRODUCTS", "SH.CHANNELS"],
            },
        )

        plan = build_query_plan_from_context(compact, request_text="show sales by category")

        self.assertEqual("clarification_required", plan.status)
        self.assertIsNone(plan.proposed_sql)
        self.assertFalse(plan.policy_validation["allowed"])
        self.assertEqual("not_evaluated", plan.policy_validation["code"])
        self.assertEqual("ambiguous_schema_match", plan.refusal_reason)

    def test_missing_required_context_blocks_plan(self):
        compact = replace(
            _compact_context(),
            selected_table_ids=["SH.SALES", "SH.PRODUCTS"],
        )

        plan = build_query_plan_from_context(compact, request_text="show revenue by product by month")

        self.assertEqual("blocked", plan.status)
        self.assertIsNone(plan.proposed_sql)
        self.assertIn("SH.TIMES", plan.refusal_reason)
        self.assertEqual("missing_required_schema_context", plan.policy_validation["reason"])

    def test_channel_pattern_missing_context_blocks_plan(self):
        compact = replace(
            _compact_context(
                request_text="show revenue by channel by month",
                request_terms=["revenue", "channel", "month"],
            ),
            selected_table_ids=["SH.SALES", "SH.TIMES"],
        )

        plan = build_query_plan_from_context(compact, request_text="show revenue by channel by month")

        self.assertEqual("blocked", plan.status)
        self.assertIsNone(plan.proposed_sql)
        self.assertIn("SH.CHANNELS", plan.refusal_reason)
        self.assertEqual("missing_required_schema_context", plan.policy_validation["reason"])

    def test_unsupported_pattern_blocks_instead_of_guessing(self):
        compact = _compact_context(
            request_text="show revenue by month",
            request_terms=["revenue", "month"],
        )

        plan = build_query_plan_from_context(compact, request_text="show revenue by month")

        self.assertEqual("blocked", plan.status)
        self.assertIsNone(plan.proposed_sql)
        self.assertEqual("unsupported_query_pattern", plan.policy_validation["reason"])

    def test_customer_country_region_patterns_block_instead_of_guessing(self):
        cases = (
            (
                "show revenue by customer by month",
                ["revenue", "customer", "month"],
            ),
            (
                "show revenue by country by month",
                ["revenue", "country", "month"],
            ),
            (
                "show revenue by region by month",
                ["revenue", "region", "month"],
            ),
        )
        for request_text, request_terms in cases:
            with self.subTest(request_text=request_text):
                compact = _compact_context(
                    request_text=request_text,
                    request_terms=request_terms,
                )

                plan = build_query_plan_from_context(compact, request_text=request_text)

                self.assertEqual("blocked", plan.status)
                self.assertIsNone(plan.proposed_sql)
                self.assertEqual("unsupported_query_pattern", plan.policy_validation["reason"])

    def test_promotion_without_revenue_or_month_blocks_instead_of_guessing(self):
        compact = _compact_context(
            request_text="show campaign cost by promotion",
            request_terms=["campaign cost", "promotion"],
        )

        plan = build_query_plan_from_context(
            compact,
            request_text="show campaign cost by promotion",
        )

        self.assertEqual("blocked", plan.status)
        self.assertIsNone(plan.proposed_sql)
        self.assertEqual("unsupported_query_pattern", plan.policy_validation["reason"])

    def test_channel_without_revenue_or_month_blocks_instead_of_guessing(self):
        compact = _compact_context(
            request_text="show channels",
            request_terms=["channel"],
        )

        plan = build_query_plan_from_context(
            compact,
            request_text="show channels",
        )

        self.assertEqual("blocked", plan.status)
        self.assertIsNone(plan.proposed_sql)
        self.assertEqual("unsupported_query_pattern", plan.policy_validation["reason"])

    def test_product_without_revenue_or_month_blocks_instead_of_guessing(self):
        compact = _compact_context(
            request_text="show products",
            request_terms=["product"],
        )

        plan = build_query_plan_from_context(
            compact,
            request_text="show products",
        )

        self.assertEqual("blocked", plan.status)
        self.assertIsNone(plan.proposed_sql)
        self.assertEqual("unsupported_query_pattern", plan.policy_validation["reason"])

    def test_policy_validation_rejects_unsafe_sql(self):
        validation = validate_query_plan_sql("delete from customers")

        self.assertFalse(validation["allowed"])
        self.assertEqual("write_or_admin_sql", validation["code"])


def _compact_context(
    *,
    request_text="show revenue by product by month",
    request_terms=None,
):
    artifacts = load_schema_artifacts(
        SCHEMA_CONTEXT_ROOT / "oracle_adw_sh.schema-metadata.v1.json",
        SCHEMA_CONTEXT_ROOT / "oracle_adw_sh.curated-seed.v1.json",
        expected_profile_id="oracle_adw_sh.v1",
    )
    return build_compact_schema_context(
        artifacts,
        request_text=request_text,
        request_terms=request_terms or ["revenue", "product", "month"],
    )


if __name__ == "__main__":
    unittest.main()
