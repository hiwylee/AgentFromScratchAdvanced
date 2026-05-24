"""Unit tests for KeywordIntentClassifier.classify() and from_user_intent().

Coverage targets:
- classify(): primary_route mapping for db/workflow/general text
- classify(): capability lists for each route
- classify(): write keyword detection yields oracle_sh.data.write
- classify(): confidence is always 1.0
- classify(): needs_clarification set when ambiguities present
- classify(): context param accepted without error
- classify(): returns IntentResult instance
- from_user_intent(): route/capability parity with classify()
- from_user_intent(): confidence is always 1.0
- from_user_intent(): empty entities yields empty slots
- from_user_intent(): blocked_write_request yields write capability
"""

import unittest

from agent_runtime.intent import KeywordIntentClassifier, analyze_user_intent
from agent_runtime.types import IntentResult


class ClassifyRouteTests(unittest.TestCase):
    """classify() primary_route tests."""

    def setUp(self):
        self.clf = KeywordIntentClassifier()

    def test_classify_db_text_returns_database_analysis_route(self):
        result = self.clf.classify("지난달 상품별 매출 추이를 보여줘")
        self.assertEqual("database_analysis", result.primary_route)

    def test_classify_workflow_returns_business_workflow_route(self):
        result = self.clf.classify("이번달 특허자산 대체 등록 진행해줘")
        self.assertEqual("business_workflow", result.primary_route)

    def test_classify_general_returns_general_answer_route(self):
        result = self.clf.classify("hello world")
        self.assertEqual("general_answer", result.primary_route)


class ClassifyCapabilityTests(unittest.TestCase):
    """classify() capability list tests."""

    def setUp(self):
        self.clf = KeywordIntentClassifier()

    def test_classify_db_text_has_schema_read_capability(self):
        result = self.clf.classify("oracle schema 조회")
        self.assertIn("oracle_sh.schema.read", result.capabilities)

    def test_classify_db_text_has_data_read_capability(self):
        result = self.clf.classify("매출 데이터 조회")
        self.assertIn("oracle_sh.data.read", result.capabilities)

    def test_classify_workflow_has_workflow_run_capability(self):
        result = self.clf.classify("이번달 특허자산 대체 등록 진행해줘")
        self.assertIn("core.workflow.run", result.capabilities)

    def test_classify_general_has_empty_capabilities(self):
        result = self.clf.classify("hello world")
        self.assertEqual([], result.capabilities)

    def test_classify_write_keyword_returns_write_capability(self):
        result = self.clf.classify("고객 데이터 삭제해줘")
        self.assertIn("oracle_sh.data.write", result.capabilities)


class ClassifyMetaTests(unittest.TestCase):
    """classify() type, confidence, clarification, and context tests."""

    def setUp(self):
        self.clf = KeywordIntentClassifier()

    def test_classify_returns_intent_result_instance(self):
        result = self.clf.classify("지난달 상품별 매출")
        self.assertIsInstance(result, IntentResult)

    def test_classify_confidence_is_1_0(self):
        for text in ("지난달 상품별 매출", "이번달 특허자산 대체 등록 진행해줘", "hello world"):
            with self.subTest(text=text):
                result = self.clf.classify(text)
                self.assertEqual(1.0, result.confidence)

    def test_classify_ambiguous_sets_needs_clarification(self):
        # A DB request with metrics but no dimension produces ambiguities in analyze_user_intent,
        # which should propagate to needs_clarification=True.
        intent = analyze_user_intent("지난달 상품별 매출 추이를 보여줘")
        if intent.ambiguities:
            result = self.clf.classify("지난달 상품별 매출 추이를 보여줘")
            self.assertTrue(result.needs_clarification)
        else:
            # If no ambiguities, needs_clarification must be False — still a valid assertion.
            result = self.clf.classify("지난달 상품별 매출 추이를 보여줘")
            self.assertFalse(result.needs_clarification)

    def test_classify_context_param_ignored(self):
        """classify() accepts an arbitrary context dict without raising."""
        try:
            result = self.clf.classify("매출 조회", context={"foo": "bar", "session_id": "s1"})
        except Exception as exc:
            self.fail(f"classify() raised unexpectedly with context kwarg: {exc}")
        self.assertIsInstance(result, IntentResult)


class FromUserIntentRouteTests(unittest.TestCase):
    """from_user_intent() route and capability tests."""

    def setUp(self):
        self.clf = KeywordIntentClassifier()

    def test_from_user_intent_database_analysis(self):
        intent = analyze_user_intent("지난달 상품별 매출 추이를 보여줘")
        result = self.clf.from_user_intent(intent)
        self.assertEqual("database_analysis", result.primary_route)

    def test_from_user_intent_workflow_execution(self):
        intent = analyze_user_intent("이번달 특허자산 대체 등록 진행해줘")
        result = self.clf.from_user_intent(intent)
        self.assertEqual("business_workflow", result.primary_route)

    def test_from_user_intent_general(self):
        intent = analyze_user_intent("hello world")
        result = self.clf.from_user_intent(intent)
        self.assertEqual("general_answer", result.primary_route)


class FromUserIntentParityTests(unittest.TestCase):
    """from_user_intent() must produce the same route/capabilities as classify()."""

    def setUp(self):
        self.clf = KeywordIntentClassifier()

    def test_from_user_intent_matches_classify_route(self):
        text = "지난달 상품별 매출 추이를 보여줘"
        intent = analyze_user_intent(text)
        classify_result = self.clf.classify(text)
        from_intent_result = self.clf.from_user_intent(intent)
        self.assertEqual(classify_result.primary_route, from_intent_result.primary_route)

    def test_from_user_intent_matches_classify_capabilities(self):
        text = "지난달 상품별 매출 추이를 보여줘"
        intent = analyze_user_intent(text)
        classify_result = self.clf.classify(text)
        from_intent_result = self.clf.from_user_intent(intent)
        self.assertEqual(
            sorted(classify_result.capabilities),
            sorted(from_intent_result.capabilities),
        )

    def test_from_user_intent_write_blocked(self):
        intent = analyze_user_intent("고객 데이터 삭제해줘")
        result = self.clf.from_user_intent(intent)
        self.assertIn("oracle_sh.data.write", result.capabilities)

    def test_from_user_intent_confidence_is_1_0(self):
        for text in ("지난달 상품별 매출", "이번달 특허자산 대체 등록 진행해줘", "hello world"):
            with self.subTest(text=text):
                intent = analyze_user_intent(text)
                result = self.clf.from_user_intent(intent)
                self.assertEqual(1.0, result.confidence)

    def test_from_user_intent_empty_entities_gives_empty_slots(self):
        """A general UserIntent has no entities, so slots must be empty."""
        intent = analyze_user_intent("hello world")
        result = self.clf.from_user_intent(intent)
        self.assertEqual({}, result.slots)


if __name__ == "__main__":
    unittest.main()
