"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { Activity, RefreshCw, Clock, Cpu, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { getEventClasses } from "@/lib/auditColors";
import type { RunEntry, StatusData } from "@/lib/types";

function timeAgo(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

function duration(started?: string, completed?: string): string | null {
  if (!started) return null;
  const end = completed ? new Date(completed).getTime() : Date.now();
  const ms = end - new Date(started).getTime();
  if (ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function EventRow({ ev }: { ev: { event: string; ts?: string; detail?: unknown } }) {
  const [open, setOpen] = useState(false);
  const hasDetail = ev.detail != null && (typeof ev.detail !== "object" || Object.keys(ev.detail as object).length > 0);

  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-2 text-xs">
        <div className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-primary/60" />
        <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-mono font-medium ${getEventClasses(ev.event)}`}>
          {ev.event}
        </span>
        <span className="text-muted-foreground/50 ml-auto font-mono">{ev.ts ? timeAgo(ev.ts) : "—"}</span>
        {hasDetail && (
          <button
            type="button"
            aria-label="Toggle event detail"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="text-muted-foreground hover:text-foreground flex-shrink-0"
          >
            {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </button>
        )}
      </div>
      {open && hasDetail && (
        <pre className="ml-5 text-[10px] font-mono text-cyan-300/60 bg-black/20 px-2 py-1 rounded border border-border/20 overflow-x-auto leading-relaxed">
          {JSON.stringify(ev.detail, null, 2)}
        </pre>
      )}
    </div>
  );
}

function StepRow({ step }: { step: { step: string; status?: string; result?: unknown; latency_ms?: number } }) {
  const [open, setOpen] = useState(false);
  const hasResult = step.result != null;

  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-secondary/60 text-muted-foreground border border-border/30">
          {step.step}
        </span>
        {step.status && (
          <span className={`text-[10px] font-mono ${
            step.status === "completed" ? "text-[oklch(0.70_0.18_145)]"
            : step.status === "failed" ? "text-[oklch(0.65_0.22_25)]"
            : "text-muted-foreground/60"
          }`}>
            {step.status}
          </span>
        )}
        {step.latency_ms != null && (
          <span className="text-[10px] font-mono text-muted-foreground/50">{step.latency_ms}ms</span>
        )}
        {hasResult && (
          <button
            type="button"
            aria-label="Toggle step result"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="text-[10px] text-muted-foreground hover:text-foreground font-mono"
          >
            {open ? "▲ result" : "▼ result"}
          </button>
        )}
      </div>
      {open && hasResult && (
        <pre className="text-[10px] font-mono text-cyan-300/60 bg-black/20 px-2 py-1 rounded border border-border/20 overflow-x-auto leading-relaxed">
          {JSON.stringify(step.result, null, 2)}
        </pre>
      )}
    </div>
  );
}

function RunCard({ run }: { run: RunEntry }) {
  const dur = duration(run.started_at, run.completed_at);

  return (
    <div className="glass rounded-xl p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <StatusBadge status={run.status ?? "unknown"} />
            <span className="text-xs font-mono text-muted-foreground truncate">
              {run.run_id ?? "—"}
            </span>
          </div>
          {run.intent && (
            <p className="text-sm text-foreground">{run.intent}</p>
          )}
        </div>
        <div className="flex-shrink-0 text-right text-xs text-muted-foreground space-y-0.5">
          {run.started_at && (
            <div className="flex items-center gap-1 justify-end">
              <Clock className="w-3 h-3" />
              {timeAgo(run.started_at)}
            </div>
          )}
          {dur && (
            <div className="font-mono text-[10px] text-muted-foreground/60">
              {dur}
            </div>
          )}
        </div>
      </div>

      {/* Action */}
      {run.action && (
        <div className="px-3 py-2 rounded-md bg-black/30 border border-border/30">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Action · </span>
          <span className="text-xs font-mono text-[oklch(0.75_0.18_200)]">{run.action}</span>
        </div>
      )}

      {/* Events timeline */}
      {run.events && run.events.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Events</div>
          <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
            {run.events.map((ev, i) => (
              <EventRow key={i} ev={ev} />
            ))}
          </div>
        </div>
      )}

      {/* Steps */}
      {run.steps && run.steps.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Steps</div>
          <div className="space-y-1.5">
            {run.steps.map((step, i) => (
              <StepRow key={i} step={step} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function StatusPage() {
  const [data, setData] = useState<StatusData | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/agent/status");
      const json = await res.json();
      setData(json);
      setLastFetched(new Date());
    } catch {
      setData({ error: "Failed to fetch status" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchStatus]);

  const runs: RunEntry[] = data?.runs ?? (data?.latest ? [data.latest] : []);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border/50 flex items-center justify-between bg-background/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[oklch(0.65_0.22_200)] to-[oklch(0.60_0.18_160)] flex items-center justify-center glow-cyan">
            <Activity className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold">Run Status Monitor</h1>
            <p className="text-xs text-muted-foreground">
              {lastFetched ? `Updated ${timeAgo(lastFetched.toISOString())}` : "Fetching…"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAutoRefresh((a) => !a)}
            aria-label={autoRefresh ? "Pause auto-refresh" : "Resume auto-refresh"}
            className={`text-xs gap-1.5 ${autoRefresh ? "text-[oklch(0.70_0.18_145)]" : "text-muted-foreground"}`}
          >
            <div className={`w-1.5 h-1.5 rounded-full ${autoRefresh ? "bg-[oklch(0.70_0.18_145)] animate-pulse" : "bg-muted-foreground"}`} />
            {autoRefresh ? "Live" : "Paused"}
          </Button>
          <Button variant="outline" size="sm" onClick={fetchStatus} disabled={loading} className="gap-1.5 text-xs">
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {data?.error && (
          <div className="glass rounded-lg p-4 border-destructive/30 text-sm text-destructive">
            {data.error}
          </div>
        )}

        {runs.length === 0 && !loading && !data?.error && (
          <div className="flex flex-col items-center justify-center h-48 gap-3 text-muted-foreground">
            <Cpu className="w-8 h-8 opacity-30" />
            <p className="text-sm">No runs found. Run <code className="font-mono text-xs bg-secondary px-1 py-0.5 rounded">agent ask</code> to create one.</p>
          </div>
        )}

        {runs.map((run, idx) => (
          <motion.div
            key={run.run_id ?? idx}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(idx * 0.05, 0.3) }}
          >
            <RunCard run={run} />
          </motion.div>
        ))}
      </div>
    </div>
  );
}
