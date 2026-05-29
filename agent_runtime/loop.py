"""Minimal agent loop with traceable state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from .session import SessionContext

from .audit import RunRecord, append_audit
from .hooks import HookRegistry
from .intent import analyze_user_intent
from .model import ActionModel, MockModel, ModelInvocationError
from .monitor import RunMonitor
from .query_plan import QueryPlanArtifact, build_query_plan_from_context
from .schema_context import build_compact_schema_context, load_schema_artifacts, load_schema_profile_from_manifest
from .tools import (
    ToolCall,
    ToolExecutionContext,
    ToolRegistry,
    ToolRunner,
    default_tool_registry,
)
from .types import Action, Budget, CancellationToken, FinalAnswer, Message, Observation, RunState

_PROJECT_ROOT = Path(__file__).parent.parent
_ARTIFACT_MANIFEST_PATH = _PROJECT_ROOT / "artifacts/artifact-manifest.v1.json"
_DEFAULT_SCHEMA_PROFILE_ID = "oracle_adw_sh.v1"


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    intent: dict[str, object]
    action: dict[str, object]
    final_answer: dict[str, object]
    status_path: str
    events_path: str
    audit_path: str

    query_plan: dict[str, object] | None = None
    plan_shadow: dict[str, object] | None = None
    plan_execution: dict[str, object] | None = None
    memory_summary: str | None = None
    eval_result: dict[str, object] | None = None  # SelfEvaluator answer-quality output
    # NOTE: this is NOT the acceptance-gate EvalRunResult from self_evolution.py
    # (schema "agent-runtime.eval-result.v1"). It holds SelfEvaluator.to_dict()
    # shape: {passed: bool, score: float, issues: list[str], suggestions: list[str]}.

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "run_id": self.run_id,
            "intent": self.intent,
            "action": self.action,
            "final_answer": self.final_answer,
            "status_path": self.status_path,
            "events_path": self.events_path,
            "audit_path": self.audit_path,
        }
        if self.query_plan is not None:
            result["query_plan"] = self.query_plan
        if self.plan_shadow is not None:
            result["plan_shadow"] = self.plan_shadow
        if self.plan_execution is not None:
            result["plan_execution"] = self.plan_execution
        if self.memory_summary is not None:
            result["memory_summary"] = self.memory_summary
        if self.eval_result is not None:
            result["eval_result"] = self.eval_result
        return result


class AgentLoop:
    def __init__(
        self,
        *,
        model: ActionModel | None = None,
        budget: Budget | None = None,
        cancellation_token: CancellationToken | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_max_attempts: int = 1,
        run_root: Path = Path(".agent/runs"),
        audit_path: Path = Path(".agent/audit.jsonl"),
        memory_dir: Path | None = None,
        hook_registry: HookRegistry | None = None,
        use_plan_execution: bool = False,
        session_ctx: "SessionContext | None" = None,
        allow_real_query: bool = False,
    ) -> None:
        self.model = model or MockModel()
        self.budget = budget or Budget()
        self.cancellation_token = cancellation_token or CancellationToken()
        self.tool_registry = tool_registry or default_tool_registry()
        self.tool_max_attempts = max(1, tool_max_attempts)
        self.run_root = run_root
        self.audit_path = audit_path
        self._memory_dir = memory_dir
        self._hook_registry = hook_registry
        self._use_plan_execution = use_plan_execution
        self._session_ctx = session_ctx
        self.allow_real_query = allow_real_query

    def run(self, user_text: str, cancellation_token: CancellationToken | None = None) -> AgentResult:
        token = cancellation_token or self.cancellation_token
        run_id = str(uuid4())
        started = monotonic()
        action_steps_used = 0
        monitor = RunMonitor(run_id=run_id, root_dir=self.run_root)
        monitor.start()
        self._audit(run_id, "run_started", {"budget": self.budget.to_dict()})

        stopped = self._stop_state(started, action_steps_used, token)
        if stopped is not None:
            state, reason = stopped
            return self._finish_stopped(monitor, {}, _control_action(reason), state, reason)

        user_message = Message(role="user", content=user_text)
        monitor.event("message_received", {"message": user_message.to_dict()})

        # Wire session context for multi-turn history windowing.
        if self._session_ctx is not None:
            self._session_ctx.add_message(user_message)

        stopped = self._stop_state(started, action_steps_used, token)
        if stopped is not None:
            state, reason = stopped
            return self._finish_stopped(monitor, {}, _control_action(reason), state, reason)

        intent = analyze_user_intent(user_text)
        intent_data = intent.to_dict()
        monitor.event(
            "intent_analyzed",
            {
                "intent": intent_data,
                "artifacts": {
                    "intent_schema": "artifacts/schemas/user-intent.schema.json",
                    "intent_prompt": "artifacts/prompts/intent-classifier.md",
                },
            },
        )
        self._audit(run_id, "intent_analyzed", {"intent": intent_data})
        if self._hook_registry is not None:
            self._hook_registry.fire("intent_analyzed", {"intent": intent_data})

        stopped = self._stop_state(started, action_steps_used, token, check_max_steps=True)
        if stopped is not None:
            state, reason = stopped
            return self._finish_stopped(monitor, intent_data, _control_action(reason), state, reason)

        # Load approved cross-session memories.
        approved_memories: list[Any] = []
        if self._memory_dir is not None:
            from .self_evolution import load_active_memories
            approved_memories = load_active_memories(self._memory_dir)

        memory_context: dict[str, Any] | None = None
        if approved_memories:
            memory_summary = _format_memory_context(approved_memories)
            memory_context = {"memory_summary": memory_summary}
            monitor.event(
                "memory_injected",
                {"memory_count": len(approved_memories), "memory_ids": [m.memory_id for m in approved_memories]},
            )
            self._audit(run_id, "memory_injected", {"memory_count": len(approved_memories)})
            if self._hook_registry is not None:
                self._hook_registry.fire("memory_injected", {"memory_count": len(approved_memories)})

        if self._session_ctx is not None:
            recent = self._session_ctx.recent_history(n=20)
            if recent:
                from .redaction import redact
                history_lines = [f"{m.role}: {redact(str(m.content))[:100]}" for m in recent]
                history_text = "\n".join(history_lines)
                if memory_context is None:
                    memory_context = {}
                # Prepared for future LLM context injection — no model adapter reads this key yet.
                memory_context["conversation_history"] = history_text

        try:
            action = self.model.choose_action(intent, context=memory_context)
        except ModelInvocationError as exc:
            action = Action(
                kind="model_error",
                reason=exc.code,
                payload={"error": exc.to_dict()},
            )
            monitor.event(
                "model_action_failed",
                {
                    "model": {"name": self.model.name, "version": self.model.version},
                    "error": exc.to_dict(),
                },
            )
            self._audit(run_id, "model_action_failed", {"error": exc.to_dict()})
            return self._finish_stopped(monitor, intent_data, action, "failed", exc.code)
        action_steps_used += 1
        monitor.event(
            "model_action_selected",
            {
                "model": {"name": self.model.name, "version": self.model.version},
                "action": action.to_dict(),
            },
        )
        self._audit(run_id, "model_action_selected", {"action": action.to_dict()})

        stopped = self._stop_state(started, action_steps_used, token)
        if stopped is not None:
            state, reason = stopped
            return self._finish_stopped(monitor, intent_data, action, state, reason)

        tool_call = _tool_call_for_action(action, user_text=user_text, registry=self.tool_registry, intent_data=intent_data)
        query_plan: QueryPlanArtifact | None = None
        real_expl = None
        if tool_call is not None:
            stopped = self._stop_state(started, action_steps_used, token, check_max_steps=True)
            if stopped is not None:
                state, reason = stopped
                return self._finish_stopped(monitor, intent_data, action, state, reason)

            tool_runner = ToolRunner(
                self.tool_registry,
                context=ToolExecutionContext(run_id=run_id, audit_path=self.audit_path),
                event_sink=monitor.event,
            )
            tool_result = tool_runner.run(tool_call, max_attempts=self.tool_max_attempts)
            action_steps_used += 1
            observation = Observation(
                source=f"tool:{tool_result.tool_name}",
                content={"tool_result": tool_result.to_dict()},
            )
            # 스키마 검사/명확화 성공 후 쿼리 플랜 생성 — ask_clarification도 포함
            if action.kind in {"inspect_schema", "ask_clarification"} and tool_result.state == "completed":
                query_plan = _build_query_plan(user_text, intent_data=intent_data)
                if query_plan is not None:
                    monitor.event("query_plan_built", {"query_plan": query_plan.to_dict()})
                    self._audit(run_id, "query_plan_built", {"query_plan": query_plan.to_dict()})

            # Milestone 8: if query plan is planned AND real query is allowed, execute
            if (
                self.allow_real_query
                and tool_result.state == "completed"
                and query_plan is not None
                and query_plan.status == "planned"
                and query_plan.proposed_sql
            ):
                adw_call = ToolCall(
                    "adw_query",
                    {
                        "sql": query_plan.proposed_sql,
                        "query_plan_id": query_plan.schema_context.get("schema_metadata_artifact_id", ""),
                    },
                )
                adw_runner = ToolRunner(
                    self.tool_registry,
                    context=ToolExecutionContext(
                        run_id=run_id,
                        audit_path=self.audit_path,
                        approved_high_risk_tools=("adw_query",),
                    ),
                    event_sink=monitor.event,
                )
                adw_tool_result = adw_runner.run(adw_call, max_attempts=1)
                action_steps_used += 1
                monitor.event("adw_query_executed", {"result": adw_tool_result.to_dict()})
                self._audit(run_id, "adw_query_executed", {"result": adw_tool_result.to_dict()})
                # Milestone 9: build real result explanation from actual ADW rows
                if adw_tool_result.state == "completed" and query_plan is not None:
                    from .result_explanation import build_real_result_explanation
                    try:
                        real_expl = build_real_result_explanation(
                            query_plan, adw_output=adw_tool_result.output
                        )
                        monitor.event(
                            "real_result_explanation_built",
                            {"result_explanation": real_expl.to_dict()},
                        )
                        self._audit(
                            run_id,
                            "real_result_explanation_built",
                            {"result_explanation": real_expl.to_dict()},
                        )
                    except Exception:
                        real_expl = None  # never block answer delivery on explanation failure
                # Merge adw result into observation
                observation = Observation(
                    source=f"tool:{tool_result.tool_name}+adw_query",
                    content={
                        "tool_result": tool_result.to_dict(),
                        "adw_query_result": adw_tool_result.to_dict(),
                    },
                )
        else:
            observation = Observation(
                source="mock_runtime",
                content={
                    "step": "no_external_tools",
                    "reason": "Milestone 1 records intent and next action only.",
                },
            )
        monitor.event("observation_recorded", {"observation": observation.to_dict()})

        stopped = self._stop_state(started, action_steps_used, token)
        if stopped is not None:
            state, reason = stopped
            return self._finish_stopped(monitor, intent_data, action, state, reason)

        final = _final_answer(action, query_plan=query_plan, real_explanation=real_expl)

        # Evaluate answer quality (deterministic, no LLM).
        _eval_result: dict[str, object] | None = None
        try:
            from .self_evaluator import SelfEvaluator
            _eval = SelfEvaluator().evaluate(user_text, final.to_dict())
            _eval_result = _eval.to_dict()
            monitor.event("answer_evaluated", {
                "passed": _eval.passed,
                "score": _eval.score,
                "issues": _eval.issues,
            })
            self._audit(run_id, "answer_evaluated", {"eval": _eval_result})
            if self._hook_registry is not None:
                self._hook_registry.fire("answer_evaluated", {"eval": _eval_result})
        except (AttributeError, TypeError, ValueError, KeyError, ImportError) as exc:
            monitor.event("answer_eval_failed", {"error": str(exc)})

        # Shadow mode: generate plan artifact without changing execution flow.
        plan_shadow: dict[str, object] | None = None
        plan: "ExecutionPlan | None" = None  # type: ignore[name-defined]
        try:
            from .executor import StepExecutor
            from .intent import KeywordIntentClassifier
            from .planner import KeywordPlanner
            intent_result = KeywordIntentClassifier().from_user_intent(intent)
            plan = KeywordPlanner().build(intent_result, request_id=run_id)
            shadow_results = StepExecutor().run_plan_shadow(plan)
            plan_shadow = {
                "plan": plan.to_dict(),
                "step_results": [r.to_dict() for r in shadow_results],
                "shadow_mode": True,
            }
            monitor.event("plan_shadow_recorded", {"plan_id": run_id, "steps": len(plan.steps)})
            if self._hook_registry is not None:
                self._hook_registry.fire("plan_shadow_recorded", {"plan_id": run_id, "steps": len(plan.steps)})
        except Exception as exc:
            monitor.event("plan_shadow_failed", {"error": str(exc)})

        # Opt-in real plan execution — additive to single-pass flow.
        plan_execution: dict[str, object] | None = None
        if self._use_plan_execution and plan is not None:
            try:
                from .executor import StepExecutor
                real_runner = ToolRunner(
                    self.tool_registry,
                    context=ToolExecutionContext(run_id=run_id, audit_path=self.audit_path),
                    event_sink=monitor.event,
                    hook_registry=self._hook_registry,
                )
                real_results = StepExecutor().run_plan(
                    plan, real_runner, tool_registry=self.tool_registry
                )
                plan_execution = {
                    "plan_id": run_id,
                    "step_results": [r.to_dict() for r in real_results],
                    "aborted": any(
                        r.error.startswith("aborted_by_step:") for r in real_results
                    ),
                }
                monitor.event(
                    "plan_execution_completed",
                    {"plan_id": run_id, "steps": len(real_results)},
                )
                if self._hook_registry is not None:
                    self._hook_registry.fire(
                        "plan_execution_completed",
                        {"plan_id": run_id, "steps": len(real_results)},
                    )
            except Exception as exc:
                monitor.event("plan_execution_failed", {"error": str(exc)})

        # Compress session history when threshold exceeded — compress_history() returns []
        # when under threshold, so no outer guard is needed.
        if self._session_ctx is not None:
            proposed = self._session_ctx.compress_history()
            if proposed:
                monitor.event("session_history_compressed", {
                    "session_id": self._session_ctx.session_id,
                    "proposed_memory_count": len(proposed),
                })

        monitor.finish("completed", {"final_answer": final.to_dict()})
        self._audit(run_id, "run_completed", {"final_answer": final.to_dict()})
        return self._result(
            monitor,
            intent_data,
            action.to_dict(),
            final,
            query_plan=query_plan,
            plan_shadow=plan_shadow,
            plan_execution=plan_execution,
            memory_summary=memory_context.get("memory_summary") if memory_context else None,
            eval_result=_eval_result,
        )

    def summarize_session(
        self,
        run_results: list[dict[str, object]],
        memory_dir: Path,
        session_id: str = "default",
        author: str = "session_summarizer",
    ) -> "SessionSummary | None":
        """Summarize a completed session and write proposed MemoryRecord files.

        Calls SessionSummarizer.summarize() and returns the SessionSummary.
        Returns None if summarization fails (never raises).
        Re-raises SecretLeakError — secret leaks must never be silenced.
        """
        import logging
        try:
            from .session_summarizer import SessionSummarizer, SessionSummary  # noqa: F401
            summary = SessionSummarizer().summarize(
                session_id=session_id,
                run_results=run_results,
                memory_dir=memory_dir,
                author=author,
            )
            self._audit(session_id, "session_summarized", {
                "failure_patterns": len(summary.failure_patterns),
                "proposed_paths": summary.proposed_memory_paths,
            })
            return summary
        except Exception as exc:
            # Re-raise secret-leak errors — never silence them.
            from .trace import SecretLeakError
            if isinstance(exc, SecretLeakError):
                raise
            logging.getLogger(__name__).warning("summarize_session failed: %s", exc)
            return None

    def _stop_state(
        self,
        started: float,
        steps_used: int,
        token: CancellationToken,
        *,
        check_max_steps: bool = False,
    ) -> tuple[RunState, str] | None:
        if token.is_cancelled:
            return "cancelled", token.reason
        if monotonic() - started >= self.budget.timeout_seconds:
            return "timed_out", "timeout_seconds_exceeded"
        if check_max_steps and steps_used >= self.budget.max_steps:
            return "stopped", "max_steps_exceeded"
        return None

    def _finish_stopped(
        self,
        monitor: RunMonitor,
        intent: dict[str, object],
        action: Action,
        state: RunState,
        reason: str,
    ) -> AgentResult:
        final = _control_final_answer(state, reason)
        summary = {
            "reason": reason,
            "action": action.to_dict(),
            "final_answer": final.to_dict(),
        }
        monitor.finish(state, summary)
        self._audit(
            monitor.run_id,
            f"run_{state}",
            {"reason": reason, "final_answer": final.to_dict()},
        )
        return self._result(monitor, intent, action.to_dict(), final)

    def _audit(self, run_id: str, event: str, data: dict[str, object]) -> None:
        append_audit(RunRecord.create(event=event, data=data, run_id=run_id), self.audit_path)

    def _result(
        self,
        monitor: RunMonitor,
        intent: dict[str, object],
        action: dict[str, object],
        final: FinalAnswer,
        query_plan: QueryPlanArtifact | None = None,
        plan_shadow: dict[str, object] | None = None,
        plan_execution: dict[str, object] | None = None,
        memory_summary: str | None = None,
        eval_result: dict[str, object] | None = None,
    ) -> AgentResult:
        return AgentResult(
            run_id=monitor.run_id,
            intent=intent,
            action=action,
            final_answer=final.to_dict(),
            status_path=str(monitor.status_path),
            events_path=str(monitor.events_path),
            audit_path=str(self.audit_path),
            query_plan=query_plan.to_dict() if query_plan is not None else None,
            plan_shadow=plan_shadow,
            plan_execution=plan_execution,
            memory_summary=memory_summary,
            eval_result=eval_result,
        )


def _english_terms_from_intent(intent_data: dict) -> list[str]:
    # 한글 쿼리에서 추출된 엔티티를 영어 동의어로 변환 — 스키마 리트리버 BM25 매칭용
    # 멀티워드 term("previous month")은 개별 단어도 추가해 단어 단위 매칭 보장
    # 추이/trend 키워드가 있으면 시간 범위 미지정이어도 "month" 주입 (월별 분석 의미)
    from .intent import DIMENSION_KEYWORDS, METRIC_KEYWORDS, TIME_RANGE_KEYWORDS

    terms: list[str] = []
    entities = intent_data.get("entities", {})
    for metric in entities.get("metrics", []):
        terms.extend(kw for kw in METRIC_KEYWORDS.get(metric, ()) if kw.isascii())
    for dim in entities.get("dimensions", []):
        terms.extend(kw for kw in DIMENSION_KEYWORDS.get(dim, ()) if kw.isascii())
    time_ranges = entities.get("time_ranges", [])
    for time_range in time_ranges:
        for kw in TIME_RANGE_KEYWORDS.get(time_range, ()):
            if kw.isascii():
                terms.append(kw)
                terms.extend(kw.split())
    if not time_ranges and intent_data.get("task_type") in {"trend_analysis", "comparison"}:
        terms.extend(["month", "monthly"])
    return list(dict.fromkeys(terms))


def _build_query_plan(user_text: str, *, intent_data: dict | None = None) -> QueryPlanArtifact | None:
    # 예외 발생 시 None 반환 — 쿼리 플랜 실패가 전체 실행을 중단시키지 않도록 격리
    try:
        profile = load_schema_profile_from_manifest(
            _DEFAULT_SCHEMA_PROFILE_ID, _ARTIFACT_MANIFEST_PATH, project_root=_PROJECT_ROOT
        )
        artifacts = load_schema_artifacts(profile.metadata_path, profile.seed_path)
        request_terms = _english_terms_from_intent(intent_data) if intent_data else []
        compact = build_compact_schema_context(artifacts, request_text=user_text, request_terms=request_terms)
        return build_query_plan_from_context(compact, request_text=user_text)
    except Exception:
        return None


def _real_execution_answer(real_expl: object, query_plan: QueryPlanArtifact | None) -> FinalAnswer:
    """Build a FinalAnswer that surfaces actual ADW query rows."""
    from .result_explanation import ResultExplanationArtifact
    if not isinstance(real_expl, ResultExplanationArtifact):
        raise TypeError(f"real_expl must be ResultExplanationArtifact, got {type(real_expl).__name__}")
    rows = list(real_expl.rows[:5])
    db_row_count = real_expl.row_count
    lines = [real_expl.summary]
    if rows:
        header = " | ".join(real_expl.columns)
        lines.append(f"\n{header}")
        lines.append("-" * len(header))
        for row in rows:
            lines.append(" | ".join(str(row.get(c, "")) for c in real_expl.columns))
        if db_row_count > len(rows):
            lines.append(f"... ({db_row_count - len(rows)} more rows in database)")
    content = "\n".join(lines)
    assumptions = list(query_plan.assumptions) if query_plan else []
    assumptions.append("Results are from real Oracle ADW execution via SQLcl read-only adapter.")
    return FinalAnswer(
        content=content,
        assumptions=assumptions,
        next_action="Results reflect actual database contents at query time.",
    )


def _final_answer(
    action: Action,
    *,
    query_plan: QueryPlanArtifact | None = None,
    real_explanation: "ResultExplanationArtifact | None" = None,
) -> FinalAnswer:
    from .result_explanation import ResultExplanationArtifact
    real_expl = real_explanation if isinstance(real_explanation, ResultExplanationArtifact) else None

    if action.kind == "refuse":
        return FinalAnswer(
            content="I cannot proceed with a write or destructive database request in the current read-only mode.",
            assumptions=["Oracle ADW work is read-only by default."],
            next_action="Ask a read-only analysis question or request an explicit safe alternative.",
        )
    if action.kind == "ask_clarification":
        if real_expl is not None and real_expl.status == "succeeded":
            return _real_execution_answer(real_expl, query_plan)
        # 스키마 검사 후 쿼리 플랜이 생성됐으면 SQL 반환 (한글 쿼리 포함)
        if query_plan is not None and query_plan.status == "planned":
            return FinalAnswer(
                content=f"Query plan ready. Proposed SQL:\n{query_plan.proposed_sql}",
                assumptions=list(query_plan.assumptions),
                next_action="SQL is policy-validated and ready for review. Use adw-query to execute.",
            )
        return FinalAnswer(
            content="I need schema or business glossary context before building a query plan.",
            assumptions=["No SQL should be generated before intent and schema context are resolved."],
            next_action="Inspect Oracle ADW schema context, then ask a clarification question if ambiguity remains.",
        )
    if action.kind == "inspect_schema":
        if real_expl is not None and real_expl.status == "succeeded":
            return _real_execution_answer(real_expl, query_plan)
        if query_plan is not None and query_plan.status == "planned":
            return FinalAnswer(
                content=f"Query plan ready. Proposed SQL:\n{query_plan.proposed_sql}",
                assumptions=list(query_plan.assumptions),
                next_action="SQL is policy-validated and ready for review. Use adw-query to execute.",
            )
        if query_plan is not None:
            return FinalAnswer(
                content=f"Schema inspected. Query plan status: {query_plan.status}. {query_plan.refusal_reason or ''}",
                assumptions=list(query_plan.assumptions),
                next_action="Refine the request to match a supported pattern: revenue by product/channel/promotion by month.",
            )
        return FinalAnswer(
            content="The next safe step is to inspect Oracle ADW schema context.",
            assumptions=["The request can remain read-only."],
            next_action="Inspect schema.",
        )
    if action.kind == "select_workflow":
        return FinalAnswer(
            content="This request should start from a versioned workflow template before any system action runs.",
            assumptions=[
                "Multi-system workflow execution requires checkpoints, reconciliation rules, and human gates.",
            ],
            next_action="Select a workflow template and prepare a reviewable execution plan.",
        )
    if action.kind == "model_error":
        return FinalAnswer(
            content="The configured model provider failed before a safe action could be selected.",
            assumptions=["No live database execution or workflow write was attempted."],
            next_action="Check model provider configuration or retry with the mock provider.",
        )
    return FinalAnswer(
        content="This request can be handled without Oracle ADW context.",
        assumptions=[],
        next_action="Answer directly.",
    )


def _tool_call_for_action(
    action: Action,
    *,
    user_text: str,
    registry: ToolRegistry,
    intent_data: dict | None = None,
) -> ToolCall | None:
    if action.kind not in {"inspect_schema", "ask_clarification"}:
        return None
    required_context = action.payload.get("required_context", [])
    if not isinstance(required_context, list):
        required_context = []
    if action.kind == "ask_clarification" and "oracle_adw_schema" not in required_context:
        return None
    request_terms = action.payload.get("request_terms", [])
    if not isinstance(request_terms, list):
        request_terms = []

    arguments: dict[str, object] = {
        "required_context": required_context,
        "request_text": user_text,
        "request_terms": request_terms,
    }
    return ToolCall("mock_schema_context", _supported_tool_arguments(registry, "mock_schema_context", arguments))


def _supported_tool_arguments(
    registry: ToolRegistry,
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    try:
        registered = registry.get(tool_name)
    except KeyError:
        return arguments
    supported = {parameter.name for parameter in registered.spec.parameters}
    return {name: value for name, value in arguments.items() if name in supported}


def _control_action(reason: str) -> Action:
    return Action(kind="final_answer", reason=reason, payload={"runtime_control": reason})


def _format_memory_context(memories: list[Any]) -> str:
    """Format approved MemoryRecord list into a plain-text block for model context."""
    lines: list[str] = []
    for mem in memories:
        lines.append(f"- [{mem.memory_id}] {mem.key}: {mem.value}")
    return "\n".join(lines)


def _control_final_answer(state: RunState, reason: str) -> FinalAnswer:
    if state == "timed_out":
        return FinalAnswer(
            content="The run timed out before it could safely continue.",
            next_action="Retry with a larger timeout or a smaller request.",
        )
    if state == "cancelled":
        return FinalAnswer(
            content="The run was cancelled before it could safely continue.",
            next_action="Start a new run when ready.",
        )
    if state == "failed":
        return FinalAnswer(
            content="The run failed before it could safely continue.",
            assumptions=[f"Failure reason: {reason}"],
            next_action="Inspect the run events and fix the failing configuration.",
        )
    return FinalAnswer(
        content="The run stopped after reaching its configured step limit.",
        assumptions=[f"Stop reason: {reason}"],
        next_action="Retry with a larger max step budget if more work is needed.",
    )
