# AgentFromScratchAdvanced — 아키텍처 레퍼런스

다른 저장소에서 이 구현을 그대로 참조해 재현할 수 있도록 작성한 상세 설계 문서입니다.

---

## 목차

1. [전체 구조](#1-전체-구조)
2. [기술 스택](#2-기술-스택)
3. [백엔드 아키텍처](#3-백엔드-아키텍처)
   - 3.1 핵심 데이터 타입
   - 3.2 Intent 분류 레이어
   - 3.3 에이전트 루프 (AgentLoop)
   - 3.4 도구 시스템 (Tools)
   - 3.5 플래너 & 실행기 (Planner/Executor)
   - 3.6 세션 관리
   - 3.7 워크플로우 엔진
   - 3.8 Self-Evolution 게이트
   - 3.9 Tacit Knowledge 레이어
   - 3.10 지원 모듈
4. [프론트엔드 아키텍처](#4-프론트엔드-아키텍처)
5. [Artifact 시스템](#5-artifact-시스템)
6. [CLI 인터페이스](#6-cli-인터페이스)
7. [핵심 데이터 흐름](#7-핵심-데이터-흐름)
8. [보안 불변 조건](#8-보안-불변-조건)
9. [디렉토리 트리](#9-디렉토리-트리)
10. [재구현 체크리스트](#10-재구현-체크리스트)

---

## 1. 전체 구조

```
monorepo/
  agent_runtime/    # Python 백엔드 — 에이전트 루프, 도구, 워크플로우
  tests/            # Python 테스트 스위트 (~541 테스트)
  bin/agent         # CLI 진입점 (shell script → Python)
  artifacts/        # 버전관리 데이터 파일 (스키마, eval, 프롬프트, 정책)
  frontend/         # Next.js 14 UI
  docs/             # 설계 문서, 런북, 트래킹
  feat/             # 기능 설계 문서
```

**핵심 원칙**: UI 레이어(Next.js)는 Python/DB와 직접 연결하지 않는다. 모든 API 라우트는 `bin/agent` CLI 서브프로세스를 스폰한다.

---

## 2. 기술 스택

| 계층 | 기술 |
|------|------|
| Backend | Python 3.13, uv, pytest |
| Frontend | Next.js 14 App Router, TypeScript, Tailwind CSS, shadcn/ui |
| DB | Oracle ADW (Autonomous Data Warehouse) — SQLcl 경유 |
| 모델 | MockModel (기본), OpenAI Responses API, OCI GenAI |
| 패키지 관리 | uv (Python), npm (Node) |

---

## 3. 백엔드 아키텍처

### 3.1 핵심 데이터 타입 (`agent_runtime/types.py`)

모든 런타임 타입은 **frozen dataclass** (불변)로 정의한다.

```python
# 메시지 역할
Role = Literal["user", "assistant", "tool", "system"]

# 에이전트가 선택할 수 있는 액션 종류
ActionKind = Literal[
    "final_answer",      # 직접 답변
    "ask_clarification", # 추가 정보 요청
    "inspect_schema",    # DB 스키마 조회
    "select_workflow",   # 워크플로우 선택
    "refuse",            # 거부 (쓰기 요청 등)
    "model_error",       # 모델 호출 실패
]

# 인텐트 라우팅 목적지
IntentRoute = Literal["database_analysis", "business_workflow", "general_answer", "unknown"]

# 실행 상태
RunState = Literal[
    "running", "completed", "failed", "cancelled",
    "timed_out", "stopped", "paused", "checkpoint_required",
    "closed", "blocked",
]
```

**주요 frozen dataclass:**

| 타입 | 역할 |
|------|------|
| `Message` | 대화 메시지 (role, content, created_at) |
| `Action` | 모델이 선택한 액션 (kind, reason, payload) |
| `Observation` | 도구 실행 결과 래퍼 (source, content) |
| `FinalAnswer` | 최종 응답 (content, assumptions, next_action) |
| `IntentResult` | 인텐트 분류 결과 — drift 시그니처 포함 |
| `Budget` | 실행 제한 (max_steps=4, timeout=30s, token=4000) |
| `CancellationToken` | 스레드 안전 취소 프리미티브 |
| `ConversationSlot` | 세션 내 단기 컨텍스트 슬롯 |

---

### 3.2 Intent 분류 레이어 (`agent_runtime/intent.py`)

**두 계층으로 구성:**

#### L0: `analyze_user_intent(text)` — 키워드 매칭 (결정적)

```
사용자 텍스트
    ↓ casefold 정규화
    ├─ WORKFLOW_KEYWORDS → workflow_execution (특허자산 대체 등)
    ├─ DB_KEYWORDS / (metric+dimension 조합) → database_analysis
    └─ 그 외 → general (answer_directly)
```

**키워드 그룹:**
- `WRITE_KEYWORDS`: insert/update/delete/삭제/수정 → `blocked_write_request`
- `DB_KEYWORDS`: adw/oracle/sql/매출/고객/상품/채널...
- `WORKFLOW_KEYWORDS`: 진행/등록/처리/workflow...
- `METRIC_KEYWORDS`: revenue/매출, count/건수
- `DIMENSION_KEYWORDS`: product/상품, channel/채널, promotion/프로모션...
- `TIME_RANGE_KEYWORDS`: 지난달/previous_month, 이번달/current_month...
- `TREND_KEYWORDS`: 추이/trend → task_type = "trend_analysis"

**반환값 `UserIntent`:**
```python
UserIntent(
    intent_type,           # "database_analysis" | "workflow_execution" | "general"
    task_type,             # "trend_analysis" | "comparison" | "aggregation" | ...
    safety_level,          # "read_only" | "blocked_write_request" | "requires_checkpoint"
    requires_oracle_adw_context,
    entities,              # {metrics: [], dimensions: [], time_ranges: []}
    required_context,      # ["oracle_adw_schema", "business_glossary", ...]
    ambiguities,           # ["metric_definition", "dimension_table_mapping", ...]
    next_action,           # "inspect_schema" | "inspect_schema_then_clarify" | ...
)
```

#### L1: `KeywordIntentClassifier` — `UserIntent` → `IntentResult` 변환

```python
IntentResult(
    capabilities,          # ["oracle_sh.schema.read", "oracle_sh.data.read"]
    slots,                 # 엔티티 딕셔너리 (비어있지 않은 것만)
    primary_route,         # IntentRoute
    confidence,            # 1.0 (키워드 기반은 항상 1.0)
    rationale,
    alternatives,
    needs_clarification,
)
```

`IntentResult.signature_dict()` — drift 해시용 결정적 서브셋 (capabilities, slots, primary_route만 포함).

---

### 3.3 에이전트 루프 (`agent_runtime/loop.py`)

**단일 패스 루프** — 멀티스텝 플랜은 opt-in.

```
AgentLoop.run(user_text)
    │
    ├─ 1. RunMonitor.start()  ← 상태/이벤트 파일 초기화
    ├─ 2. CancellationToken / Budget 체크
    ├─ 3. analyze_user_intent(user_text)  ← 인텐트 분류
    ├─ 4. load_active_memories()          ← 승인된 메모리 주입
    ├─ 5. model.choose_action(intent, context)  ← 모델 액션 선택
    ├─ 6. _tool_call_for_action()         ← inspect_schema/ask_clarification 시 도구 호출
    │       └─ ToolRunner.run(ToolCall("mock_schema_context", ...))
    │             └─ _build_query_plan()  ← 스키마 조회 후 쿼리 플랜 생성
    ├─ 7. SelfEvaluator.evaluate()        ← 답변 품질 평가 (결정적, LLM 없음)
    ├─ 8. KeywordPlanner.build() + StepExecutor.run_plan_shadow()  ← shadow 플랜
    ├─ 9. [opt-in] StepExecutor.run_plan()  ← 실제 플랜 실행
    ├─ 10. SessionContext.compress_history()  ← 히스토리 임계값 초과 시 압축
    └─ 11. monitor.finish() + append_audit()
```

**`AgentResult` 반환 구조:**
```python
AgentResult(
    run_id,          # UUID
    intent,          # UserIntent.to_dict()
    action,          # Action.to_dict()
    final_answer,    # FinalAnswer.to_dict()
    status_path,     # runs/{run_id}/status.json 경로
    events_path,     # runs/{run_id}/events.jsonl 경로
    audit_path,      # audit.jsonl 경로
    query_plan,      # QueryPlanArtifact.to_dict() (있을 때)
    plan_shadow,     # {plan, step_results, shadow_mode: True}
    plan_execution,  # {plan_id, step_results, aborted}
    memory_summary,  # 주입된 메모리 텍스트 (있을 때)
    eval_result,     # SelfEvaluator 결과
)
```

**중단 체크 패턴** (`_stop_state`):
- `token.is_cancelled` → state="cancelled"
- `monotonic() - started >= budget.timeout_seconds` → state="timed_out"
- `steps_used >= budget.max_steps` (check_max_steps=True) → state="stopped"

---

### 3.4 도구 시스템 (`agent_runtime/tools.py`)

**계층 구조:**

```
ToolSpec          ← 도구 명세 (이름, 파라미터, 위험도, capabilities)
    ↓ register
ToolRegistry      ← 도구 등록/조회
    ↓ run
ToolRunner        ← 실행, 정책 체크, 재시도, 이벤트 발생
    ↓
ToolResult        ← {tool_name, state, attempts, latency_ms, output, error}
```

**기본 등록 도구 (`default_tool_registry()`):**

| 도구 | capabilities | 설명 |
|------|-------------|------|
| `mock_schema_context` | `oracle_sh.schema.read` | Oracle ADW SH 스키마 컨텍스트 반환 (외부 접속 없음) |
| `mock_data_query` | `oracle_sh.data.read` | 결정적 가짜 쿼리 결과 반환 |

**정책 게이트 (`_policy_error`):**
- `read_only=False` + `approved_write_tools`에 미포함 → 차단
- `risk_level="high"` + `approved_high_risk_tools`에 미포함 → 차단

**`ToolSpec` 필드:**
```python
ToolSpec(
    name,             # alphanumeric + '-' + '_'
    description,
    parameters,       # tuple[ToolParameter, ...]
    risk_level,       # "low" | "medium" | "high"
    read_only,        # bool (기본 True)
    capabilities,     # tuple[str, ...] — 플래너와 연결되는 태그
    cost_estimate,    # "fast" | "medium" | "slow"
)
```

---

### 3.5 플래너 & 실행기 (`agent_runtime/planner.py`, `executor.py`)

#### `KeywordPlanner` — 결정적 ExecutionPlan 생성

```
IntentResult.primary_route
    ├─ "database_analysis" → [inspect_schema, execute_query]  (2단계)
    ├─ "business_workflow" → [select_workflow, execute_workflow]  (2단계, risk=high)
    └─ "general_answer"   → [answer]  (1단계)
```

**`ExecutionPlan`:**
- `topological_groups()`: Kahn 알고리즘으로 DAG 위상 정렬 → 병렬 실행 그룹 반환
- `validate()`: 미지 depends_on, 순환 의존 검사

**`PlanStep` 핵심 필드:**
```python
PlanStep(
    step_id,
    description,
    required_capabilities,   # ["schema_inspection", "database_read"]
    primary_capability,       # 도구 매칭에 사용
    depends_on,               # DAG 엣지
    success_criteria,         # ["output.tables_found > 0"]
    retry_policy,             # {"max_attempts": 3}
    risk_level,               # "low" | "medium" | "high"
    requires_approval,        # risk_level=="high" 시 자동 True
    fallback_strategy,        # "retry" | "skip" | "clarify" | "abort"
)
```

#### `StepExecutor`

| 모드 | 메서드 | 동작 |
|------|--------|------|
| Shadow | `run_plan_shadow(plan)` | 구조 검증만, 도구 실행 없음 |
| Real | `run_plan(plan, tool_runner)` | 실제 도구 실행, 검증, 폴백 |

**실행 흐름 (real mode):**
```
topological_groups()
    └─ 각 그룹, 각 스텝:
        ├─ requires_approval → approval_callback(step)
        ├─ _find_tool_for_capability(primary_capability)
        ├─ tool_runner.run(ToolCall)
        ├─ ToolResultVerifier.verify(result, success_criteria)
        └─ suggested_action 처리:
             "proceed"/"retry" → StepResult(ok)
             "skip"            → StepResult(skipped)
             "abort"           → StepResult(ok) + aborted_by = step_id
             "clarify"         → StepResult(error="clarification_needed:...")
             "use_alternative" → 대체 도구로 재시도
```

---

### 3.6 세션 관리 (`agent_runtime/session.py`)

#### `SessionContext`

**저장 경로:** `{run_dir}/{session_id}/`
- `messages.jsonl` — 대화 히스토리 (추가 전용, redact 적용)
- `state.json` — 슬롯, 예산, 메타데이터 (0o600)
- `session_dir/` — 0o700

**핵심 기능:**

| 메서드 | 설명 |
|--------|------|
| `add_message(msg)` | 대화 히스토리 추가 |
| `recent_history(n=20)` | 최근 N개 메시지 (LLM 컨텍스트 주입용) |
| `compress_history(threshold=40)` | 임계값 초과 시 오래된 턴을 MemoryRecord로 제안 (자동 적용 안 함) |
| `set_slot(key, value, source_step_id)` | 단기 컨텍스트 슬롯 설정 |
| `cache_tool_result(tool_name, input_hash)` | 도구 결과 캐시 |
| `save(session_dir)` | 디스크 영속화 |
| `load(session_dir)` | 디스크에서 복원 |

#### `BudgetTracker`

- `would_exceed(cost_estimate)` — cost_budget_usd=0.0이면 항상 False (제한 없음)
- `charge_tokens(tokens)`, `charge_retry()`

---

### 3.7 워크플로우 엔진 (`agent_runtime/workflow.py`)

**목적:** 멀티시스템 비즈니스 프로세스 (특허자산 대체 등록) 오케스트레이션.

#### 커넥터 패턴 (`WorkflowConnector` Protocol)

```python
class WorkflowConnector(Protocol):
    def lookup_a(self, period: str) -> list[Record]: ...    # 소스 시스템 A
    def lookup_b(self, period: str) -> list[Record]: ...    # 비교 시스템 B
    def enrich_c(self, period, records) -> list[Record]: ...# 보강 시스템 C
    def load_d(self, period, records) -> dict: ...          # 타깃 시스템 D
```

#### `WorkflowEngine.run_patent_asset_replacement(period)` 흐름

```
1. 워크플로우 템플릿 선택
2. lookup_a() + lookup_b() ← ThreadPoolExecutor 병렬 실행
3. _reconcile() ← 레코드 조정 (충돌, 누락 필드 검사)
4. 조정 상태 분기:
   ├─ missing_required → enrich_c() 호출 후 재조정
   └─ 보강 불필요 → skip
5. 조정 결과 분기:
   ├─ unresolved → human_gate (state="paused", review_packet 생성)
   ├─ records 없음 → state="closed"
   └─ resolved → trusted_checkpoint 생성 (SHA-256 해시)
                  state="checkpoint_required"
```

#### Trusted Checkpoint 패턴

```python
trusted_checkpoint = {
    "schema_version": "agent-runtime.workflow-checkpoint.v1",
    "identity": f"{template_id}:{version}:{run_id}:{hash[:16]}",
    "hash": sha256(canonical_payload),  # sort_keys=True, deterministic
    "record_ids": [...],
}
```

**재개** (`resume_with_human_decision`):
1. checkpoint 존재 확인 (메모리 → 디스크 fallback)
2. `decision.action == "approve_load"` 확인
3. `_validate_trusted_checkpoint()` — identity/hash 재계산 검증
4. approved_record_ids로 레코드 필터링
5. `VerificationEpisode` 생성 (best-effort, 실패 시 무시)
6. `connector.load_d()` 실행

#### Reconciliation 규칙

| 규칙 ID | 심각도 | 설명 |
|---------|--------|------|
| `identity_match` | blocking | A, B 두 시스템 모두에 존재해야 함 |
| `field_value_consistency` | blocking | 동일 필드에 서로 다른 값 충돌 |
| `period_valid` | blocking | 레코드 period가 요청 period와 일치해야 함 |
| `required_fields_present` | warning | 필수 필드 존재 여부 |
| `asset_status_valid` | blocking | asset_status == "eligible" |
| `no_duplicate_registration` | blocking | target_registered != True |

---

### 3.8 Self-Evolution 게이트 (`agent_runtime/self_evolution.py`)

**철학:** 개선 후보를 기록하되, 자동 적용은 절대 없음. 수락은 게이트 통과 조건 전부 충족 시에만.

#### 핵심 타입

| 타입 | 역할 |
|------|------|
| `MemoryRecord` | 승인된 크로스세션 메모리 (status=active + review_status=approved만 로드) |
| `ImprovementCandidateRecord` | 개선 후보 (proposed → accepted/rejected/superseded) |
| `RollbackPlan` | 롤백 아티팩트 목록 및 검증 명령 |
| `DriftCheckResult` | 결정적 동작 drift 검사 결과 |
| `SelfEvolutionGateReport` | 수락 게이트 통과 보고서 |

#### 수락 게이트 (`evaluate_self_evolution_gate`) 조건

```
candidate.status == "proposed"
candidate.review.decision == "approved"
candidate.provenance.review_status == "approved"
eval_result.passed == True  (골든 픽스처 전부 통과)
drift_result.passed == True  (결정적 동작 드리프트 없음)
rollback_plan이 모든 affected_artifacts 경로를 커버
behavior-shaping 후보는 한 번에 한 artifact_type만 변경
```

#### MemoryRecord 라이프사이클

```
SessionSummarizer → MemoryRecord(status="proposed", review_status="pending")
    ↓ operator review-candidate approve
MemoryRecord(status="active", review_status="approved")
    ↓ load_active_memories()
AgentLoop 컨텍스트 주입
```

#### Drift Check

```python
run_drift_checks(fixture_path, output_dir):
    load_drift_cases()  # fixture의 각 케이스
    for case in cases:
        for repeat in range(case.repeats):  # 기본 2회
            loop.run(case.input_text)
            extract signature(trace)
    compare signatures → DriftCaseResult
```

서명(signature) = intent(capabilities/slots/route) + action.kind + final_answer.next_action + query_plan(status/tables/sql_sha256)

---

### 3.9 Tacit Knowledge 레이어 (`agent_runtime/tacit_knowledge.py`)

**목적:** 인간 검증 에피소드에서 암묵적 지식(heuristic)을 추출해 미래 정책으로 발전시킴.

#### 구성 요소

```
VerificationEpisode     ← 검증 에피소드 레코드
    └─ CorrectionDiff   ← AI 출력과 인간 수정 사이 word-level diff
    └─ semantic_type    ← policy_risk | escalation | tone | domain_nuance | ...

VerificationEpisodeStore  ← append-only JSONL 스토어 (세션별)

TacitSignalExtractor      ← 에피소드 → suspected_heuristics 추출

ReflectionAgent           ← 에피소드 → ReflectionResult
    └─ failure_analysis, missing_context, extracted_heuristics, policy_proposal
```

#### 에피소드 생성 시점

`WorkflowEngine.resume_with_human_decision()` 내에서 human decision 기록 시 best-effort로 생성:

```python
VerificationEpisode.create(
    session_id=run_id,
    ai_output=str(checkpoint["review_packet"]),
    final_resolution="human_approved" | "human_rejected",
    human_revision=decision.reasoning,
    confidence_after=decision.confidence,
    uncertainty_regions=decision.uncertainty_regions,
    consultation_trace=decision.consultation_trace,
    reason_tags=decision.reason_tags,
)
```

#### CLI 명령

```bash
bin/agent tacit list                          # 에피소드 목록
bin/agent tacit reflect --episode-id <uuid>  # 특정 에피소드 반성
bin/agent tacit heuristics                    # 전체 heuristic 추출
```

---

### 3.10 지원 모듈

| 모듈 | 역할 |
|------|------|
| `audit.py` | append-only JSONL 감사 로그 (모든 시크릿 redact) |
| `monitor.py` | per-run 상태/이벤트 파일 (`{run_root}/{run_id}/status.json`, `events.jsonl`) |
| `redaction.py` | `redact(dict|str)` — 민감 정보 제거 후 반환 |
| `hooks.py` | `HookRegistry` — per-event 핸들러 (redact 강제 적용) |
| `skills.py` | `SkillRegistry` — 조합 가능한 스킬 조회 |
| `self_evaluator.py` | `SelfEvaluator` — 5개 결정적 체크로 답변 품질 평가 |
| `session_summarizer.py` | `SessionSummarizer` — 실패 패턴 추출 → MemoryRecord 제안 (자동 적용 없음) |
| `schema_context.py` | Artifact-first 렉시컬 스키마 리트리버 (Oracle SH 테이블) |
| `query_plan.py` | 결정적 쿼리 플랜 빌더 (지원 SH revenue 패턴용) |
| `result_explanation.py` | FakeSqlExecutionAdapter 기반 가짜 결과 설명 |
| `sql_execution.py` | Backend-neutral 어댑터 경계 (`SqlclReadOnlyAdapter`, 기본 비활성) |
| `sqlcl_runner.py` | SQLcl 서브프로세스 경계 (stdin-only 자격증명, 출력 cap) |
| `oracle_adw.py` | 설정 로드, SQL 정책 검증, SQLcl/wallet 확인 |
| `self_evolution.py` | 자기진화 게이트 (개선 후보 기록 및 검증) |
| `trace.py` | 버전 관리 trace 이벤트 정규화, `SecretLeakError` |
| `eval_runner.py` | 골든 픽스처 eval 러너 (회귀 검사) |
| `model.py` | `MockModel`, `OpenAIResponsesModel`, `OpenAIResponsesConfig` |
| `verifier.py` | `ToolResultVerifier` — 성공 기준 검사, 폴백 제안 |

---

## 4. 프론트엔드 아키텍처

### 4.1 Next.js 14 App Router 구조

```
frontend/
  app/
    page.tsx                    # 채팅 인터페이스 (agent ask)
    status/page.tsx             # 실행 상태 모니터 (라이브 폴링)
    audit/page.tsx              # 감사 로그 뷰어 (JSONL 테이블)
    workflow/page.tsx           # 워크플로우 실행기
    tacit/page.tsx              # Tacit Knowledge 페이지
    memory/page.tsx             # 메모리 뷰어
    operator/page.tsx           # 운영자 컨트롤
    schema/page.tsx             # Oracle ADW 스키마 인스펙터
    api/agent/
      ask/route.ts              # POST → bin/agent ask 서브프로세스
      status/route.ts           # GET → 최신 실행 상태 JSON
      audit/route.ts            # GET → 감사 JSONL 파싱
      workflow/route.ts         # POST → bin/agent workflow 서브프로세스
      workflow/approve/route.ts # POST → bin/agent workflow resume
      memory/route.ts           # GET → artifacts/memory 읽기
      tacit/route.ts            # GET → bin/agent tacit
      operator/route.ts         # POST → 운영자 명령
  components/
    Sidebar.tsx                 # 네비게이션 사이드바
    StatusBadge.tsx             # 상태 배지 컴포넌트
    ui/                         # shadcn/ui 컴포넌트
  lib/
    types.ts                    # TypeScript 타입 정의
    auditColors.ts              # 감사 이벤트 색상 매핑
    errors.ts                   # 에러 처리 유틸리티
    utils.ts                    # cn() 등 유틸리티
```

### 4.2 API 라우트 패턴

모든 API 라우트는 동일한 패턴을 따른다:

```typescript
// 1. 환경변수에서 bin/agent 경로 읽기
const agentBin = process.env.AGENT_BIN_PATH ?? "bin/agent";

// 2. CLI 서브프로세스 스폰
const proc = spawn(agentBin, ["ask", query, "--run-dir", runDir, ...]);

// 3. stdout/stderr 수집
let stdout = "", stderr = "";
proc.stdout.on("data", d => stdout += d);
proc.stderr.on("data", d => stderr += d);

// 4. JSON 파싱 후 반환
const result = JSON.parse(stdout);
return NextResponse.json(result);
```

### 4.3 프론트엔드 환경 변수

| 변수 | 설명 |
|------|------|
| `AGENT_BIN_PATH` | `bin/agent` 절대 경로 |
| `AGENT_PROJECT_DIR` | 저장소 루트 절대 경로 |
| `AGENT_RUN_DIR` | `agent ask` 실행 디렉토리 (기본 `/tmp/afs-runs`) |
| `AGENT_AUDIT_LOG` | 감사 로그 경로 |
| `AGENT_WORKFLOW_RUN_DIR` | 워크플로우 실행 디렉토리 |
| `AGENT_WORKFLOW_AUDIT_LOG` | 워크플로우 감사 로그 |
| `AGENT_MEMORY_DIR` | `artifacts/memory` 경로 |

### 4.4 UI 컴포넌트 패턴 (채팅 페이지)

```
ChatPage
  ├─ IntentMeta       ← intent_type, task_type, safety_level, confidence
  ├─ ResultCard       ← 에이전트 결과 종합 표시
  │    ├─ ClarificationBlock  ← needs_clarification 시
  │    ├─ QueryPlanBlock      ← proposed_sql, dimensions/measures
  │    ├─ EvalBadge           ← SelfEvaluator 결과 (pass/fail + 체크 목록)
  │    ├─ PlanBlock           ← plan_shadow 또는 plan_execution
  │    └─ MemorySummaryBlock  ← 주입된 메모리
  └─ DynamicSuggestions ← final_answer.next_action 기반 후속 질문 제안
```

---

## 5. Artifact 시스템

```
artifacts/
  artifact-manifest.v1.json    # 단일 롤백 소스 (버전 레지스트리)
  schemas/
    user-intent.schema.json
    plan.schema.v1.json
    session-context.schema.v1.json
    memory-record.schema.v1.json
    improvement-candidate.schema.v1.json
    rollback-plan.schema.v1.json
    gate-report.schema.v1.json
    verification-episode.schema.v1.json
    workflow-template.schema.json
  prompts/
    intent-classifier.md         # 인텐트 분류기 프롬프트
  policies/
    redaction-policy.json
  evals/
    golden/                      # 골든 픽스처 (수동 편집 금지)
  memory/
    runtime-memory.v1.json       # 승인된 런타임 메모리
  workflows/
    patent-asset-replacement-registration.json  # 워크플로우 템플릿
```

### Artifact Manifest 구조

```json
{
  "prompt_versions": {"intent_classifier": {"path": "...", "version": "1"}},
  "policy_versions": {"redaction": {...}},
  "memory_versions": {"runtime": {...}},
  "eval_versions": {
    "golden_fixture": {"path": "artifacts/evals/golden", "version": "1"},
    "drift_fixture": {"path": "...", "version": "1"}
  }
}
```

---

## 6. CLI 인터페이스

### 서브커맨드 구조

```
bin/agent
  ask <text>                      # 에이전트 질의
    --run-dir, --audit-log
    --max-steps, --timeout-seconds
    --model-provider (mock|openai|oci)
    --memory-dir                  # 크로스세션 메모리 활성화

  status                          # 최신 실행 상태 조회
    --run-dir

  workflow <text>                 # 워크플로우 실행
    --run-dir, --audit-log

  workflow resume                 # 중단된 워크플로우 재개
    --run-id, --decision, --actor, --reason

  tacit list                      # 검증 에피소드 목록
  tacit reflect --episode-id      # 특정 에피소드 반성
  tacit heuristics                # 전체 heuristic 추출

  operator
    adw-smoke --confirm-live-adw-smoke          # 연결 테스트
    adw-query --sql "..." --confirm-live-adw-query
    adw-provision-working-user --grant-profile ... --confirm-live-adw-admin-provision
    propose-improvement --candidate-id ... --candidate-type ...
    review-candidate list|show|approve|reject
```

### 모델 프로바이더 선택

```
AGENT_MODEL_PROVIDER or LLM env var → 기본 mock
  mock  → MockModel() (결정적)
  openai → OpenAIResponsesConfig.from_env() → OpenAIResponsesModel
  oci   → OpenAIResponsesConfig.from_oci_env() → OpenAIResponsesModel
```

---

## 7. 핵심 데이터 흐름

### 7.1 `agent ask` 흐름

```
사용자 입력
    │
    ▼
CLI → AgentLoop.run(user_text)
    │
    ├─ analyze_user_intent()   → UserIntent
    ├─ load_active_memories()  → [MemoryRecord, ...]
    ├─ model.choose_action()   → Action
    │
    ├─ [inspect_schema] ToolRunner → mock_schema_context
    │       └─ build_compact_schema_context()
    │       └─ build_query_plan_from_context()  → QueryPlanArtifact
    │
    ├─ _final_answer(action, query_plan)  → FinalAnswer
    ├─ SelfEvaluator.evaluate()           → EvalResult
    ├─ KeywordPlanner + StepExecutor.run_plan_shadow()
    │
    └─ AgentResult → JSON stdout → Frontend
```

### 7.2 워크플로우 흐름

```
bin/agent workflow "특허자산 대체 등록"
    │
    ▼
WorkflowEngine.run_patent_asset_replacement()
    │
    ├─ lookup_a() ──┐ 병렬
    ├─ lookup_b() ──┘
    ├─ _reconcile()
    ├─ [missing_required] enrich_c()
    ├─ _reconcile() (재조정)
    │
    ├─ [unresolved] → state="paused" (review_packet 생성)
    └─ [resolved]   → trusted_checkpoint 생성 → state="checkpoint_required"
                           │ (checkpoint.json에 저장, chmod 0o600)
                           │
bin/agent workflow resume --run-id ... --decision approve_load --actor ...
    │
    └─ load_checkpoint_from_disk()
    └─ _validate_trusted_checkpoint()  (identity + hash 재계산)
    └─ VerificationEpisode 생성
    └─ connector.load_d()
    └─ state="completed"
```

### 7.3 Self-Evolution 후보 흐름

```
operator propose-improvement ...
    │
    └─ build_improvement_candidate()   → ImprovementCandidateRecord
    └─ write_improvement_candidate()   → artifacts/improvement-candidates/{id}.json

operator review-candidate approve --candidate-id ... --reviewer ...
    │
    └─ CandidateReview(decision="approved")
    └─ write_improvement_candidate(overwrite=True)

evaluate_self_evolution_gate(candidate, rollback_plan, eval_result, drift_result)
    → SelfEvolutionGateReport(status="passed"|"blocked")
    # passed여야만 수락 가능 (자동 적용 없음 — 항상 인간 검토 필요)
```

---

## 8. 보안 불변 조건

1. **시크릿 누출 금지**: 모든 출력·감사 레코드는 `redact()` 통과 후 기록.
2. **ADW 실행 게이트**: `SqlclReadOnlyAdapter.allow_real_execution=True` 명시 없이는 실제 SQL 실행 불가. 기본값은 비활성.
3. **SQL 정책 검증**: `validate_read_only_sql()` 통과 없이는 SQLcl 서브프로세스 호출 불가.
4. **운영자 명령 이중 확인**: `adw-smoke`, `adw-query`, `adw-provision-working-user`는 모두 `--confirm-*` 플래그 필수.
5. **자기진화 게이트**: `self_evolution.py`는 변경을 자동 적용하지 않음. 기록만 함.
6. **MemoryRecord 승인 조건**: `status=="active"` AND `provenance.review_status=="approved"` 둘 다 만족해야 로드.
7. **Workflow 체크포인트 검증**: human decision 처리 시 `identity` + `hash` 재계산으로 조작 탐지.
8. **관리자 식별자 안전화**: `_safe_oracle_identifier()`, `_safe_working_user()` 통해 SQL 인젝션 방지.
9. **파일 권한**: session dir = 0o700, 내부 파일 = 0o600, checkpoint.json = 0o600.
10. **환경 변수 분리**: `.env` 파일, Oracle wallet, API key는 절대 커밋하지 않음.

---

## 9. 디렉토리 트리

```
AgentFromScratchAdvanced/
├── bin/
│   └── agent                              ← CLI 진입점 (shell → Python)
├── agent_runtime/
│   ├── __init__.py
│   ├── types.py                           ← 핵심 frozen dataclass
│   ├── intent.py                          ← 키워드 인텐트 분류기
│   ├── model.py                           ← MockModel, OpenAI 어댑터
│   ├── loop.py                            ← AgentLoop (단일 패스)
│   ├── tools.py                           ← ToolRegistry, ToolRunner
│   ├── planner.py                         ← KeywordPlanner, ExecutionPlan
│   ├── executor.py                        ← StepExecutor (shadow/real)
│   ├── verifier.py                        ← ToolResultVerifier
│   ├── session.py                         ← SessionContext, BudgetTracker
│   ├── hooks.py                           ← HookRegistry
│   ├── skills.py                          ← SkillRegistry
│   ├── self_evaluator.py                  ← SelfEvaluator (결정적 5-체크)
│   ├── session_summarizer.py              ← SessionSummarizer
│   ├── workflow.py                        ← WorkflowEngine (A/B/C/D)
│   ├── schema_context.py                  ← SH 스키마 컨텍스트 리트리버
│   ├── query_plan.py                      ← 결정적 쿼리 플랜 빌더
│   ├── result_explanation.py              ← 가짜 결과 설명
│   ├── sql_execution.py                   ← SqlclReadOnlyAdapter
│   ├── sqlcl_runner.py                    ← SQLcl 서브프로세스 경계
│   ├── oracle_adw.py                      ← OracleAdwConfig, SQL 정책
│   ├── self_evolution.py                  ← 자기진화 게이트, MemoryRecord
│   ├── tacit_knowledge.py                 ← VerificationEpisode, ReflectionAgent
│   ├── audit.py                           ← append-only JSONL 감사
│   ├── monitor.py                         ← per-run 상태/이벤트
│   ├── redaction.py                       ← 시크릿 제거
│   ├── trace.py                           ← trace 정규화, SecretLeakError
│   ├── eval_runner.py                     ← 골든 픽스처 eval
│   └── cli.py                             ← argparse 진입점
├── tests/
│   ├── test_agent_loop.py
│   ├── test_workflow_engine.py
│   ├── test_self_evolution.py
│   └── ...
├── artifacts/
│   ├── artifact-manifest.v1.json
│   ├── schemas/
│   ├── prompts/
│   ├── policies/
│   ├── evals/golden/
│   ├── memory/
│   └── workflows/
├── frontend/
│   ├── app/
│   │   ├── page.tsx                       ← 채팅
│   │   ├── workflow/page.tsx
│   │   ├── tacit/page.tsx
│   │   ├── audit/page.tsx
│   │   ├── status/page.tsx
│   │   ├── memory/page.tsx
│   │   ├── operator/page.tsx
│   │   ├── schema/page.tsx
│   │   └── api/agent/
│   │       ├── ask/route.ts
│   │       ├── status/route.ts
│   │       ├── audit/route.ts
│   │       ├── workflow/route.ts
│   │       ├── workflow/approve/route.ts
│   │       ├── memory/route.ts
│   │       ├── tacit/route.ts
│   │       └── operator/route.ts
│   ├── components/
│   │   ├── Sidebar.tsx
│   │   ├── StatusBadge.tsx
│   │   └── ui/                            ← shadcn/ui 컴포넌트
│   ├── lib/
│   │   ├── types.ts
│   │   ├── auditColors.ts
│   │   ├── errors.ts
│   │   └── utils.ts
│   ├── .env.local.example
│   ├── package.json
│   └── tsconfig.json
├── docs/
│   ├── tracking/
│   │   ├── current-state.md
│   │   ├── todo.md
│   │   └── change-log.md
│   └── design-docs/
├── CLAUDE.md
└── pyproject.toml
```

---

## 10. 재구현 체크리스트

새 저장소에서 이 아키텍처를 재현할 때 순서대로 구현하면 된다.

### Phase 1 — 핵심 타입 & 루프

- [ ] `types.py`: `Message`, `Action`, `Observation`, `FinalAnswer`, `Budget`, `CancellationToken`, `IntentResult`
- [ ] `intent.py`: 키워드 그룹 + `analyze_user_intent()` + `KeywordIntentClassifier`
- [ ] `model.py`: `MockModel` (결정적 ActionKind 반환)
- [ ] `monitor.py`: `RunMonitor` — `status.json` + `events.jsonl`
- [ ] `audit.py`: append-only JSONL `RunRecord`
- [ ] `redaction.py`: `redact()`
- [ ] `loop.py`: `AgentLoop.run()` — 단일 패스

### Phase 2 — 도구 & 플래너

- [ ] `tools.py`: `ToolSpec`, `ToolRegistry`, `ToolRunner`, `default_tool_registry()`
- [ ] `verifier.py`: `ToolResultVerifier`
- [ ] `planner.py`: `PlanStep`, `ExecutionPlan` (Kahn 정렬), `KeywordPlanner`
- [ ] `executor.py`: `StepExecutor` (shadow mode 먼저)
- [ ] `session.py`: `SessionContext`, `BudgetTracker`

### Phase 3 — 워크플로우

- [ ] `workflow.py`: `WorkflowConnector` Protocol + `MockPatentAssetConnector`
- [ ] `workflow.py`: `WorkflowEngine.run_patent_asset_replacement()`
- [ ] `workflow.py`: `_reconcile()` — 조정 규칙
- [ ] `workflow.py`: trusted_checkpoint (SHA-256 해시)
- [ ] `workflow.py`: `resume_with_human_decision()`
- [ ] `artifacts/workflows/patent-asset-replacement-registration.json`

### Phase 4 — Self-Evolution & Memory

- [ ] `self_evolution.py`: `MemoryRecord`, `ImprovementCandidateRecord`
- [ ] `self_evolution.py`: `evaluate_self_evolution_gate()`
- [ ] `self_evolution.py`: `load_active_memories()`
- [ ] `self_evolution.py`: `run_drift_checks()`
- [ ] `session_summarizer.py`: `SessionSummarizer`
- [ ] `self_evaluator.py`: `SelfEvaluator` (5-체크)

### Phase 5 — Tacit Knowledge

- [ ] `tacit_knowledge.py`: `VerificationEpisode`, `CorrectionDiff`
- [ ] `tacit_knowledge.py`: `VerificationEpisodeStore`
- [ ] `tacit_knowledge.py`: `TacitSignalExtractor`, `ReflectionAgent`

### Phase 6 — Oracle ADW 연결

- [ ] `oracle_adw.py`: `OracleAdwConfig.from_env()`, `validate_read_only_sql()`
- [ ] `sqlcl_runner.py`: `run_sqlcl_subprocess()` (stdin-only 자격증명)
- [ ] `sql_execution.py`: `SqlclReadOnlyAdapter` (allow_real_execution=False 기본)
- [ ] `schema_context.py`: 스키마 메타데이터 리트리버
- [ ] `query_plan.py`: 결정적 쿼리 플랜 빌더

### Phase 7 — CLI

- [ ] `cli.py`: `ask`, `status`, `workflow`, `workflow resume`, `tacit`, `operator` 서브커맨드
- [ ] `bin/agent`: 진입점 스크립트

### Phase 8 — 프론트엔드

- [ ] Next.js 14 App Router 세팅 + Tailwind + shadcn/ui
- [ ] `.env.local.example` 환경변수 정의
- [ ] API 라우트: `ask`, `status`, `audit`, `workflow`, `workflow/approve`, `memory`, `tacit`, `operator`
- [ ] 페이지: 채팅, 워크플로우, 감사, 상태, 메모리, 운영자, 스키마, tacit
- [ ] `Sidebar.tsx`, `StatusBadge.tsx`

### Phase 9 — Artifact 시스템

- [ ] `artifact-manifest.v1.json` 생성
- [ ] JSON Schema 정의 (user-intent, plan, session-context, memory-record 등)
- [ ] 골든 eval 픽스처
- [ ] 워크플로우 템플릿 JSON

---

*이 문서는 2026-05-28 기준 구현을 반영합니다.*
