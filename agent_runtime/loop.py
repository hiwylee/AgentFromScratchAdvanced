"""Minimal agent loop with traceable state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from uuid import uuid4

from .audit import RunRecord, append_audit
from .intent import analyze_user_intent
from .model import MockModel
from .monitor import RunMonitor
from .types import Action, Budget, FinalAnswer, Message, Observation


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    intent: dict[str, object]
    action: dict[str, object]
    final_answer: dict[str, object]
    status_path: str
    events_path: str
    audit_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "intent": self.intent,
            "action": self.action,
            "final_answer": self.final_answer,
            "status_path": self.status_path,
            "events_path": self.events_path,
            "audit_path": self.audit_path,
        }


class AgentLoop:
    def __init__(
        self,
        *,
        model: MockModel | None = None,
        budget: Budget | None = None,
        run_root: Path = Path(".agent/runs"),
        audit_path: Path = Path(".agent/audit.jsonl"),
    ) -> None:
        self.model = model or MockModel()
        self.budget = budget or Budget()
        self.run_root = run_root
        self.audit_path = audit_path

    def run(self, user_text: str) -> AgentResult:
        run_id = str(uuid4())
        started = monotonic()
        monitor = RunMonitor(run_id=run_id, root_dir=self.run_root)
        monitor.start()
        self._audit(run_id, "run_started", {"budget": self.budget.to_dict()})

        user_message = Message(role="user", content=user_text)
        monitor.event("message_received", {"message": user_message.to_dict()})

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

        if monotonic() - started > self.budget.timeout_seconds:
            final = FinalAnswer(content="The run timed out before action selection.")
            monitor.finish("timed_out", {"final_answer": final.to_dict()})
            return self._result(monitor, intent_data, Action("final_answer", "timeout").to_dict(), final)

        action = self.model.choose_action(intent)
        monitor.event(
            "model_action_selected",
            {
                "model": {"name": self.model.name, "version": self.model.version},
                "action": action.to_dict(),
            },
        )
        self._audit(run_id, "model_action_selected", {"action": action.to_dict()})

        observation = Observation(
            source="mock_runtime",
            content={
                "step": "no_external_tools",
                "reason": "Milestone 1 records intent and next action only.",
            },
        )
        monitor.event("observation_recorded", {"observation": observation.to_dict()})

        final = _final_answer(action)
        monitor.finish("completed", {"final_answer": final.to_dict()})
        self._audit(run_id, "run_completed", {"final_answer": final.to_dict()})
        return self._result(monitor, intent_data, action.to_dict(), final)

    def _audit(self, run_id: str, event: str, data: dict[str, object]) -> None:
        append_audit(RunRecord.create(event=event, data=data, run_id=run_id), self.audit_path)

    def _result(
        self,
        monitor: RunMonitor,
        intent: dict[str, object],
        action: dict[str, object],
        final: FinalAnswer,
    ) -> AgentResult:
        return AgentResult(
            run_id=monitor.run_id,
            intent=intent,
            action=action,
            final_answer=final.to_dict(),
            status_path=str(monitor.status_path),
            events_path=str(monitor.events_path),
            audit_path=str(self.audit_path),
        )


def _final_answer(action: Action) -> FinalAnswer:
    if action.kind == "refuse":
        return FinalAnswer(
            content="I cannot proceed with a write or destructive database request in the current read-only mode.",
            assumptions=["Oracle ADW work is read-only by default."],
            next_action="Ask a read-only analysis question or request an explicit safe alternative.",
        )
    if action.kind == "ask_clarification":
        return FinalAnswer(
            content="I need schema or business glossary context before building a query plan.",
            assumptions=["No SQL should be generated before intent and schema context are resolved."],
            next_action="Inspect Oracle ADW schema context, then ask a clarification question if ambiguity remains.",
        )
    if action.kind == "inspect_schema":
        return FinalAnswer(
            content="The next safe step is to inspect Oracle ADW schema context.",
            assumptions=["The request can remain read-only."],
            next_action="Inspect schema.",
        )
    return FinalAnswer(
        content="This request can be handled without Oracle ADW context.",
        assumptions=[],
        next_action="Answer directly.",
    )
