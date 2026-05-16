"""Workflow orchestration skeleton for mock business processes."""

from __future__ import annotations

import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .audit import RunRecord, append_audit
from .monitor import RunMonitor
from .redaction import redact
from .types import utc_now


Record = dict[str, Any]
DEFAULT_TEMPLATE_PATH = Path("artifacts/workflows/patent-asset-replacement-registration.json")


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    system: str
    action: str
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkflowTemplate:
    template_id: str
    template_version: int
    workflow_id: str
    required_fields: tuple[str, ...]
    nodes: tuple[dict[str, Any], ...]
    review_packet_required_fields: tuple[str, ...]
    reconciliation_rules: tuple[dict[str, Any], ...]
    audit_required_events: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "template_version": self.template_version,
            "workflow_id": self.workflow_id,
            "required_fields": list(self.required_fields),
            "nodes": list(self.nodes),
            "review_packet_required_fields": list(self.review_packet_required_fields),
            "reconciliation_rules": list(self.reconciliation_rules),
            "audit_required_events": list(self.audit_required_events),
        }


@dataclass(frozen=True)
class StepResult:
    step_id: str
    state: str
    system: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HumanDecision:
    actor: str
    action: str
    policy_basis: str
    approved_record_ids: tuple[str, ...]
    decided_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkflowConnector(Protocol):
    """Connector shape for source, enrichment, and target systems."""

    def lookup_a(self, period: str) -> list[Record]:
        raise NotImplementedError

    def lookup_b(self, period: str) -> list[Record]:
        raise NotImplementedError

    def enrich_c(self, period: str, records: list[Record]) -> list[Record]:
        raise NotImplementedError

    def load_d(self, period: str, records: list[Record]) -> dict[str, Any]:
        raise NotImplementedError


class MockPatentAssetConnector:
    """Deterministic mock A/B/C/D connector for milestone tests and CLI wiring."""

    def __init__(
        self,
        *,
        system_a: dict[str, list[Record]] | None = None,
        system_b: dict[str, list[Record]] | None = None,
        system_c: dict[str, list[Record]] | None = None,
    ) -> None:
        self._system_a = _default_system_a() if system_a is None else system_a
        self._system_b = _default_system_b() if system_b is None else system_b
        self._system_c = _default_system_c() if system_c is None else system_c
        self.loaded_batches: list[dict[str, Any]] = []

    def lookup_a(self, period: str) -> list[Record]:
        return _copy_records(self._system_a.get(period, []))

    def lookup_b(self, period: str) -> list[Record]:
        return _copy_records(self._system_b.get(period, []))

    def enrich_c(self, period: str, records: list[Record]) -> list[Record]:
        requested = {record["patent_id"] for record in records if record.get("patent_id")}
        return [
            record
            for record in _copy_records(self._system_c.get(period, []))
            if record.get("patent_id") in requested
        ]

    def load_d(self, period: str, records: list[Record]) -> dict[str, Any]:
        batch = {"period": period, "records": _copy_records(records)}
        self.loaded_batches.append(batch)
        return {
            "loaded": True,
            "period": period,
            "record_count": len(records),
            "patent_ids": [record["patent_id"] for record in records],
        }


