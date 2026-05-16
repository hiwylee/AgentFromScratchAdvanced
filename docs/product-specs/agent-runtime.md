# Agent Runtime Product Spec

## Goal

Build a local agent runtime that starts simple and becomes capable of handling
complex development tasks through explicit planning, controlled tools, memory,
and verification.

The first product specialization is natural-language access to Oracle
Autonomous Data Warehouse data: the agent should help users inspect schemas,
ask questions in plain language, generate safe queries, explain results, and
iterate without requiring the user to write SQL by hand.

## Primary Users

- Technical analysts who know the business question but do not want to hand
  write every SQL query.
- Developers or data engineers who need a safe agent to inspect Oracle ADW
  schemas and produce grounded analysis steps.
- Project maintainers who need the agent runtime itself to be observable,
  testable, and improvable over time.

## Product Principles

- Intent first: do not jump from user text directly to SQL or tools.
- Grounded answers: every database answer should be tied to schema context,
  query text, assumptions, and result evidence.
- Safe by default: use read-only workflows and least-privileged database access.
- Explain uncertainty: ask clarifying questions when business terms or schema
  mappings are ambiguous.
- Improve with evidence: convert failures into audit records, eval fixtures,
  policy updates, or memory candidates.

## Initial User Experience

The first usable version should run from a CLI:

```text
agent "summarize this repository"
```

It should show the steps it takes, tool calls it performs, and the final answer.

For Oracle ADW questions, the first visible capability should be structured
intent analysis:

```text
agent ask "지난달 상품별 매출 추이를 보여줘"
```

Expected early output:

- detected intent type;
- extracted metric, dimension, time range, and output request;
- missing context or ambiguity;
- safety classification;
- next action, such as inspect schema or ask a clarification question.

## Milestone Ladder

1. Minimal loop: task input, state, model decision, final answer.
2. Tool loop: structured tool calls, observations, retry limits.
3. File tools: read-only repository inspection.
4. Edit tools: scoped file modification with diffs.
5. Verification: command execution, test capture, failure summaries.
6. Planning: explicit task plans, checkpoints, and progress updates.
7. Memory: project-local notes and reusable guidance.
8. Harness hardening: policy checks, fixtures, regression tests, and evals.
9. Complex work: long-running task orchestration and subtask decomposition.
10. Oracle ADW natural-language workflows: schema grounding, SQL planning,
    query validation, result explanation, and domain-specific memory.

## Non-Goals For The First Version

- Rebuilding every Codex feature.
- Supporting every tool type.
- Running unsafe shell commands.
- Persisting long-term memory outside the project.
- Multi-agent delegation.
- Direct write/delete database operations before explicit safety policies exist.

## Success Criteria For Milestone 1

- A single command runs without network access when using a mock model.
- The core loop is covered by tests.
- The state transitions are inspectable.
- The design leaves room for real model and tool adapters.
- User intent is represented as structured data, not only prose.
- Audit and trace records are produced without exposing secrets.
- The CLI can show whether a request needs Oracle ADW context before any
  database connection is attempted.

## MVP Boundary

The MVP is not full autonomous natural-language-to-SQL. The MVP is a reliable
agent foundation that can classify intent, explain its next action, record
auditable state, and safely perform a minimal Oracle ADW read-only smoke query.

Full NL-to-SQL requires compact schema context, eval gates, SQL validation, and
result explanation to be in place first.

## Oracle ADW Specialization Direction

Oracle ADW work should be introduced as a first-class capability, not as a
generic shell shortcut. The runtime should eventually include:

- an Oracle ADW connector using SQLcl and environment variables;
- schema introspection and sampled metadata;
- natural-language-to-query planning with explicit assumptions;
- read-only query execution by default;
- query review and safety policy before execution;
- result summarization with links back to the executed query;
- eval fixtures that pair natural-language questions with expected SQL and
  expected answer properties.
