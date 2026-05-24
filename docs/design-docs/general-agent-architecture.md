# P1-P7 General Agent Architecture

## 개요

P1-P7 마일스톤은 AgentFromScratch에 의도 우선(intent-first) 에이전트 루프를 구현했습니다.
사용자의 한글 쿼리를 바탕으로 의도를 분석하고, 결정론적 플래닝과 도구 실행을 통해 Oracle ADW 데이터 조회와 워크플로우 실행을 지원합니다.

**기존 single-pass 루프에서의 변화:**
- 의도 분류(intent classification)를 입력 검증으로 추가
- Cross-session 메모리 주입(memory injection) 지원
- 계획 생성과 shadow 모드 실행 기록
- 훅 기반 이벤트 시스템(hook registry)으로 관찰성 강화
- 기술(skill)과 도구(tool) 레지스트리 분리

## 아키텍처 다이어그램 (텍스트)

```
User Text (한글 쿼리)
  ↓
AgentLoop.run()
  ├─ analyze_user_intent() → UserIntent
  ├─ KeywordIntentClassifier.from_user_intent() → IntentResult
  ├─ load_active_memories(memory_dir) → [MemoryRecord]
  ├─ hook_registry.fire("memory_injected", ...)
  ├─ model.choose_action(intent, context=memory_summary) → Action
  ├─ _tool_call_for_action(action) → ToolCall (optional)
  ├─ ToolRunner.run(tool_call) → ToolResult
  │   ├─ hook_registry.fire("tool_started", ...)
  │   ├─ handler(arguments) → output
  │   ├─ hook_registry.fire("tool_completed", ...)
  ├─ _final_answer(action, query_plan) → FinalAnswer
  ├─ KeywordPlanner.build(intent_result) → ExecutionPlan
  ├─ StepExecutor.run_plan_shadow(plan) → [StepResult]
  ├─ hook_registry.fire("plan_shadow_recorded", ...)
  ↓
AgentResult {
  run_id, intent, action, final_answer,
  status_path, events_path, audit_path,
  query_plan?, plan_shadow?, memory_summary?
}
```

## 빠른 시작

### 3.1 기본 실행 (기존과 동일)

```bash
bin/agent ask "지난달 상품별 매출 추이를 보여줘" \
  --run-dir /tmp/afs-runs \
  --audit-log /tmp/afs.jsonl
```

**출력:**
```
{
  "run_id": "abc123...",
  "intent": {"intent_type": "database_analysis", "task_type": "trend_analysis", ...},
  "action": {"kind": "inspect_schema", ...},
  "final_answer": {"content": "Query plan ready. Proposed SQL:...", ...},
  "memory_summary": null,
  "plan_shadow": {"plan": {...}, "steps": [...], "shadow_mode": true}
}
```

### 3.2 Cross-session 메모리 활성화

`memory_dir` 파라미터를 설정하면 approved 상태의 메모리 레코드를 자동으로 주입합니다.

```python
from agent_runtime.loop import AgentLoop
from pathlib import Path

loop = AgentLoop(
    memory_dir=Path("artifacts/memory")
)
result = loop.run("이번달 채널별 매출을 보여줘")
```

**메모리 파일 형식** (`artifacts/memory/my-memory.json`):
```json
{
  "schema_version": "agent-runtime.memory-record.v1",
  "memory_id": "preferred_metric_revenue",
  "key": "preferred_metric",
  "value": "revenue",
  "status": "active",
  "tags": ["sales_domain"],
  "provenance": {
    "source_type": "operator",
    "source_id": "manual",
    "author": "hiwylee@gmail.com",
    "recorded_at": "2026-05-24T00:00:00Z",
    "confidence": 1.0,
    "evidence": [],
    "scope": "project",
    "expires_at": null,
    "review_status": "approved"
  }
}
```

**조건:**
- `status: "active"` AND `provenance.review_status: "approved"` 인 파일만 주입됨
- 주입되면 `memory_injected` 이벤트 발화
- 결과의 `memory_summary` 필드에 포함됨

