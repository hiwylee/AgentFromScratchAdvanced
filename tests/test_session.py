import os
import stat
import tempfile
import unittest
from pathlib import Path

from agent_runtime.session import BudgetTracker, SessionContext
from agent_runtime.types import Budget, Message


class BudgetTrackerTests(unittest.TestCase):
    def _make_budget(self, cost_budget_usd: float = 0.0, max_steps: int = 3) -> Budget:
        return Budget(
            max_steps=max_steps,
            timeout_seconds=30,
            token_budget=4000,
            cost_budget_usd=cost_budget_usd,
            row_budget=100,
        )

    def test_would_exceed_returns_false_when_no_cost_limit(self):
        tracker = BudgetTracker(initial=self._make_budget(cost_budget_usd=0.0))
        self.assertFalse(tracker.would_exceed("fast"))
        self.assertFalse(tracker.would_exceed("medium"))
        self.assertFalse(tracker.would_exceed("slow"))

    def test_would_exceed_returns_true_when_budget_exceeded(self):
        # cost_budget_usd=0.005 — a "medium" call costs 0.01 which would exceed it
        tracker = BudgetTracker(
            initial=self._make_budget(cost_budget_usd=0.005),
            cost_used_usd=0.0,
        )
        self.assertTrue(tracker.would_exceed("medium"))

    def test_would_exceed_returns_false_when_budget_not_exceeded(self):
        # cost_budget_usd=1.0 — a "fast" call costs 0.001 which is fine
        tracker = BudgetTracker(initial=self._make_budget(cost_budget_usd=1.0))
        self.assertFalse(tracker.would_exceed("fast"))

    def test_charge_retry_returns_true_within_budget(self):
        tracker = BudgetTracker(initial=self._make_budget(max_steps=3))
        self.assertTrue(tracker.charge_retry())  # retries=1
        self.assertTrue(tracker.charge_retry())  # retries=2
        self.assertTrue(tracker.charge_retry())  # retries=3

    def test_charge_retry_returns_false_when_exceeds_max_steps(self):
        tracker = BudgetTracker(initial=self._make_budget(max_steps=2))
        tracker.charge_retry()  # retries=1
        tracker.charge_retry()  # retries=2
        result = tracker.charge_retry()  # retries=3 > max_steps=2
        self.assertFalse(result)

    def test_charge_tokens_accumulates(self):
        tracker = BudgetTracker(initial=self._make_budget())
        tracker.charge_tokens(100)
        tracker.charge_tokens(50)
        self.assertEqual(150, tracker.tokens_used)

    def test_to_dict_contains_required_fields(self):
        budget = self._make_budget(cost_budget_usd=1.0, max_steps=5)
        tracker = BudgetTracker(initial=budget, tokens_used=42, cost_used_usd=0.05, tool_retries=1)
        d = tracker.to_dict()
        self.assertEqual(42, d["tokens_used"])
        self.assertAlmostEqual(0.05, d["cost_used_usd"])
        self.assertEqual(1, d["tool_retries"])
        self.assertIn("initial", d)
        self.assertEqual(5, d["initial"]["max_steps"])


class SessionContextBasicTests(unittest.TestCase):
    def _make_session(self, session_id: str = "test-session") -> SessionContext:
        return SessionContext(session_id=session_id)

    def test_add_message_appends_to_history(self):
        session = self._make_session()
        self.assertEqual(0, len(session.conversation_history))
        session.add_message(Message(role="user", content="hello"))
        session.add_message(Message(role="assistant", content="hi"))
        self.assertEqual(2, len(session.conversation_history))

    def test_set_and_get_slot(self):
        session = self._make_session()
        session.set_slot("intent", "query", source_step_id="step-1")
        value = session.get_slot("intent")
        self.assertEqual("query", value)

    def test_get_slot_returns_none_for_missing_key(self):
        session = self._make_session()
        self.assertIsNone(session.get_slot("nonexistent"))

    def test_set_slot_overwrites_existing(self):
        session = self._make_session()
        session.set_slot("key", "first")
        session.set_slot("key", "second")
        self.assertEqual("second", session.get_slot("key"))

    def test_cache_tool_result_and_hit(self):
        session = self._make_session()
        session.cache_tool_result("my_tool", "abc123", {"result": "ok"})
        result = session.get_cached_result("my_tool", "abc123")
        self.assertEqual({"result": "ok"}, result)

    def test_cache_miss_returns_none(self):
        session = self._make_session()
        self.assertIsNone(session.get_cached_result("my_tool", "nonexistent"))

    def test_cache_key_is_scoped_by_tool_name(self):
        session = self._make_session()
        session.cache_tool_result("tool_a", "hash1", "value_a")
        session.cache_tool_result("tool_b", "hash1", "value_b")
        self.assertEqual("value_a", session.get_cached_result("tool_a", "hash1"))
        self.assertEqual("value_b", session.get_cached_result("tool_b", "hash1"))


