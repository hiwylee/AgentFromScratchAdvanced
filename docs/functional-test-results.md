# Functional Test Results — 2026-05-29

All tests run against `hiwylee/AgentFromScratchAdvanced` main branch.
Test environment: local macOS, Python 3.13, SQLcl 25.4.2, Oracle ADW live.

## Unit Test Suite

```bash
uv run --python 3.13 python -m pytest -q
# → 559 passed, 109 subtests passed
```

## CLI Functional Tests

| # | Command | Expected | Result |
|---|---------|----------|--------|
| 1 | `agent ask "지난달 상품별 매출" --model-provider mock` | intent=database_analysis, query_plan=planned, SQL shown | PASS |
| 2 | `agent ask "지난달 채널별 매출" --allow-real-query` | real ADW rows in final_answer, source=real/oracle_adw | PASS (150 rows) |
| 3 | `agent ask "고객 테이블 삭제해줘"` | action=refuse, content shows read-only message | PASS (safety_level=blocked_write_request) |
| 4 | `agent workflow "특허자산 대체 등록"` | state=checkpoint_required (human gate) | PASS |
| 5 | `agent operator adw-smoke --confirm-live-adw-smoke` | state=succeeded, smoke_check=1 | PASS |
| 6 | `agent tacit list` | (no episodes found) | PASS |
| 7 | `agent status --run-dir /tmp/afs-runs` | state=completed, event_count>0 | PASS |

## Known Behaviors

- **Test #3 (write refuse)**: The intent classifier correctly sets `safety_level=blocked_write_request`. The `action.kind=refuse` is triggered by the agent loop, not intent classification alone. Final answer correctly refuses execution.
- **Test #4 (workflow)**: `checkpoint_required` is the correct state — the mock workflow pauses at the human gate after parallel A/B lookup and reconciliation. Resume requires `bin/agent workflow --resume`.
- **Test #7 (status)**: Returns `state` (not `status`) at the top level. JSON key is `state: "completed"`.

## M8 / M9 Live Verification

```bash
bin/agent ask "지난달 상품별 매출 추이를 보여줘" --allow-real-query --model-provider mock
```

**Output (truncated):**
```
Query returned 240 row(s) from Oracle ADW (real execution).
Columns: month, product_category, revenue. First row: 1998-01, Electronics, 151647.15.

month   | product_category            | revenue
-------------------------------------------------
1998-01 | Electronics                 | 151647.15
1998-01 | Hardware                    | 641850.31
1998-01 | Peripherals and Accessories | 792861.35
1998-01 | Photo                       | 387240.50
1998-01 | Software/Other              | 303821.18
... (235 more rows)
```

Events recorded: `adw_query_executed`, `real_result_explanation_built`
Artifact: `source=real/oracle_adw`, `real_database_execution=true`, `row_count=240`
