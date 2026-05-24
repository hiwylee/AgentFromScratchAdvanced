"""Tests for SessionContext.recent_history() context windowing (P10-B)."""

import unittest

from agent_runtime.session import SessionContext
from agent_runtime.types import Message


class RecentHistoryTests(unittest.TestCase):
    def _make_session(self) -> SessionContext:
        return SessionContext(session_id="win-test")

    def _add_messages(self, session: SessionContext, count: int) -> None:
        for i in range(count):
            role = "user" if i % 2 == 0 else "assistant"
            session.add_message(Message(role=role, content=f"message {i}"))

    def test_recent_history_returns_all_when_fewer_than_n(self):
        session = self._make_session()
        self._add_messages(session, 5)
        result = session.recent_history(n=20)
        self.assertEqual(5, len(result))

    def test_recent_history_returns_last_n(self):
        session = self._make_session()
        self._add_messages(session, 30)
        result = session.recent_history(n=10)
        self.assertEqual(10, len(result))

    def test_recent_history_returns_most_recent_messages(self):
        session = self._make_session()
        self._add_messages(session, 5)
        result = session.recent_history(n=3)
        # Should be messages 2, 3, 4 (last 3)
        self.assertEqual("message 2", result[0].content)
        self.assertEqual("message 4", result[2].content)

    def test_recent_history_n_zero_returns_all(self):
        session = self._make_session()
        self._add_messages(session, 5)
        result = session.recent_history(n=0)
        self.assertEqual(5, len(result))

    def test_recent_history_n_negative_returns_all(self):
        session = self._make_session()
        self._add_messages(session, 5)
        result = session.recent_history(n=-1)
        self.assertEqual(5, len(result))

    def test_recent_history_returns_copy_not_reference(self):
        session = self._make_session()
        self._add_messages(session, 5)
        result = session.recent_history(n=5)
        result.clear()
        self.assertEqual(5, len(session.conversation_history))

    def test_recent_history_empty_session_returns_empty(self):
        session = self._make_session()
        result = session.recent_history(n=10)
        self.assertEqual([], result)

    def test_recent_history_n_equals_count_returns_all(self):
        session = self._make_session()
        self._add_messages(session, 7)
        result = session.recent_history(n=7)
        self.assertEqual(7, len(result))

    def test_conversation_history_unchanged_by_windowing(self):
        session = self._make_session()
        self._add_messages(session, 25)
        _ = session.recent_history(n=5)
        self.assertEqual(25, len(session.conversation_history))

    def test_recent_history_preserves_message_order(self):
        session = self._make_session()
        session.add_message(Message(role="user", content="first"))
        session.add_message(Message(role="assistant", content="second"))
        session.add_message(Message(role="user", content="third"))
        result = session.recent_history(n=2)
        self.assertEqual("second", result[0].content)
        self.assertEqual("third", result[1].content)

    def test_recent_history_n_one_returns_last_message(self):
        session = self._make_session()
        self._add_messages(session, 10)
        result = session.recent_history(n=1)
        self.assertEqual(1, len(result))
        self.assertEqual("message 9", result[0].content)


if __name__ == "__main__":
    unittest.main()
