"use client";

import { useState, useEffect, useCallback } from "react";
import { Brain, RefreshCw, Trash2, CheckCircle2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

interface MemoryRecordFile {
  schema_version?: string;
  memory_id?: string;
  key?: string;
  value?: string;
  status?: "active" | "proposed";
  tags?: string[];
  relevance?: number;
  provenance?: {
    recorded_at?: string;
    confidence?: number;
    source?: string;
    session_id?: string;
  };
  _path: string;
}

type StatusFilter = "all" | "active" | "proposed";

function formatDate(ts?: string) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  try {
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function StatusBadge({ status }: { status?: string }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-mono font-medium text-[oklch(0.70_0.18_145)] border-[oklch(0.60_0.18_145/0.4)] bg-[oklch(0.60_0.18_145/0.1)]">
        active
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-mono font-medium text-[oklch(0.78_0.18_80)] border-[oklch(0.70_0.18_80/0.4)] bg-[oklch(0.70_0.18_80/0.1)]">
      proposed
    </span>
  );
}

function RecordCard({
  record,
  onApprove,
  onDelete,
  busy,
}: {
  record: MemoryRecordFile;
  onApprove: (r: MemoryRecordFile) => void;
  onDelete: (r: MemoryRecordFile) => void;
  busy: boolean;
}) {
  const filename = record._path.split("/").pop() ?? record._path;
  const title = record.memory_id ?? filename;
  const confidence = record.provenance?.confidence;

  return (
    <div className="glass rounded-lg p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={record.status} />
            <span className="font-mono text-sm text-foreground truncate">{title}</span>
          </div>
          {record.key && (
            <p className="text-xs text-muted-foreground font-mono">{record.key}</p>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {record.status === "proposed" && (
            <button
              type="button"
              aria-label="Approve record"
              disabled={busy}
              onClick={() => onApprove(record)}
              className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-[oklch(0.60_0.18_145/0.4)] text-[oklch(0.70_0.18_145)] bg-[oklch(0.60_0.18_145/0.08)] hover:bg-[oklch(0.60_0.18_145/0.18)] transition-colors disabled:opacity-50"
            >
              <CheckCircle2 className="w-3 h-3" />
              Approve
            </button>
          )}
          <button
            type="button"
            aria-label="Delete record"
            disabled={busy}
            onClick={() => onDelete(record)}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-[oklch(0.55_0.22_25/0.4)] text-[oklch(0.65_0.22_25)] bg-[oklch(0.55_0.22_25/0.08)] hover:bg-[oklch(0.55_0.22_25/0.18)] transition-colors disabled:opacity-50"
          >
            <Trash2 className="w-3 h-3" />
            Delete
          </button>
        </div>
      </div>

      {record.value && (
        <p className="text-sm text-foreground/80 line-clamp-3 leading-relaxed">{record.value}</p>
      )}

      {record.tags && record.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {record.tags.map((tag) => (
            <span
              key={tag}
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[oklch(0.70_0.20_300/0.12)] border border-[oklch(0.70_0.20_300/0.25)] text-[oklch(0.75_0.18_290)]"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 text-[10px] text-muted-foreground/60 font-mono">
        <span>{formatDate(record.provenance?.recorded_at)}</span>
        {confidence != null && (
          <span>confidence: {(confidence * 100).toFixed(0)}%</span>
        )}
        {record.provenance?.source && (
          <span className="truncate">{record.provenance.source}</span>
        )}
      </div>
    </div>
  );
}

export default function MemoryPage() {
  const [records, setRecords] = useState<MemoryRecordFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [busyPaths, setBusyPaths] = useState<Set<string>>(new Set());

  const fetchRecords = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/agent/memory");
      const json = await res.json();
      setRecords(json.records ?? []);
    } catch {
      setRecords([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  const handleApprove = useCallback(async (record: MemoryRecordFile) => {
    setBusyPaths((prev) => new Set(prev).add(record._path));
    try {
      const res = await fetch("/api/agent/memory", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: record._path, status: "active" }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "Unknown error" }));
        toast.error(`Approve failed: ${err.error}`);
        return;
      }
      setRecords((prev) =>
        prev.map((r) => (r._path === record._path ? { ...r, status: "active" } : r))
      );
    } finally {
      setBusyPaths((prev) => {
        const next = new Set(prev);
        next.delete(record._path);
        return next;
      });
    }
  }, []);

  const handleDelete = useCallback(async (record: MemoryRecordFile) => {
    if (!window.confirm("Delete this memory record?")) return;
    setBusyPaths((prev) => new Set(prev).add(record._path));
    try {
      const res = await fetch("/api/agent/memory", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: record._path }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "Unknown error" }));
        toast.error(`Delete failed: ${err.error}`);
        return;
      }
      setRecords((prev) => prev.filter((r) => r._path !== record._path));
    } finally {
      setBusyPaths((prev) => {
        const next = new Set(prev);
        next.delete(record._path);
        return next;
      });
    }
  }, []);

  const filtered = records.filter((r) => {
    if (filter === "all") return true;
    return r.status === filter;
  });

  const counts = {
    all: records.length,
    active: records.filter((r) => r.status === "active").length,
    proposed: records.filter((r) => r.status === "proposed").length,
  };

  const tabs: { label: string; value: StatusFilter }[] = [
    { label: `All (${counts.all})`, value: "all" },
    { label: `Active (${counts.active})`, value: "active" },
    { label: `Proposed (${counts.proposed})`, value: "proposed" },
  ];

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-border/50 flex items-center justify-between bg-background/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[oklch(0.70_0.20_300)] to-[oklch(0.72_0.19_280)] flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold">Memory Manager</h1>
            <p className="text-xs text-muted-foreground">cross-session runtime memory</p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          type="button"
          aria-label="Refresh memory records"
          onClick={fetchRecords}
          disabled={loading}
          className="gap-1.5 text-xs"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <div role="tablist" aria-label="Filter memory records by status" className="px-6 py-3 border-b border-border/30 flex items-center gap-1 bg-background/50">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            role="tab"
            type="button"
            aria-selected={filter === tab.value}
            onClick={() => setFilter(tab.value)}
            className={`text-xs px-3 py-1 rounded-full border font-mono transition-all ${
              filter === tab.value
                ? "bg-primary/20 border-primary/40 text-primary"
                : "border-border/30 text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <ScrollArea className="flex-1">
        {loading && (
          <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground text-sm">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading memory records…
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-2 text-muted-foreground">
            <Brain className="w-8 h-8 opacity-30" />
            <p className="text-sm">No memory records found.</p>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="p-6 grid gap-3">
            {filtered.map((record) => (
              <RecordCard
                key={record._path}
                record={record}
                onApprove={handleApprove}
                onDelete={handleDelete}
                busy={busyPaths.has(record._path)}
              />
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
