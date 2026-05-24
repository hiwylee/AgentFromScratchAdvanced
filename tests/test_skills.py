"""Unit tests for SkillSpec and SkillRegistry (agent_runtime.skills).

Coverage targets:
- SkillSpec.to_dict() excludes handler field
- SkillSpec.to_dict() includes name, description, required_capabilities, version
- SkillSpec is frozen (FrozenInstanceError on field re-assignment)
- SkillRegistry.register() + get() round-trip
- SkillRegistry.get() raises KeyError for unknown skill name
- SkillRegistry.register() raises ValueError on duplicate name
- SkillRegistry.register() raises ValueError on name containing spaces
- SkillRegistry.register() raises ValueError on empty name
- SkillRegistry.find_by_capabilities() returns skills that intersect the required set
- SkillRegistry.find_by_capabilities() returns [] when no skills intersect
- SkillRegistry.find_by_capabilities() returns [] when required list is empty
- SkillRegistry.all_registered() returns [] on fresh registry
- SkillRegistry.all_registered() includes spec after register
- SkillRegistry.specs() (to_dict results) never contains handler field
- SkillSpec with non-callable handler raises ValueError on register
- SkillRegistry.find_by_capabilities() returns all matching skills when several qualify
"""

import unittest
from dataclasses import FrozenInstanceError

from agent_runtime.skills import SkillRegistry, SkillSpec


def _dummy_handler(args: dict) -> dict:
    return {"ok": True}


def _make_spec(
    name: str = "test_skill",
    description: str = "A test skill.",
    required_capabilities: tuple = ("sql_read",),
    handler=_dummy_handler,
    version: str = "1.0",
) -> SkillSpec:
    return SkillSpec(
        name=name,
        description=description,
        required_capabilities=required_capabilities,
        handler=handler,
        version=version,
    )


class SkillSpecTests(unittest.TestCase):

    def test_spec_to_dict_excludes_handler(self):
        """to_dict() must not expose the handler callable."""
        spec = _make_spec()

        result = spec.to_dict()

        self.assertNotIn("handler", result)

    def test_spec_to_dict_has_required_fields(self):
        """to_dict() includes name, description, required_capabilities, and version."""
        spec = _make_spec(
            name="revenue_skill",
            description="Builds revenue queries.",
            required_capabilities=("sql_read", "schema_context"),
            version="2.0",
        )

        result = spec.to_dict()

        self.assertEqual("revenue_skill", result["name"])
        self.assertEqual("Builds revenue queries.", result["description"])
        self.assertEqual(["sql_read", "schema_context"], result["required_capabilities"])
        self.assertEqual("2.0", result["version"])

    def test_spec_frozen_cannot_mutate(self):
        """Assigning to a field on a frozen SkillSpec raises FrozenInstanceError."""
        spec = _make_spec()

        with self.assertRaises(FrozenInstanceError):
            spec.name = "mutated_name"  # type: ignore[misc]


class SkillRegistryRegisterAndGetTests(unittest.TestCase):

    def test_register_and_get(self):
        """A registered skill is retrievable by its exact name."""
        registry = SkillRegistry()
        spec = _make_spec(name="my_skill")
        registry.register(spec)

        result = registry.get("my_skill")

        self.assertIs(spec, result)

    def test_get_unknown_raises_key_error(self):
        """get() raises KeyError when the skill name was never registered."""
        registry = SkillRegistry()

        with self.assertRaises(KeyError):
            registry.get("not_registered")

    def test_duplicate_register_raises(self):
        """Registering a skill whose name is already registered raises ValueError."""
        registry = SkillRegistry()
        registry.register(_make_spec(name="dup_skill"))

        with self.assertRaises(ValueError):
            registry.register(_make_spec(name="dup_skill"))

    def test_invalid_name_raises(self):
        """A name containing a space (not alphanumeric/dash/underscore) raises ValueError."""
        registry = SkillRegistry()
        spec = _make_spec(name="bad name")

        with self.assertRaises(ValueError):
            registry.register(spec)

    def test_empty_name_raises(self):
        """An empty-string skill name raises ValueError on register."""
        registry = SkillRegistry()
        spec = _make_spec(name="")

        with self.assertRaises(ValueError):
            registry.register(spec)

    def test_non_callable_handler_raises(self):
        """A SkillSpec carrying a non-callable handler raises ValueError on register."""
        registry = SkillRegistry()
        # Bypass frozen validation by constructing with object() as handler
        # then rely on register() to detect it.
        spec = SkillSpec(
            name="bad_handler_skill",
            description="Has a non-callable handler.",
            required_capabilities=("sql_read",),
            handler=object(),  # type: ignore[arg-type]
        )

        with self.assertRaises(ValueError):
            registry.register(spec)


class SkillRegistryFindByCapabilitiesTests(unittest.TestCase):

    def test_find_by_capabilities_match(self):
        """Skills whose required_capabilities intersect the query are returned."""
        registry = SkillRegistry()
        registry.register(_make_spec(name="sql_skill", required_capabilities=("sql_read", "schema_context")))

        results = registry.find_by_capabilities(["sql_read"])

        self.assertEqual(1, len(results))
        self.assertEqual("sql_skill", results[0].name)

    def test_find_by_capabilities_no_match(self):
        """find_by_capabilities() returns [] when no skill intersects the required set."""
        registry = SkillRegistry()
        registry.register(_make_spec(name="sql_skill", required_capabilities=("sql_read",)))

        results = registry.find_by_capabilities(["vision", "audio"])

        self.assertEqual([], results)

    def test_find_by_capabilities_empty_required(self):
        """find_by_capabilities() returns [] when the required list is empty."""
        registry = SkillRegistry()
        registry.register(_make_spec(name="sql_skill", required_capabilities=("sql_read",)))

        results = registry.find_by_capabilities([])

        self.assertEqual([], results)

    def test_find_returns_multiple_matching_skills(self):
        """All skills that intersect the required capabilities are returned."""
        registry = SkillRegistry()
        registry.register(_make_spec(name="skill_a", required_capabilities=("sql_read", "schema_context")))
        registry.register(_make_spec(name="skill_b", required_capabilities=("schema_context", "audit")))
        registry.register(_make_spec(name="skill_c", required_capabilities=("unrelated",)))

        results = registry.find_by_capabilities(["schema_context"])

        names = {r.name for r in results}
        self.assertIn("skill_a", names)
        self.assertIn("skill_b", names)
        self.assertNotIn("skill_c", names)


class SkillRegistryIntrospectionTests(unittest.TestCase):

    def test_all_registered_empty(self):
        """all_registered() returns an empty list on a fresh registry."""
        registry = SkillRegistry()

        self.assertEqual([], registry.all_registered())

    def test_all_registered_after_register(self):
        """all_registered() contains the registered SkillSpec after register()."""
        registry = SkillRegistry()
        spec = _make_spec(name="introspect_skill")
        registry.register(spec)

        result = registry.all_registered()

        self.assertIn(spec, result)

    def test_specs_excludes_handler(self):
        """specs() returns dicts produced by to_dict(), which never include handler."""
        registry = SkillRegistry()
        registry.register(_make_spec(name="dict_skill"))

        for spec_dict in registry.specs():
            self.assertNotIn("handler", spec_dict)


if __name__ == "__main__":
    unittest.main()
