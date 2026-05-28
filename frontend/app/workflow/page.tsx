"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { GitBranch, Play, Loader2, CheckCircle2, Circle, AlertCircle, Clock, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { parseError } from "@/lib/errors";
import type { WorkflowResult, HumanGate } from "@/lib/types";

const STEP_EXAMPLES = [
  "이번달 특허자산 대체 등록 진행해줘",
  "금월 특허 자산 대체 등록 워크플로우 실행",
  "특허자산 대체 등록 처리 시작해줘",
];

type StepStatus = "pending" | "running" | "completed" | "failed" | "skipped" | "paused";

function normalizeStatus(s?: string): StepStatus {
  if (!s) return "pending";
  if (s === "paused" || s === "checkpoint_required") return "paused";
  if (["running", "completed", "failed", "skipped", "pending"].includes(s)) return s as StepStatus;
  return "pending";
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "completed") return <CheckCircle2 className="w-4 h-4 text-[oklch(0.70_0.18_145)]" />;
  if (status === "running") return <Loader2 className="w-4 h-4 text-[oklch(0.65_0.22_200)] animate-spin" />;
  if (status === "failed") return <AlertCircle className="w-4 h-4 text-[oklch(0.65_0.22_25)]" />;
  if (status === "paused") return <Clock className="w-4 h-4 text-[oklch(0.80_0.18_80)] animate-pulse" />;
  if (status === "skipped") return <Clock className="w-4 h-4 text-muted-foreground/40" />;
  return <Circle className="w-4 h-4 text-muted-foreground/60" />;
}

function stepBorderColor(status: StepStatus): string {
  if (status === "completed") return "border-[oklch(0.70_0.18_145)] bg-[oklch(0.60_0.18_145/0.15)]";
  if (status === "running") return "border-[oklch(0.65_0.22_200)] bg-[oklch(0.55_0.22_200/0.15)]";
  if (status === "failed") return "border-[oklch(0.65_0.22_25)] bg-[oklch(0.55_0.22_25/0.15)]";
  if (status === "paused") return "border-[oklch(0.80_0.18_80)] bg-[oklch(0.70_0.18_80/0.15)]";
  return "border-border/50 bg-secondary/30";
}

function stepTextColor(status: StepStatus): string {
  if (status === "completed") return "text-[oklch(0.70_0.18_145)]";
  if (status === "running") return "text-[oklch(0.65_0.22_200)]";
  if (status === "failed") return "text-[oklch(0.65_0.22_25)]";
  if (status === "paused") return "text-[oklch(0.80_0.18_80)]";
  return "text-foreground/80";
}

// ── HumanDecisionGate ─────────────────────────────────────────────

