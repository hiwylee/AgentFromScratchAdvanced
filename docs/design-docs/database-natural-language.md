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

## Milestone 5 Plan: Compact Schema Context

The first compact schema strategy is an artifact-first lexical retrieval path
over working-user-visible Oracle ADW metadata plus curated business seeds. It
uses deterministic keyword scoring first, not embeddings, so the earliest
implementation stays dependency-light, inspectable, and easy to test. Embedding
retrieval may be added later behind the same artifact shapes after golden evals
show lexical retrieval is the bottleneck.

The first business profile is `oracle_adw_sh.v1`. It should prefer `SH`
business-analysis semantics: sales, products, customers, channels, promotions,
countries, and time. `SSB` remains a later `oracle_adw_ssb_stress.v1` profile
for row-limit, timeout, star-schema, and cost-control stress tests.

### Retrieval Flow

1. Load the schema metadata snapshot for the active profile.
2. Load curated table and glossary seed files for the same profile.
3. Extract request terms from intent fields: entities, metrics, dimensions,
   filters, time ranges, and known business terms.
4. Score tables using exact and partial matches over curated table names,
   aliases, glossary terms, column names, column comments, table comments, and
   relationship hints.
5. Select a small table candidate set first. The first default limit is 6
   tables, with at most 2 bridge or lookup tables added through relationships.
6. Expand only selected tables into full column, relationship, synonym,
   glossary, and safety metadata.
7. Add sample values only for columns allowed by the masking policy.
8. Record the final compact context and retrieval evidence with the answer
   trace.

The first scorer should be deterministic and testable. Suggested initial
weights are:

- exact curated table or glossary alias match: 100;
- exact table name or synonym match: 80;
- exact column name or column alias match: 60;
- comment or description phrase match: 40;
- partial token match: 15;
- relationship expansion from a selected fact table: 10.

Ties should prefer curated `primary` tables, then higher relationship density,
then lexicographic table name for repeatability. Low scores should not be
silently accepted; if the top score is weak or several candidates are equally
plausible, the runtime should ask for clarification instead of generating SQL.

### Schema Metadata JSON

Schema metadata is a generated snapshot of what the working user can see. It
must not include credentials, wallet paths, raw connection strings, or unmasked
sample values. Store generated snapshots under a future generated-artifact
directory, for example:

```text
docs/generated/schema-context/oracle_adw_sh.schema-metadata.v1.json
```

Initial shape:

```json
{
  "schema_version": "agent-runtime.schema-metadata.v1",
  "profile_id": "oracle_adw_sh.v1",
  "source": {
    "database": "oracle_adw",
    "introspected_as": "DB_USER",
    "introspection_mode": "working_user_visible",
    "captured_at": "2026-05-16T00:00:00Z"
  },
  "tables": [
    {
      "table_id": "SH.SALES",
      "owner": "SH",
      "name": "SALES",
      "kind": "table",
      "role": "fact",
      "description": "Sales fact table for business analysis.",
      "synonyms": ["SALES"],
      "curated_priority": "primary",
      "row_count_estimate": null,
      "columns": [
        {
          "name": "AMOUNT_SOLD",
          "data_type": "NUMBER",
          "nullable": false,
          "semantic_type": "currency_amount",
          "business_terms": ["sales amount", "revenue"],
          "description": "Sales amount measure.",
          "sample_policy": "aggregate_only"
        }
      ],
      "relationships": [
        {
          "type": "foreign_key",
          "from_columns": ["PROD_ID"],
          "to_table_id": "SH.PRODUCTS",
          "to_columns": ["PROD_ID"],
          "confidence": "database_constraint"
        }
      ]
    }
  ]
}
```

`row_count_estimate` is optional and may be `null` when the working user cannot
read reliable statistics. `confidence` should distinguish database constraints,
curated relationships, and inferred relationships. Inferred relationships are
allowed in context, but generated SQL should explain that assumption.

### Curated Table And Glossary Seeds

Curated seeds provide business semantics that Oracle dictionary metadata often
lacks. Store them as versioned JSON artifacts beside the generated schema
metadata, for example:

```text
docs/generated/schema-context/oracle_adw_sh.curated-seed.v1.json
```

Initial shape:

