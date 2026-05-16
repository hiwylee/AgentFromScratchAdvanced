# Architecture Sketch

## Core Shape

The runtime should be split into narrow interfaces:

- `AgentLoop`: owns turn execution and stopping conditions.
- `Model`: turns messages and tool schemas into the next assistant action.
- `ToolRegistry`: validates and dispatches tool calls.
- `StateStore`: records messages, tool observations, and checkpoints.
- `Policy`: decides whether an action is allowed.
- `Reporter`: emits progress updates and final output.
- `AuditLog`: append-only record of decisions, tool calls, observations,
  policy checks, and improvement candidates.
- `EvalRunner`: runs regression fixtures before prompt, policy, or memory
  changes are accepted.
- `BudgetManager`: tracks token, cost, row, and time budgets.
- `WorkflowEngine`: executes versioned workflow templates as monitorable,
  checkpointed plan graphs.
- `ConnectorRegistry`: provides typed access to external systems behind policy
  and audit boundaries.
- `HumanGate`: pauses execution for review, approval, correction, or exception
  handling.

Workflow-oriented capabilities should be first-class because business requests
can span multiple systems and multi-stage reconciliation:

- `WorkflowTemplateRegistry`: versioned templates for known business workflows.
- `WorkflowPlanner`: maps workflow intent into an executable graph.
- `ReconciliationEngine`: validates records across source, comparison, and
  enrichment systems.
- `WorkflowStateStore`: persists checkpoints, step outputs, exceptions, and
  human decisions.
- `WorkflowReporter`: emits progress, review packets, and completion reports.

Oracle ADW-focused capabilities should be modeled as dedicated components
rather than ad hoc shell commands:

- `DataSourceRegistry`: configured database connections and metadata.
- `SchemaContext`: compact schema, relationship, and sample-value context.
- `QueryPlanner`: natural language to candidate query plans.
- `QueryPolicy`: read/write safety, row limits, and approval boundaries.
- `ResultInterpreter`: turns rows into grounded natural-language answers.
- `OracleAdwConnector`: loads environment configuration, checks SQLcl, and
  executes approved read-only queries.

## First Implementation Bias

Start with in-process components and a mock model. Add API-backed models and
process isolation after the loop is testable.

Prompts, policies, tool schemas, and memory should be data files
(`YAML`, `JSON`, or Markdown) rather than hard-coded Rust constants when they
are expected to change often. This keeps prompt and policy iteration fast even
if the core runtime is implemented in Rust.

Use adapter boundaries early:

- SQLcl is the first Oracle execution backend, but callers should depend on an
  Oracle connector interface rather than subprocess details.
- The first model can be a mock, but the agent loop should depend on a model
  interface rather than fixture-specific behavior.
- Intent analysis should produce structured data that downstream planning,
  policy, and reporting can consume.

## Observability From The Start

The first runtime should emit structured events for:

- intent classification;
- plan creation and revision;
- tool calls and observations;
- policy allow/deny decisions;
- model token and cost estimates;
- query latency and row counts;
- cancellation and timeout events.

These events should avoid secrets and should be suitable for both local
debugging and future evaluation reports.

## Workflow Execution Model

Longer business requests should run as workflow graphs:

- source lookups can run in parallel;
- reconciliation waits for required inputs;
- enrichment runs conditionally when fields or evidence are missing;
- target-system writes or loads require explicit policy gates;
- unresolved reconciliation failures pause at a human gate;
- every step writes status, audit, and checkpoint records.

The same model should support DB analysis workflows and multi-system business
workflows, so database tools are connector-backed steps rather than special
cases.

## Reference Areas In `../codex`

Investigate these concepts before implementation:

- instruction loading through `AGENTS.md`;
- sandbox and exec policy;
- tool call lifecycle;
- plan and progress reporting;
- test support for mocked model responses.

Do not copy structure before confirming that the complexity is needed here.

## Open Decisions

- Primary language: Rust, TypeScript, Python, or another choice.
- CLI shape and config format.
- Model provider abstraction.
- Tool schema format.
- Test strategy for model-driven behavior.
- Whether the first Oracle execution backend uses SQLcl subprocesses or a
  direct driver.
- Prompt, policy, memory, and eval file formats.
- First workflow template format and human-gate review packet format.