### 3.3 훅 등록 (코드 예제)

```python
from agent_runtime.hooks import HookRegistry
from agent_runtime.loop import AgentLoop

registry = HookRegistry()

# 의도 분석 이벤트
registry.register("intent_analyzed", lambda event, data: print(
    f"intent: {data['intent']['intent_type']}"
))

# 메모리 주입 이벤트
registry.register("memory_injected", lambda event, data: print(
    f"memories injected: {data['memory_count']}"
))

# 도구 실행 이벤트
registry.register("tool_started", lambda event, data: print(
    f"running tool: {data['tool']['name']}"
))

registry.register("tool_completed", lambda event, data: print(
    f"tool result: {data['result']['state']}"
))

# 계획 shadow 모드
registry.register("plan_shadow_recorded", lambda event, data: print(
    f"plan shadow: {data['steps']} steps"
))

loop = AgentLoop(hook_registry=registry)
result = loop.run("지난달 매출을 보여줘")
```

## 컴포넌트 레퍼런스

### 4.1 AgentLoop

메인 에이전트 루프의 진입점. 의도 분석부터 최종 답변까지 전체 실행을 오케스트레이션합니다.

**`__init__` 파라미터:**

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `model` | `ActionModel \| None` | `MockModel()` | 행동 선택 모델 (현재는 MockModel만 구현) |
| `budget` | `Budget \| None` | `Budget()` | 최대 스텝, 타임아웃, 토큰 한계 설정 |
| `cancellation_token` | `CancellationToken \| None` | `CancellationToken()` | 실행 중단 신호 |
| `tool_registry` | `ToolRegistry \| None` | `default_tool_registry()` | 등록된 도구 모음 |
| `tool_max_attempts` | `int` | `1` | 도구 호출 재시도 횟수 |
| `run_root` | `Path` | `Path(".agent/runs")` | 실행 결과 저장 디렉토리 |
| `audit_path` | `Path` | `Path(".agent/audit.jsonl")` | 감시(audit) 로그 파일 |
| `memory_dir` | `Path \| None` | `None` | Cross-session 메모리 로드 디렉토리 |
| `hook_registry` | `HookRegistry \| None` | `None` | 이벤트 훅 레지스트리 |

**주요 메서드:**

```python
def run(self, user_text: str, cancellation_token: CancellationToken | None = None) -> AgentResult:
    """사용자 쿼리를 처리하고 AgentResult를 반환합니다."""
```

### 4.2 HookRegistry

이벤트 기반 관찰성을 제공하는 훅 시스템. 핸들러는 데이터가 자동으로 `redact()` 처리된 후 호출되며, 핸들러 실패는 격리됩니다.

**메서드:**

```python
def register(self, event: str, handler: HookHandler) -> None:
    """이벤트 핸들러를 등록합니다.
    
    Args:
        event: 이벤트 이름
        handler: Callable[[str, dict], None] 서명
    """

def fire(self, event: str, data: dict[str, Any]) -> None:
    """이벤트를 발화합니다.
    
    - data는 자동으로 redact() 처리됨
    - 핸들러 실패는 catch되고 무시됨
    - 한 핸들러의 실패가 다른 핸들러를 차단하지 않음
    """

def handlers_for(self, event: str) -> list[HookHandler]:
    """등록된 핸들러 목록을 반환합니다."""

def registered_events(self) -> list[str]:
    """최소 하나의 핸들러를 가진 이벤트 목록을 반환합니다."""
```

**발화되는 이벤트:**

