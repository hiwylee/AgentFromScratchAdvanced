"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send, Bot, User, Loader2, ChevronDown, ChevronRight, Zap,
  CheckCircle2, XCircle, AlertCircle, HelpCircle, MemoryStick,
  GitBranch, Database,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import type { AgentResult, EvalResult, IntentResult, PlanResult, QueryPlan } from "@/lib/types";

// ── Helpers ────────────────────────────────────────────────────────

function uuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback for non-secure contexts (HTTP dev access via IP)
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function asObj(v: unknown): Record<string, unknown> | null {
  return v != null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function asStr(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v === "string") return v || null;
  if (typeof v === "object") return null;
  return String(v);
}

// ── Collapsible JSON block ─────────────────────────────────────────

function JsonBlock({ data }: { data: unknown }) {
  const [collapsed, setCollapsed] = useState(true);
  return (
    <div className="mt-3 rounded-md border border-border/50 overflow-hidden">
      <button
        type="button"
        aria-label="Toggle raw JSON"
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-mono text-muted-foreground hover:text-foreground bg-secondary/30 hover:bg-secondary/50 transition-colors text-left"
      >
        {collapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        Raw JSON
      </button>
      {!collapsed && (
        <pre className="px-3 py-2 text-xs font-mono text-cyan-300/80 bg-black/30 overflow-x-auto leading-relaxed">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── P9: EvalBadge ──────────────────────────────────────────────────

const EVAL_CHECKS = [
  "비어있지 않음",
  "오류 접두사 없음",
  "거부만 아님",
  "어휘 겹침",
  "최소 길이",
];

function EvalBadge({ evalResult }: { evalResult: EvalResult }) {
  const [open, setOpen] = useState(false);
  const checks = evalResult.checks ?? [];
  const passed = evalResult.passed;
  const passCount = checks.length > 0
    ? checks.filter((c) => c.passed).length
    : (passed ? EVAL_CHECKS.length : 0);
  const total = checks.length > 0 ? checks.length : EVAL_CHECKS.length;

  return (
    <div className="glass rounded-md px-3 py-2 space-y-1.5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Toggle eval details"
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="text-xs uppercase tracking-widest text-muted-foreground">Eval</div>
        <div className="flex items-center gap-1.5">
          <span className={`text-xs font-mono px-2 py-0.5 rounded-full border ${
            passed
              ? "text-[oklch(0.75_0.15_145)] bg-[oklch(0.60_0.18_145/0.1)] border-[oklch(0.60_0.18_145/0.3)]"
              : "text-[oklch(0.70_0.20_25)] bg-[oklch(0.55_0.22_25/0.1)] border-[oklch(0.55_0.22_25/0.3)]"
          }`}>
            {checks.length > 0 ? `${passCount}/${total} ` : ""}{passed ? "✓ PASS" : "✗ FAIL"}
          </span>
          {open ? <ChevronDown className="w-3 h-3 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 text-muted-foreground" />}
        </div>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-1 space-y-1">
              {checks.length > 0 ? (
                checks.map((c, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    {c.passed
                      ? <CheckCircle2 className="w-3 h-3 text-[oklch(0.70_0.18_145)] flex-shrink-0" />
                      : <XCircle className="w-3 h-3 text-[oklch(0.65_0.22_25)] flex-shrink-0" />
                    }
                    <span className="font-mono text-foreground/80">{c.name}</span>
                    {c.detail && <span className="text-muted-foreground">{c.detail}</span>}
                  </div>
                ))
              ) : (
                EVAL_CHECKS.map((name, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    {passed
                      ? <CheckCircle2 className="w-3 h-3 text-[oklch(0.70_0.18_145)] flex-shrink-0" />
                      : <XCircle className="w-3 h-3 text-[oklch(0.65_0.22_25)] flex-shrink-0" />
                    }
                    <span className="font-mono text-foreground/80">{name}</span>
                  </div>
                ))
              )}
              {evalResult.score != null && (
                <div className="text-xs text-muted-foreground pt-1 font-mono">
                  score: {evalResult.score.toFixed(3)}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Intent with confidence + alternatives ─────────────────────────

function confidenceColor(c: number): string {
  if (c >= 0.85) return "text-[oklch(0.70_0.18_145)]";
  if (c >= 0.65) return "text-[oklch(0.82_0.16_80)]";
  return "text-[oklch(0.65_0.22_25)]";
}

function IntentMeta({ intent }: { intent: IntentResult }) {
  return (
    <div className="glass rounded-md px-3 py-2 space-y-1.5">
      <div className="text-xs uppercase tracking-widest text-muted-foreground">Intent</div>
      <div className="flex flex-wrap gap-2 items-center">
        {intent.intent_type && (
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-secondary/60 text-cyan-300">
            {intent.intent_type}
          </span>
        )}
        {intent.task_type && (
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-secondary/60 text-muted-foreground">
            {intent.task_type}
          </span>
        )}
        {intent.safety_level && (
          <span className="text-xs font-mono px-2 py-0.5 rounded bg-secondary/60 text-yellow-400/80">
            {intent.safety_level}
          </span>
        )}
        {intent.confidence != null && (
          <span className={`text-xs font-mono ${confidenceColor(intent.confidence)}`}>
            {(intent.confidence * 100).toFixed(0)}%
          </span>
        )}
      </div>
      {intent.alternatives && intent.alternatives.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs text-muted-foreground/60">대안:</span>
          {intent.alternatives.map((alt, i) => (
            <span key={i} className="text-xs font-mono text-muted-foreground/70 bg-secondary/30 px-1.5 py-0.5 rounded">
              {alt.intent_type} <span className="text-muted-foreground/50">({(alt.confidence * 100).toFixed(0)}%)</span>
            </span>
          ))}
        </div>
      )}
      {intent.next_action && intent.next_action !== "none" && (
        <div className="text-xs text-muted-foreground">
          Next: <span className="text-foreground/70">{intent.next_action}</span>
        </div>
      )}
    </div>
  );
}

// ── P8: PlanBlock ─────────────────────────────────────────────────

function PlanBlock({ plan }: { plan: PlanResult }) {
  const [open, setOpen] = useState(false);
  // Backend: plan_shadow = { plan: { steps: [...] }, shadow_mode: true }
  const steps = plan.plan?.steps ?? plan.steps ?? [];
  const isLive = !plan.shadow_mode && plan.mode === "execution";
  const mode = isLive ? "live" : "dry-run";
  const modeColor = isLive
    ? "text-[oklch(0.75_0.15_145)] border-[oklch(0.60_0.18_145/0.4)] bg-[oklch(0.60_0.18_145/0.08)]"
    : "text-[oklch(0.65_0.22_200)] border-[oklch(0.65_0.22_200/0.4)] bg-[oklch(0.65_0.22_200/0.08)]";

  return (
    <div className="glass rounded-md px-3 py-2 space-y-1.5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Toggle plan details"
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2">
          <GitBranch className="w-3 h-3 text-muted-foreground" />
          <div className="text-xs uppercase tracking-widest text-muted-foreground">Plan</div>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${modeColor}`}>
            {mode}
          </span>
          <span className="text-xs font-mono text-muted-foreground">{steps.length} steps</span>
          {open ? <ChevronDown className="w-3 h-3 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 text-muted-foreground" />}
        </div>
      </button>

      <AnimatePresence>
        {open && steps.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-1 space-y-1.5">
              {steps.map((step, i) => {
                const v = step.verification;
                const name = step.name ?? step.step_id ?? `step-${i + 1}`;
                const status = step.status ?? (v?.passed === false ? "failed" : "completed");
                return (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className="flex-shrink-0 w-4 text-center font-mono text-muted-foreground/50">{i + 1}.</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="font-mono text-foreground/80 truncate">{name}</span>
                        {status === "completed" && <CheckCircle2 className="w-3 h-3 text-[oklch(0.70_0.18_145)] flex-shrink-0" />}
                        {status === "failed" && <XCircle className="w-3 h-3 text-[oklch(0.65_0.22_25)] flex-shrink-0" />}
                        {status === "skipped" && <span className="text-[10px] text-muted-foreground/50 font-mono">skipped</span>}
                        {status === "running" && <Loader2 className="w-3 h-3 animate-spin text-[oklch(0.65_0.22_200)] flex-shrink-0" />}
                        {step.latency_ms != null && (
                          <span className="text-[10px] font-mono text-muted-foreground/50">{step.latency_ms}ms</span>
                        )}
                      </div>
                      {v && !v.passed && v.failure_reason && (
                        <div className="text-[10px] text-[oklch(0.65_0.22_25)] font-mono mt-0.5 truncate">
                          {v.failure_reason}
                          {v.suggested_action && ` → ${v.suggested_action}`}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Query Plan block ──────────────────────────────────────────────

function QueryPlanBlock({ queryPlan }: { queryPlan: QueryPlan }) {
  const [open, setOpen] = useState(false);
  const statusColor =
    queryPlan.status === "planned"
      ? "text-[oklch(0.75_0.15_145)] border-[oklch(0.60_0.18_145/0.4)] bg-[oklch(0.60_0.18_145/0.08)]"
      : queryPlan.status === "blocked"
      ? "text-[oklch(0.65_0.22_25)] border-[oklch(0.65_0.22_25/0.4)] bg-[oklch(0.55_0.22_25/0.08)]"
      : "text-[oklch(0.82_0.16_80)] border-[oklch(0.82_0.16_80/0.4)] bg-[oklch(0.80_0.18_80/0.08)]";

  return (
    <div className="glass rounded-md px-3 py-2 space-y-1.5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Toggle query plan"
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2">
          <Database className="w-3 h-3 text-muted-foreground" />
          <div className="text-xs uppercase tracking-widest text-muted-foreground">Query Plan</div>
        </div>
        <div className="flex items-center gap-1.5">
          {queryPlan.status && (
            <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${statusColor}`}>
              {queryPlan.status}
            </span>
          )}
          {open ? <ChevronDown className="w-3 h-3 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 text-muted-foreground" />}
        </div>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-1 space-y-2">
              {queryPlan.proposed_sql && (
                <div>
                  <div className="text-[10px] font-mono text-muted-foreground/60 mb-1">Proposed SQL</div>
                  <pre className="text-xs font-mono text-cyan-300/80 bg-black/20 px-3 py-2 rounded border border-border/20 overflow-x-auto whitespace-pre-wrap">
                    {queryPlan.proposed_sql}
                  </pre>
                </div>
              )}
              {queryPlan.refusal_reason && (
                <div className="text-xs text-[oklch(0.65_0.22_25)] font-mono">
                  {queryPlan.refusal_reason}
                </div>
              )}
              {queryPlan.assumptions && queryPlan.assumptions.length > 0 && (
                <div>
                  <div className="text-[10px] font-mono text-muted-foreground/60 mb-0.5">Assumptions</div>
                  {queryPlan.assumptions.map((a, i) => (
                    <div key={i} className="text-xs text-muted-foreground">· {a}</div>
                  ))}
                </div>
              )}
              {((queryPlan.dimensions && queryPlan.dimensions.length > 0) ||
                (queryPlan.measures && queryPlan.measures.length > 0)) && (
                <div>
                  <div className="text-[10px] font-mono text-muted-foreground/60 mb-1">Dimensions / Measures</div>
                  <div className="flex flex-wrap gap-1.5">
                    {queryPlan.dimensions?.map((d, i) => (
                      <span key={i} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[oklch(0.65_0.22_200/0.1)] border border-[oklch(0.65_0.22_200/0.3)] text-[oklch(0.75_0.18_200)]">
                        {d.alias ?? d.column}
                      </span>
                    ))}
                    {queryPlan.measures?.map((m, i) => (
                      <span key={i} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[oklch(0.80_0.18_80/0.1)] border border-[oklch(0.82_0.16_80/0.3)] text-[oklch(0.82_0.16_80)]">
                        {m.alias ?? m.column}{m.aggregation ? `(${m.aggregation})` : ""}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── P10: MemorySummaryBlock ────────────────────────────────────────

function MemorySummaryBlock({ memorySummary }: { memorySummary: string | Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const isString = typeof memorySummary === "string";
  const records = !isString ? ((memorySummary as Record<string, unknown>).records as unknown[]) : null;
  const totalInjected = !isString
    ? (memorySummary as Record<string, unknown>).total_injected as number | undefined
    : null;

  return (
    <div className="glass rounded-md px-3 py-2 space-y-1.5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Toggle memory details"
        className="w-full flex items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2">
          <MemoryStick className="w-3 h-3 text-[oklch(0.75_0.18_290)]" />
          <div className="text-xs uppercase tracking-widest text-muted-foreground">Memory</div>
        </div>
        <div className="flex items-center gap-1.5">
          {totalInjected != null && (
            <span className="text-xs font-mono text-[oklch(0.75_0.18_290)]">{totalInjected} injected</span>
          )}
          {open ? <ChevronDown className="w-3 h-3 text-muted-foreground" /> : <ChevronRight className="w-3 h-3 text-muted-foreground" />}
        </div>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-1">
              {isString ? (
                <div className="text-xs text-muted-foreground leading-relaxed">{memorySummary}</div>
              ) : records && Array.isArray(records) && records.length > 0 ? (
                <div className="space-y-1">
                  {(records as Record<string, unknown>[]).map((r, i) => (
                    <div key={i} className="text-xs font-mono text-[oklch(0.75_0.18_290)]/80 truncate">
                      · {asStr(r.key) ?? asStr(r.memory_id) ?? `record-${i}`}
                      {typeof r.relevance === "number" && (
                        <span className="text-muted-foreground/50 ml-1">({(r.relevance * 100).toFixed(0)}%)</span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <pre className="text-xs font-mono text-cyan-300/60 overflow-x-auto">
                  {JSON.stringify(memorySummary, null, 2)}
                </pre>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Clarification block ───────────────────────────────────────────

function ClarificationBlock({
  prompt,
  onSelect,
}: {
  prompt: string;
  onSelect: (answer: string) => void;
}) {
  const [custom, setCustom] = useState("");
  return (
    <div className="mt-2 rounded-md border border-[oklch(0.82_0.16_80/0.4)] bg-[oklch(0.70_0.18_80/0.06)] p-3 space-y-2">
      <div className="flex items-center gap-2">
        <HelpCircle className="w-3.5 h-3.5 text-[oklch(0.82_0.16_80)]" />
        <span className="text-xs uppercase tracking-widest text-[oklch(0.82_0.16_80)]">명확화 필요</span>
      </div>
      <p className="text-sm text-foreground leading-relaxed">{prompt}</p>
      <div className="flex gap-2 flex-wrap">
        <input
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && custom.trim()) { onSelect(custom.trim()); setCustom(""); }}}
          placeholder="직접 입력…"
          className="flex-1 min-w-0 text-xs h-7 px-2 rounded border border-border/40 bg-input/40 font-mono placeholder:text-muted-foreground/40 focus:outline-none focus:border-primary/50"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-label="전송"
          className="text-xs h-7 px-3"
          onClick={() => { if (custom.trim()) { onSelect(custom.trim()); setCustom(""); }}}
        >
          전송
        </Button>
      </div>
    </div>
  );
}

// ── ErrorCard ─────────────────────────────────────────────────────

function ErrorCard({ error }: { error: string }) {
  const isLong = error.length > 120;
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-2 rounded-md border border-destructive/40 bg-destructive/5 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-destructive/20">
        <AlertCircle className="w-3.5 h-3.5 text-destructive/80" />
        <span className="text-xs uppercase tracking-widest text-destructive/80 font-semibold">Error</span>
      </div>
      <pre className={`px-3 py-2 text-xs font-mono text-destructive/90 whitespace-pre-wrap break-all leading-relaxed ${!expanded && isLong ? "max-h-24 overflow-hidden" : ""}`}>
        {error}
      </pre>
      {isLong && (
        <button
          type="button"
          aria-label="Toggle full error"
          onClick={() => setExpanded((e) => !e)}
          className="w-full text-center text-xs text-muted-foreground hover:text-foreground py-1 border-t border-destructive/20 transition-colors"
        >
          {expanded ? "Show less" : "Show full error"}
        </button>
      )}
    </div>
  );
}

// ── ResultCard ────────────────────────────────────────────────────

function ResultCard({
  result,
  onClarify,
}: {
  result: AgentResult;
  onClarify?: (text: string) => void;
}) {
  const intent = result.intent;
  const action = asObj(result.action as unknown);
  const finalAnswer = result.final_answer;
  const runId = result.run_id;

  // P8: prefer plan_execution if present (real run), fall back to plan_shadow (dry-run)
  const planExecution = result.plan_execution;
  const planShadow = result.plan_shadow;
  const activePlan = planExecution ?? planShadow;

  const queryPlan = result.query_plan;
  const evalResult = result.eval_result;
  const memorySummary = result.memory_summary;
  const needsClarification = intent?.needs_clarification;
  const clarificationPrompt = intent?.clarification_prompt;

  return (
    <div className="space-y-2 mt-2">
      {/* Clarification takes precedence */}
      {needsClarification && clarificationPrompt && onClarify && (
        <ClarificationBlock prompt={clarificationPrompt} onSelect={onClarify} />
      )}

      {/* Intent */}
      {intent && <IntentMeta intent={intent} />}

      {/* Action */}
      {action && (
        <div className="glass rounded-md px-3 py-2 space-y-1">
          <div className="text-xs uppercase tracking-widest text-muted-foreground">Action</div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono px-2 py-0.5 rounded bg-[oklch(0.65_0.22_200/0.15)] border border-[oklch(0.65_0.22_200/0.3)] text-[oklch(0.75_0.18_200)]">
              {asStr(action.kind) ?? "—"}
            </span>
          </div>
          {asStr(action.reason) && (
            <div className="text-sm text-muted-foreground leading-relaxed">{asStr(action.reason)}</div>
          )}
        </div>
      )}

      {/* Final Answer */}
      {finalAnswer && asStr(finalAnswer.content) && (
        <div className="rounded-md px-3 py-2 bg-[oklch(0.72_0.19_280/0.1)] border border-[oklch(0.72_0.19_280/0.25)] space-y-1.5">
          <div className="text-xs uppercase tracking-widest text-[oklch(0.72_0.19_280)]">Final Answer</div>
          <div className="text-base text-foreground leading-relaxed">{asStr(finalAnswer.content)}</div>
          {finalAnswer.next_action && finalAnswer.next_action !== "none" && (
            <div className="text-xs text-muted-foreground">
              Next: <span className="text-foreground/70">{finalAnswer.next_action}</span>
            </div>
          )}
          {Array.isArray(finalAnswer.assumptions) && finalAnswer.assumptions.length > 0 && (
            <ul className="text-sm text-muted-foreground space-y-0.5 list-disc list-inside">
              {finalAnswer.assumptions.map((a, i) => (
                <li key={i}>{String(a)}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Query Plan */}
      {queryPlan && <QueryPlanBlock queryPlan={queryPlan} />}

      {/* P9: Eval */}
      {evalResult && <EvalBadge evalResult={evalResult} />}

      {/* P8: Plan */}
      {activePlan && <PlanBlock plan={activePlan} />}

      {/* P10: Memory */}
      {memorySummary && (
        <MemorySummaryBlock memorySummary={memorySummary as string | Record<string, unknown>} />
      )}

      {/* Run ID + Raw */}
      {runId && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-muted-foreground/60">run: {runId}</span>
        </div>
      )}

      <JsonBlock data={result} />
    </div>
  );
}

// ── Suggested queries ─────────────────────────────────────────────

const SUGGESTED = [
  "What tables are available in the Oracle ADW schema?",
  "Show me the top 10 customers by revenue",
  "Run a workflow for Q1 sales reconciliation",
  "Check the status of the latest agent run",
];

function getSuggestionsFromResult(result?: AgentResult): string[] {
  if (!result) return [];
  const suggestions: string[] = [];
  const nextAction = result.final_answer?.next_action ?? result.intent?.next_action;
  if (nextAction && typeof nextAction === "string" && nextAction.trim()) {
    suggestions.push(nextAction.trim());
  }
  if (Array.isArray(result.suggested_queries)) {
    for (const s of result.suggested_queries) {
      if (typeof s === "string" && s.trim()) suggestions.push(s.trim());
    }
  }
  return [...new Set(suggestions)].slice(0, 4);
}

function DynamicSuggestions({
  result,
  onSelect,
}: {
  result?: AgentResult;
  onSelect: (query: string) => void;
}) {
  const fromApi = getSuggestionsFromResult(result);
  const items = fromApi.length > 0 ? fromApi : SUGGESTED.slice(0, 4);
  const isApi = fromApi.length > 0;

  return (
    <div className="flex flex-col gap-2 mt-3">
      <div className="text-[10px] font-mono text-muted-foreground/50 uppercase tracking-widest">
        {isApi ? "Agent 제안" : "예시 질문"}
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((s) => (
          <button
            key={s}
            type="button"
            aria-label={`Ask: ${s}`}
            onClick={() => onSelect(s)}
            className="text-sm px-3 py-1.5 rounded-lg glass border border-border/40 hover:border-primary/40 text-muted-foreground hover:text-foreground transition-all duration-150 text-left"
          >
            {s.length > 60 ? s.slice(0, 60) + "…" : s}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Message type ──────────────────────────────────────────────────

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: AgentResult;
  error?: string;
  ts: number;
}

// ── ChatPage ──────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(query?: string) {
    const text = (query ?? input).trim();
    if (!text || loading) return;

    const userMsg: Message = {
      id: uuid(),
      role: "user",
      content: text,
      ts: Date.now(),
    };

    setMessages((m) => [...m, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/agent/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text }),
      });
      const data: AgentResult = await res.json();

      const finalAnswerContent =
        typeof data.final_answer?.content === "string"
          ? data.final_answer.content
          : (data.raw as string | undefined) ?? "";

      const assistantMsg: Message = {
        id: uuid(),
        role: "assistant",
        content: finalAnswerContent,
        result: res.ok ? data : undefined,
        error: !res.ok ? ((data.error as string | undefined) ?? "Unknown error") : undefined,
        ts: Date.now(),
      };
      setMessages((m) => [...m, assistantMsg]);
    } catch (err) {
      toast.error("Failed to reach agent API");
      const errMsg: Message = {
        id: uuid(),
        role: "assistant",
        content: "Failed to connect to the agent backend.",
        error: err instanceof Error ? err.message : String(err),
        ts: Date.now(),
      };
      setMessages((m) => [...m, errMsg]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border/50 flex items-center gap-3 bg-background/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[oklch(0.72_0.19_280)] to-[oklch(0.65_0.22_200)] flex items-center justify-center glow-purple">
          <Bot className="w-4 h-4 text-white" />
        </div>
        <div>
          <h1 className="text-base font-semibold text-foreground">Agent Chat</h1>
          <p className="text-sm text-muted-foreground">Natural language interface to AgentFromScratch</p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        <AnimatePresence initial={false}>
          {messages.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center h-full min-h-[300px] gap-6"
            >
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[oklch(0.72_0.19_280)] to-[oklch(0.65_0.22_200)] flex items-center justify-center glow-purple">
                <Zap className="w-8 h-8 text-white" />
              </div>
              <div className="text-center">
                <h2 className="text-xl font-semibold gradient-text mb-2">AgentFromScratch Console</h2>
                <p className="text-base text-muted-foreground max-w-xs">
                  Ask questions in natural language. The agent will interpret your intent, select actions, and return structured results.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
                {SUGGESTED.map((s) => (
                  <button
                    key={s}
                    type="button"
                    aria-label={`Ask: ${s}`}
                    onClick={() => handleSubmit(s)}
                    className="text-left text-sm px-3 py-3 rounded-lg glass border border-border/40 hover:border-primary/40 text-muted-foreground hover:text-foreground transition-all duration-150"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </motion.div>
          )}

          {messages.map((msg, idx) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role === "assistant" && (
                <div className="w-7 h-7 rounded-md bg-gradient-to-br from-[oklch(0.72_0.19_280)] to-[oklch(0.65_0.22_200)] flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Bot className="w-3.5 h-3.5 text-white" />
                </div>
              )}
              <div className={`max-w-[75%] ${msg.role === "user" ? "items-end" : "items-start"} flex flex-col`}>
                <div
                  className={`rounded-xl px-4 py-3 text-base leading-relaxed ${
                    msg.role === "user"
                      ? "bg-primary/15 border border-primary/25 text-foreground"
                      : "glass text-foreground"
                  }`}
                >
                  {msg.content}
                  {msg.error && <ErrorCard error={msg.error} />}
                  {msg.result && !msg.error && (
                    <ResultCard
                      result={msg.result}
                      onClarify={(answer) => handleSubmit(answer)}
                    />
                  )}
                </div>
                <span className="text-xs text-muted-foreground/50 mt-1 px-1 font-mono">
                  {new Date(msg.ts).toLocaleTimeString()}
                </span>
                {msg.role === "assistant" && idx === messages.length - 1 && !loading && (
                  <DynamicSuggestions result={msg.result} onSelect={handleSubmit} />
                )}
              </div>
              {msg.role === "user" && (
                <div className="w-7 h-7 rounded-md bg-secondary flex items-center justify-center flex-shrink-0 mt-0.5">
                  <User className="w-3.5 h-3.5 text-muted-foreground" />
                </div>
              )}
            </motion.div>
          ))}

          {loading && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex gap-3"
            >
              <div className="w-7 h-7 rounded-md bg-gradient-to-br from-[oklch(0.72_0.19_280)] to-[oklch(0.65_0.22_200)] flex items-center justify-center flex-shrink-0 mt-0.5">
                <Bot className="w-3.5 h-3.5 text-white" />
              </div>
              <div className="glass rounded-xl px-4 py-3 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
                <span className="text-base text-muted-foreground font-mono">Agent processing</span>
                <span className="cursor-blink text-primary">_</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 pb-4 pt-2 border-t border-border/50 bg-background/60 backdrop-blur-sm">
        <div className="flex gap-2 items-end max-w-4xl mx-auto">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the agent anything… (Enter to send, Shift+Enter for newline)"
            className="min-h-[48px] max-h-[160px] resize-none bg-input/50 border-border/60 focus:border-primary/50 font-mono text-sm placeholder:text-muted-foreground/40"
            rows={1}
          />
          <Button
            onClick={() => handleSubmit()}
            disabled={!input.trim() || loading}
            size="icon"
            aria-label={loading ? "Agent processing" : "Send message"}
            className="h-12 w-12 flex-shrink-0 bg-primary hover:bg-primary/80 glow-purple transition-all"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}
