# Human Verification Tacit Knowledge Layer

## 목적

기존 Agentic AI 시스템에 다음 기능을 추가한다:

* 인간 검증 과정에서 발생하는 암묵지(Tacit Knowledge) 수집
* 인간 수정 패턴 기반 self-improving agent 구현
* verification/correction 과정 자체를 학습 가능한 memory로 저장
* future execution 시 human verification heuristic 재사용
* 조직 특화 검증 정책(policy) 자동 생성 기반 구축

이 문서의 핵심은:
"정답 저장"이 아니라
"인간이 무엇을 의심하고 어떻게 검증하는가"를 시스템이 학습하게 만드는 것이다.

---

## 배경: 기존 시스템의 한계

현재 AgentFromScratchAdvanced의 Human Gate는:

```
AI 출력 → 인간 검토 → approve/reject
```

이 구조에서 시스템이 학습하는 것은 오직 **최종 결과(approve/reject)**뿐이다.

하지만 실제 조직에서 인간 검증자는:
- "이 출력의 어떤 부분이 의심스러운가?"
- "왜 이 수정이 필요한가?"
- "이런 케이스에서 누구에게 확인해야 하는가?"

…를 암묵적으로 알고 있다. 이 지식이 시스템에 축적되지 않는다.

---

## 핵심 개념

### 1. Verification Episode (검증 에피소드)

한 번의 인간 검증 사건을 완전히 기록하는 단위:

```
{
  ai_output: "원본 AI 출력",
  human_revision: "인간이 수정한 결과",
  correction_diff: {
    removed: [...],
    inserted: [...],
    semantic_type: "policy_risk | tone | domain_nuance | escalation | ..."
  },
  reason_tags: ["tone mismatch", "domain nuance", "policy risk"],
  consultation_trace: [
    { person: "법무팀", reason: "계약 조항 확인 필요" }
  ],
  confidence_before: 0.7,
  confidence_after: 0.95,
  final_resolution: "human_override | human_approved | human_rejected | escalated"
}
```

### 2. Tacit Signal (암묵 신호)

에피소드에서 추출되는 조직 특화 heuristic:

- "이런 상황에서는 법무팀에 물어봐야 한다"
- "금융 관련 출력은 항상 tone 확인이 필요하다"
- "escalation 마커가 있으면 senior reviewer로 라우팅"

### 3. Reflection (반성)

에피소드를 바탕으로 AI가 자기 실패를 분석:

- 왜 틀렸는가?
- 어떤 context가 부족했는가?
- 어떤 policy 변경이 필요한가?

---

## 아키텍처

```
Human Decision (workflow.py)
         │
         ▼
VerificationEpisodeStore  ←── JSONL append (audit.py 패턴 재사용)
         │
         ├──► TacitSignalExtractor  →  suspected_heuristics
         │
         └──► ReflectionAgent       →  failure_analysis + policy_proposal
                    │
                    ▼
              (future) MemoryRecord proposal  →  self_evolution gate
```

---

## 구현 모듈

### `agent_runtime/tacit_knowledge.py`

**CorrectionDiff**: AI 출력과 인간 수정 간의 차이를 구조화

```python
@dataclass(frozen=True)
class CorrectionDiff:
    removed: tuple[str, ...]
    inserted: tuple[str, ...]
    tone_change: str | None
    terminology_changes: tuple[str, ...]
    semantic_type: str  # literal_to_contextual | tone | policy_risk | domain_nuance | escalation | no_change | other
```

**VerificationEpisode**: 검증 에피소드 전체 기록

```python
@dataclass(frozen=True)
class VerificationEpisode:
    episode_id: str              # UUID
    timestamp: str               # ISO 8601
    session_id: str
    ai_output: str
    human_revision: str | None
    correction_diff: CorrectionDiff | None
    confidence_before: float | None
    confidence_after: float | None
    uncertainty_regions: tuple[str, ...]
    consultation_trace: tuple[dict, ...]
    reason_tags: tuple[str, ...]
    final_resolution: str
    schema_version: str
```

**VerificationEpisodeStore**: JSONL append-only 스토어

- `append(episode)` → session별 JSONL 파일에 기록
- `load_session(session_id)` → 해당 세션 에피소드 로드
- `load_all()` → 전체 에피소드 로드

**TacitSignalExtractor**: 에피소드에서 heuristic 추출

- reason_tags → 매핑된 heuristic
- semantic_type → 패턴별 heuristic
- consultation_trace → "consult X when Y" 형식

**ReflectionAgent**: 에피소드 반성 (self_evaluator.py 패턴 재사용)

- `reflect(episode)` → ReflectionResult
  - failure_analysis
  - missing_context
  - extracted_heuristics
  - policy_proposal

---

## CLI 확장

```bash
# 에피소드 목록
bin/agent tacit list [--episodes-dir PATH]

# 특정 에피소드 반성
bin/agent tacit reflect --episode-id UUID [--episodes-dir PATH]

# 전체 heuristic 추출
bin/agent tacit heuristics [--episodes-dir PATH]
```

---

## 스키마

`artifacts/schemas/verification-episode.schema.v1.json`

schema_version: `agent-runtime.verification-episode.v1`

---

## 설계 원칙

1. **No Auto-Apply**: 추출된 heuristic과 policy proposal은 절대 자동 적용되지 않는다. 오직 제안만 한다. self_evolution.py 패턴 준수.

2. **Append-Only**: 에피소드 스토어는 audit.py와 동일하게 append-only JSONL. 기존 기록을 수정하지 않는다.

3. **Redact First**: 모든 기록은 redact()를 통과한다. 비밀 정보가 에피소드에 포함되지 않는다.

4. **Deterministic**: ReflectionAgent와 TacitSignalExtractor는 LLM 없이 결정론적으로 동작한다. self_evaluator.py 패턴 준수. LLM critic은 future wiring으로 남겨둔다.

5. **Frozen Dataclasses**: 모든 핵심 데이터 구조는 frozen=True. 불변성 보장.

---

## 확장 경로

```
현재 (v1):
  에피소드 수집 → heuristic 추출 → policy proposal (수동 검토)

미래 (v2):
  에피소드 → MemoryRecord 자동 제안 → self_evolution gate 통과 → agent context 주입

미래 (v3):
  누적 에피소드 → 패턴 학습 → proactive uncertainty flagging
  ("이런 케이스는 검증 필요할 것 같습니다" 라고 AI가 먼저 알림)
```

---

## 기대 효과

- 인간 검증자의 암묵지를 명시적 heuristic으로 변환
- 반복적인 수정 패턴을 자동으로 감지하고 정책화
- 조직 특화 검증 문화를 코드로 내재화
- 장기적으로 인간-AI 협업의 마찰을 줄이고 신뢰를 높이는 시스템
  으로 진화시키는 것이다.