```json
{
  "schema_version": "agent-runtime.curated-schema-seed.v1",
  "profile_id": "oracle_adw_sh.v1",
  "source": {
    "author": "project",
    "updated_at": "2026-05-16T00:00:00Z",
    "evidence": "Oracle SH sample schema business semantics"
  },
  "tables": [
    {
      "table_id": "SH.SALES",
      "role": "fact",
      "priority": "primary",
      "aliases": ["sales", "revenue", "transactions"],
      "default_measures": ["AMOUNT_SOLD", "QUANTITY_SOLD"],
      "default_time_columns": ["TIME_ID"],
      "common_joins": ["SH.PRODUCTS", "SH.CUSTOMERS", "SH.TIMES"],
      "notes": "Prefer for sales trend, revenue, quantity, and aggregation questions."
    }
  ],
  "glossary": [
    {
      "term": "revenue",
      "aliases": ["sales amount", "amount sold"],
      "maps_to": [
        {
          "table_id": "SH.SALES",
          "column": "AMOUNT_SOLD",
          "expression": "SUM(AMOUNT_SOLD)"
        }
      ],
      "ambiguity": "low"
    }
  ],
  "sample_value_allowlist": [
    {
      "table_id": "SH.CHANNELS",
      "columns": ["CHANNEL_DESC"],
      "max_values": 20,
      "reason": "Low-risk business category values help disambiguate channel filters."
    }
  ]
}
```

Seeds should be small, reviewed, and profile-specific. They should not replace
database metadata; they rank and explain metadata already visible to the
working user. If a seed references a table or column missing from the metadata
snapshot, the build should fail or mark the seed invalid.

### Sample-Value Masking Policy

Default behavior is no raw sample values in model context. Sample values are
allowed only when a column is explicitly allowlisted by the curated seed and
passes the sensitive-column checks.

Blocked sample-value categories:

- names, email addresses, phone numbers, postal addresses, IP addresses, URLs,
  account identifiers, national identifiers, payment data, free text, dates of
  birth, exact timestamps tied to people, and any column whose name or comment
  contains sensitive tokens such as `name`, `email`, `phone`, `address`,
  `ssn`, `birth`, `password`, `token`, `key`, or `secret`;
- high-cardinality identifiers and keys, even when they are not personal data;
- any value from a table or column without explicit sample allowlisting.

Allowed sample context:

- low-cardinality business categories from allowlisted columns, capped at 20
  distinct values per column;
- numeric profile summaries such as min, max, null count, and approximate
  distinct count when they do not reveal individual records;
- date grains such as available years or months, not person-level exact dates.

If a value fails masking, record only the reason and a masked placeholder such
as `<masked:sensitive_column>` or `<masked:high_cardinality>`. Do not hash raw
values for model context; hashes can still leak joinability and are not needed
for early NL-to-SQL retrieval.

### Context Recording Requirements

Every generated answer that uses database schema context must record a compact
schema context event in the trace and audit path. The record must be redacted
and should include:

- `profile_id`, schema metadata artifact id, curated seed artifact id, and
  artifact versions;
- request terms used for retrieval;
- selected table ids, selected columns, relationship ids, and glossary entries;
- retrieval scores and tie-break reasons;
- tables considered but rejected, with short rejection reasons;
- masking policy version, sample columns included, sample columns rejected, and
  masked-value counts;
- token or character estimate for the final context;
- whether the runtime proceeded, refused, or asked for clarification;
- generated SQL id or query-plan id when a later milestone produces SQL.

Do not record credentials, wallet paths, connection descriptors, raw secret
environment values, or unmasked blocked samples. The context record is part of
answer provenance and should be sufficient for a reviewer to understand why a
query plan used specific tables.

### Testable Acceptance Criteria

- Given SH sales trend prompts, retrieval selects `SH.SALES` plus relevant
  dimensions such as `SH.PRODUCTS`, `SH.CUSTOMERS`, `SH.CHANNELS`, or
  `SH.TIMES` without loading the full schema into model context.
- Given an ambiguous term that maps to multiple dimensions with similar scores,
  retrieval emits a clarification-required result rather than guessing.
- Given seed references to missing metadata, validation fails deterministically.
- Given sensitive customer columns, sample values are masked or omitted even if
  a prompt asks to see examples.
- Given allowlisted low-cardinality category columns, capped sample values may
  appear with masking metadata.
