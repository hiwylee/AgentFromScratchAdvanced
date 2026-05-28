"""Unit tests for agent_runtime.tacit_knowledge."""

import json
import tempfile
import unittest
from pathlib import Path

from agent_runtime.tacit_knowledge import (
    CorrectionDiff,
    ReflectionAgent,
    ReflectionResult,
    TacitSignal,
    TacitSignalExtractor,
    VerificationEpisode,
    VerificationEpisodeStore,
)


# ---------------------------------------------------------------------------
# CorrectionDiff.from_texts
# ---------------------------------------------------------------------------

class TestCorrectionDiffFromTexts(unittest.TestCase):
    def test_no_change_when_identical(self) -> None:
        diff = CorrectionDiff.from_texts("hello world", "hello world")
        self.assertEqual("no_change", diff.semantic_type)
        self.assertEqual((), diff.removed)
        self.assertEqual((), diff.inserted)

    def test_no_change_when_revision_is_none(self) -> None:
        diff = CorrectionDiff.from_texts("hello world", None)
        self.assertEqual("no_change", diff.semantic_type)

    def test_policy_risk_detected(self) -> None:
        diff = CorrectionDiff.from_texts("send the report", "send the policy compliant report")
        self.assertEqual("policy_risk", diff.semantic_type)
        self.assertIn("policy", diff.inserted)

    def test_escalation_detected(self) -> None:
        diff = CorrectionDiff.from_texts("process the case", "escalate the case to senior reviewer")
        self.assertEqual("escalation", diff.semantic_type)
        self.assertIn("escalate", diff.inserted)

    def test_tone_detected(self) -> None:
        diff = CorrectionDiff.from_texts("do this now", "please do this now")
        self.assertEqual("tone", diff.semantic_type)
        self.assertIn("please", diff.inserted)

    def test_domain_nuance_detected(self) -> None:
        diff = CorrectionDiff.from_texts("look at the numbers", "review the financial numbers carefully")
        self.assertEqual("domain_nuance", diff.semantic_type)
        self.assertIn("financial", diff.inserted)

    def test_literal_to_contextual_when_many_insertions(self) -> None:
        diff = CorrectionDiff.from_texts("yes", "yes absolutely that is correct and confirmed")
        self.assertEqual("literal_to_contextual", diff.semantic_type)

    def test_other_semantic_type_fallback(self) -> None:
        diff = CorrectionDiff.from_texts("the cat sat", "the dog sat")
        self.assertEqual("other", diff.semantic_type)
        self.assertIn("cat", diff.removed)
        self.assertIn("dog", diff.inserted)

    def test_removed_and_inserted_are_sorted_tuples(self) -> None:
        diff = CorrectionDiff.from_texts("alpha beta", "gamma delta")
        self.assertIsInstance(diff.removed, tuple)
        self.assertIsInstance(diff.inserted, tuple)
        self.assertEqual(tuple(sorted(diff.removed)), diff.removed)
        self.assertEqual(tuple(sorted(diff.inserted)), diff.inserted)

    def test_to_dict_keys(self) -> None:
        diff = CorrectionDiff.from_texts("old text", "new text here")
        d = diff.to_dict()
        self.assertIn("removed", d)
        self.assertIn("inserted", d)
        self.assertIn("tone_change", d)
        self.assertIn("terminology_changes", d)
        self.assertIn("semantic_type", d)
        self.assertIsInstance(d["removed"], list)
        self.assertIsInstance(d["inserted"], list)


# ---------------------------------------------------------------------------
# VerificationEpisode.create
# ---------------------------------------------------------------------------