| 이벤트 | 데이터 필드 | 의미 |
|--------|-----------|------|
| `intent_analyzed` | `intent` | 사용자 의도 분류 완료 |
| `memory_injected` | `memory_count`, `memory_ids` | Approved 메모리 주입됨 |
| `model_action_selected` | `model`, `action` | 모델이 행동 선택함 |
| `tool_started` | `call`, `tool` | 도구 실행 시작 |
| `tool_completed` | `result` | 도구 실행 완료 (상태: completed) |
| `tool_failed` | `result` | 도구 실행 실패 |
| `tool_blocked` | `call`, `tool`, `policy`, `result` | 도구가 정책으로 차단됨 |
| `tool_invalid` | `call`, `result` | 도구 호출이 유효하지 않음 |
| `tool_attempt_failed` | `tool_name`, `attempt`, `error` | 도구 호출 재시도 실패 |
| `query_plan_built` | `query_plan` | 쿼리 계획 생성됨 |
| `plan_shadow_recorded` | `plan_id`, `steps` | Shadow 모드 계획 기록됨 |
| `plan_shadow_failed` | `error` | Shadow 모드 계획 생성 실패 |

### 4.3 SkillRegistry

고수준 기능 조합을 위한 스킬 레지스트리. 현재 `schema_and_query` 스킬만 구현되어 있습니다.

**메서드:**

```python
def register(self, spec: SkillSpec) -> None:
    """스킬을 등록합니다.
    
    Args:
        spec: name, description, required_capabilities, handler를 포함한 스킬 명세
    """

def get(self, name: str) -> SkillSpec:
    """이름으로 스킬을 조회합니다. (KeyError if not found)"""

def find_by_capabilities(self, required: list[str]) -> list[SkillSpec]:
    """필요한 capability를 가진 스킬을 검색합니다.
    
    Returns:
        required와 교집합이 있는 모든 스킬
    """

def all_registered(self) -> list[SkillSpec]:
    """등록된 모든 스킬을 반환합니다."""

def default_skill_registry() -> SkillRegistry:
    """기본 스킬이 등록된 레지스트리를 생성합니다."""
```

**기본 스킬:**

```python
SkillSpec(
    name="schema_and_query",
    description="Oracle SH 스키마 검사 후 데이터 쿼리",
    required_capabilities=("oracle_sh.schema.read", "oracle_sh.data.read"),
    handler=_schema_and_query_handler,
    version="1.0",
)
```

### 4.4 도구 (Tools)

**등록된 도구:**

| 도구 이름 | Capability | 설명 | Parameters |
|---------|-----------|------|-----------|
| `mock_schema_context` | `oracle_sh.schema.read` | Oracle ADW 스키마 검사 (외부 접근 없음) | `required_context[]`, `request_text`, `request_terms[]` |
| `mock_data_query` | `oracle_sh.data.read` | Oracle ADW SH 데이터 쿼리 (시뮬레이션) | `query_plan_id`, `dimension`, `metric` |

**Capability 기반 도구 검색:**

```python
from agent_runtime.tools import find_tools_by_capabilities, default_tool_registry

registry = default_tool_registry()

# Read-only 도구 검색
read_tools = find_tools_by_capabilities(
    registry,
    required=["oracle_sh.schema.read", "oracle_sh.data.read"]
)
# → [ToolSpec(name="mock_schema_context"), ToolSpec(name="mock_data_query")]
```

### 4.5 SessionContext

한 세션의 단기 상태를 관리합니다. `MemoryRecord`와 달리 세션에만 존재하며 자동 리뷰 게이트를 거치지 않습니다.

**필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| `session_id` | `str` | 세션 고유 ID |
| `conversation_history` | `list[Message]` | 메시지 목록 |
| `slots` | `dict[str, ConversationSlot]` | 세션 슬롯 (키-값 저장소) |
| `tool_results_cache` | `dict[str, Any]` | 도구 결과 캐시 |
| `budget_tracker` | `BudgetTracker \| None` | 예산 사용 추적 |
| `approved_memories` | `list[Any]` | Approved 메모리 목록 (메모리 디렉토리에서 fresh 로드) |

**메서드:**

```python
def set_slot(self, key: str, value: Any, source_step_id: str = "") -> None:
    """세션 슬롯에 값을 저장합니다."""

def get_slot(self, key: str) -> Any | None:
    """세션 슬롯에서 값을 조회합니다."""

def save(self, session_dir: Path) -> None:
    """세션을 디스크에 저장합니다.
    
    파일:
      - messages.jsonl (append-only, redacted)
      - state.json (slots, budget 상태)
    
    권한: 0o700 (dir), 0o600 (files)
    """

@classmethod
def load(cls, session_dir: Path) -> "SessionContext":
    """이전에 저장된 세션을 로드합니다."""
```