- Every compact context build produces a redacted context record with artifact
  versions and selected/rejected table evidence.

## Milestone 6 Plan: Query-Plan Artifacts Before Execution

Milestone 6 starts with proposed query-plan artifacts, not live SQL execution.
The first implementation consumes compact schema context and emits a
versioned `agent-runtime.query-plan.v1` artifact with:

- selected schema context artifact ids and versions;
- selected table ids, glossary matches, considered/rejected table evidence,
  and masking policy version;
- proposed SQL text when the schema context is sufficient;
- assumptions for metric, dimension, time-grain, and missing filter choices;
- read-only policy validation result from the Oracle ADW SQL policy;
- execution metadata that explicitly says execution is disabled and
  `not_executed`;
- refusal or clarification reasons when no SQL should be proposed.

The first supported pattern is intentionally narrow: SH revenue by product
category by calendar month. It maps:

- revenue to `SUM(SALES.AMOUNT_SOLD)` from the curated glossary;
- product grouping to `PRODUCTS.PROD_CATEGORY`;
- month grouping to `TIMES.CALENDAR_MONTH_DESC`;
- joins through `SALES.PROD_ID = PRODUCTS.PROD_ID` and
  `SALES.TIME_ID = TIMES.TIME_ID`.

The proposed SQL uses table aliases and unqualified table names that are
compatible with the current parser-less read-only policy and the working-user
private synonym plan. No query plan should be executed until a later milestone
connects the backend-neutral SQL execution adapter under explicit safety gates.

Acceptance criteria for this slice:

- Given compact context for a revenue/product/month prompt, produce a
  `planned` query-plan artifact with proposed SQL and `allowed` policy
  validation.
- Given ambiguous compact context, produce `clarification_required` and no SQL.
- Given missing required table context, produce `blocked` and no SQL.
- Given unsafe SQL text, policy validation rejects it before any execution
  boundary is considered.

## Fake Result Explanation Artifacts After Query Planning

After query planning, the next result-explanation wave should remain fixture
driven. It may consume a `planned` query-plan artifact and pass the proposed SQL
shape to `FakeSqlExecutionAdapter`, but the returned rows are deterministic
fixtures for eval and harness development only. They are not Oracle ADW output,
not SQLcl output, and not evidence about real database contents. Real ADW/SQLcl
execution stays closed until the separate execution-runner safety gates are
implemented and reviewed.

The fake-result explanation artifact should keep these concerns separate:

- query-plan provenance, including query-plan id, selected compact context
  artifacts, policy result, assumptions, and proposed SQL id or text reference;
- fake adapter metadata, including adapter name, adapter version, fixture id,
  deterministic scenario id, row count, column names, and any fixture limits;
- execution state, including `real_database_execution: false` and a clear
  fake or simulated execution status;
- explanation text and row-level summary grounded only in the fixture rows;
- caveats that the explanation is an eval artifact and must not be represented
  as a factual answer from the live database.

Acceptance criteria for this slice:

- Given a supported `planned` query-plan artifact, the explanation step
  consumes the artifact instead of rebuilding schema context or SQL from the
  original prompt.
- The step uses `FakeSqlExecutionAdapter` and records adapter name, adapter
  version, fixture id, scenario id, and row count in provenance.
- Every artifact and trace/audit record marks `real_database_execution` as
  `false`.
- Explanation wording is cautious: it may describe what the fake rows show for
  the fixture, but it never implies actual Oracle ADW facts, production
  records, current business metrics, or successful live SQL execution.
- The artifact preserves query-plan provenance, selected schema evidence, and
  policy-validation outcome so reviewers can trace the explanation back to the
  planned query.
- If the query plan is blocked, ambiguous, unsupported, or policy-rejected, no
  fake rows are explained and the artifact records the refusal reason.

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

- First live SQL execution backend: SQLcl subprocess or direct Oracle driver.
  The current decision is adapter first, with SQLcl as the first closed
  implementation behind the adapter.
- Whether to use an existing SQL parser for validation.
- Whether the first metadata snapshot can rely on working-user-visible
  constraints for all SH relationships, or whether curated relationships must
  fill gaps until grants are broadened.
- Whether domain glossary memory stays manually curated for Milestone 5 or can
  accept reviewed usage-derived suggestions in a later milestone.
- Which frozen eval set should gate self-improvement changes.