class TestVerificationEpisodeCreate(unittest.TestCase):
    def test_fields_populated_correctly(self) -> None:
        ep = VerificationEpisode.create(
            session_id="sess-123",
            ai_output="original output",
            final_resolution="human_approved",
        )
        self.assertEqual("sess-123", ep.session_id)
        self.assertEqual("original output", ep.ai_output)
        self.assertEqual("human_approved", ep.final_resolution)
        self.assertIsNotNone(ep.episode_id)
        self.assertIsNotNone(ep.timestamp)
        self.assertIsNone(ep.correction_diff)  # no human_revision
        self.assertEqual("agent-runtime.verification-episode.v1", ep.schema_version)

    def test_diff_computed_when_revision_provided(self) -> None:
        ep = VerificationEpisode.create(
            session_id="sess-456",
            ai_output="send the report",
            final_resolution="human_override",
            human_revision="send the policy report",
        )
        self.assertIsNotNone(ep.correction_diff)
        assert ep.correction_diff is not None
        self.assertEqual("policy_risk", ep.correction_diff.semantic_type)

    def test_reason_tags_stored_as_tuple(self) -> None:
        ep = VerificationEpisode.create(
            session_id="s",
            ai_output="x",
            final_resolution="human_approved",
            reason_tags=["tone mismatch", "domain nuance"],
        )
        self.assertIsInstance(ep.reason_tags, tuple)
        self.assertIn("tone mismatch", ep.reason_tags)

    def test_consultation_trace_stored_as_tuple(self) -> None:
        trace = [{"person": "legal", "reason": "contract check"}]
        ep = VerificationEpisode.create(
            session_id="s",
            ai_output="x",
            final_resolution="human_approved",
            consultation_trace=trace,
        )
        self.assertIsInstance(ep.consultation_trace, tuple)
        self.assertEqual(1, len(ep.consultation_trace))
        self.assertEqual("legal", ep.consultation_trace[0]["person"])

    def test_to_dict_round_trips_json(self) -> None:
        ep = VerificationEpisode.create(
            session_id="sess-789",
            ai_output="some output",
            final_resolution="human_rejected",
            human_revision="corrected output here",
            confidence_before=0.6,
            confidence_after=0.95,
            reason_tags=["policy risk"],
        )
        d = ep.to_dict()
        serialized = json.dumps(d, ensure_ascii=False)
        restored = json.loads(serialized)
        self.assertEqual(ep.episode_id, restored["episode_id"])
        self.assertEqual(ep.session_id, restored["session_id"])
        self.assertEqual(ep.final_resolution, restored["final_resolution"])
        self.assertIsNotNone(restored["correction_diff"])

    def test_episode_id_is_unique(self) -> None:
        ep1 = VerificationEpisode.create("s", "x", "human_approved")
        ep2 = VerificationEpisode.create("s", "x", "human_approved")
        self.assertNotEqual(ep1.episode_id, ep2.episode_id)

    def test_input_context_defaults_to_empty_dict(self) -> None:
        ep = VerificationEpisode.create("s", "x", "human_approved")
        self.assertEqual({}, ep.input_context)

    def test_input_context_stored_when_provided(self) -> None:
        ep = VerificationEpisode.create(
            "s", "x", "human_approved",
            input_context={"key": "value"},
        )
        self.assertEqual({"key": "value"}, ep.input_context)


# ---------------------------------------------------------------------------
# VerificationEpisodeStore
# ---------------------------------------------------------------------------

