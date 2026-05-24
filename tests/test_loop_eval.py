"""Tests for SelfEvaluator integration in AgentLoop (P10-A wiring)."""

import unittest
from unittest.mock import MagicMock

from agent_runtime.loop import AgentLoop, AgentResult
from agent_runtime.hooks import HookRegistry


class AgentResultEvalFieldTests(unittest.TestCase):
    """AgentResult carries eval_result field."""

    def test_eval_result_defaults_to_none(self):
        result = AgentResult(
            run_id="r1",
            intent={},
            action={},
            final_answer={"content": "ok"},
            status_path="",
            events_path="",
            audit_path="",
        )
        self.assertIsNone(result.eval_result)

    def test_to_dict_omits_eval_result_when_none(self):
        result = AgentResult(
            run_id="r1",
            intent={},
            action={},
            final_answer={"content": "ok"},
            status_path="",
            events_path="",
            audit_path="",
        )
        d = result.to_dict()
        self.assertNotIn("eval_result", d)

    def test_to_dict_includes_eval_result_when_set(self):
        eval_data = {"passed": True, "score": 0.8, "issues": [], "suggestions": []}
        result = AgentResult(
            run_id="r1",
            intent={},
            action={},
            final_answer={"content": "ok"},
            status_path="",
            events_path="",
            audit_path="",
            eval_result=eval_data,
        )
        d = result.to_dict()
        self.assertIn("eval_result", d)
        self.assertEqual(True, d["eval_result"]["passed"])


class AgentLoopEvalIntegrationTests(unittest.TestCase):
    """AgentLoop.run() calls SelfEvaluator and populates AgentResult.eval_result."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self._run_root = Path(self._tmp.name) / "runs"
        self._audit = Path(self._tmp.name) / "audit.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def _make_loop(self, hook_registry=None):
        return AgentLoop(
            run_root=self._run_root,
            audit_path=self._audit,
            hook_registry=hook_registry,
        )

    def test_run_produces_eval_result(self):
        loop = self._make_loop()
        result = loop.run("지난달 상품별 매출 추이를 보여줘")
        # eval_result should be present and be a dict
        self.assertIsNotNone(result.eval_result)
        self.assertIsInstance(result.eval_result, dict)

    def test_eval_result_has_required_keys(self):
        loop = self._make_loop()
        result = loop.run("지난달 채널별 매출을 보여줘")
        er = result.eval_result
        self.assertIsNotNone(er)
        self.assertIn("passed", er)
        self.assertIn("score", er)
        self.assertIn("issues", er)

    def test_eval_result_score_in_range(self):
        loop = self._make_loop()
        result = loop.run("이번달 매출 알려줘")
        er = result.eval_result
        self.assertIsNotNone(er)
        self.assertGreaterEqual(er["score"], 0.0)
        self.assertLessEqual(er["score"], 1.0)

    def test_answer_evaluated_hook_fired(self):
        fired = []
        hooks = HookRegistry()
        hooks.register("answer_evaluated", lambda event, data: fired.append(data))

        loop = self._make_loop(hook_registry=hooks)
        loop.run("지난달 상품별 매출")

        self.assertTrue(len(fired) >= 1, "answer_evaluated hook must fire at least once")
        payload = fired[0]
        self.assertIn("eval", payload)

    def test_answer_evaluated_hook_data_has_passed(self):
        fired = []
        hooks = HookRegistry()
        hooks.register("answer_evaluated", lambda event, data: fired.append(data))

        loop = self._make_loop(hook_registry=hooks)
        loop.run("이번달 채널별 매출")

        self.assertTrue(fired)
        self.assertIn("passed", fired[0].get("eval", {}))

    def test_eval_result_in_to_dict(self):
        loop = self._make_loop()
        result = loop.run("지난달 매출을 보여줘")
        d = result.to_dict()
        self.assertIn("eval_result", d)

    def test_no_eval_result_does_not_break_run(self):
        """Even if SelfEvaluator is not wired (eval_result=None), run must succeed."""
        loop = self._make_loop()
        result = loop.run("뭔가 질문")
        # Must return a valid AgentResult regardless
        self.assertIsNotNone(result.run_id)
        self.assertIsNotNone(result.final_answer)


if __name__ == "__main__":
    unittest.main()
