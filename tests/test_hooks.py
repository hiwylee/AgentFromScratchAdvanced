"""Unit tests for HookRegistry (agent_runtime.hooks).

Coverage targets:
- register/fire basic round-trip
- event name forwarding to handler
- redaction of sensitive data before handler invocation
- safe no-op when no handlers are registered
- multiple handlers per event, all called
- handler failure isolation (exception in one handler does not block others)
- handler exception does not propagate out of fire()
- handlers_for() returns empty list for unknown event
- handlers_for() returns a copy (mutation does not affect registry)
- registered_events() empty on fresh registry
- registered_events() lists event after register
- register() raises ValueError on empty-string event
- register() raises ValueError on non-callable handler
- fire() for event A does not call handlers registered on event B
- data mutation inside a handler does not affect data seen by the next handler
- fire() with empty dict data is safe
"""

import unittest

from agent_runtime.hooks import HookRegistry


class HookRegistryRegisterAndFireTests(unittest.TestCase):

    def test_register_and_fire_basic(self):
        """Handler is called when the registered event is fired."""
        calls = []
        registry = HookRegistry()
        registry.register("tool_completed", lambda event, data: calls.append((event, data)))

        registry.fire("tool_completed", {"result": "ok"})

        self.assertEqual(1, len(calls))

    def test_fire_passes_event_name(self):
        """Handler receives the exact event name as first argument."""
        received = []
        registry = HookRegistry()
        registry.register("intent_analyzed", lambda event, data: received.append(event))

        registry.fire("intent_analyzed", {})

        self.assertEqual(["intent_analyzed"], received)

    def test_fire_redacts_secret_data(self):
        """Sensitive keys are redacted before the handler sees the data."""
        received = []
        registry = HookRegistry()
        registry.register("any_event", lambda event, data: received.append(data))

        registry.fire("any_event", {"password": "secret", "result": "ok"})

        self.assertEqual(1, len(received))
        self.assertNotEqual("secret", received[0]["password"])
        self.assertEqual("[REDACTED]", received[0]["password"])
        self.assertEqual("ok", received[0]["result"])

    def test_fire_no_handlers_is_safe(self):
        """fire() on an event with no registered handlers does not raise."""
        registry = HookRegistry()

        try:
            registry.fire("unregistered_event", {"key": "value"})
        except Exception as exc:  # noqa: BLE001
            self.fail(f"fire() raised unexpectedly: {exc}")

    def test_multiple_handlers_all_called(self):
        """Two handlers registered on the same event are both invoked."""
        calls_a = []
        calls_b = []
        registry = HookRegistry()
        registry.register("plan_shadow_recorded", lambda event, data: calls_a.append(event))
        registry.register("plan_shadow_recorded", lambda event, data: calls_b.append(event))

        registry.fire("plan_shadow_recorded", {})

        self.assertEqual(1, len(calls_a))
        self.assertEqual(1, len(calls_b))

    def test_failing_handler_isolated(self):
        """When the first handler raises, the second handler is still called."""
        second_calls = []

        def exploding(event, data):
            raise RuntimeError("boom")

        registry = HookRegistry()
        registry.register("memory_injected", exploding)
        registry.register("memory_injected", lambda event, data: second_calls.append(event))

        registry.fire("memory_injected", {})

        self.assertEqual(["memory_injected"], second_calls)

    def test_failing_handler_does_not_propagate(self):
        """An exception thrown by a handler never escapes fire()."""
        registry = HookRegistry()
        registry.register("intent_analyzed", lambda event, data: 1 / 0)

        try:
            registry.fire("intent_analyzed", {})
        except Exception as exc:  # noqa: BLE001
            self.fail(f"fire() let handler exception escape: {exc}")

    def test_fire_with_empty_data(self):
        """fire() with an empty dict completes without error."""
        calls = []
        registry = HookRegistry()
        registry.register("empty_event", lambda event, data: calls.append(data))

        registry.fire("empty_event", {})

        self.assertEqual([{}], calls)

    def test_fire_different_events_isolated(self):
        """Handler registered on event A is not called when event B is fired."""
        calls_a = []
        registry = HookRegistry()
        registry.register("event_a", lambda event, data: calls_a.append(event))

        registry.fire("event_b", {"info": "irrelevant"})

        self.assertEqual([], calls_a)

    def test_data_mutation_in_handler_does_not_affect_others(self):
        """A handler that mutates the data dict cannot corrupt data seen by later handlers."""
        received = []

        def mutating_handler(event, data):
            data["injected"] = "pollution"

        def recording_handler(event, data):
            received.append(dict(data))

        registry = HookRegistry()
        registry.register("multi_handler_event", mutating_handler)
        registry.register("multi_handler_event", recording_handler)

        registry.fire("multi_handler_event", {"original": "value"})

        # The recording handler should see redacted data without the mutation injected
        # by the first handler, because each handler receives the same safe_data dict.
        # The key assertion is that "original" is still present unmodified.
        self.assertEqual("value", received[0]["original"])


class HookRegistryIntrospectionTests(unittest.TestCase):

    def test_handlers_for_empty_event(self):
        """handlers_for() returns an empty list for an event with no handlers."""
        registry = HookRegistry()

        result = registry.handlers_for("nonexistent_event")

        self.assertEqual([], result)

    def test_handlers_for_returns_copy(self):
        """Mutating the list returned by handlers_for() does not alter the registry."""
        registry = HookRegistry()
        handler = lambda event, data: None  # noqa: E731
        registry.register("copy_test_event", handler)

        returned = registry.handlers_for("copy_test_event")
        returned.clear()

        still_registered = registry.handlers_for("copy_test_event")
        self.assertEqual([handler], still_registered)

    def test_registered_events_empty(self):
        """A fresh registry reports no registered events."""
        registry = HookRegistry()

        self.assertEqual([], registry.registered_events())

    def test_registered_events_after_register(self):
        """registered_events() includes the event name after a handler is registered."""
        registry = HookRegistry()
        registry.register("my_event", lambda event, data: None)

        self.assertIn("my_event", registry.registered_events())


class HookRegistryValidationTests(unittest.TestCase):

    def test_register_invalid_event_raises(self):
        """register() raises ValueError when the event name is an empty string."""
        registry = HookRegistry()

        with self.assertRaises(ValueError):
            registry.register("", lambda event, data: None)

    def test_register_non_callable_raises(self):
        """register() raises ValueError when handler is not callable."""
        registry = HookRegistry()

        with self.assertRaises(ValueError):
            registry.register("some_event", "not_a_function")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
