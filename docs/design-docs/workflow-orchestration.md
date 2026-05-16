# Workflow Orchestration Design

## Objective

Support natural-language business requests that require multi-step workflow
execution across multiple systems, not only one-shot database analysis.

Example request:

```text
이번달 특허자산 대체 등록 진행해줘
```

This kind of request may require source-system lookup, comparison-system lookup,
multi-stage reconciliation, enrichment from a third system, final loading into a
target system, and human review when automated reconciliation is not safe.

## Core Concept

Treat business workflow execution as a first-class agent capability:

```text
User intent
-> Workflow intent classification
-> Workflow template selection
-> Plan graph
-> Step execution
-> Reconciliation checkpoints
-> Human-in-the-loop gates
-> Target-system write/load
-> Audit and completion report
```

The workflow engine should reuse the same agent primitives used for database
analysis:

- structured intent;
- policy checks;
- connector interfaces;
- audit logs;
- monitorable run state;
- eval fixtures;
- human approval gates.

## Components

- `WorkflowEngine`: owns workflow lifecycle, step scheduling, retries, and
  completion state.
- `WorkflowTemplateRegistry`: maps known business workflows to versioned
  templates.
- `WorkflowPlanner`: turns intent and templates into an executable plan graph.
- `ConnectorRegistry`: provides typed access to systems such as A, B, C, and D.
- `ReconciliationEngine`: performs deterministic and model-assisted validation
  across source datasets.
- `HumanGate`: pauses execution and requests approval, correction, or exception
  handling.
- `WorkflowStateStore`: persists step inputs, outputs, decisions, and artifacts.
- `WorkflowReporter`: produces progress, exception, and completion reports.

## Example Multi-System Flow

For a patent asset replacement registration workflow:

1. Query source system A for the current-month candidate patent asset records.
2. Query comparison system B for records that should match or constrain A.
3. Run multi-stage reconciliation:
   - identity matching;
   - date and period validation;
   - asset status validation;
   - duplicate detection;
   - missing-field checks;
   - business-rule checks;
   - exception classification.
4. If required fields are missing, query enrichment system C.
5. Re-run reconciliation after enrichment.
6. If records are systemically reconcilable, load validated records into target
   system D.
7. If records are not systemically reconcilable, pause at a human gate with:
   - conflicting records;
   - failed rules;
   - recommended action;
   - required approval or correction.
8. After human action, resume from the checkpoint and either continue or close
   with exceptions.

## Workflow Plan Graph

Workflows should be represented as a graph, not only a flat list:

- sequential steps for fixed dependencies;
- parallel branches for independent source-system lookups;
- join steps for reconciliation;
- conditional branches for enrichment, exception handling, and human review;
- checkpoint nodes before target-system writes or irreversible actions.

Every node should define:

- input contract;
- output contract;
- connector or tool used;
- policy requirements;
- retry behavior;
- timeout and cancellation behavior;
- audit fields;
- rollback or compensation note when applicable.

## Template And Review Packet Format

The first workflow template format is JSON, validated by
`artifacts/schemas/workflow-template.schema.json`.

The first concrete template is
`artifacts/workflows/patent-asset-replacement-registration.json`. It is a mock
template only: it defines the A/B/C/D systems, graph nodes, reconciliation
rules, human-gate review packet fields, target-load checkpoint, and audit event
expectations. The current runtime loads and validates basic template invariants
but still executes the first template through explicit Python flow. A generic
template scheduler remains a later milestone before arbitrary workflow
templates can be trusted.

Human-gate review packets should also be JSON for the first slice. A review
packet is not a loose chat question; it should contain the workflow/run ids,
affected records, failed rules, system evidence, proposed resolution, allowed
actions, and approval impact.

## Human-In-The-Loop

Human review is required when:

- reconciliation confidence is insufficient;
- source systems conflict on authoritative values;
- target-system write/load would be irreversible or high impact;
- required evidence is missing;
- business policy requires approval;
- the agent reaches an unknown exception class.

The agent should produce a review packet rather than a vague question:

- workflow id and run id;
- records affected;
- failed validation rules;
- evidence from systems A/B/C;
- proposed resolution;
- available actions;
- impact of approval or rejection.

## Database Analysis Integration

Database analysis is a reusable workflow capability:

- schema inspection can support connector setup;
- SQL queries can implement read-only source-system lookup;
- compact schema context can help map business terms to fields;
- reconciliation rules can be evaluated over query results;
- result explanations can become review packets or completion reports.

For DB-backed systems, the workflow engine should call database tools through
the same query policy and least-privilege boundaries used by natural-language
DB analysis.

## Safety Rules

- Default to read-only source-system access.
- Treat target-system writes or loads as explicit high-risk steps.
- Require checkpoint and approval policy before D-system loading.
- Do not approve target-system loads from caller-editable result JSON.
  Persistent resume requires signed or hashed checkpoint storage.
- Keep workflow approval mock-only until the checkpoint store can verify a
  template digest, reviewed packet digest, approver policy, idempotency key,
  and replay state.
- Never embed secrets in workflow templates, logs, or review packets.
- Redact CLI, monitor, audit, and review-packet outputs before they can contain
  Oracle-backed connector errors or secret-shaped values.
- Store every source query, transformation, reconciliation result, and human
  decision in audit records.
- Make workflow templates versioned artifacts.

## MVP Slice

The first workflow milestone should not connect real A/B/C/D systems. It should
prove the orchestration model with mock connectors:

1. classify a workflow intent;
2. select a mock workflow template;
3. execute parallel mock A/B lookups;
4. run deterministic reconciliation rules;
5. branch to mock C enrichment when needed;
6. pause at a human gate for unresolved exceptions;
7. expose monitorable run status and audit events.
8. prevent rejected checkpoints, mutated connector inputs, empty result sets,
   duplicate registrations, and invalid asset statuses from reaching target D.
