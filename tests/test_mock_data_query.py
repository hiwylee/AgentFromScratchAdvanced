"""Unit tests for mock_data_query tool and default_skill_registry().

Coverage targets:
- mock_data_query is registered in default_tool_registry()
- capability is oracle_sh.data.read
- read_only=True
- risk_level="low"
- handler returns rows with row_count > 0
- handler output has real_database_execution: False, oracle_adw_execution: False
- dimension parameter is reflected in result rows
- missing dimension falls back to default ("product")
- default_skill_registry() contains schema_and_query skill
- schema_and_query required_capabilities includes oracle_sh.schema.read and oracle_sh.data.read
- find_by_capabilities(["oracle_sh.data.read"]) returns schema_and_query
- schema_and_query handler returns dict with required_capabilities key
"""

import unittest

from agent_runtime.skills import SkillRegistry, default_skill_registry
from agent_runtime.tools import (
    ToolCall,
    default_tool_registry,
    find_tools_by_capabilities,
)

# Direct import of the private handler for handler-only tests (avoids ToolRunner overhead).
from agent_runtime.tools import _mock_data_query  # type: ignore[attr-defined]


class MockDataQueryRegistrationTests(unittest.TestCase):

    def test_mock_data_query_registered_in_default_registry(self):
        """default_tool_registry() includes mock_data_query."""
        registry = default_tool_registry()

        names = [registered.spec.name for registered in registry.all_registered()]

        self.assertIn("mock_data_query", names)

    def test_mock_data_query_capability_is_data_read(self):
        """mock_data_query spec carries the oracle_sh.data.read capability."""
        registry = default_tool_registry()

        spec = registry.get("mock_data_query").spec

        self.assertIn("oracle_sh.data.read", spec.capabilities)

    def test_mock_data_query_is_read_only(self):
        """mock_data_query spec has read_only=True."""
        registry = default_tool_registry()

        spec = registry.get("mock_data_query").spec

        self.assertTrue(spec.read_only)

    def test_mock_data_query_risk_level_low(self):
        """mock_data_query spec has risk_level='low'."""
        registry = default_tool_registry()

        spec = registry.get("mock_data_query").spec

        self.assertEqual("low", spec.risk_level)


class MockDataQueryHandlerTests(unittest.TestCase):

    def test_mock_data_query_returns_fake_rows(self):
        """Handler returns a non-empty rows list and a positive row_count."""
        result = _mock_data_query({})

        self.assertIn("rows", result)
        self.assertIsInstance(result["rows"], list)
        self.assertGreater(result["row_count"], 0)

    def test_mock_data_query_no_real_execution(self):
        """Handler output declares real_database_execution=False and oracle_adw_execution=False."""
        result = _mock_data_query({})

        self.assertFalse(result["real_database_execution"])
        self.assertFalse(result["oracle_adw_execution"])

    def test_mock_data_query_dimension_param(self):
        """The dimension parameter name is used as the key in each row dict."""
        result = _mock_data_query({"dimension": "channel"})

        self.assertEqual("channel", result["dimension"])
        for row in result["rows"]:
            self.assertIn("channel", row)

    def test_mock_data_query_default_dimension(self):
        """When dimension is omitted the handler defaults to 'product'."""
        result = _mock_data_query({})

        self.assertEqual("product", result["dimension"])
        for row in result["rows"]:
            self.assertIn("product", row)

    def test_mock_data_query_metric_param(self):
        """The metric parameter name is used as the value key in each row dict."""
        result = _mock_data_query({"metric": "count"})

        self.assertEqual("count", result["metric"])
        for row in result["rows"]:
            self.assertIn("count", row)

    def test_mock_data_query_query_plan_id_reflected(self):
        """query_plan_id argument is echoed back in the output."""
        result = _mock_data_query({"query_plan_id": "plan-abc-123"})

        self.assertEqual("plan-abc-123", result["query_plan_id"])

    def test_mock_data_query_mode_field(self):
        """Output contains mode='mock_data_query_read_only' to identify execution path."""
        result = _mock_data_query({})

        self.assertEqual("mock_data_query_read_only", result["mode"])

    def test_mock_data_query_external_access_false(self):
        """Handler declares external_access=False."""
        result = _mock_data_query({})

        self.assertFalse(result["external_access"])


class DefaultSkillRegistryTests(unittest.TestCase):

    def test_default_skill_registry_has_schema_and_query(self):
        """default_skill_registry() registers a skill named schema_and_query."""
        registry = default_skill_registry()

        names = [spec.name for spec in registry.all_registered()]

        self.assertIn("schema_and_query", names)

    def test_schema_and_query_skill_capabilities(self):
        """schema_and_query required_capabilities contains both schema.read and data.read."""
        registry = default_skill_registry()

        spec = registry.get("schema_and_query")

        self.assertIn("oracle_sh.schema.read", spec.required_capabilities)
        self.assertIn("oracle_sh.data.read", spec.required_capabilities)

    def test_find_by_capabilities_finds_schema_and_query(self):
        """find_by_capabilities(['oracle_sh.data.read']) returns schema_and_query."""
        registry = default_skill_registry()

        results = registry.find_by_capabilities(["oracle_sh.data.read"])

        names = [spec.name for spec in results]
        self.assertIn("schema_and_query", names)

    def test_schema_and_query_handler_returns_dict(self):
        """schema_and_query handler is callable and returns a dict with required_capabilities."""
        registry = default_skill_registry()
        spec = registry.get("schema_and_query")

        result = spec.handler({})

        self.assertIsInstance(result, dict)
        self.assertIn("required_capabilities", result)


class FindToolsByCapabilitiesDataReadTests(unittest.TestCase):

    def test_find_tools_by_capabilities_returns_mock_data_query(self):
        """find_tools_by_capabilities(['oracle_sh.data.read']) includes mock_data_query spec."""
        registry = default_tool_registry()

        results = find_tools_by_capabilities(registry, ["oracle_sh.data.read"])

        names = [spec.name for spec in results]
        self.assertIn("mock_data_query", names)


if __name__ == "__main__":
    unittest.main()