class SessionContextPersistenceTests(unittest.TestCase):
    def _make_budget_tracker(self) -> BudgetTracker:
        return BudgetTracker(
            initial=Budget(max_steps=5, timeout_seconds=60, token_budget=8000, cost_budget_usd=0.5, row_budget=200),
            tokens_used=100,
            cost_used_usd=0.01,
            tool_retries=1,
        )

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sess-001"
            session = SessionContext(
                session_id="sess-001",
                budget_tracker=self._make_budget_tracker(),
                instruction_sources=["system", "user"],
            )
            session.add_message(Message(role="user", content="hello world"))
            session.add_message(Message(role="assistant", content="hi there"))
            session.set_slot("product", "Widget", source_step_id="step-2")

            session.save(session_dir)
            loaded = SessionContext.load(session_dir)

            self.assertEqual("sess-001", loaded.session_id)
            self.assertEqual(2, len(loaded.conversation_history))
            self.assertEqual("user", loaded.conversation_history[0].role)
            self.assertEqual("hello world", loaded.conversation_history[0].content)
            self.assertEqual("Widget", loaded.get_slot("product"))
            self.assertIn("product", loaded.slots)
            self.assertIsNotNone(loaded.budget_tracker)
            self.assertEqual(100, loaded.budget_tracker.tokens_used)
            self.assertEqual(["system", "user"], loaded.instruction_sources)

    def test_save_creates_state_json_and_messages_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sess-002"
            session = SessionContext(session_id="sess-002")
            session.save(session_dir)

            self.assertTrue((session_dir / "state.json").exists())
            self.assertTrue((session_dir / "messages.jsonl").exists())

    def test_save_sets_file_permissions_0o600(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sess-003"
            session = SessionContext(session_id="sess-003")
            session.add_message(Message(role="user", content="test"))
            session.save(session_dir)

            state_mode = stat.S_IMODE(os.stat(session_dir / "state.json").st_mode)
            messages_mode = stat.S_IMODE(os.stat(session_dir / "messages.jsonl").st_mode)
            self.assertEqual(0o600, state_mode)
            self.assertEqual(0o600, messages_mode)

    def test_save_sets_directory_permissions_0o700(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sess-004"
            session = SessionContext(session_id="sess-004")
            session.save(session_dir)

            dir_mode = stat.S_IMODE(os.stat(session_dir).st_mode)
            self.assertEqual(0o700, dir_mode)

    def test_save_redacts_sensitive_content(self):
        previous = os.environ.get("SESSION_TEST_PASSWORD")
        os.environ["SESSION_TEST_PASSWORD"] = "super-secret-value"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                session_dir = Path(tmp) / "sess-005"
                session = SessionContext(session_id="sess-005")
                session.add_message(Message(role="user", content="my password is super-secret-value"))
                session.set_slot("SESSION_TEST_PASSWORD", "super-secret-value")
                session.save(session_dir)

                messages_text = (session_dir / "messages.jsonl").read_text(encoding="utf-8")
                state_text = (session_dir / "state.json").read_text(encoding="utf-8")
                combined = messages_text + state_text
                self.assertNotIn("super-secret-value", combined)
                self.assertIn("[REDACTED]", combined)
        finally:
            if previous is None:
                os.environ.pop("SESSION_TEST_PASSWORD", None)
            else:
                os.environ["SESSION_TEST_PASSWORD"] = previous

    def test_load_with_no_budget_returns_none_budget_tracker(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sess-006"
            session = SessionContext(session_id="sess-006")
            session.save(session_dir)

            loaded = SessionContext.load(session_dir)
            self.assertIsNone(loaded.budget_tracker)

    def test_load_empty_messages_returns_empty_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sess-007"
            session = SessionContext(session_id="sess-007")
            session.save(session_dir)

            loaded = SessionContext.load(session_dir)
            self.assertEqual([], loaded.conversation_history)


if __name__ == "__main__":
    unittest.main()
