"use client";

import { useState, useCallback } from "react";
import { BookOpenCheck, RefreshCw, Lightbulb, ChevronDown, ChevronRight, Loader2, AlertCircle, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import type {
  VerificationEpisode,
  TacitEpisodesResponse,
  TacitHeuristicsResponse,
  TacitReflectResponse,
} from "@/lib/types";

// ── Helpers ─────────────────────────────────────────────────────────

function resolutionColor(r: string) {
  if (r === "human_approved") return "text-[oklch(0.70_0.18_145)] border-[oklch(0.70_0.18_145/0.4)]";
  if (r === "human_rejected") return "text-[oklch(0.65_0.22_25)] border-[oklch(0.65_0.22_25/0.4)]";
  if (r === "human_override") return "text-[oklch(0.80_0.18_80)] border-[oklch(0.80_0.18_80/0.4)]";
  if (r === "escalated") return "text-[oklch(0.65_0.22_200)] border-[oklch(0.65_0.22_200/0.4)]";
  return "text-muted-foreground border-border/50";
}

function semanticBadge(s?: string) {
  const map: Record<string, string> = {
    policy_risk: "bg-[oklch(0.55_0.22_25/0.2)] text-[oklch(0.65_0.22_25)] border-[oklch(0.65_0.22_25/0.3)]",
    escalation: "bg-[oklch(0.55_0.22_200/0.2)] text-[oklch(0.65_0.22_200)] border-[oklch(0.65_0.22_200/0.3)]",
    domain_nuance: "bg-[oklch(0.55_0.22_280/0.2)] text-[oklch(0.72_0.19_280)] border-[oklch(0.72_0.19_280/0.3)]",
    tone: "bg-[oklch(0.55_0.18_80/0.2)] text-[oklch(0.80_0.18_80)] border-[oklch(0.80_0.18_80/0.3)]",
    literal_to_contextual: "bg-[oklch(0.55_0.18_145/0.2)] text-[oklch(0.70_0.18_145)] border-[oklch(0.70_0.18_145/0.3)]",
    no_change: "bg-secondary/30 text-muted-foreground border-border/30",
  };
  return map[s ?? ""] ?? "bg-secondary/30 text-muted-foreground border-border/30";
}

function fmt(ts: string) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

// ── EpisodeRow ───────────────────────────────────────────────────────

function EpisodeRow({
  ep,
  onReflect,
}: {
  ep: VerificationEpisode;
  onReflect: (id: string) => Promise<TacitReflectResponse | null>;
}) {
  const [open, setOpen] = useState(false);
  const [reflection, setReflection] = useState<TacitReflectResponse | null>(null);
  const [reflecting, setReflecting] = useState(false);

  async function handleReflect() {
    setReflecting(true);
    const r = await onReflect(ep.episode_id);
    setReflection(r);
    setReflecting(false);
    setOpen(true);
  }

  return (
    <div className="border border-border/50 rounded-lg bg-secondary/20 overflow-hidden">
      {/* Header row */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-secondary/40 transition-colors"
      >
        {open ? <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" /> : <ChevronRight className="w-4 h-4 text-muted-foreground flex-shrink-0" />}
        <span className={`text-xs font-mono border px-1.5 py-0.5 rounded flex-shrink-0 ${resolutionColor(ep.final_resolution)}`}>
          {ep.final_resolution.replace("human_", "")}
        </span>
        {ep.correction_diff?.semantic_type && ep.correction_diff.semantic_type !== "no_change" && (
          <span className={`text-[10px] font-mono border px-1.5 py-0.5 rounded flex-shrink-0 ${semanticBadge(ep.correction_diff.semantic_type)}`}>
            {ep.correction_diff.semantic_type}
          </span>
        )}
        <span className="text-xs text-muted-foreground truncate flex-1 font-mono">{ep.episode_id.slice(0, 12)}…</span>
        <span className="text-xs text-muted-foreground/60 flex-shrink-0 flex items-center gap-1">
          <Clock className="w-3 h-3" />{fmt(ep.timestamp)}
        </span>
      </button>

      {/* Expanded detail */}
      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-border/40 pt-3">
          {/* AI output */}
          <div>
            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">AI Output</div>
            <pre className="text-xs text-foreground/80 bg-secondary/30 rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap">{ep.ai_output}</pre>
          </div>

          {/* Human revision */}
          {ep.human_revision && (
            <div>
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Human Revision</div>
              <pre className="text-xs text-[oklch(0.70_0.18_145)] bg-[oklch(0.60_0.18_145/0.1)] rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap">{ep.human_revision}</pre>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            {/* Correction diff */}
            {ep.correction_diff && ep.correction_diff.semantic_type !== "no_change" && (
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Correction Diff</div>
                <div className="space-y-1 text-xs">
                  {ep.correction_diff.removed && ep.correction_diff.removed.length > 0 && (
                    <div className="text-[oklch(0.65_0.22_25)]">− {ep.correction_diff.removed.slice(0, 5).join(", ")}</div>
                  )}
                  {ep.correction_diff.inserted && ep.correction_diff.inserted.length > 0 && (
                    <div className="text-[oklch(0.70_0.18_145)]">+ {ep.correction_diff.inserted.slice(0, 5).join(", ")}</div>
                  )}
                </div>
              </div>
            )}

            {/* Confidence */}
            {ep.confidence_after != null && (
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Confidence After</div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-secondary/50">
                    <div className="h-1.5 rounded-full bg-[oklch(0.70_0.18_145)]" style={{ width: `${Math.round(ep.confidence_after * 100)}%` }} />
                  </div>
                  <span className="text-xs text-muted-foreground">{Math.round(ep.confidence_after * 100)}%</span>
                </div>
              </div>
            )}
          </div>

          {/* Reason tags */}
          {ep.reason_tags && ep.reason_tags.length > 0 && (
            <div>
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Reason Tags</div>
              <div className="flex flex-wrap gap-1">
                {ep.reason_tags.map((t) => (
                  <span key={t} className="text-[10px] border border-border/50 rounded px-1.5 py-0.5 text-muted-foreground">{t}</span>
                ))}
              </div>
            </div>
          )}

          {/* Consultation trace */}
          {ep.consultation_trace && ep.consultation_trace.length > 0 && (
            <div>
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Consultation</div>
              <div className="space-y-1">
                {ep.consultation_trace.map((c, i) => (
                  <div key={i} className="text-xs text-muted-foreground">
                    <span className="text-foreground/80">{c.person}</span> — {c.reason}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Reflection */}
          {reflection && !reflection.error && (
            <div className="border border-[oklch(0.72_0.19_280/0.3)] rounded-lg p-3 bg-[oklch(0.72_0.19_280/0.05)] space-y-2">
              <div className="text-[10px] text-[oklch(0.72_0.19_280)] uppercase tracking-wider flex items-center gap-1">
                <Lightbulb className="w-3 h-3" /> Reflection
              </div>
              <div className="text-xs space-y-1.5">
                <div><span className="text-muted-foreground">Failure: </span>{reflection.failure_analysis}</div>
                <div><span className="text-muted-foreground">Missing: </span>{reflection.missing_context}</div>
                {reflection.extracted_heuristics?.length > 0 && (
                  <div>
                    <span className="text-muted-foreground">Heuristics:</span>
                    <ul className="mt-1 space-y-0.5">
                      {reflection.extracted_heuristics.map((h, i) => (
                        <li key={i} className="text-[oklch(0.70_0.18_145)]">• {h}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div><span className="text-muted-foreground">Policy: </span>{reflection.policy_proposal}</div>
              </div>
            </div>
          )}

          <Button
            size="sm"
            variant="outline"
            onClick={handleReflect}
            disabled={reflecting}
            className="text-xs h-7"
          >
            {reflecting ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Lightbulb className="w-3 h-3 mr-1" />}
            Reflect
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────

type Tab = "episodes" | "heuristics";

export default function TacitPage() {
  const [tab, setTab] = useState<Tab>("episodes");
  const [episodes, setEpisodes] = useState<VerificationEpisode[]>([]);
  const [heuristics, setHeuristics] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (t: Tab) => {
    setLoading(true);
    setError(null);
    try {
      const action = t === "episodes" ? "list" : "heuristics";
      const res = await fetch(`/api/agent/tacit?action=${action}`);
      const data = await res.json();
      if (t === "episodes") {
        const ep = (data as TacitEpisodesResponse).episodes ?? [];
        setEpisodes(ep);
        if (ep.length === 0 && !data.error) toast.info("No verification episodes yet");
      } else {
        const h = (data as TacitHeuristicsResponse).heuristics ?? [];
        setHeuristics(h);
        if (h.length === 0 && !data.error) toast.info("No heuristics extracted yet");
      }
      if (data.error) setError(data.error);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const reflect = useCallback(async (episodeId: string): Promise<TacitReflectResponse | null> => {
    try {
      const res = await fetch(`/api/agent/tacit?action=reflect&episode_id=${episodeId}`);
      return await res.json();
    } catch {
      toast.error("Reflection failed");
      return null;
    }
  }, []);

  function switchTab(t: Tab) {
    setTab(t);
    setEpisodes([]);
    setHeuristics([]);
    setError(null);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-border/50 px-6 py-4 flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-semibold text-foreground flex items-center gap-2">
            <BookOpenCheck className="w-4 h-4 text-primary" />
            Tacit Knowledge
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">Human verification episodes &amp; extracted heuristics</p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => load(tab)}
          disabled={loading}
          className="h-8 text-xs"
        >
          {loading ? <Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> : <RefreshCw className="w-3 h-3 mr-1.5" />}
          Load
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border/50 px-6 flex-shrink-0">
        {(["episodes", "heuristics"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => switchTab(t)}
            className={`px-4 py-2.5 text-xs font-medium capitalize border-b-2 transition-colors ${
              tab === t
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t}
            {t === "episodes" && episodes.length > 0 && (
              <span className="ml-1.5 text-[10px] bg-primary/20 text-primary rounded-full px-1.5">{episodes.length}</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-3">
        {error && (
          <div className="flex items-start gap-2 text-xs text-[oklch(0.65_0.22_25)] bg-[oklch(0.55_0.22_25/0.1)] border border-[oklch(0.65_0.22_25/0.3)] rounded-lg p-3">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {!loading && !error && tab === "episodes" && episodes.length === 0 && (
          <div className="text-center py-16 text-muted-foreground/50 text-sm">
            Click <span className="font-mono text-xs border border-border/50 rounded px-1">Load</span> to fetch verification episodes
          </div>
        )}

        {tab === "episodes" && episodes.map((ep) => (
          <EpisodeRow key={ep.episode_id} ep={ep} onReflect={reflect} />
        ))}

        {!loading && !error && tab === "heuristics" && heuristics.length === 0 && (
          <div className="text-center py-16 text-muted-foreground/50 text-sm">
            Click <span className="font-mono text-xs border border-border/50 rounded px-1">Load</span> to fetch extracted heuristics
          </div>
        )}

        {tab === "heuristics" && heuristics.length > 0 && (
          <div className="space-y-2">
            {heuristics.map((h, i) => (
              <div key={i} className="flex items-start gap-2 text-sm border border-border/50 rounded-lg px-4 py-3 bg-secondary/20">
                <Lightbulb className="w-4 h-4 text-[oklch(0.80_0.18_80)] flex-shrink-0 mt-0.5" />
                <span className="text-foreground/80">{h}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