**주의:** `approved_memories`는 디스크에 저장되지 않습니다. 항상 `memory_dir`에서 fresh로 로드됩니다.

### 4.6 메모리 레코드 형식

`artifacts/memory/` 디렉토리에 저장되는 JSON 파일 형식입니다.

**필드:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `schema_version` | `str` | Yes | `"agent-runtime.memory-record.v1"` |
| `memory_id` | `str` | Yes | 고유 메모리 ID |
| `key` | `str` | Yes | 메모리 키 (예: `preferred_metric`) |
| `value` | `str` | Yes | 메모리 값 (예: `revenue`) |
| `status` | `str` | Yes | `"active"` \| `"proposed"` \| `"rejected"` \| `"expired"` |
| `tags` | `str[]` | No | 메모리 태그 |
| `provenance` | `object` | Yes | 출처 정보 (아래 참조) |

**Provenance 필드:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `source_type` | `str` | Yes | `"operator"` \| `"user"` \| `"self_evolution"` |
| `source_id` | `str` | Yes | 출처 ID |
| `author` | `str` | Yes | 작성자 이메일 |
| `recorded_at` | `str` | Yes | ISO 8601 타임스탬프 |
| `confidence` | `number` | Yes | 0.0-1.0 신뢰도 |
| `evidence` | `str[]` | No | 근거 목록 |
| `scope` | `str` | Yes | `"project"` \| `"user"` |
| `expires_at` | `str \| null` | No | 만료 시간 (없으면 무기한) |
| `review_status` | `str` | Yes | `"pending"` \| `"approved"` \| `"rejected"` \| `"changes_requested"` |

**주입 조건:**
```
status == "active" AND review_status == "approved"
```

**예제:**

```json
{
  "schema_version": "agent-runtime.memory-record.v1",
  "memory_id": "revenue_metric_preference",
  "key": "preferred_metric",
  "value": "revenue",
  "status": "active",
  "tags": ["sales", "metric"],
  "provenance": {
    "source_type": "operator",
    "source_id": "manual",
    "author": "hiwylee@gmail.com",
    "recorded_at": "2026-05-24T10:30:00Z",
    "confidence": 1.0,
    "evidence": ["user_preference"],
    "scope": "project",
    "expires_at": null,
    "review_status": "approved"
  }
}
```

### 4.7 Plan / Shadow Mode

Shadow 모드는 실행에 영향을 주지 않으면서 계획 artifact를 생성합니다.

**AgentResult.plan_shadow 필드:**

```python
plan_shadow: dict[str, object] | None = {
    "plan": {
        "request_id": "run-id-abc123",
        "goal": "route=database_analysis",
        "primary_route": "database_analysis",
        "steps": [
            {
                "step_id": "inspect_schema",
                "description": "데이터베이스 스키마 검사",
                "required_capabilities": ["schema_inspection"],
                "primary_capability": "schema_inspection",
                "depends_on": [],
                "success_criteria": ["output.tables_found > 0"],
                "expected_output": "스키마 컨텍스트",
                "retry_policy": {"max_attempts": 3},
                "risk_level": "low",
                "requires_approval": False,
                "fallback_strategy": "retry"
            },
            {
                "step_id": "execute_query",
                "description": "데이터베이스에 쿼리 실행",
                "required_capabilities": ["sql_execution"],
                "primary_capability": "sql_execution",
                "depends_on": ["inspect_schema"],
                ...
            }
        ],
        "assumptions": []
    },
    "step_results": [
        {
            "step_id": "inspect_schema",
            "tool_name": null,
            "tool_result": null,
            "verification": null,
            "skipped": True,
            "error": ""
        },
        ...
    ],
    "shadow_mode": True
}
```

**Shadow 모드 확인:**

