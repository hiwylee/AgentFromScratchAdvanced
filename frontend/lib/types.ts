// Shared types aligned with AgentFromScratch P8-P10 backend output shapes.

export type RunState =
  | "running" | "completed" | "failed" | "cancelled"
  | "timed_out" | "stopped" | "paused" | "checkpoint_required"
  | "closed" | "blocked" | "pending" | "unknown";

// ── P9: SelfEvaluator ──────────────────────────────────────────────
export interface EvalCheck {
  name: string;
  passed: boolean;
  detail?: string;
}

export interface EvalResult {
  passed: boolean;
  score?: number;
  checks?: EvalCheck[];
  issues?: string[];
  suggestions?: string[];
}

// ── P10: Memory ────────────────────────────────────────────────────
export interface MemoryRecord {
  memory_id?: string;
  key?: string;
  value?: string;
  status?: "active" | "proposed";
  relevance?: number;
  tags?: string[];
  created_at?: string;
}

export interface MemorySummary {
  records?: MemoryRecord[];
  total_injected?: number;
  summary?: string;
}

// ── Intent (P1 + confidence/alternatives from IntentResult) ────────
export interface IntentAlternative {
  intent_type: string;
  confidence: number;
}

export interface IntentResult {
  intent_type?: string;
  task_type?: string;
  safety_level?: string;
  next_action?: string;
  requires_oracle_adw_context?: boolean;
  entities?: Record<string, string[]>;
  // P1 fields not yet shown in UI:
  confidence?: number;
  alternatives?: IntentAlternative[];
  needs_clarification?: boolean;
  clarification_prompt?: string | null;
  ambiguities?: string[];
}

// ── P8: Plan Execution ─────────────────────────────────────────────
export type PlanStepStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface PlanStepVerification {
  passed: boolean;
  failure_reason?: string;
  suggested_action?: string;
  issues?: string[];
}

export interface PlanStep {
  step_id?: string;
  name?: string;
  action?: string;
  status?: PlanStepStatus;
  requires_approval?: boolean;
  risk_level?: string;
  required_capabilities?: string[];
  fallback_strategy?: string;
  latency_ms?: number;
  attempts?: number;
  tool_result?: Record<string, unknown>;
  verification?: PlanStepVerification;
  result?: unknown;
}

export interface PlanStepResult {
  step_id?: string;
  status?: PlanStepStatus;
  output?: unknown;
  latency_ms?: number;
}

export interface PlanDefinition {
  request_id?: string;
  goal?: string;
  primary_route?: string;
  steps?: PlanStep[];
  assumptions?: string[];
}

// Matches actual backend shape: { plan: { steps: [...] }, step_results: [], shadow_mode: true }
export interface PlanResult {
  plan?: PlanDefinition;
  step_results?: PlanStepResult[];
  shadow_mode?: boolean;
  // legacy / computed fields kept for compatibility
  mode?: "shadow" | "execution";
  plan_id?: string;
  steps?: PlanStep[];
  status?: string;
}

// ── Query Plan (action.kind = inspect_schema / database_analysis) ──
export interface QueryPlanDimension {
  alias?: string;
  column?: string;
  type?: string;
}

export interface QueryPlanMeasure {
  alias?: string;
  column?: string;
  aggregation?: string;
}

export interface QueryPlan {
  schema_version?: string;
  status?: "planned" | "blocked" | "clarification_required";
  proposed_sql?: string;
  assumptions?: string[];
  dimensions?: QueryPlanDimension[];
  measures?: QueryPlanMeasure[];
  refusal_reason?: string | null;
}

// ── Agent Result (AgentLoop output) ───────────────────────────────
export interface AgentResult {
  run_id?: string;
  intent?: IntentResult;
  action?: {
    kind?: string;
    reason?: string;
    payload?: Record<string, unknown>;
  };
  final_answer?: {
    content?: string;
    next_action?: string;
    assumptions?: string[];
  };
  // P8
  plan_shadow?: PlanResult;
  plan_execution?: PlanResult;
  query_plan?: QueryPlan;
  // P9
  eval_result?: EvalResult;
  // P10
  memory_summary?: string | MemorySummary;
  // Paths
  status_path?: string;
  events_path?: string;
  audit_path?: string;
  // Suggestions
  suggested_queries?: string[];
  // Error
  error?: string;
  error_code?: string;
  raw?: string;
  [key: string]: unknown;
}

// ── Status / Run Monitor ───────────────────────────────────────────
export interface RunEvent {
  event: string;
  ts?: string;
  detail?: unknown;
}

export interface RunStep {
  step: string;
  status?: string;
  result?: unknown;
  latency_ms?: number;
}

export interface RunEntry {
  run_id?: string;
  status?: RunState;
  started_at?: string;
  completed_at?: string;
  intent?: string;
  action?: string;
  events?: RunEvent[];
  steps?: RunStep[];
  [key: string]: unknown;
}

