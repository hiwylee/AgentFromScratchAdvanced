import json
import tempfile
import unittest
from pathlib import Path

from agent_runtime.intent import UserIntent
from agent_runtime.loop import AgentLoop
from agent_runtime.monitor import latest_status
from agent_runtime.types import Action, Budget, CancellationToken


class RuntimeControlTests(unittest.TestCase):
    def test_zero_max_steps_stops_after_intent_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=0, timeout_seconds=30),
            )

            result = loop.run("summarize this repository")

            self.assertEqual("general", result.intent["intent_type"])
            self.assertEqual("final_answer", result.action["kind"])
            self.assertEqual("max_steps_exceeded", result.action["reason"])
            self.assertIn("step limit", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("stopped", status["state"])

            event_names = _event_names(Path(result.events_path))
            self.assertIn("intent_analyzed", event_names)
            self.assertNotIn("model_action_selected", event_names)

    def test_one_max_step_allows_the_milestone_one_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=1, timeout_seconds=30),
            )

            result = loop.run("summarize this repository")

            self.assertEqual("final_answer", result.action["kind"])
            self.assertEqual("completed", latest_status(tmp_path / "runs")["state"])
            event_names = _event_names(Path(result.events_path))
            self.assertIn("model_action_selected", event_names)
            self.assertIn("observation_recorded", event_names)

    def test_zero_timeout_times_out_before_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                budget=Budget(max_steps=4, timeout_seconds=0),
            )

            result = loop.run("summarize this repository")

            self.assertEqual({}, result.intent)
            self.assertEqual("timeout_seconds_exceeded", result.action["reason"])
            self.assertIn("timed out", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("timed_out", status["state"])
            self.assertEqual(["run_finished"], _event_names(Path(result.events_path)))

    def test_pre_cancelled_token_cancels_before_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = CancellationToken()
            token.cancel("user_requested")
            loop = AgentLoop(
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                cancellation_token=token,
            )

            result = loop.run("summarize this repository")

            self.assertEqual({}, result.intent)
            self.assertEqual("user_requested", result.action["reason"])
            self.assertIn("cancelled", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("cancelled", status["state"])

    def test_cancellation_during_action_selection_stops_before_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            token = CancellationToken()
            loop = AgentLoop(
                model=CancelDuringActionSelection(token),
                run_root=tmp_path / "runs",
                audit_path=tmp_path / "audit.jsonl",
                cancellation_token=token,
            )

            result = loop.run("summarize this repository")

            self.assertEqual("final_answer", result.action["kind"])
            self.assertEqual("model_requested_cancel", token.reason)
            self.assertIn("cancelled", result.final_answer["content"])

            status = latest_status(tmp_path / "runs")
            self.assertIsNotNone(status)
            assert status is not None
            self.assertEqual("cancelled", status["state"])

            event_names = _event_names(Path(result.events_path))
            self.assertIn("model_action_selected", event_names)
            self.assertNotIn("observation_recorded", event_names)


class CancelDuringActionSelection:
    name = "cancel-test-model"
    version = "1"

    def __init__(self, token: CancellationToken) -> None:
        self.token = token

    def choose_action(self, intent: UserIntent) -> Action:
        self.token.cancel("model_requested_cancel")
        return Action(
            kind="final_answer",
            reason="test action selected",
            payload={"next_action": intent.next_action},
        )


def _event_names(events_path: Path) -> list[str]:
    return [
        json.loads(line)["event"]
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]


if __name__ == "__main__":
    unittest.main()