```python
if result.plan_shadow and result.plan_shadow.get("shadow_mode"):
    plan = result.plan_shadow["plan"]
    steps = plan["steps"]
    for step in steps:
        print(f"Step: {step['step_id']}, Requires: {step['required_capabilities']}")
```

### 4.8 Capability 태그 네이밍 규칙

| 태그 | 의미 |
|------|------|
| `oracle_sh.schema.read` | Oracle SH 스키마 조회 |
| `oracle_sh.data.read` | Oracle SH 데이터 SELECT |
| `oracle_sh.data.write` | Oracle SH DML (차단됨) |
| `core.workflow.run` | 워크플로우 실행 |
| `schema_inspection` | 스키마 검사 (generic) |
| `database_read` | 데이터베이스 읽기 (generic) |
| `sql_execution` | SQL 실행 |
| `workflow_selection` | 워크플로우 선택 |
| `workflow_execution` | 워크플로우 실행 |

## 보안 불변식

1. **Pending 메모리는 절대 주입되지 않음**
   ```python
   # load_active_memories()는 아래 조건만 만족하는 파일을 로드
   if status == "active" and review_status == "approved":
       yield MemoryRecord(...)
   ```

2. **HookRegistry.fire()는 항상 redact() 후 핸들러 호출**
   ```python
   def fire(self, event: str, data: dict[str, Any]) -> None:
       safe_data = redact(data)  # 비밀 제거
       for handler in self._handlers.get(event, []):
           try:
               handler(event, safe_data)
           except Exception:
               pass  # 핸들러 실패 격리
   ```

3. **ToolRunner 훅도 double-redaction 방어**
   ```python
   def _event(self, event: str, data: dict[str, Any]) -> None:
       append_audit(RunRecord.create(..., data=redact(data), ...))
       if self.event_sink is not None:
           self.event_sink(event, redact(data))  # 이중 redaction
       if self.hook_registry is not None:
           self.hook_registry.fire(event, redact(data))
   ```

4. **SessionContext.approved_memories는 디스크에 저장되지 않음**
   - 항상 `memory_dir`에서 fresh 로드
   - 세션 파일(messages.jsonl, state.json)에는 포함되지 않음

5. **Shadow 모드는 실행 흐름을 절대 변경하지 않음**
   ```python
   # StepExecutor.run_plan_shadow()는 plan만 검증하고 stub 결과 반환
   # 실제 tool 호출 없음
   def run_plan_shadow(self, plan: ExecutionPlan) -> list[StepResult]:
       errors = plan.validate()
       return [StepResult(..., skipped=True, error=error_str) for ...]
   ```

## 트러블슈팅

### Q: `plan_shadow_failed` 이벤트가 monitor에 기록될 때

**의미:** Shadow 모드에서 계획 생성 중 예외 발생

**확인:**
```python
# 이벤트를 보면
monitor.event("plan_shadow_failed", {"error": str(exc)})

# loop.py 라인 246-247에서 예외 캡처됨
except Exception as exc:
    monitor.event("plan_shadow_failed", {"error": str(exc)})
```

**대응:**
- Shadow 모드는 실행 흐름에 영향을 주지 않음
- 계획 생성 실패 후에도 `final_answer`와 `query_plan`은 정상 반환됨
- 로그에서 예외 메시지 확인

### Q: `memory_injected` 이벤트가 발화되지 않을 때

**확인할 사항:**

1. `memory_dir` 파라미터가 설정되었는가?
   ```python
   loop = AgentLoop(memory_dir=Path("artifacts/memory"))
   ```

2. 메모리 파일이 존재하는가?
   ```bash
   ls -la artifacts/memory/
   ```

3. 파일이 올바른 조건을 만족하는가?
   ```python
   # 체크항목
   - schema_version == "agent-runtime.memory-record.v1"
   - status == "active"
   - provenance.review_status == "approved"
   ```

4. 파일 형식이 유효한가?
   ```bash
   python -c "import json; json.load(open('artifacts/memory/my-memory.json'))"
   ```

