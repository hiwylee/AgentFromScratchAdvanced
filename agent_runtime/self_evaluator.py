"""Structural and lexical self-evaluation of agent answers.

The SelfEvaluator inspects a ``FinalAnswer`` dictionary and produces an
``EvalResult`` describing whether the answer is well-formed. All checks are
deterministic and stdlib-only — no LLM calls. The evaluator is intentionally
conservative: it only flags clearly broken or stubbed answers so that the
loop's existing intent classifier remains the source of truth for routing.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


# Korean + English error/refusal markers shared across the runtime.
_ERROR_PREFIXES: tuple[str, ...] = ("Error:", "error:", "오류:", "실패:")
_REFUSAL_PHRASES: tuple[str, ...] = (
    "지원하지 않",
    "처리할 수 없",
    "알 수 없",
    "cannot",
    "not supported",
    "unknown",
)
_KEYWORD_STOP_WORDS: frozenset[str] = frozenset(
    {
        # Korean particles / common verbs
        "을", "를", "이", "가", "은", "는", "의", "에", "서", "로", "와", "과",
        "보여", "줘", "알려",
        # English stop words
        "the", "a", "an", "show", "me", "what", "is",
    }
)


@dataclass
class EvalResult:
    """Outcome of a deterministic answer-quality check."""

    passed: bool
    score: float
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SelfEvaluator:
    """Evaluates FinalAnswer quality without LLM calls.

    Checks (all deterministic):
      1. Non-empty: answer content is not blank.
      2. Not an error-only response: content doesn't start with "Error:" / "error:".
      3. Not a refusal-only response: short content + refusal phrase.
      4. Lexical overlap: at least one query keyword appears in the answer.
      5. Length: answer is at least 20 chars (not a stub).
    """

    _ERROR_PREFIXES: tuple[str, ...] = _ERROR_PREFIXES
    _REFUSAL_PHRASES: tuple[str, ...] = _REFUSAL_PHRASES

    def evaluate(self, query: str, answer: dict[str, Any]) -> EvalResult:
        """Return an EvalResult for the given query/answer pair.

        Args:
            query: original user text.
            answer: ``FinalAnswer.to_dict()`` — has at least a ``content`` field.
        """
        content_value = answer.get("content", "") if isinstance(answer, dict) else ""
        content: str = content_value or ""
        issues: list[str] = []
        suggestions: list[str] = []

        # Check 1: non-empty content. Empty answers short-circuit further checks
        # because the remaining heuristics depend on having text to inspect.
        if not content.strip():
            issues.append("empty_answer")
            suggestions.append("Ensure the model produces non-empty content")
            return EvalResult(
                passed=False,
                score=0.0,
                issues=issues,
                suggestions=suggestions,
            )

        # Check 2: not error-only — content starts with a known error prefix.
        if any(content.startswith(prefix) for prefix in self._ERROR_PREFIXES):
            issues.append("error_response")
            suggestions.append(
                "Answer starts with error prefix — retry or use fallback"
            )

        # Check 3: short refusal-only message.
        if len(content) < 50 and any(p in content for p in self._REFUSAL_PHRASES):
            issues.append("refusal_only")
            suggestions.append(
                "Add supported query examples to the refusal message"
            )

        # Check 4: lexical overlap between query keywords and the answer.
        query_keywords = _extract_keywords(query)
        answer_lower = content.lower()
        matched = [kw for kw in query_keywords if kw in answer_lower]
        if query_keywords and not matched:
            issues.append("no_keyword_overlap")
            suggestions.append(
                f"Query keywords not in answer: {query_keywords[:3]}"
            )

        # Check 5: stub-length answer.
        if len(content) < 20:
            issues.append("answer_too_short")

        # Score: 1.0 minus 0.2 per issue, floor 0.0.
        score = max(0.0, 1.0 - 0.2 * len(issues))

        # ``no_keyword_overlap`` alone is informational and must not flip
        # ``passed`` to False — keyword heuristics are best-effort.
        blocking_issues = [i for i in issues if i != "no_keyword_overlap"]
        passed = not blocking_issues

        return EvalResult(
            passed=passed,
            score=score,
            issues=issues,
            suggestions=suggestions,
        )


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful Korean/English keywords, skipping stop words.

    Tokens are sequences of Hangul, ASCII letters, or digits of length >= 2
    that are not in the stop-word set.
    """
    if not isinstance(text, str) or not text:
        return []
    tokens = re.findall(r"[가-힣a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in _KEYWORD_STOP_WORDS and len(t) >= 2]


__all__ = ["EvalResult", "SelfEvaluator"]
