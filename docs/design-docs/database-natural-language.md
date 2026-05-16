# Database Natural Language Design

## Objective

Make the agent strong at answering questions over Oracle ADW data while keeping
query generation inspectable, safe, and testable.

## Initial Capability Shape

The first database workflow should target Oracle Autonomous Data Warehouse and
should be read-only:

1. inspect available data sources;
2. introspect schema and relationships;
3. build compact schema context;
4. translate a natural-language question into a query plan;
5. validate the query against policy;
6. execute with row and timeout limits;
7. explain the result and show the query used.

Database analysis should also be usable inside larger workflows. A workflow
step may use Oracle ADW to retrieve source records, compare datasets, evaluate
reconciliation rules, enrich missing context, or produce review evidence.

## Safety Defaults

- Read-only operations by default.
- No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, or procedural execution in
  early milestones.
- Require explicit approval before any future write-capable mode.
- Apply row limits and timeouts even for read queries.
- Keep query text, parameters, and result summaries in state for auditability.
- Never print `.env` values for passwords, wallet passwords, API keys, or
  secret-bearing connection strings.
- Use `DB_USER` / `DB_USER_PASS` for normal query work. Use admin credentials
  only for explicit setup or metadata tasks.
- Treat database-level least privilege as the primary safety boundary. The
  working user should have only the permissions needed for approved read-only
  workflows.
- Treat application-level SQL validation as a second safety layer, not the only
  defense.
- Block or explicitly review edge cases such as `SELECT ... FOR UPDATE`, DDL,
  DML, procedural blocks, database links, resource-heavy hints, and functions
  with side effects.

## Intent And Planning

User intent analysis is mandatory before database work. The intent stage should
extract:

- task type, such as lookup, aggregation, trend analysis, comparison, anomaly
  check, or metadata exploration;
- requested entities, metrics, dimensions, filters, time ranges, and output
  format;
- required context, such as schema, business glossary, or sample values;
- ambiguity signals based on missing schema matches or undefined business terms;
- safety level and whether the request can remain read-only.

LLM self-reported confidence should not be trusted alone. Prefer deterministic
signals such as missing glossary entries, unresolved tables, unresolved columns,
or multiple equally plausible schema matches.

For latency, the runtime may combine intent and initial plan generation in one
structured model call, while keeping the output fields separate.

## Compact Schema Context

Large Oracle ADW environments can contain thousands of tables. The runtime
should not send the entire schema to the model. Schema context should be built
with a layered retrieval strategy:

- start with curated high-value schemas, tables, and business glossary entries;
- use embedding or keyword retrieval over table names, column names, comments,
  and known business terms;
- ask for table candidates first, then expand only the chosen tables with full
  column and relationship details;
- expose sample values only when needed and only after PII and sensitive-column
  checks;
- record which schema context was used for each answer.

Compact schema context is a core accuracy feature, not an optimization.

## Harness Requirements

- Maintain schema fixtures for tests.
- Maintain natural-language question fixtures with expected SQL properties.
- Test refusal behavior for unsafe requests.
- Test ambiguity handling when the schema does not support a confident answer.
- Maintain a frozen golden eval set that must not be edited to make a new
  prompt, policy, or memory change pass.
- Prefer execution-based evals, such as comparing result properties, over only
  string-matching generated SQL.
- Track prompt, policy, and memory versions for rollback.
- Store memory entries with source, timestamp, author, confidence, and evidence
  to reduce memory poisoning risk.
- Add drift checks for repeated questions whose answers or query plans change
  unexpectedly.
- Add workflow eval fixtures where database analysis is one step inside a
  larger reconciliation process.

## Open Decisions

- First SQL execution path: direct Oracle driver or SQLcl subprocess.
- Whether to use an existing SQL parser for validation.
- How much sample data can be exposed to the model.
- Whether domain glossary memory is configured manually or learned from usage.
- Which frozen eval set should gate self-improvement changes.