**디버깅:**
```python
from agent_runtime.self_evolution import load_active_memories
from pathlib import Path

memories = load_active_memories(Path("artifacts/memory"))
print(f"Loaded {len(memories)} memories")
for mem in memories:
    print(f"  - {mem.memory_id}: {mem.key}={mem.value}")
```

### Q: `SessionContext.load()` 실패 시

**일반적인 원인:**

1. **state.json 파일이 없음**
   ```
   FileNotFoundError: [Errno 2] No such file or directory: '.../state.json'
   ```

2. **JSON 형식 오류**
   ```python
   # state.json이 유효한 JSON인지 확인
   import json
   json.load(open("session_dir/state.json"))
   ```

3. **필수 필드 누락**
   ```json
   // state.json에 반드시 필요한 필드
   {
     "session_id": "...",
     "redaction_status": "clean",
     "instruction_sources": [],
     "slots": {},
     "budget": null
   }
   ```

**대응:**
```python
from pathlib import Path
from agent_runtime.session import SessionContext

try:
    ctx = SessionContext.load(Path("session_dir"))
except FileNotFoundError as e:
    print(f"session file missing: {e}")
except json.JSONDecodeError as e:
    print(f"invalid json: {e}")
except Exception as e:
    print(f"load failed: {type(e).__name__}: {e}")
```

## 실행 예제

### 전체 흐름 (메모리 + 훅 + Shadow 모드)

```python
from agent_runtime.loop import AgentLoop
from agent_runtime.hooks import HookRegistry
from pathlib import Path

# 1. 훅 레지스트리 구성
hooks = HookRegistry()

def log_intent(event: str, data: dict) -> None:
    intent = data.get("intent", {})
    print(f"[Intent] type={intent.get('intent_type')}, task={intent.get('task_type')}")

def log_memory(event: str, data: dict) -> None:
    count = data.get("memory_count", 0)
    if count > 0:
        print(f"[Memory] {count} approved memories injected")

def log_tool(event: str, data: dict) -> None:
    if event == "tool_started":
        tool = data.get("tool", {})
        print(f"[Tool] running {tool.get('name')}")
    elif event == "tool_completed":
        result = data.get("result", {})
        print(f"[Tool] {result.get('tool_name')} → {result.get('state')}")

hooks.register("intent_analyzed", log_intent)
hooks.register("memory_injected", log_memory)
hooks.register("tool_started", log_tool)
hooks.register("tool_completed", log_tool)

# 2. AgentLoop 구성 (메모리 + 훅)
loop = AgentLoop(
    memory_dir=Path("artifacts/memory"),
    hook_registry=hooks,
    run_root=Path("/tmp/afs-runs"),
    audit_path=Path("/tmp/afs.jsonl"),
)

# 3. 실행
result = loop.run("지난달 상품별 매출 추이를 보여줘")

# 4. 결과 확인
print(f"\nRun ID: {result.run_id}")
print(f"Intent: {result.intent['intent_type']}")
print(f"Action: {result.action['kind']}")
print(f"Memory Summary: {result.memory_summary}")

# 5. Shadow 모드 계획 확인
if result.plan_shadow:
    plan = result.plan_shadow["plan"]
    print(f"\nShadow Plan: {len(plan['steps'])} steps")
    for step in plan["steps"]:
        print(f"  - {step['step_id']}: {step['description']}")
```

**출력:**
```
[Intent] type=database_analysis, task=trend_analysis
[Memory] 1 approved memories injected
[Tool] running mock_schema_context
[Tool] mock_schema_context → completed

Run ID: abc123def456...
Intent: database_analysis
Action: inspect_schema
Memory Summary: - [preferred_metric] preferred_metric: revenue

Shadow Plan: 2 steps
  - inspect_schema: 데이터베이스 스키마 검사
  - execute_query: 데이터베이스에 쿼리 실행
```

## 추가 리소스

- [Self-Evolution Design](./self-evolution.md) — 개선 루프와 메모리 관리
- [Architecture](./architecture.md) — 전체 시스템 아키텍처
- [Database Natural Language](./database-natural-language.md) — 자연언어 쿼리 분석
