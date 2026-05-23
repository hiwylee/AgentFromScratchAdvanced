"""Unit tests for ToolSpec.capabilities and find_tools_by_capabilities."""

import unittest

from agent_runtime.tools import (
    ToolParameter,
    ToolRegistry,
    ToolSpec,
    default_tool_registry,
    find_tools_by_capabilities,
)


def _make_registry(*specs_and_handlers) -> ToolRegistry:
    registry = ToolRegistry()
    for spec, handler in specs_and_handlers:
        registry.register(spec, handler)
    return registry


class ToolSpecCapabilitiesTests(unittest.TestCase):
    def test_toolspec_capabilities_default_empty(self):
        spec = ToolSpec(name="echo", description="Echo.")
        self.assertEqual((), spec.capabilities)

    def test_toolspec_cost_estimate_default_fast(self):
        spec = ToolSpec(name="echo", description="Echo.")
        self.assertEqual("fast", spec.cost_estimate)

    def test_toolspec_capabilities_in_to_dict(self):
        spec = ToolSpec(
            name="echo",
            description="Echo.",
            capabilities=("oracle_sh.schema.read",),
            cost_estimate="medium",
        )
        d = spec.to_dict()
        self.assertEqual(["oracle_sh.schema.read"], d["capabilities"])
        self.assertEqual("medium", d["cost_estimate"])

    def test_mock_schema_context_has_capabilities(self):
        registry = default_tool_registry()
        specs = registry.specs()
        mock_spec = next(s for s in specs if s["name"] == "mock_schema_context")
        self.assertIn("oracle_sh.schema.read", mock_spec["capabilities"])
        self.assertEqual("fast", mock_spec["cost_estimate"])


class FindToolsByCapabilitiesTests(unittest.TestCase):
    def _build_registry(self) -> ToolRegistry:
        return _make_registry(
            (
                ToolSpec(
                    name="schema_reader",
                    description="Read schema.",
                    capabilities=("oracle_sh.schema.read",),
                    read_only=True,
                    risk_level="low",
                ),
                lambda args: {},
            ),
            (
                ToolSpec(
                    name="data_writer",
                    description="Write data.",
                    capabilities=("oracle_sh.data.write",),
                    read_only=False,
                    risk_level="low",
                ),
                lambda args: {},
            ),
            (
                ToolSpec(
                    name="high_risk_reader",
                    description="High risk read.",
                    capabilities=("oracle_sh.data.read",),
                    read_only=True,
                    risk_level="high",
                ),
                lambda args: {},
            ),
            (
                ToolSpec(
                    name="no_caps",
                    description="No capabilities.",
                    capabilities=(),
                    read_only=True,
                    risk_level="low",
                ),
                lambda args: {},
            ),
        )

    def test_returns_matching_tool(self):
        registry = self._build_registry()
        results = find_tools_by_capabilities(registry, ["oracle_sh.schema.read"])
        names = [s.name for s in results]
        self.assertIn("schema_reader", names)

    def test_empty_required_returns_empty(self):
        registry = self._build_registry()
        results = find_tools_by_capabilities(registry, [])
        self.assertEqual([], results)

    def test_tool_without_capabilities_not_matched(self):
        registry = self._build_registry()
        results = find_tools_by_capabilities(registry, ["oracle_sh.schema.read"])
        names = [s.name for s in results]
        self.assertNotIn("no_caps", names)

    def test_action_none_skips_policy_check(self):
        # Without action (action=None), policy is skipped — write and high-risk tools returned
        registry = self._build_registry()
        results = find_tools_by_capabilities(
            registry,
            ["oracle_sh.data.write", "oracle_sh.data.read"],
            action=None,
        )
        names = [s.name for s in results]
        self.assertIn("data_writer", names)
        self.assertIn("high_risk_reader", names)

    def test_action_provided_blocks_write_tool(self):
        from agent_runtime.types import Action

        registry = self._build_registry()
        action = Action(kind="inspect_schema", reason="test")
        results = find_tools_by_capabilities(
            registry,
            ["oracle_sh.data.write"],
            action=action,
        )
        names = [s.name for s in results]
        self.assertNotIn("data_writer", names)

    def test_action_provided_blocks_high_risk_tool(self):
        from agent_runtime.types import Action

        registry = self._build_registry()
        action = Action(kind="inspect_schema", reason="test")
        results = find_tools_by_capabilities(
            registry,
            ["oracle_sh.data.read"],
            action=action,
        )
        names = [s.name for s in results]
        self.assertNotIn("high_risk_reader", names)

    def test_action_provided_allows_low_risk_read_only_tool(self):
        from agent_runtime.types import Action

        registry = self._build_registry()
        action = Action(kind="inspect_schema", reason="test")
        results = find_tools_by_capabilities(
            registry,
            ["oracle_sh.schema.read"],
            action=action,
        )
        names = [s.name for s in results]
        self.assertIn("schema_reader", names)

    def test_partial_match_includes_tool(self):
        # Only one of the required capabilities needs to match
        registry = self._build_registry()
        results = find_tools_by_capabilities(
            registry,
            ["oracle_sh.schema.read", "nonexistent.cap"],
        )
        names = [s.name for s in results]
        self.assertIn("schema_reader", names)

    def test_no_match_returns_empty(self):
        registry = self._build_registry()
        results = find_tools_by_capabilities(registry, ["nonexistent.capability"])
        self.assertEqual([], results)

    def test_default_registry_mock_tool_matched_by_capability(self):
        registry = default_tool_registry()
        results = find_tools_by_capabilities(registry, ["oracle_sh.schema.read"])
        names = [s.name for s in results]
        self.assertIn("mock_schema_context", names)


if __name__ == "__main__":
    unittest.main()