export interface StatusData {
  runs?: RunEntry[];
  latest?: RunEntry;
  error?: string;
  raw?: string;
}

// ── Audit ──────────────────────────────────────────────────────────
export interface AuditEntry {
  _line: number;
  event?: string;
  run_id?: string;
  ts?: string;
  timestamp?: string;
  // P9 answer_evaluated fields
  eval_result?: EvalResult;
  // P10 session_summarized fields
  summary?: {
    session_id?: string;
    total_runs?: number;
    failed_runs?: number;
    success_rate?: number;
    failure_patterns?: string[];
    proposed_memory_paths?: string[];
  };
  [key: string]: unknown;
}

export interface AuditData {
  entries: AuditEntry[];
  total: number;
  eventTypes: string[];
  error?: string;
}

// ── Workflow ───────────────────────────────────────────────────────
export interface WorkflowStepDef {
  id: string;
  label: string;
  description: string;
}

// Actual backend step shape
export interface WorkflowStep {
  step_id?: string;
  name?: string;         // legacy
  state?: string;        // backend field
  status?: string;       // legacy
  system?: string;
  action?: string;
  details?: Record<string, unknown>;
  result?: unknown;
}

export interface TrustedCheckpoint {
  schema_version?: string;
  identity?: string;
  hash?: string;
  run_id?: string;
  workflow_id?: string;
  template_id?: string;
  template_version?: number;
  period?: string;
  record_ids?: string[];
}

export interface ReviewPacket {
  workflow_id?: string;
  run_id?: string;
  template_id?: string;
  template_version?: number;
  period?: string;
  affected_records?: string[];
  failed_rules?: unknown[];
  system_evidence?: Record<string, unknown>;
  proposed_resolution?: string;
  allowed_actions?: string[];
  approval_impact?: string;
  trusted_checkpoint?: TrustedCheckpoint;
}

export interface HumanGate {
  required?: boolean;
  state?: "checkpoint_required" | "paused" | "not_required" | "not_available";
  review_packet?: ReviewPacket;
}

export interface WorkflowResult {
  run_id?: string;
  state?: string;
  status?: string;       // legacy compat
  steps?: WorkflowStep[];
  current_step?: string;
  human_gate?: HumanGate;
  reconciliation?: Record<string, unknown>;
  target_load?: Record<string, unknown>;
  human_decision?: Record<string, unknown>;
  template?: Record<string, unknown>;
  period?: string;
  request_text?: string;
  // unsupported_workflow
  supported_workflows?: string[];
  // error
  error?: string;
  error_code?: string;
  // legacy
  requires_approval?: boolean;
  approval_context?: { step: string; prompt: string; data?: unknown };
  raw?: string;
  [key: string]: unknown;
}

export interface StructuredError {
  code: string;
  message: string;
  step?: string;
  supported?: string[];
  isKnown: boolean;
}

// ── Tacit Knowledge ────────────────────────────────────────────────
export interface CorrectionDiff {
  removed?: string[];
  inserted?: string[];
  tone_change?: string | null;
  terminology_changes?: string[];
  semantic_type?: string;
}

export interface ConsultationEntry {
  person: string;
  reason: string;
}

export interface VerificationEpisode {
  episode_id: string;
  timestamp: string;
  session_id: string;
  ai_output: string;
  final_resolution: "human_override" | "human_approved" | "human_rejected" | "escalated";
  human_revision?: string | null;
  correction_diff?: CorrectionDiff | null;
  confidence_before?: number | null;
  confidence_after?: number | null;
  uncertainty_regions?: string[];
  consultation_trace?: ConsultationEntry[];
  reason_tags?: string[];
  reflection_summary?: string | null;
  schema_version?: string;
}

export interface TacitSignal {
  episode_id: string;
  suspected_heuristics: string[];
  source_tags: string[];
  source_semantic_type?: string | null;
}

export interface ReflectionResult {
  episode_id: string;
  failure_analysis: string;
  missing_context: string;
  extracted_heuristics: string[];
  policy_proposal: string;
}

export interface TacitEpisodesResponse {
  episodes: VerificationEpisode[];
  error?: string;
}

export interface TacitHeuristicsResponse {
  heuristics: string[];
  error?: string;
}

export interface TacitReflectResponse extends ReflectionResult {
  error?: string;
}

// ── Schema Inspector ───────────────────────────────────────────────
export interface TableEntry {
  name: string;
  score?: number;
  columns?: string[];
  description?: string;
  row_count?: number;
}

export interface GlossaryMatch {
  term: string;
  definition?: string;
  score?: number;
}

export interface SchemaContext {
  selected_tables?: TableEntry[];
  glossary_matches?: GlossaryMatch[];
  query?: string;
  schema_name?: string;
  inspected_at?: string;
  total_tables?: number;
  error?: string;
}
