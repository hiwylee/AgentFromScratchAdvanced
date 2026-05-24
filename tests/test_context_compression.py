"""Tests for SessionContext.compress_history() and AgentLoop session wiring."""
import unittest
from pathlib import Path

from agent_runtime.session import SessionContext, BudgetTracker
from agent_runtime.types import Budget, Message


def _make_session(n_messages: int) -> SessionContext:
    ctx = SessionContext(session_id="test-session")
    for i in range(n_messages):
        ctx.add_message(Message(role="user" if i % 2 == 0 else "assistant", content=f"msg {i}"))
    return ctx


class CompressHistoryTests(unittest.TestCase):

    def test_no_compression_under_threshold(self):
        ctx = _make_session(5)
        result = ctx.compress_history(threshold=10)
        self.assertEqual(result, [])
        self.assertEqual(len(ctx.conversation_history), 5)

    def test_compression_over_threshold(self):
        ctx = _make_session(6)
        records = ctx.compress_history(threshold=4)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, "proposed")
        self.assertEqual(records[0].provenance.review_status, "pending")

    def test_compressed_record_never_auto_applied(self):
        ctx = _make_session(10)
        records = ctx.compress_history(threshold=4)
        for r in records:
            self.assertEqual(r.status, "proposed")
            self.assertNotEqual(r.status, "active")

    def test_history_truncated_after_compression(self):
        ctx = _make_session(10)
        ctx.compress_history(threshold=4)
        # After compression, history should be <= threshold // 2
        self.assertLessEqual(len(ctx.conversation_history), 4)

    def test_compression_at_exact_threshold_does_nothing(self):
        ctx = _make_session(4)
        records = ctx.compress_history(threshold=4)
        self.assertEqual(records, [])

    def test_scope_is_session(self):
        ctx = _make_session(10)
        records = ctx.compress_history(threshold=4)
        self.assertEqual(records[0].provenance.scope, "session")


class AgentLoopSessionWiringTests(unittest.TestCase):

    def test_loop_runs_without_session_ctx(self):
        """Existing single-turn behavior unchanged when no session_ctx."""
        from agent_runtime.loop import AgentLoop
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop(run_root=Path(tmp), audit_path=Path(tmp) / "audit.jsonl")
            result = loop.run("hello")
            self.assertIsNotNone(result.run_id)

    def test_loop_runs_with_session_ctx(self):
        """Loop works when session_ctx is provided."""
        from agent_runtime.loop import AgentLoop
        from agent_runtime.types import Budget
        import tempfile
        ctx = SessionContext(session_id="loop-test")
        with tempfile.TemporaryDirectory() as tmp:
            loop = AgentLoop(
                run_root=Path(tmp),
                audit_path=Path(tmp) / "audit.jsonl",
                session_ctx=ctx,
            )
            result = loop.run("hello")
            self.assertIsNotNone(result.run_id)
            # Message should have been added to session
            self.assertGreaterEqual(len(ctx.conversation_history), 1)


if __name__ == "__main__":
    unittest.main()