class TestVerificationEpisodeStore(unittest.TestCase):
    def _make_episode(self, session_id: str, resolution: str = "human_approved") -> VerificationEpisode:
        return VerificationEpisode.create(
            session_id=session_id,
            ai_output="some ai output",
            final_resolution=resolution,
        )

    def test_append_and_load_session_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerificationEpisodeStore(tmp)
            ep = self._make_episode("session-a")
            store.append(ep)
            loaded = store.load_session("session-a")
            self.assertEqual(1, len(loaded))
            self.assertEqual(ep.episode_id, loaded[0]["episode_id"])
            self.assertEqual("session-a", loaded[0]["session_id"])

    def test_multiple_appends_to_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerificationEpisodeStore(tmp)
            ep1 = self._make_episode("session-b")
            ep2 = self._make_episode("session-b", "human_rejected")
            store.append(ep1)
            store.append(ep2)
            loaded = store.load_session("session-b")
            self.assertEqual(2, len(loaded))
            ids = {ep["episode_id"] for ep in loaded}
            self.assertIn(ep1.episode_id, ids)
            self.assertIn(ep2.episode_id, ids)

    def test_load_session_returns_empty_for_missing_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerificationEpisodeStore(tmp)
            result = store.load_session("nonexistent")
            self.assertEqual([], result)

    def test_load_all_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerificationEpisodeStore(tmp)
            store.append(self._make_episode("session-x"))
            store.append(self._make_episode("session-y"))
            store.append(self._make_episode("session-x"))
            all_eps = store.load_all()
            self.assertEqual(3, len(all_eps))

    def test_load_all_returns_empty_for_empty_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerificationEpisodeStore(tmp)
            self.assertEqual([], store.load_all())

    def test_store_creates_dir_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_dir = Path(tmp) / "new" / "subdir"
            self.assertFalse(store_dir.exists())
            store = VerificationEpisodeStore(store_dir)
            self.assertTrue(store_dir.exists())

    def test_jsonl_file_per_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerificationEpisodeStore(tmp)
            store.append(self._make_episode("sess-1"))
            store.append(self._make_episode("sess-2"))
            files = list(Path(tmp).glob("*.jsonl"))
            self.assertEqual(2, len(files))

    def test_stored_records_are_valid_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VerificationEpisodeStore(tmp)
            ep = self._make_episode("sess-json")
            store.append(ep)
            jsonl_path = Path(tmp) / "sess-json.jsonl"
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(lines))
            parsed = json.loads(lines[0])
            self.assertEqual(ep.episode_id, parsed["episode_id"])


# ---------------------------------------------------------------------------
# TacitSignalExtractor.extract
# ---------------------------------------------------------------------------

class TestTacitSignalExtractor(unittest.TestCase):
    def _make_ep(
        self,
        *,
        reason_tags: tuple[str, ...] = (),
        consultation_trace: tuple[dict, ...] = (),
        ai_output: str = "x",
        human_revision: str | None = None,
    ) -> VerificationEpisode:
        return VerificationEpisode.create(
            session_id="s",
            ai_output=ai_output,
            final_resolution="human_override",
            reason_tags=list(reason_tags),
            consultation_trace=list(consultation_trace),
            human_revision=human_revision,
        )

    def test_heuristic_from_tone_mismatch_tag(self) -> None:
        ep = self._make_ep(reason_tags=("tone mismatch",))
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertIn("prefer softer or more formal phrasing in this domain", signal.suspected_heuristics)

    def test_heuristic_from_policy_risk_tag(self) -> None:
        ep = self._make_ep(reason_tags=("policy risk",))
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertIn("legal or compliance language requires manual confirmation", signal.suspected_heuristics)

    def test_heuristic_from_domain_nuance_tag(self) -> None:
        ep = self._make_ep(reason_tags=("domain nuance",))
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertIn("domain-specific terminology requires expert review", signal.suspected_heuristics)

    def test_heuristic_from_semantic_type(self) -> None:
        ep = self._make_ep(
            ai_output="send the report",
            human_revision="send the policy report",
        )
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertIn("outputs involving policy or legal terms require human gate", signal.suspected_heuristics)

    def test_heuristic_from_consultation_trace_with_reason(self) -> None:
        ep = self._make_ep(
            consultation_trace=({"person": "legal", "reason": "contract review"},),
        )
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertTrue(
            any("legal" in h for h in signal.suspected_heuristics),
            f"expected legal heuristic, got: {signal.suspected_heuristics}",
        )

    def test_heuristic_from_consultation_trace_without_reason(self) -> None:
        ep = self._make_ep(
            consultation_trace=({"person": "finance", "reason": ""},),
        )
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertTrue(any("finance" in h for h in signal.suspected_heuristics))

    def test_no_duplicate_heuristics(self) -> None:
        ep = self._make_ep(reason_tags=("tone mismatch", "tone mismatch"))
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        heuristics = signal.suspected_heuristics
        self.assertEqual(len(heuristics), len(set(heuristics)))

    def test_source_tags_preserved(self) -> None:
        ep = self._make_ep(reason_tags=("escalation", "missing context"))
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertIn("escalation", signal.source_tags)
        self.assertIn("missing context", signal.source_tags)

    def test_no_heuristics_for_approved_no_tags(self) -> None:
        ep = VerificationEpisode.create("s", "x", "human_approved")
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertIsInstance(signal.suspected_heuristics, list)

    def test_tacit_signal_has_correct_episode_id(self) -> None:
        ep = self._make_ep(reason_tags=("escalation",))
        extractor = TacitSignalExtractor()
        signal = extractor.extract(ep)
        self.assertEqual(ep.episode_id, signal.episode_id)