function HumanDecisionGate({
  runId,
  humanGate,
  onDecision,
}: {
  runId: string;
  humanGate: HumanGate;
  onDecision: (result: WorkflowResult) => void;
}) {
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [confidence, setConfidence] = useState<number>(0.8);
  const [reasonTags, setReasonTags] = useState("");
  const [uncertaintyRegions, setUncertaintyRegions] = useState("");
  const [consultPerson, setConsultPerson] = useState("");
  const [consultReason, setConsultReason] = useState("");
  const [consultList, setConsultList] = useState<{ person: string; reason: string }[]>([]);
  const [submitting, setSubmitting] = useState<"approve" | "reject" | "skip" | null>(null);
  const [packetExpanded, setPacketExpanded] = useState(false);
  const [tacitExpanded, setTacitExpanded] = useState(false);

  const packet = humanGate.review_packet;
  const checkpoint = packet?.trusted_checkpoint;
  const busy = submitting !== null;

  async function submit(decision: "approve" | "reject" | "skip") {
    if (busy) return;
    setSubmitting(decision);
    try {
      const res = await fetch("/api/agent/workflow/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: runId,
          decision,
          actor: actor.trim() || undefined,
          reason: reason.trim() || undefined,
          reasoning: reasoning.trim() || undefined,
          confidence,
          reason_tags: reasonTags.split(",").map((t) => t.trim()).filter(Boolean),
          uncertainty_regions: uncertaintyRegions.split(",").map((t) => t.trim()).filter(Boolean),
          consultation_trace: consultList,
        }),
      });
      const data: WorkflowResult = await res.json();
      if (!res.ok) {
        toast.error(`Decision failed: ${(data as Record<string, unknown>).error ?? res.statusText}`);
        return;
      }
      toast.success(`Decision submitted: ${decision}`);
      onDecision(data);
    } catch (err) {
      toast.error(`Failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="rounded-xl border bg-secondary/10 backdrop-blur-sm p-5 space-y-4"
      style={{ borderColor: "oklch(0.80 0.18 80 / 0.6)" }}
    >
      <div className="flex items-center gap-2">
        <span
          className="text-[10px] px-2 py-0.5 rounded-full border font-mono font-semibold tracking-widest animate-pulse"
          style={{
            borderColor: "oklch(0.80 0.18 80 / 0.5)",
            color: "oklch(0.80 0.18 80)",
            backgroundColor: "oklch(0.70 0.18 80 / 0.1)",
          }}
        >
          CHECKPOINT
        </span>
        <span className="font-mono text-sm" style={{ color: "oklch(0.80 0.18 80)" }}>
          pre_load_checkpoint
        </span>
      </div>

      {/* Affected records */}
      {packet?.affected_records && packet.affected_records.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground/70 font-mono uppercase tracking-widest">Affected Records</div>
          <div className="flex flex-wrap gap-1.5">
            {packet.affected_records.map((id) => (
              <span key={id} className="text-xs font-mono px-2 py-0.5 rounded bg-secondary/60 text-cyan-300/80">
                {id}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Proposed resolution */}
      {packet?.proposed_resolution && (
        <p className="text-sm text-foreground/80 leading-relaxed">{packet.proposed_resolution}</p>
      )}

      {/* Approval impact */}
      {packet?.approval_impact && (
        <p className="text-sm text-muted-foreground leading-relaxed">{packet.approval_impact}</p>
      )}

      {/* Review packet details */}
      {packet && (
        <div className="space-y-1">
          <button
            type="button"
            onClick={() => setPacketExpanded((v) => !v)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Toggle review packet"
          >
            {packetExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Review packet
          </button>
          {packetExpanded && (
            <pre className="text-xs font-mono text-cyan-300/70 bg-black/20 px-3 py-2 rounded border border-border/20 overflow-x-auto">
              {JSON.stringify(packet, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Checkpoint identity */}
      {checkpoint?.identity && (
        <div className="rounded-md border border-border/30 bg-black/20 px-3 py-2 space-y-1">
          <div className="text-[10px] font-mono text-muted-foreground/60 uppercase tracking-widest">Checkpoint</div>
          <div className="text-xs font-mono text-cyan-300/70 break-all">{checkpoint.identity}</div>
          {checkpoint.hash && (
            <div className="text-[10px] font-mono text-muted-foreground/50 break-all">hash: {checkpoint.hash}</div>
          )}
        </div>
      )}

      {/* Actor + reason */}
      <div className="space-y-2">
        <Input
          aria-label="Reviewer name"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          placeholder="Reviewer name (optional)"
          className="font-mono text-sm bg-input/40 border-border/40 placeholder:text-muted-foreground/40"
          disabled={busy}
        />
        <Textarea
          aria-label="Approval reason or comment"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason or comment (optional)…"
          className="min-h-[60px] resize-none bg-input/40 border-border/40 text-sm placeholder:text-muted-foreground/40"
          disabled={busy}
        />
      </div>

      {/* Tacit Knowledge section (collapsible) */}
      <div className="border border-border/30 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => setTacitExpanded((v) => !v)}
          className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/30 transition-colors text-left"
        >
          {tacitExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          <span className="font-mono uppercase tracking-wider text-[10px]">Tacit Knowledge</span>
          <span className="text-[10px] text-muted-foreground/50">— reasoning, confidence, consultation</span>
        </button>
        {tacitExpanded && (
          <div className="px-3 pb-3 space-y-2 border-t border-border/20 pt-2">
            {/* Reasoning */}
            <Textarea
              aria-label="Why you made this decision"
              value={reasoning}
              onChange={(e) => setReasoning(e.target.value)}
              placeholder="Why did you make this decision? (tacit reasoning)"
              className="min-h-[56px] resize-none bg-input/40 border-border/40 text-xs placeholder:text-muted-foreground/40"
              disabled={busy}
            />
            {/* Confidence slider */}
            <div className="space-y-1">
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>Decision confidence</span>
                <span className="font-mono">{Math.round(confidence * 100)}%</span>
              </div>
              <input
                type="range"
                min={0} max={1} step={0.05}
                value={confidence}
                onChange={(e) => setConfidence(parseFloat(e.target.value))}
                disabled={busy}
                className="w-full accent-primary h-1.5"
              />
            </div>
            {/* Reason tags */}
            <Input
              aria-label="Reason tags"
              value={reasonTags}
              onChange={(e) => setReasonTags(e.target.value)}
              placeholder="Reason tags (comma-separated): tone mismatch, policy risk…"
              className="font-mono text-xs bg-input/40 border-border/40 placeholder:text-muted-foreground/40"
              disabled={busy}
            />
            {/* Uncertainty regions */}
            <Input
              aria-label="Uncertainty regions"
              value={uncertaintyRegions}
              onChange={(e) => setUncertaintyRegions(e.target.value)}
              placeholder="Uncertain areas (comma-separated): financial terms, legal phrasing…"
              className="font-mono text-xs bg-input/40 border-border/40 placeholder:text-muted-foreground/40"
              disabled={busy}
            />
            {/* Consultation trace */}
            <div className="space-y-1">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Consultation</div>
              {consultList.map((c, i) => (
                <div key={i} className="flex items-center gap-1 text-xs text-muted-foreground">
                  <span className="text-foreground/70 font-mono">{c.person}</span>
                  <span>—</span>
                  <span>{c.reason}</span>
                  <button
                    type="button"
                    onClick={() => setConsultList((l) => l.filter((_, j) => j !== i))}
                    className="ml-auto text-[oklch(0.65_0.22_25)] hover:text-[oklch(0.65_0.22_25)] text-[10px]"
                  >✕</button>
                </div>
              ))}
              <div className="flex gap-1">
                <Input
                  value={consultPerson}
                  onChange={(e) => setConsultPerson(e.target.value)}
                  placeholder="Person"
                  className="font-mono text-xs bg-input/40 border-border/40 h-7 placeholder:text-muted-foreground/40"
                  disabled={busy}
                />
                <Input
                  value={consultReason}
                  onChange={(e) => setConsultReason(e.target.value)}
                  placeholder="Reason for consulting"
                  className="font-mono text-xs bg-input/40 border-border/40 h-7 placeholder:text-muted-foreground/40 flex-1"
                  disabled={busy}
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs px-2"
                  disabled={busy || !consultPerson.trim()}
                  onClick={() => {
                    if (consultPerson.trim()) {
                      setConsultList((l) => [...l, { person: consultPerson.trim(), reason: consultReason.trim() }]);
                      setConsultPerson("");
                      setConsultReason("");
                    }
                  }}
                >+</Button>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          aria-label="Approve workflow checkpoint"
          disabled={busy}
          onClick={() => submit("approve")}
          className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium text-white transition-opacity disabled:opacity-50"
          style={{ backgroundColor: "oklch(0.70 0.18 145)" }}
        >
          {submitting === "approve" ? <Loader2 className="w-4 h-4 animate-spin" /> : <span>✓</span>}
          Approve Load
        </button>
        <button
          type="button"
          aria-label="Reject workflow"
          disabled={busy}
          onClick={() => submit("reject")}
          className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium text-white transition-opacity disabled:opacity-50"
          style={{ backgroundColor: "oklch(0.65 0.22 25)" }}
        >
          {submitting === "reject" ? <Loader2 className="w-4 h-4 animate-spin" /> : <span>✗</span>}
          Reject
        </button>
        <button
          type="button"
          aria-label="Request manual correction"
          disabled={busy}
          onClick={() => submit("skip")}
          className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium text-muted-foreground border border-border/50 hover:border-border hover:text-foreground transition-colors disabled:opacity-50"
        >
          {submitting === "skip" ? <Loader2 className="w-4 h-4 animate-spin" /> : <span>→</span>}
          Request Correction
        </button>
      </div>
    </motion.div>
  );
}

// ── Error block ───────────────────────────────────────────────────

function WorkflowErrorBlock({ result }: { result: WorkflowResult }) {
  const err = parseError(result);
  if (!err) return null;

  return (
    <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 space-y-1">
      <div className="text-xs uppercase tracking-widest text-destructive/80 font-semibold">오류</div>
      {err.code === "unsupported_workflow" ? (
        <div className="space-y-1">
          <div className="text-sm text-destructive font-medium">지원하지 않는 워크플로우 요청입니다.</div>
          {err.supported && err.supported.length > 0 && (
            <div className="text-sm text-muted-foreground">
              지원 워크플로우:{" "}
              {err.supported.map((w) => (
                <span key={w} className="font-mono text-foreground">{w}</span>
              ))}
            </div>
          )}
          <div className="text-sm text-muted-foreground">
            요청 텍스트에{" "}
            <span className="text-yellow-400">특허</span> +{" "}
            <span className="text-yellow-400">대체</span> +{" "}
            <span className="text-yellow-400">등록</span>{" "}
            세 단어가 포함되어야 합니다.
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <div className="text-sm font-mono text-destructive/90">[{err.code}] {err.message}</div>
          {err.step && (
            <div className="text-xs text-muted-foreground">Step: <span className="font-mono">{err.step}</span></div>
          )}
          {!err.isKnown && (
            <div className="text-xs text-muted-foreground/60 italic">알 수 없는 오류 유형</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── WorkflowPage ──────────────────────────────────────────────────

export default function WorkflowPage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WorkflowResult | null>(null);

  const workflowDone = result?.state === "completed" || result?.state === "failed" || result?.state === "closed";
  const checkpointPending =
    !workflowDone && (
      result?.human_gate?.state === "checkpoint_required" ||
      result?.human_gate?.state === "paused" ||
      !!result?.approval_context  // legacy compat
    );

  async function handleRun() {
    const text = query.trim();
    if (!text || loading) return;
    setLoading(true);
    setResult(null);

    try {
      const res = await fetch("/api/agent/workflow", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: text }),
      });
      const data: WorkflowResult = await res.json();
      setResult(data);

      if (data.error && data.state !== "checkpoint_required") {
        const err = parseError(data);
        toast.error(err?.isKnown ? `[${err.code}] ${err.message}` : `Workflow error: ${data.error}`);
      } else if (data.human_gate?.state === "checkpoint_required") {
        toast("Checkpoint reached — review required", { icon: "⚠" });
      } else if (!data.error) {
        toast.success("Workflow completed");
      }
    } catch (err) {
      toast.error("Failed to reach workflow API");
      setResult({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      setLoading(false);
    }
  }

  function handleDecision(resumeResult: WorkflowResult) {
    // Merge resume result into existing result to preserve steps/reconciliation
    setResult((prev) => ({ ...prev, ...resumeResult }));
    if (resumeResult.state === "closed" || resumeResult.state === "completed") {
      toast.success("Workflow completed after decision");
    } else if (resumeResult.state === "failed") {
      toast.error("Workflow rejected");
    }
  }

  const steps = result?.steps ?? [];
  const hasSteps = steps.length > 0;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border/50 flex items-center gap-3 bg-background/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[oklch(0.70_0.20_300)] to-[oklch(0.65_0.22_200)] flex items-center justify-center">
          <GitBranch className="w-4 h-4 text-white" />
        </div>
        <div>
          <h1 className="text-base font-semibold">Workflow Runner</h1>
          <p className="text-sm text-muted-foreground">A/B 조회 → 보강 → 조정 → 검토 → 로드</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* Input card */}
        <div className="glass rounded-xl p-4 space-y-3">
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-widest">Workflow Request</div>
          <Textarea
            aria-label="Workflow request input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="이번달 특허자산 대체 등록 진행해줘"
            className="min-h-[80px] resize-none bg-input/40 border-border/40 font-mono text-sm placeholder:text-muted-foreground/40"
            disabled={loading}
          />
          <div className="flex items-center gap-2 flex-wrap">
            <Button
              type="button"
              aria-label={loading ? "Agent processing" : "Run workflow"}
              onClick={handleRun}
              disabled={!query.trim() || loading}
              className="gap-2 bg-primary hover:bg-primary/80 glow-purple"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {loading ? "실행 중…" : "워크플로우 실행"}
            </Button>
            <div className="flex gap-1.5 flex-wrap">
              {STEP_EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  aria-label={`Use example: ${ex}`}
                  onClick={() => setQuery(ex)}
                  disabled={loading}
                  className="text-sm px-2 py-1 rounded-md border border-border/40 text-muted-foreground hover:text-foreground hover:border-border/80 transition-colors"
                >
                  {ex.length > 40 ? ex.slice(0, 40) + "…" : ex}
                </button>
              ))}
            </div>
          </div>
          <div className="text-xs text-muted-foreground border border-border/30 rounded-md px-3 py-2 bg-secondary/20">
            {"※ 현재 지원 워크플로우: 특허자산 대체 등록 (한국어, '특허'+'대체'+'등록' 포함 필요)"}
          </div>
        </div>

        {/* Pipeline steps */}
        <div className="glass rounded-xl p-5 space-y-4">
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-widest">Pipeline State</div>

          {!result && (
            <div className="flex flex-col items-center justify-center py-8 gap-2 text-muted-foreground/60">
              <GitBranch className="w-6 h-6" />
              <p className="text-xs text-center">워크플로우를 실행하면<br/>실제 스텝이 여기에 표시됩니다</p>
            </div>
          )}

          {result && hasSteps && (
            <div className="flex flex-col gap-0">
              {steps.map((step, idx) => {
                const isLast = idx === steps.length - 1;
                const label = step.step_id ?? step.name ?? `step-${idx + 1}`;
                const status = normalizeStatus(step.state ?? step.status);
                return (
                  <div key={label} className="flex gap-4">
                    <div className="flex flex-col items-center flex-shrink-0">
                      <div className={`w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-500 ${stepBorderColor(status)}`}>
                        <StepIcon status={status} />
                      </div>
                      {!isLast && (
                        <div className={`w-0.5 h-8 transition-all duration-700 ${
                          status === "completed" ? "bg-[oklch(0.70_0.18_145/0.5)]" : "bg-border/20"
                        }`} />
                      )}
                    </div>
                    <motion.div
                      className="flex-1 pb-4"
                      animate={{ opacity: status === "pending" ? 0.65 : 1 }}
                      transition={{ duration: 0.3 }}
                    >
                      <div className="flex items-center gap-2 mb-0.5 h-8 flex-wrap">
                        <span className={`text-sm font-medium ${stepTextColor(status)}`}>{label}</span>
                        {step.system && (
                          <span className="text-[10px] font-mono text-muted-foreground/50 px-1 py-0.5 rounded bg-secondary/40">
                            {step.system}
                          </span>
                        )}
                        {status === "paused" && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full border border-[oklch(0.80_0.18_80/0.4)] text-[oklch(0.80_0.18_80)] bg-[oklch(0.70_0.18_80/0.1)] font-mono">
                            checkpoint
                          </span>
                        )}
                      </div>
                      {step.details && Object.keys(step.details).length > 0 && (
                        <div className="text-xs font-mono text-muted-foreground/60">
                          {Object.entries(step.details)
                            .filter(([, v]) => v != null && typeof v !== "object")
                            .map(([k, v]) => `${k}: ${v}`)
                            .join(" · ")}
                        </div>
                      )}
                    </motion.div>
                  </div>
                );
              })}
            </div>
          )}

          {result && !hasSteps && (
            <div className="text-sm text-muted-foreground font-mono">
              state: <span className="text-foreground/70">{result.state ?? result.status ?? "—"}</span>
            </div>
          )}
        </div>

        {/* Human Decision Gate */}
        <AnimatePresence>
          {checkpointPending && result?.run_id && (result.human_gate || result.approval_context) && (
            <HumanDecisionGate
              runId={result.run_id}
              humanGate={result.human_gate ?? { state: "checkpoint_required" }}
              onDecision={handleDecision}
            />
          )}
        </AnimatePresence>

        {/* Completion / failure banner */}
        <AnimatePresence>
          {workflowDone && result && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="glass rounded-xl p-4 flex items-center gap-3"
              style={
                result.state === "completed"
                  ? { borderColor: "oklch(0.70 0.18 145 / 0.4)", background: "oklch(0.60 0.18 145 / 0.08)" }
                  : { borderColor: "oklch(0.65 0.22 25 / 0.4)", background: "oklch(0.55 0.22 25 / 0.08)" }
              }
            >
              <span className="text-lg">{result.state === "completed" ? "✓" : "✗"}</span>
              <div>
                <div className="text-sm font-semibold" style={{ color: result.state === "completed" ? "oklch(0.70 0.18 145)" : "oklch(0.65 0.22 25)" }}>
                  Workflow {result.state}
                </div>
                {result.human_decision && (
                  <div className="text-xs text-muted-foreground font-mono">
                    {(result.human_decision as Record<string,unknown>).action as string} · actor: {(result.human_decision as Record<string,unknown>).actor as string}
                  </div>
                )}
                {!!(result.target_load && (result.target_load as Record<string,unknown>).result) && (
                  <div className="text-xs text-muted-foreground font-mono">
                    {`Loaded ${String(((result.target_load as Record<string,unknown>).result as Record<string,unknown>).record_count ?? "?")} record(s) → system D`}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Result */}
        <AnimatePresence>
          {result && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="glass rounded-xl p-4 space-y-2"
            >
              <div className="text-xs font-medium text-muted-foreground uppercase tracking-widest">Raw Result</div>
              {result.error && <WorkflowErrorBlock result={result} />}
              <pre className="text-xs font-mono text-cyan-300/80 leading-relaxed overflow-x-auto max-h-96">
                {JSON.stringify(result, null, 2)}
              </pre>
              {result.run_id && (
                <div className="text-xs font-mono text-muted-foreground">Run ID: {result.run_id}</div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

      </div>
    </div>
  );
}
