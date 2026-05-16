# Architecture Sketch

## Core Shape

The runtime should be split into narrow interfaces:

- `AgentLoop`: owns turn execution and stopping conditions.
- `Model`: turns messages and tool schemas into the next assistant action.
- `ToolRegistry`: validates and dispatches tool calls.
- `StateStore`: records messages, tool observations, and checkpoints.
- `Policy`: decides whether an action is allowed.
- `Reporter`: emits progress updates and final output.

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