class WorkflowEngine:
    def __init__(
        self,
        connector: WorkflowConnector | None = None,
        *,
        template_path: Path = DEFAULT_TEMPLATE_PATH,
        run_root: Path = Path(".agent/workflows"),
        audit_path: Path = Path(".agent/audit.jsonl"),
    ) -> None:
        self.connector = connector or MockPatentAssetConnector()
        self.template = load_workflow_template(template_path)
        self.run_root = run_root
        self.audit_path = audit_path
        self._checkpoint_store: dict[str, dict[str, Any]] = {}

    def run_patent_asset_replacement(self, *, period: str = "current_month") -> dict[str, Any]:
        run_id = str(uuid4())
        monitor = RunMonitor(run_id=run_id, root_dir=self.run_root)
        monitor.start()
        self._event(monitor, run_id, "workflow_template_selected", {"template": self.template.to_dict(), "period": period})

        steps: list[StepResult] = [
            StepResult(
                step_id="template_selected",
                state="completed",
                system="workflow",
                action="select_template",
                details={"template_id": self.template.template_id},
            )
        ]

        try:
            records_a, records_b = self._lookup_sources(period, monitor, run_id, steps)
            reconciliation = _reconcile(
                {"A": records_a, "B": records_b},
                required_fields=self.template.required_fields,
                requested_period=period,
            )

            if reconciliation["missing_required"]:
                records_c = self.connector.enrich_c(
                    period,
                    [reconciliation["records"][patent_id] for patent_id in reconciliation["missing_required"]],
                )
                steps.append(
                    StepResult(
                        step_id="enrich_missing_fields",
                        state="completed",
                        system="C",
                        action="enrich",
                        details={
                            "requested_count": len(reconciliation["missing_required"]),
                            "record_count": len(records_c),
                        },
                    )
                )
                self._event(monitor, run_id, "workflow_node_completed", steps[-1].to_dict())
                reconciliation = _reconcile(
                    {"A": records_a, "B": records_b, "C": records_c},
                    required_fields=self.template.required_fields,
                    requested_period=period,
                )
            else:
                steps.append(
                    StepResult(
                        step_id="enrich_missing_fields",
                        state="skipped",
                        system="C",
                        action="enrich",
                        details={"reason": "required_information_present"},
                    )
                )
                self._event(monitor, run_id, "workflow_node_completed", steps[-1].to_dict())

            self._event(monitor, run_id, "reconciliation_completed", {"reconciliation": reconciliation})

            unresolved = reconciliation["status"] != "resolved"
            if unresolved:
                review_packet = _review_packet(
                    run_id=run_id,
                    template=self.template,
                    period=period,
                    reconciliation=reconciliation,
                )
                human_gate = {"required": True, "state": "paused", "review_packet": review_packet}
                steps.append(
                    StepResult(
                        step_id="human_review_unresolved",
                        state="paused",
                        system="workflow",
                        action="review",
                        details={"review_packet": review_packet},
                    )
                )
                self._event(monitor, run_id, "human_gate_opened", {"review_packet": review_packet})
                target_load = _blocked_load("human_gate_unresolved")
                steps.append(_load_step("blocked", "human_gate_unresolved"))
                state = "paused"
            elif not reconciliation["records"]:
                review_packet = None
                human_gate = {"required": False, "state": "not_required", "review_packet": None}
                target_load = _blocked_load("no_records_to_load")
                steps.append(_load_step("skipped", "no_records_to_load"))
                state = "closed"
            else:
                review_packet = _checkpoint_packet(
                    run_id=run_id,
                    template=self.template,
                    period=period,
                    reconciliation=reconciliation,
                )
                human_gate = {"required": True, "state": "checkpoint_required", "review_packet": review_packet}
                steps.append(
                    StepResult(
                        step_id="pre_load_checkpoint",
                        state="paused",
                        system="workflow",
                        action="checkpoint",
                        details={"review_packet": review_packet},
                    )
                )
                self._event(monitor, run_id, "target_load_checkpoint_requested", {"review_packet": review_packet})
                target_load = _blocked_load("explicit_checkpoint_required")
                steps.append(_load_step("skipped", "explicit_checkpoint_required"))
                state = "checkpoint_required"
                self._checkpoint_store[run_id] = {
                    "state": state,
                    "period": period,
                    "records": deepcopy(list(reconciliation["records"].values())),
                    "reconciliation": deepcopy(reconciliation),
                    "review_packet": deepcopy(review_packet),
                }

            result = _result(
                run_id=run_id,
                state=state,
                template=self.template,
                period=period,
                steps=steps,
                reconciliation=reconciliation,
                human_gate=human_gate,
                target_load=target_load,
                monitor=monitor,
                audit_path=self.audit_path,
            )
            if state in {"paused", "checkpoint_required"}:
                monitor.pause(state, {"workflow": result})
            else:
                monitor.finish(state, {"workflow": result})
            self._audit(run_id, "workflow_completed", {"workflow": result})
            return result
        except Exception as exc:  # noqa: BLE001 - this boundary converts connector failures to workflow state.
            failure = {
                "state": "failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            steps.append(
                StepResult(
                    step_id="workflow_failure",
                    state="failed",
                    system="workflow",
                    action="fail",
                    details=failure,
                )
            )
            result = _result(
                run_id=run_id,
                state="failed",
                template=self.template,
                period=period,
                steps=steps,
                reconciliation={"status": "failed", "errors": [failure]},
                human_gate={"required": False, "state": "not_available", "review_packet": None},
                target_load=_blocked_load("workflow_failed"),
                monitor=monitor,
                audit_path=self.audit_path,
            )
            monitor.finish("failed", {"workflow": result})
            self._audit(run_id, "workflow_completed", {"workflow": result})
            return result

    def resume_with_human_decision(
        self,
        run_id: str,
        decision: HumanDecision,
    ) -> dict[str, Any]:
        checkpoint = self._checkpoint_store.get(run_id)
        if checkpoint is None:
            return {
                "state": "blocked",
                "reason": "trusted_checkpoint_not_found",
                "human_decision": decision.to_dict(),
                "target_load": _blocked_load("trusted_checkpoint_not_found"),
            }
        monitor = _resume_monitor(run_id, self.run_root)
        if decision.action != "approve_load":
            self._audit(run_id, "human_decision_recorded", {"decision": decision.to_dict(), "accepted": False})
            result = {
                "state": "closed",
                "reason": decision.action,
                "human_decision": decision.to_dict(),
                "target_load": _blocked_load("human_decision_not_approve_load"),
            }
            self._checkpoint_store.pop(run_id, None)
            monitor.finish("closed", {"workflow": result})
            self._audit(run_id, "workflow_completed", {"workflow": result})
            return result
        if checkpoint["state"] != "checkpoint_required":
            self._audit(run_id, "human_decision_recorded", {"decision": decision.to_dict(), "accepted": False})
            result = {
                "state": "blocked",
                "reason": "run_not_at_load_checkpoint",
                "human_decision": decision.to_dict(),
                "target_load": _blocked_load("run_not_at_load_checkpoint"),
            }
            monitor.finish("blocked", {"workflow": result})
            self._audit(run_id, "workflow_completed", {"workflow": result})
            return result

        records = [
            deepcopy(record)
            for record in checkpoint["records"]
            if record["patent_id"] in set(decision.approved_record_ids)
        ]
        approved_ids = {record["patent_id"] for record in records}
        if approved_ids != set(decision.approved_record_ids):
            self._audit(run_id, "human_decision_recorded", {"decision": decision.to_dict(), "accepted": False})
            result = {
                "state": "blocked",
                "reason": "approved_records_not_in_checkpoint",
                "human_decision": decision.to_dict(),
                "target_load": _blocked_load("approved_records_not_in_checkpoint"),
            }
            monitor.finish("blocked", {"workflow": result})
            self._audit(run_id, "workflow_completed", {"workflow": result})
            return result
        self._audit(run_id, "human_decision_recorded", {"decision": decision.to_dict(), "accepted": True})
        monitor.event("human_decision_recorded", {"decision": decision.to_dict(), "accepted": True})
        monitor.event(
            "workflow_node_started",
            {"step_id": "load_target_d", "system": "D", "action": "load"},
        )
        try:
            load_result = self.connector.load_d(checkpoint["period"], records)
        except Exception as exc:  # noqa: BLE001 - target failure becomes workflow state.
            result = {
                "state": "failed",
                "reason": "target_load_failed",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "human_decision": decision.to_dict(),
                "target_load": _blocked_load("target_load_failed"),
            }
            monitor.finish("failed", {"workflow": result})
            self._audit(run_id, "workflow_completed", {"workflow": result})
            return result
        result = {
            "state": "completed",
            "human_decision": decision.to_dict(),
            "target_load": {
                "state": "completed",
                "system": "D",
                "approved": True,
                "result": load_result,
            },
        }
        monitor.event("workflow_node_completed", {"step_id": "load_target_d", "system": "D", "action": "load"})
        monitor.finish("completed", {"workflow": result})
        self._audit(run_id, "workflow_completed", {"workflow": result})
        self._checkpoint_store.pop(run_id, None)
        return result

    def _lookup_sources(
        self,
        period: str,
        monitor: RunMonitor,
        run_id: str,
        steps: list[StepResult],
    ) -> tuple[list[Record], list[Record]]:
        for step_id, system in (("lookup_source_a", "A"), ("lookup_comparison_b", "B")):
            self._event(
                monitor,
                run_id,
                "workflow_node_started",
                {"step_id": step_id, "system": system, "action": "lookup"},
            )
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(self.connector.lookup_a, period)
            future_b = executor.submit(self.connector.lookup_b, period)
            try:
                records_a = future_a.result()
            except Exception as exc:
                raise RuntimeError("lookup_source_a failed") from exc
            try:
                records_b = future_b.result()
            except Exception as exc:
                raise RuntimeError("lookup_comparison_b failed") from exc

        for step_id, system, record_count in (
            ("lookup_source_a", "A", len(records_a)),
            ("lookup_comparison_b", "B", len(records_b)),
        ):
            step = StepResult(
                step_id=step_id,
                state="completed",
                system=system,
                action="lookup",
                details={"record_count": record_count},
            )
            steps.append(step)
            self._event(monitor, run_id, "workflow_node_completed", step.to_dict())
        return records_a, records_b

    def _event(self, monitor: RunMonitor, run_id: str, event: str, data: dict[str, Any]) -> None:
        monitor.event(event, data)
        self._audit(run_id, event, data)

    def _audit(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        append_audit(RunRecord.create(event=event, data=redact(data), run_id=run_id), self.audit_path)


def load_workflow_template(path: Path = DEFAULT_TEMPLATE_PATH) -> WorkflowTemplate:
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate_workflow_template(data)
    nodes = tuple(data["graph"]["nodes"])
    required = tuple(data["review_packet"]["required_fields"])
    reconciliation = data["reconciliation"]
    return WorkflowTemplate(
        template_id=data["template_id"],
        template_version=int(data["template_version"]),
        workflow_id=data["intent"]["task_type"],
        required_fields=tuple(reconciliation["target_required_fields"]),
        nodes=nodes,
        review_packet_required_fields=required,
        reconciliation_rules=tuple(reconciliation["rules"]),
        audit_required_events=tuple(data["audit"]["required_events"]),
    )


def _reconcile(
    sources: dict[str, list[Record]],
    *,
    required_fields: tuple[str, ...],
    requested_period: str,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[tuple[str, Any]]]] = {}
    malformed: list[dict[str, Any]] = []
    source_counts = {source: len(records) for source, records in sorted(sources.items())}

    for source, records in sorted(sources.items()):
        for index, record in enumerate(records):
            patent_id = record.get("patent_id")
            if not patent_id:
                malformed.append({"source": source, "index": index, "record": dict(record)})
                continue
            fields = grouped.setdefault(str(patent_id), {})
            fields.setdefault("_sources", []).append((source, source))
            for field_name, value in sorted(record.items()):
                fields.setdefault(field_name, []).append((source, value))

    reconciled_records: dict[str, Record] = {}
    conflicts: list[dict[str, Any]] = []
    missing_required: list[str] = []
    failed_rules: list[dict[str, Any]] = []

    for patent_id in sorted(grouped):
        record_values = grouped[patent_id]
        reconciled: Record = {"patent_id": patent_id}
        present_sources = sorted({source for source, _ in record_values.get("_sources", [])})
        if "A" not in present_sources or "B" not in present_sources:
            failed_rules.append(
                {
                    "rule_id": "identity_match",
                    "patent_id": patent_id,
                    "severity": "blocking",
                    "message": "Record must be present in both systems A and B.",
                    "sources": present_sources,
                }
            )

        field_names = sorted((set(record_values) - {"_sources"}) | set(required_fields))
        for field_name in field_names:
            observed = record_values.get(field_name, [])
            non_empty = [
                (source, value)
                for source, value in observed
                if value is not None and value != ""
            ]
            unique_values = sorted({value for _, value in non_empty}, key=str)
            if len(unique_values) == 1:
                reconciled[field_name] = unique_values[0]
            elif len(unique_values) > 1:
                conflict = {
                    "patent_id": patent_id,
                    "field": field_name,
                    "values": [
                        {"source": source, "value": value}
                        for source, value in sorted(non_empty, key=lambda item: (item[0], str(item[1])))
                    ],
                }
                conflicts.append(conflict)
                failed_rules.append(
                    {
                        "rule_id": "field_value_consistency",
                        "patent_id": patent_id,
                        "severity": "blocking",
                        "message": f"Conflicting values for {field_name}.",
                        "evidence": conflict,
                    }
                )

        if reconciled.get("period") != requested_period:
            failed_rules.append(
                {
                    "rule_id": "period_valid",
                    "patent_id": patent_id,
                    "severity": "blocking",
                    "message": "Record period does not match requested period.",
                    "expected": requested_period,
                    "actual": reconciled.get("period"),
                }
            )

        if any(_is_missing(reconciled.get(field_name)) for field_name in required_fields):
            missing_required.append(patent_id)
            failed_rules.append(
                {
                    "rule_id": "required_fields_present",
                    "patent_id": patent_id,
                    "severity": "warning",
                    "message": "Required fields are missing.",
                }
            )

        status_values = [
            value
            for _, value in record_values.get("asset_status", [])
            if value is not None and value != ""
        ]
        invalid_statuses = sorted({value for value in status_values if value != "eligible"}, key=str)
        if invalid_statuses:
            failed_rules.append(
                {
                    "rule_id": "asset_status_valid",
                    "patent_id": patent_id,
                    "severity": "blocking",
                    "message": "Asset status is not eligible for replacement registration.",
                    "actual": invalid_statuses,
                }
            )

        duplicate_values = [
            value
            for _, value in record_values.get("target_registered", [])
            if value is True or str(value).lower() == "true"
        ]
        if duplicate_values:
            failed_rules.append(
                {
                    "rule_id": "no_duplicate_registration",
                    "patent_id": patent_id,
                    "severity": "blocking",
                    "message": "Candidate record is already registered in the target-equivalent comparison view.",
                }
            )

        reconciled_records[patent_id] = {
            key: reconciled[key]
            for key in sorted(reconciled)
        }

    for malformed_record in malformed:
        failed_rules.append(
            {
                "rule_id": "identity_present",
                "severity": "blocking",
                "message": "Source record is missing patent_id.",
                "evidence": malformed_record,
            }
        )

    return {
        "status": "unresolved" if conflicts or missing_required or failed_rules else "resolved",
        "source_counts": source_counts,
        "records": reconciled_records,
        "missing_required": sorted(set(missing_required)),
        "conflicts": conflicts,
        "malformed_records": malformed,
        "failed_rules": failed_rules,
    }


