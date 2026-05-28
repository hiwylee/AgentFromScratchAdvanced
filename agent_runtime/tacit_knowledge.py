"""Tacit knowledge capture: verification episodes, correction diffs, reflection."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .redaction import redact


# --- Data Classes ---

@dataclass(frozen=True)
class CorrectionDiff:
    removed: tuple[str, ...] = ()
    inserted: tuple[str, ...] = ()
    tone_change: str | None = None
    terminology_changes: tuple[str, ...] = ()
    semantic_type: str = "other"  # literal_to_contextual | tone | policy_risk | domain_nuance | escalation | no_change | other

    @classmethod
    def from_texts(cls, ai_output: str, human_revision: str | None) -> "CorrectionDiff":
        """Deterministic diff: word-level removed/inserted, heuristic semantic_type."""
        if not human_revision or ai_output == human_revision:
            return cls(semantic_type="no_change")
        ai_words = set(ai_output.lower().split())
        rev_words = set(human_revision.lower().split())
        removed = tuple(sorted(ai_words - rev_words))
        inserted = tuple(sorted(rev_words - ai_words))
        # heuristic semantic_type classification
        semantic_type = "other"
        policy_keywords = {"policy", "compliance", "legal", "risk", "regulation", "정책", "법적", "규정"}
        domain_keywords = {"financial", "finance", "technical", "domain", "금융", "재무", "기술"}
        escalation_keywords = {"escalate", "escalation", "urgent", "critical", "긴급", "에스컬레이션"}
        tone_keywords = {"please", "kindly", "sorry", "apologize", "죄송", "부탁"}
        inserted_set = set(w.lower() for w in inserted)
        if inserted_set & policy_keywords:
            semantic_type = "policy_risk"
        elif inserted_set & escalation_keywords:
            semantic_type = "escalation"
        elif inserted_set & tone_keywords:
            semantic_type = "tone"
        elif inserted_set & domain_keywords:
            semantic_type = "domain_nuance"
        elif len(inserted) > len(removed):
            semantic_type = "literal_to_contextual"
        return cls(removed=removed, inserted=inserted, semantic_type=semantic_type)

    def to_dict(self) -> dict:
        return {
            "removed": list(self.removed),
            "inserted": list(self.inserted),
            "tone_change": self.tone_change,
            "terminology_changes": list(self.terminology_changes),
            "semantic_type": self.semantic_type,
        }


@dataclass(frozen=True)
class VerificationEpisode:
    episode_id: str
    timestamp: str
    session_id: str
    ai_output: str
    final_resolution: str  # human_override | human_approved | human_rejected | escalated
    input_context: dict = field(default_factory=dict)
    retrieved_context: dict = field(default_factory=dict)
    human_revision: str | None = None
    correction_diff: CorrectionDiff | None = None
    confidence_before: float | None = None
    confidence_after: float | None = None
    uncertainty_regions: tuple[str, ...] = ()
    consultation_trace: tuple[dict, ...] = ()
    reason_tags: tuple[str, ...] = ()
    reflection_summary: str | None = None
    schema_version: str = "agent-runtime.verification-episode.v1"

    @classmethod
    def create(
        cls,
        session_id: str,
        ai_output: str,
        final_resolution: str,
        *,
        human_revision: str | None = None,
        confidence_before: float | None = None,
        confidence_after: float | None = None,
        uncertainty_regions: Sequence[str] = (),
        consultation_trace: Sequence[dict] = (),
        reason_tags: Sequence[str] = (),
        input_context: dict | None = None,
    ) -> "VerificationEpisode":
        diff = CorrectionDiff.from_texts(ai_output, human_revision) if human_revision else None
        return cls(
            episode_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            ai_output=ai_output,
            final_resolution=final_resolution,
            human_revision=human_revision,
            correction_diff=diff,
            confidence_before=confidence_before,
            confidence_after=confidence_after,
            uncertainty_regions=tuple(uncertainty_regions),
            consultation_trace=tuple(consultation_trace),
            reason_tags=tuple(reason_tags),
            input_context=input_context or {},
        )

    def to_dict(self) -> dict:
        d = {
            "episode_id": self.episode_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "ai_output": self.ai_output,
            "final_resolution": self.final_resolution,
            "input_context": self.input_context,
            "retrieved_context": self.retrieved_context,
            "human_revision": self.human_revision,
            "correction_diff": self.correction_diff.to_dict() if self.correction_diff else None,
            "confidence_before": self.confidence_before,
            "confidence_after": self.confidence_after,
            "uncertainty_regions": list(self.uncertainty_regions),
            "consultation_trace": list(self.consultation_trace),
            "reason_tags": list(self.reason_tags),
            "reflection_summary": self.reflection_summary,
            "schema_version": self.schema_version,
        }
        return d


# --- Episode Store ---

class VerificationEpisodeStore:
    """Append-only JSONL store for verification episodes. Mirrors audit.py pattern."""

    def __init__(self, store_dir: str | Path) -> None:
        self._dir = Path(store_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe}.jsonl"

    def append(self, episode: VerificationEpisode) -> None:
        record = redact(episode.to_dict())
        with self._path(episode.session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_session(self, session_id: str) -> list[dict]:
        p = self._path(session_id)
        if not p.exists():
            return []
        episodes = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                episodes.append(json.loads(line))
        return episodes

    def load_all(self) -> list[dict]:
        episodes = []
        for f in sorted(self._dir.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    episodes.append(json.loads(line))
        return episodes


# --- Tacit Signal Extractor ---

_TAG_TO_HEURISTIC: dict[str, str] = {
    "tone mismatch": "prefer softer or more formal phrasing in this domain",
    "domain nuance": "domain-specific terminology requires expert review",
    "policy risk": "legal or compliance language requires manual confirmation",
    "escalation": "high-risk cases should be escalated before final output",
    "missing context": "agent lacked sufficient context; retrieve more before answering",
    "hallucination risk": "output contains unverifiable claims; flag for human review",
}

_SEMANTIC_TO_HEURISTIC: dict[str, str] = {
    "policy_risk": "outputs involving policy or legal terms require human gate",
    "escalation": "escalation markers detected; route to senior reviewer",
    "domain_nuance": "domain-specific correction pattern; consult domain expert",
    "tone": "tone adjustment needed; review phrasing before delivery",
    "literal_to_contextual": "literal translation insufficient; contextual business phrasing needed",
}


@dataclass
class TacitSignal:
    episode_id: str
    suspected_heuristics: list[str]
    source_tags: list[str]
    source_semantic_type: str | None


class TacitSignalExtractor:
    """Extracts suspected heuristics from a VerificationEpisode deterministically."""

    def extract(self, episode: VerificationEpisode) -> TacitSignal:
        heuristics: list[str] = []
        for tag in episode.reason_tags:
            h = _TAG_TO_HEURISTIC.get(tag.lower().strip())
            if h and h not in heuristics:
                heuristics.append(h)
        semantic_type = episode.correction_diff.semantic_type if episode.correction_diff else None
        if semantic_type and semantic_type != "no_change" and semantic_type != "other":
            h = _SEMANTIC_TO_HEURISTIC.get(semantic_type)
            if h and h not in heuristics:
                heuristics.append(h)
        if episode.consultation_trace:
            for entry in episode.consultation_trace:
                person = entry.get("person", "")
                reason = entry.get("reason", "")
                if person:
                    h = f"consult {person} when: {reason}" if reason else f"consult {person} for this domain"
                    if h not in heuristics:
                        heuristics.append(h)
        return TacitSignal(
            episode_id=episode.episode_id,
            suspected_heuristics=heuristics,
            source_tags=list(episode.reason_tags),
            source_semantic_type=semantic_type,
        )


# --- Reflection Result ---

@dataclass(frozen=True)
class ReflectionResult:
    episode_id: str
    failure_analysis: str
    missing_context: str
    extracted_heuristics: tuple[str, ...]
    policy_proposal: str

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "failure_analysis": self.failure_analysis,
            "missing_context": self.missing_context,
            "extracted_heuristics": list(self.extracted_heuristics),
            "policy_proposal": self.policy_proposal,
        }


_RESOLUTION_TO_ANALYSIS: dict[str, str] = {
    "human_override": "The AI output was overridden by a human, indicating a gap between AI judgment and organizational expectation.",
    "human_rejected": "The AI output was rejected outright, suggesting a fundamental mismatch with requirements.",
    "escalated": "The case was escalated, indicating the AI lacked authority or confidence to resolve it autonomously.",
    "human_approved": "The AI output was approved. No failure detected.",
}

_SEMANTIC_TO_MISSING: dict[str, str] = {
    "policy_risk": "Policy or compliance context was missing from the generation prompt.",
    "domain_nuance": "Domain-specific terminology context was insufficient.",
    "tone": "Audience tone preference was not provided.",
    "escalation": "Risk threshold context for escalation was not available.",
    "literal_to_contextual": "Business phrasing conventions for this domain were not in context.",
}


class ReflectionAgent:
    """Deterministic reflection on a VerificationEpisode. Mirrors self_evaluator.py pattern.

    Future: wire optional LLM critic the same way SelfEvaluator does.
    """

    def reflect(self, episode: VerificationEpisode) -> ReflectionResult:
        failure_analysis = _RESOLUTION_TO_ANALYSIS.get(
            episode.final_resolution,
            "Unknown resolution type; manual review recommended.",
        )
        semantic_type = episode.correction_diff.semantic_type if episode.correction_diff else None
        missing_context = _SEMANTIC_TO_MISSING.get(
            semantic_type or "",
            "Insufficient context; review agent retrieval and prompt.",
        )
        extractor = TacitSignalExtractor()
        signal = extractor.extract(episode)
        heuristics = tuple(signal.suspected_heuristics)
        if heuristics:
            policy_lines = [f"- {h}" for h in heuristics]
            policy_proposal = "Suggested policy updates:\n" + "\n".join(policy_lines)
        else:
            policy_proposal = "No actionable policy update identified from this episode."
        return ReflectionResult(
            episode_id=episode.episode_id,
            failure_analysis=failure_analysis,
            missing_context=missing_context,
            extracted_heuristics=heuristics,
            policy_proposal=policy_proposal,
        )
