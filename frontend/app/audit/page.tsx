"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { motion } from "framer-motion";
import { FileText, Filter, RefreshCw, Search, Layers, List } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getEventClasses } from "@/lib/auditColors";
import type { AuditEntry, AuditData } from "@/lib/types";

// ── Helpers ────────────────────────────────────────────────────────

function formatTs(ts?: string) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  try {
    return d.toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch { return ts; }
}

function formatDuration(startTs?: string, endTs?: string): string | null {
  if (!startTs || !endTs) return null;
  const ms = new Date(endTs).getTime() - new Date(startTs).getTime();
  if (isNaN(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function summarize(entry: AuditEntry): string {
  const skip = new Set(["event", "run_id", "ts", "timestamp", "_line"]);
  const parts = Object.entries(entry)
    .filter(([k, v]) => !skip.has(k) && v != null)
    .slice(0, 3)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`);
  return parts.join(" · ") || "—";
}

// ── Detail panels ──────────────────────────────────────────────────

function EvalDetail({ entry }: { entry: AuditEntry }) {
  const evalResult = entry.eval_result ??
    (entry.data != null && typeof entry.data === "object" && !Array.isArray(entry.data)
      ? (entry.data as Record<string, unknown>).eval_result
      : undefined);
  if (!evalResult || typeof evalResult !== "object") {
    return <pre className="px-4 py-3 text-xs font-mono text-cyan-300/80 leading-relaxed">{JSON.stringify(entry, null, 2)}</pre>;
  }
  const er = evalResult as { passed?: boolean; score?: number; checks?: Array<{ name: string; passed: boolean; detail?: string }> };
  return (
    <div className="px-4 py-3 space-y-3">
      <div className="flex items-center gap-2">
        <span className={`text-xs font-mono px-2 py-0.5 rounded-full border ${er.passed
          ? "text-[oklch(0.75_0.15_145)] border-[oklch(0.60_0.18_145/0.4)] bg-[oklch(0.60_0.18_145/0.1)]"
          : "text-[oklch(0.70_0.20_25)] border-[oklch(0.55_0.22_25/0.4)] bg-[oklch(0.55_0.22_25/0.1)]"}`}>
          {er.passed ? "✓ PASSED" : "✗ FAILED"}
        </span>
        {er.score != null && <span className="text-xs font-mono text-muted-foreground">score: {er.score.toFixed(2)}</span>}
      </div>
      {er.checks && er.checks.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Checks</div>
          {er.checks.map((c, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <span className={c.passed ? "text-[oklch(0.75_0.15_145)]" : "text-[oklch(0.70_0.20_25)]"}>{c.passed ? "✓" : "✗"}</span>
              <span className="font-mono text-foreground/80">{c.name}</span>
              {c.detail && <span className="text-muted-foreground">{c.detail}</span>}
            </div>
          ))}
        </div>
      )}
      <details className="text-xs">
        <summary className="text-muted-foreground cursor-pointer hover:text-foreground">Raw JSON</summary>
        <pre className="mt-1 font-mono text-cyan-300/70 leading-relaxed overflow-x-auto">{JSON.stringify(entry, null, 2)}</pre>
      </details>
    </div>
  );
}

function SessionDetail({ entry }: { entry: AuditEntry }) {
  const summary = entry.summary ??
    (entry.data != null && typeof entry.data === "object" && !Array.isArray(entry.data)
      ? (entry.data as Record<string, unknown>).summary
      : undefined);
  if (!summary || typeof summary !== "object") {
    return <pre className="px-4 py-3 text-xs font-mono text-cyan-300/80 leading-relaxed">{JSON.stringify(entry, null, 2)}</pre>;
  }
  const s = summary as {
    session_id?: string; total_runs?: number; failed_runs?: number;
    success_rate?: number; failure_patterns?: string[]; proposed_memory_paths?: string[];
  };
  return (
    <div className="px-4 py-3 space-y-3">
      <div className="grid grid-cols-2 gap-2 text-xs">
        {s.total_runs != null && <div><span className="text-muted-foreground">Total runs: </span><span className="font-mono">{s.total_runs}</span></div>}
        {s.failed_runs != null && <div><span className="text-muted-foreground">Failed: </span><span className="font-mono text-[oklch(0.70_0.20_25)]">{s.failed_runs}</span></div>}
        {s.success_rate != null && <div><span className="text-muted-foreground">Success: </span><span className="font-mono">{(s.success_rate * 100).toFixed(0)}%</span></div>}
      </div>
      {s.failure_patterns && s.failure_patterns.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Failure Patterns</div>
          {s.failure_patterns.map((p, i) => (
            <div key={i} className="text-xs font-mono text-[oklch(0.82_0.16_80)] bg-[oklch(0.70_0.18_80/0.08)] px-2 py-1 rounded border border-[oklch(0.70_0.18_80/0.2)]">{p}</div>
          ))}
        </div>
      )}
      {s.proposed_memory_paths && s.proposed_memory_paths.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Proposed Memory</div>
          {s.proposed_memory_paths.map((p, i) => (
            <div key={i} className="text-xs font-mono text-[oklch(0.75_0.18_290)] truncate">{p}</div>
          ))}
        </div>
      )}
      <details className="text-xs">
        <summary className="text-muted-foreground cursor-pointer hover:text-foreground">Raw JSON</summary>
        <pre className="mt-1 font-mono text-cyan-300/70 leading-relaxed overflow-x-auto">{JSON.stringify(entry, null, 2)}</pre>
      </details>
    </div>
  );
}

function DetailPanel({ entry, onClose }: { entry: AuditEntry; onClose: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      className="w-80 border-l border-border/50 flex flex-col bg-background/50"
    >
      <div className="px-4 py-3 border-b border-border/30 flex items-center justify-between">
        <span className={`inline-flex px-2 py-0.5 rounded-full border text-[10px] font-mono font-medium ${getEventClasses(entry.event)}`}>
          {entry.event ?? "—"}
        </span>
        <button onClick={onClose} aria-label="Close detail panel" className="text-muted-foreground hover:text-foreground text-xs">✕</button>
      </div>
      <ScrollArea className="flex-1">
        {entry.event === "answer_evaluated" ? <EvalDetail entry={entry} />
          : entry.event === "session_summarized" ? <SessionDetail entry={entry} />
          : <pre className="px-4 py-3 text-xs font-mono text-cyan-300/80 leading-relaxed">{JSON.stringify(entry, null, 2)}</pre>}
      </ScrollArea>
    </motion.div>
  );
}

// ── Group view ─────────────────────────────────────────────────────

interface RunGroup {
  run_id: string;
  events: AuditEntry[];
  startTs?: string;
  endTs?: string;
}

function buildGroups(entries: AuditEntry[]): RunGroup[] {
  const map = new Map<string, RunGroup>();

  for (const e of entries) {
    const key = e.run_id ?? "__session__";
    if (!map.has(key)) {
      map.set(key, { run_id: key, events: [] });
    }
    const g = map.get(key)!;
    g.events.push(e);
    const ts = e.ts ?? (typeof e.timestamp === "string" ? e.timestamp : undefined);
    if (ts) {
      if (!g.startTs || ts < g.startTs) g.startTs = ts;
      if (!g.endTs || ts > g.endTs) g.endTs = ts;
    }
  }

  return Array.from(map.values()).reverse();
}

function GroupRow({
  group,
  idx,
  onSelect,
  selectedLine,
}: {
  group: RunGroup;
  idx: number;
  onSelect: (e: AuditEntry) => void;
  selectedLine: number | null;
}) {
  const [open, setOpen] = useState(idx === 0);
  const dur = formatDuration(group.startTs, group.endTs);
  const isSession = group.run_id === "__session__";

  return (
    <div className="border-b border-border/20">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-4 py-2 text-xs hover:bg-secondary/20 transition-colors text-left"
      >
        <span className="font-mono text-[10px] text-muted-foreground/50 w-3">{open ? "▼" : "▶"}</span>
        <span className={`font-mono truncate max-w-[180px] ${isSession ? "text-[oklch(0.75_0.18_290)]" : "text-muted-foreground"}`}>
          {isSession ? "session" : group.run_id}
        </span>
        <span className="text-muted-foreground/50">{group.events.length} events</span>
        {dur && <span className="text-muted-foreground/40 font-mono">{dur}</span>}
      </button>
      {open && (
        <div className="pl-6">
          {group.events.map((entry) => (
            <button
              key={entry._line}
              type="button"
              onClick={() => onSelect(entry)}
              className={`w-full flex items-center gap-2 px-4 py-1.5 text-xs cursor-pointer transition-colors border-l-2 text-left ${
                selectedLine === entry._line ? "bg-primary/10 border-primary/50" : "hover:bg-secondary/20 border-transparent"
              }`}
            >
              <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-mono font-medium flex-shrink-0 ${getEventClasses(entry.event)}`}>
                {entry.event ?? "—"}
              </span>
              <span className="font-mono text-muted-foreground/50 text-[10px] flex-shrink-0">
                {formatTs(entry.ts ?? (typeof entry.timestamp === "string" ? entry.timestamp : undefined))}
              </span>
              <span className="text-muted-foreground truncate">{summarize(entry)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────

export default function AuditPage() {
  const [data, setData] = useState<AuditData | null>(null);
  const [loading, setLoading] = useState(false);
  const [eventFilter, setEventFilter] = useState("");
  const [searchRaw, setSearchRaw] = useState("");
  const [search, setSearch] = useState("");
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null);
  const [viewMode, setViewMode] = useState<"table" | "group">("table");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce search 200ms
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setSearch(searchRaw), 200);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [searchRaw]);

  const fetchAudit = useCallback(async (event?: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (event) params.set("event", event);
      params.set("limit", "500");
      const res = await fetch(`/api/agent/audit?${params}`);
      const json = await res.json();
      setData(json);
    } catch {
      setData({ entries: [], total: 0, eventTypes: [], error: "Failed to fetch audit log" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAudit(eventFilter || undefined); }, [fetchAudit, eventFilter]);

  const searchLower = search.toLowerCase();
  const entries = useMemo(() =>
    (data?.entries ?? []).filter((e) =>
      !searchLower || JSON.stringify(e).toLowerCase().includes(searchLower)
    ),
    [data?.entries, searchLower]
  );

  const groups = useMemo(() => buildGroups(entries), [entries]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border/50 flex items-center justify-between bg-background/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[oklch(0.70_0.20_300)] to-[oklch(0.72_0.19_280)] flex items-center justify-center">
            <FileText className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold">Audit Log Viewer</h1>
            <p className="text-xs text-muted-foreground">
              {data?.total ?? "…"} total entries · showing {entries.length}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md border border-border/40 overflow-hidden">
            <button
              type="button"
              onClick={() => setViewMode("table")}
              aria-label="Table view"
              className={`px-2 py-1.5 text-xs transition-colors ${viewMode === "table" ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}
            >
              <List className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setViewMode("group")}
              aria-label="Group view"
              className={`px-2 py-1.5 text-xs transition-colors ${viewMode === "group" ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"}`}
            >
              <Layers className="w-3.5 h-3.5" />
            </button>
          </div>
          <Button variant="outline" size="sm" onClick={() => fetchAudit(eventFilter || undefined)} disabled={loading} className="gap-1.5 text-xs">
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="px-6 py-3 border-b border-border/30 flex items-center gap-3 bg-background/50">
        <div className="flex items-center gap-1.5 flex-1 max-w-xs">
          <Search className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
          <Input
            value={searchRaw}
            onChange={(e) => setSearchRaw(e.target.value)}
            placeholder="Search entries…"
            className="h-7 text-xs bg-input/40 border-border/40 font-mono"
          />
        </div>
        <div className="flex items-center gap-1.5">
          <Filter className="w-3.5 h-3.5 text-muted-foreground" />
          <div className="flex gap-1 flex-wrap">
            <button
              type="button"
              onClick={() => setEventFilter("")}
              className={`text-xs px-2 py-0.5 rounded-full border font-mono transition-all ${!eventFilter ? "bg-primary/20 border-primary/40 text-primary" : "border-border/30 text-muted-foreground hover:text-foreground"}`}
            >
              all
            </button>
            {(data?.eventTypes ?? []).map((et) => (
              <button
                key={et}
                type="button"
                onClick={() => setEventFilter(et === eventFilter ? "" : et)}
                className={`text-xs px-2 py-0.5 rounded-full border font-mono transition-all ${
                  eventFilter === et ? "bg-primary/20 border-primary/40 text-primary" : "border-border/30 text-muted-foreground hover:text-foreground"
                }`}
              >
                {et}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Content */}
        <ScrollArea className="flex-1">
          {data?.error && (
            <div className="px-4 py-8 text-center text-destructive text-sm">{data.error}</div>
          )}
          {entries.length === 0 && !loading && !data?.error && (
            <div className="px-4 py-8 text-center text-muted-foreground text-sm">
              No audit entries found. The log file may not exist yet.
            </div>
          )}

          {viewMode === "group" ? (
            <div>
              {groups.map((g, gIdx) => (
                <GroupRow
                  key={g.run_id}
                  group={g}
                  idx={gIdx}
                  selectedLine={selectedEntry?._line ?? null}
                  onSelect={(e) => setSelectedEntry(selectedEntry?._line === e._line ? null : e)}
                />
              ))}
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-background/95 backdrop-blur-sm z-10">
                <tr className="border-b border-border/40">
                  <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-medium w-40">Timestamp</th>
                  <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-medium w-40">Event</th>
                  <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-medium w-48">Run ID</th>
                  <th className="text-left px-4 py-2.5 text-[10px] uppercase tracking-widest text-muted-foreground font-medium">Summary</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, idx) => (
                  <motion.tr
                    key={entry._line}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: Math.min(idx * 0.005, 0.15) }}
                    onClick={() => setSelectedEntry(selectedEntry?._line === entry._line ? null : entry)}
                    className={`border-b border-border/20 cursor-pointer transition-colors ${
                      selectedEntry?._line === entry._line ? "bg-primary/10" : "hover:bg-secondary/30"
                    }`}
                  >
                    <td className="px-4 py-2 font-mono text-muted-foreground whitespace-nowrap">
                      {formatTs(entry.ts ?? (typeof entry.timestamp === "string" ? entry.timestamp : undefined))}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`inline-flex px-2 py-0.5 rounded-full border text-[10px] font-mono font-medium ${getEventClasses(entry.event)}`}>
                        {entry.event ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-2 font-mono text-muted-foreground/70 truncate max-w-[180px]">
                      {entry.run_id ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-muted-foreground truncate max-w-[300px]">
                      {summarize(entry)}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          )}
        </ScrollArea>

        {/* Detail panel */}
        {selectedEntry && (
          <DetailPanel entry={selectedEntry} onClose={() => setSelectedEntry(null)} />
        )}
      </div>
    </div>
  );
}