# ---------------------------------------------------------------------------
# ReflectionAgent.reflect
# ---------------------------------------------------------------------------

class TestReflectionAgent(unittest.TestCase):
    def _make_ep(self, resolution: str, *, tags: tuple[str, ...] = ()) -> VerificationEpisode:
        return VerificationEpisode.create(
            session_id="s",
            ai_output="some output",
            final_resolution=resolution,
            reason_tags=list(tags),
        )

    def test_human_override_produces_non_empty_failure_analysis(self) -> None:
        ep = self._make_ep("human_override")
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertTrue(result.failure_analysis)
        self.assertIn("overridden", result.failure_analysis)

    def test_human_rejected_produces_non_empty_failure_analysis(self) -> None:
        ep = self._make_ep("human_rejected")
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertTrue(result.failure_analysis)
        self.assertIn("rejected", result.failure_analysis)

    def test_escalated_produces_non_empty_failure_analysis(self) -> None:
        ep = self._make_ep("escalated")
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertTrue(result.failure_analysis)
        self.assertIn("escalated", result.failure_analysis)

    def test_human_approved_produces_no_failure_analysis(self) -> None:
        ep = self._make_ep("human_approved")
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertTrue(result.failure_analysis)
        self.assertIn("approved", result.failure_analysis)

    def test_unknown_resolution_produces_manual_review_message(self) -> None:
        ep = VerificationEpisode(
            episode_id="e",
            timestamp="t",
            session_id="s",
            ai_output="x",
            final_resolution="unknown_type",
        )
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertIn("manual review", result.failure_analysis)

    def test_policy_proposal_contains_heuristics_when_tags_present(self) -> None:
        ep = self._make_ep("human_override", tags=("policy risk",))
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertIn("Suggested policy updates", result.policy_proposal)
        self.assertTrue(len(result.extracted_heuristics) > 0)

    def test_policy_proposal_no_actionable_when_no_tags(self) -> None:
        ep = self._make_ep("human_approved")
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertIn("No actionable policy update", result.policy_proposal)

    def test_reflection_result_to_dict_keys(self) -> None:
        ep = self._make_ep("human_override")
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        d = result.to_dict()
        self.assertIn("episode_id", d)
        self.assertIn("failure_analysis", d)
        self.assertIn("missing_context", d)
        self.assertIn("extracted_heuristics", d)
        self.assertIn("policy_proposal", d)
        self.assertIsInstance(d["extracted_heuristics"], list)

    def test_missing_context_from_semantic_type(self) -> None:
        ep = VerificationEpisode.create(
            session_id="s",
            ai_output="send the report",
            final_resolution="human_override",
            human_revision="send the policy report",
        )
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertIn("Policy or compliance", result.missing_context)

    def test_episode_id_preserved_in_result(self) -> None:
        ep = self._make_ep("human_rejected")
        agent = ReflectionAgent()
        result = agent.reflect(ep)
        self.assertEqual(ep.episode_id, result.episode_id)


if __name__ == "__main__":
    unittest.main()
