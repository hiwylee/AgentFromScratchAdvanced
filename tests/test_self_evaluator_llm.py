"""Tests for optional LLM critique path in SelfEvaluator."""
import unittest

from agent_runtime.self_evaluator import EvalResult, SelfEvaluator


class HasLlmCriticTests(unittest.TestCase):

    def test_no_critic_by_default(self):
        ev = SelfEvaluator()
        self.assertFalse(ev.has_llm_critic)

    def test_has_critic_when_set(self):
        ev = SelfEvaluator(llm_critic=lambda q, a: "looks good")
        self.assertTrue(ev.has_llm_critic)


class LlmCriticGoodAnswerTests(unittest.TestCase):

    def test_no_issue_when_critic_says_ok(self):
        ev = SelfEvaluator(llm_critic=lambda q, a: "The answer looks good and complete.")
        result = ev.evaluate("show revenue", {"content": "Revenue for Q1 was 1.2M across all channels."})
        # No LLM-based issue added when critique has no ISSUE/FAIL marker
        llm_issues = [i for i in result.issues if i.startswith("llm_critique:")]
        self.assertEqual(llm_issues, [])

    def test_suggestion_added_when_critic_responds(self):
        ev = SelfEvaluator(llm_critic=lambda q, a: "The answer looks good.")
        result = ev.evaluate("show revenue", {"content": "Revenue for Q1 was 1.2M across all channels."})
        llm_suggestions = [s for s in result.suggestions if "LLM critique" in s]
        self.assertEqual(len(llm_suggestions), 1)


class LlmCriticIssueTests(unittest.TestCase):

    def test_issue_added_when_critic_flags_issue(self):
        ev = SelfEvaluator(llm_critic=lambda q, a: "ISSUE: answer is incomplete and missing details")
        result = ev.evaluate(
            "show revenue by channel",
            {"content": "Revenue data is available in the system for all channels and periods."},
        )
        llm_issues = [i for i in result.issues if i.startswith("llm_critique:")]
        self.assertGreater(len(llm_issues), 0)

    def test_issue_prefix_format(self):
        ev = SelfEvaluator(llm_critic=lambda q, a: "ISSUE: missing data")
        result = ev.evaluate("query", {"content": "Here is some answer with sufficient length for checks."})
        llm_issues = [i for i in result.issues if i.startswith("llm_critique:")]
        for issue in llm_issues:
            self.assertTrue(issue.startswith("llm_critique:"), f"Bad prefix: {issue}")

    def test_fail_keyword_triggers_issue(self):
        ev = SelfEvaluator(llm_critic=lambda q, a: "This answer fails to address the question")
        result = ev.evaluate("query", {"content": "A sufficiently long answer that passes structural checks here."})
        llm_issues = [i for i in result.issues if i.startswith("llm_critique:")]
        self.assertGreater(len(llm_issues), 0)


class LlmCriticDegradationTests(unittest.TestCase):

    def test_exception_in_critic_does_not_crash(self):
        def _crashing_critic(q, a):
            raise ValueError("LLM unavailable")

        ev = SelfEvaluator(llm_critic=_crashing_critic)
        # Must not raise
        result = ev.evaluate("show revenue", {"content": "Revenue for Q1 was 1.2M across all channels."})
        self.assertIsInstance(result, EvalResult)

    def test_exception_in_critic_still_has_structural_result(self):
        def _crashing_critic(q, a):
            raise RuntimeError("network error")

        ev = SelfEvaluator(llm_critic=_crashing_critic)
        result = ev.evaluate("show revenue", {"content": "Revenue for Q1 was 1.2M across all channels."})
        # Structural checks still ran — no llm_critique issues, but passed should be True
        llm_issues = [i for i in result.issues if i.startswith("llm_critique:")]
        self.assertEqual(llm_issues, [])
        self.assertTrue(result.passed)

    def test_none_return_from_critic_handled(self):
        ev = SelfEvaluator(llm_critic=lambda q, a: None)  # type: ignore
        result = ev.evaluate("show revenue", {"content": "Revenue for Q1 was 1.2M across all channels."})
        self.assertIsInstance(result, EvalResult)


class BackwardCompatibilityTests(unittest.TestCase):
    """SelfEvaluator() with no args must behave identically to before."""

    def test_empty_answer_fails(self):
        ev = SelfEvaluator()
        result = ev.evaluate("show revenue", {"content": ""})
        self.assertFalse(result.passed)
        self.assertIn("empty_answer", result.issues)

    def test_good_answer_passes(self):
        ev = SelfEvaluator()
        result = ev.evaluate(
            "show revenue",
            {"content": "Revenue for Q1 was 1.2 million across all channels and regions."},
        )
        self.assertTrue(result.passed)

    def test_score_range(self):
        ev = SelfEvaluator()
        result = ev.evaluate("show revenue", {"content": "Revenue data here for Q1 analysis."})
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)


if __name__ == "__main__":
    unittest.main()
