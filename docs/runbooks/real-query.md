# Real ADW Query Runbook (Milestone 8 / 9)

This runbook covers real Oracle ADW query execution from the agent loop via
the `adw_query` tool. All commands are operator-only and require live credentials.

## Prerequisites

Ensure `.env` is loaded with valid credentials:

- `SQLCL_PATH`: absolute path to SQLcl executable
- `DB_USER` / `DB_USER_PASS`: working read-only user (e.g. `AIAGENT`)
- `DB_DSN`: wallet TNS alias
- `DB_WALLET_PATH`: wallet directory

Verify connection before enabling real queries:

```bash
bin/agent operator adw-smoke --confirm-live-adw-smoke
```

## Enable Real ADW Queries

Add `--allow-real-query` to any `agent ask` command:

```bash
bin/agent ask "지난달 상품별 매출 추이를 보여줘" \
  --allow-real-query \
  --run-dir /tmp/afs-runs \
  --audit-log /tmp/afs.jsonl
```

**What happens:**
1. Schema context tool (`mock_schema_context`) runs → builds query plan
2. If query plan is `planned` and `--allow-real-query` is set:
   - `adw_query` tool fires with `approved_high_risk_tools=("adw_query",)`
   - SQL is validated through read-only policy before execution
   - `SqlclReadOnlyAdapter(allow_real_execution=True)` runs SQLcl subprocess
3. Real rows are returned (bounded to 10 rows in observation; 240 row example: product revenue by month)
4. `real_result_explanation_built` event recorded with `source="real/oracle_adw"`
5. `final_answer.content` shows actual table: month | product_category | revenue

**Safety properties:**
- SQL is always re-validated via `validate_read_only_sql()` before execution
- `adw_query` is `risk_level="high"` — ToolRunner blocks it unless in `approved_high_risk_tools`
- `--allow-real-query` absent → `adw_query` never invoked; fake results used
- No DDL, DML, or procedural SQL can pass the read-only policy

## Audit Records

Every `adw_query` execution appends to the audit log:

| Event | Description |
|---|---|
| `adw_query_executed` | SQL hash, row count, backend metadata (no raw SQL, no passwords) |
| `real_result_explanation_built` | ResultExplanationArtifact with `real_database_execution=true` |

## Milestone 9: Real Result Explanation

When `adw_query` succeeds, a `ResultExplanationArtifact` is built automatically:

```json
{
  "source": "real/oracle_adw",
  "real_database_execution": true,
  "backend": "sqlcl",
  "row_count": 240,
  "columns": ["month", "product_category", "revenue"],
  "summary": "Query returned 240 row(s) from Oracle ADW (real execution)."
}
```

The agent `final_answer.content` shows a formatted table (first 5 rows + truncation hint).

## Common Failures

- **`config_error: adw_config_unavailable`**: `.env` credentials not loaded. Run `source .env` first or check environment.
- **`blocked: sql_policy_violation`**: Proposed SQL contains write/DDL tokens. Check query plan assumptions.
- **`adw_query state: failed`**: SQLcl connection issue. Run `adw-smoke` first to verify connectivity.
- **`adw_query state: blocked`** (without `--allow-real-query`): Expected — real execution not enabled.

## DB User Permissions

`AIAGENT` holds:
- `CREATE SESSION` (system privilege)
- `SELECT ON ADMIN.SH_CHANNELS_V` / `SH_CUSTOMERS_V` / `SH_PRODUCTS_V` / `SH_SALES_V` / `SH_TIMES_V`
- Private synonyms: `CHANNELS → ADMIN.SH_CHANNELS_V`, etc.

No `SELECT ANY TABLE` or broad roles. Object-level access via ADMIN-owned views.
