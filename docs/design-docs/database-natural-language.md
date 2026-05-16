# Database Natural Language Design

## Objective

Make the agent strong at answering questions over database data while keeping
query generation inspectable, safe, and testable.

## Initial Capability Shape

The first database workflow should be read-only:

1. inspect available data sources;
2. introspect schema and relationships;
3. build compact schema context;
4. translate a natural-language question into a query plan;
5. validate the query against policy;
6. execute with row and timeout limits;
7. explain the result and show the query used.

## Safety Defaults

- Read-only operations by default.
- No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, or procedural execution in
  early milestones.
- Require explicit approval before any future write-capable mode.
- Apply row limits and timeouts even for read queries.
- Keep query text, parameters, and result summaries in state for auditability.

## Harness Requirements

- Maintain schema fixtures for tests.
- Maintain natural-language question fixtures with expected SQL properties.
- Test refusal behavior for unsafe requests.
- Test ambiguity handling when the schema does not support a confident answer.

## Open Decisions

- First database target: SQLite, PostgreSQL, or Oracle.
- Whether to use an existing SQL parser for validation.
- How much sample data can be exposed to the model.
- Whether domain glossary memory is configured manually or learned from usage.