def _review_packet(
    *,
    run_id: str,
    template: WorkflowTemplate,
    period: str,
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    affected = sorted(set(reconciliation["missing_required"]) | {item.get("patent_id") for item in reconciliation["conflicts"]})
    affected = [item for item in affected if item]
    return {
        "workflow_id": template.workflow_id,
        "run_id": run_id,
        "template_id": template.template_id,
        "template_version": template.template_version,
        "period": period,
        "affected_records": affected,
        "failed_rules": reconciliation["failed_rules"],
        "system_evidence": {
            "source_counts": reconciliation["source_counts"],
            "conflicts": reconciliation["conflicts"],
            "missing_required": reconciliation["missing_required"],
            "malformed_records": reconciliation["malformed_records"],
        },
        "proposed_resolution": "Review failed rules, correct source data, or approve corrected records.",
        "allowed_actions": [
            "approve_corrected_records",
            "reject_workflow",
            "request_manual_correction",
            "close_with_exceptions",
        ],
        "approval_impact": "Approval may allow target-system D load for approved records only.",
    }


def _checkpoint_packet(
    *,
    run_id: str,
    template: WorkflowTemplate,
    period: str,
    reconciliation: dict[str, Any],
) -> dict[str, Any]:
    return {
        **_review_packet(
            run_id=run_id,
            template=template,
            period=period,
            reconciliation=reconciliation,
        ),
        "affected_records": sorted(reconciliation["records"]),
        "failed_rules": [],
        "proposed_resolution": "Approve validated records for target-system D load.",
        "allowed_actions": ["approve_load", "reject_workflow", "request_manual_correction"],
    }


def _result(
    *,
    run_id: str,
    state: str,
    template: WorkflowTemplate,
    period: str,
    steps: list[StepResult],
    reconciliation: dict[str, Any],
    human_gate: dict[str, Any],
    target_load: dict[str, Any],
    monitor: RunMonitor,
    audit_path: Path,
) -> dict[str, Any]:
    return deepcopy(redact({
        "run_id": run_id,
        "state": state,
        "template": template.to_dict(),
        "period": period,
        "steps": [step.to_dict() for step in steps],
        "reconciliation": reconciliation,
        "human_gate": human_gate,
        "target_load": target_load,
        "status_path": str(monitor.status_path),
        "events_path": str(monitor.events_path),
        "audit_path": str(audit_path),
    }))


def _validate_workflow_template(data: dict[str, Any]) -> None:
    node_ids = [node["node_id"] for node in data["graph"]["nodes"]]
    duplicate_node_ids = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    if duplicate_node_ids:
        raise ValueError(f"duplicate workflow node ids: {duplicate_node_ids}")

    known_nodes = set(node_ids)
    for start_node in data["graph"]["start"]:
        if start_node not in known_nodes:
            raise ValueError(f"unknown workflow start node: {start_node}")

    for node in data["graph"]["nodes"]:
        for dependency in node.get("depends_on", []):
            if dependency not in known_nodes:
                raise ValueError(f"unknown workflow dependency: {node['node_id']} -> {dependency}")
        for next_node in node.get("next", []):
            if next_node not in known_nodes:
                raise ValueError(f"unknown workflow next node: {node['node_id']} -> {next_node}")
        if node["type"] == "load":
            policy = node.get("policy", {})
            if policy.get("risk_level") != "high" or policy.get("requires_approval") is not True:
                raise ValueError(f"load node must require high-risk approval: {node['node_id']}")
            if "pre_load_checkpoint" not in node.get("depends_on", []):
                raise ValueError(f"load node must depend on pre_load_checkpoint: {node['node_id']}")


def _resume_monitor(run_id: str, run_root: Path) -> RunMonitor:
    monitor = RunMonitor(run_id=run_id, root_dir=run_root)
    monitor.run_dir.mkdir(parents=True, exist_ok=True)
    if monitor.events_path.exists():
        with monitor.events_path.open(encoding="utf-8") as events_file:
            monitor.event_count = sum(1 for _ in events_file)
    monitor.state = "running"
    monitor.write_status()
    return monitor


def _load_step(state: str, reason: str) -> StepResult:
    return StepResult(
        step_id="load_target_d",
        state=state,
        system="D",
        action="load",
        details={"reason": reason},
    )


def _blocked_load(reason: str) -> dict[str, Any]:
    return {"state": "blocked", "system": "D", "approved": False, "reason": reason}


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


def _copy_records(records: list[Record]) -> list[Record]:
    return [dict(record) for record in records]


def _default_system_a() -> dict[str, list[Record]]:
    return {
        "current_month": [
            {
                "patent_id": "PA-100",
                "replacement_asset_id": "RA-900",
                "owner": "ip_ops",
                "period": "current_month",
            },
            {
                "patent_id": "PA-200",
                "replacement_asset_id": None,
                "owner": "ip_ops",
                "period": "current_month",
            },
        ]
    }


def _default_system_b() -> dict[str, list[Record]]:
    return {
        "current_month": [
            {
                "patent_id": "PA-100",
                "replacement_asset_id": "RA-900",
                "owner": "ip_ops",
                "period": "current_month",
            },
            {
                "patent_id": "PA-200",
                "replacement_asset_id": None,
                "owner": "ip_ops",
                "period": "current_month",
            },
        ]
    }


def _default_system_c() -> dict[str, list[Record]]:
    return {
        "current_month": [
            {
                "patent_id": "PA-200",
                "replacement_asset_id": "RA-901",
                "owner": "ip_ops",
                "period": "current_month",
            }
        ]
    }
