"use client";

import { useState } from "react";
import { Settings2, Database, Terminal, Loader2, ListChecks, ShieldCheck, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";

type SectionResult = Record<string, unknown> | null;

function StatusBadge({ status }: { status: string }) {
  const ok = status === "ok" || status === "passed" || status === "succeeded" || status === "approved" || status === "already_compliant" || status === "created";
  return (
    <span
      className="text-xs font-mono px-2 py-0.5 rounded-full border"
      style={
        ok
          ? { color: "oklch(0.70 0.18 145)", borderColor: "oklch(0.70 0.18 145 / 0.4)", background: "oklch(0.60 0.18 145 / 0.12)" }
          : { color: "oklch(0.65 0.22 25)", borderColor: "oklch(0.65 0.22 25 / 0.4)", background: "oklch(0.55 0.22 25 / 0.12)" }
      }
    >
      {status}
    </span>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <div
      className="rounded-lg border p-3 text-sm font-mono whitespace-pre-wrap break-all"
      style={{ borderColor: "oklch(0.65 0.22 25 / 0.4)", background: "oklch(0.55 0.22 25 / 0.08)", color: "oklch(0.65 0.22 25)" }}
    >
      {message}
    </div>
  );
}

function CollapsibleJson({ result, label = "Raw JSON" }: { result: SectionResult; label?: string }) {
  const [open, setOpen] = useState(false);
  if (!result) return null;
  return (
    <div className="space-y-1">
      <button
        type="button"
        aria-label={`Toggle ${label}`}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs text-muted-foreground/60 hover:text-muted-foreground transition-colors"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {label}
      </button>
      {open && (
        <pre className="text-xs font-mono text-cyan-300/80 bg-black/20 px-3 py-2 rounded border border-border/20 overflow-x-auto">
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </div>
  );
}

function SmokeResult({ result }: { result: SectionResult }) {
  if (!result) return null;
  // backend returns { state, latency_ms, message } or { status, ... }
  const status = typeof result.state === "string" ? result.state : typeof result.status === "string" ? result.status : null;
  const latency = typeof result.latency_ms === "number" ? result.latency_ms : null;
  const message = typeof result.message === "string" ? result.message : null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {status && <StatusBadge status={status} />}
        {latency !== null && <span className="text-xs font-mono text-muted-foreground">{latency} ms</span>}
      </div>
      {message && <p className="text-sm text-muted-foreground">{message}</p>}
      <CollapsibleJson result={result} />
    </div>
  );
}

function QueryResult({ result }: { result: SectionResult }) {
  if (!result) return null;
  // backend wraps query output in result.response.rows
  const response = result.response && typeof result.response === "object" ? result.response as Record<string, unknown> : null;
  const rows = Array.isArray(response?.rows) ? (response!.rows as unknown[]) : Array.isArray(result.rows) ? (result.rows as unknown[]) : null;

  if (rows && rows.length > 0 && typeof rows[0] === "object" && rows[0] !== null) {
    const cols = Object.keys(rows[0] as Record<string, unknown>);
    const display = rows.slice(0, 10) as Record<string, unknown>[];
    return (
      <div className="space-y-2">
        <div className="text-xs text-muted-foreground font-mono">{rows.length} row{rows.length !== 1 ? "s" : ""}</div>
        <div className="overflow-x-auto">
          <table className="text-xs font-mono w-full border-collapse">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c} className="text-left px-2 py-1 border-b border-border/40 text-muted-foreground">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {display.map((row, i) => (
                <tr key={i} className="border-b border-border/20">
                  {cols.map((c) => <td key={c} className="px-2 py-1 text-foreground/80">{String(row[c] ?? "")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <CollapsibleJson result={result} />
      </div>
    );
  }

  return <CollapsibleJson result={result} label="Result JSON" />;
}

function ProvisionResult({ result }: { result: SectionResult }) {
  if (!result) return null;
  const classification = typeof result.provisioning_classification === "string" ? result.provisioning_classification : null;
  const user = typeof result.working_user === "string" ? result.working_user : null;
  const actions = Array.isArray(result.actions_applied) ? result.actions_applied as string[] : [];

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        {classification && <StatusBadge status={classification} />}
        {user && <span className="text-xs font-mono text-muted-foreground">user: {user}</span>}
      </div>
      {actions.length > 0 && (
        <div className="space-y-0.5">
          {actions.map((a, i) => (
            <div key={i} className="text-xs font-mono text-muted-foreground">· {a}</div>
          ))}
        </div>
      )}
      <CollapsibleJson result={result} />
    </div>
  );
}

export default function OperatorPage() {
  const [smokeLoading, setSmokeLoading] = useState(false);
  const [smokeResult, setSmokeResult] = useState<SectionResult>(null);
  const [smokeError, setSmokeError] = useState<string | null>(null);

  const [queryLoading, setQueryLoading] = useState(false);
  const [queryResult, setQueryResult] = useState<SectionResult>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [sql, setSql] = useState("");

  const [provisionLoading, setProvisionLoading] = useState(false);
  const [provisionResult, setProvisionResult] = useState<SectionResult>(null);
  const [provisionError, setProvisionError] = useState<string | null>(null);

  const [listLoading, setListLoading] = useState(false);
  const [listResult, setListResult] = useState<SectionResult>(null);
  const [listError, setListError] = useState<string | null>(null);

  const [candidateId, setCandidateId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [rejectNotes, setRejectNotes] = useState("");
  const [actionLoading, setActionLoading] = useState<"show" | "approve" | "reject" | null>(null);
  const [actionResult, setActionResult] = useState<SectionResult>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function callOperator(body: Record<string, unknown>): Promise<SectionResult> {
    const res = await fetch("/api/agent/operator", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error((data as Record<string, unknown>).error as string ?? `HTTP ${res.status}`);
    return data as SectionResult;
  }

  async function handleSmoke() {
    setSmokeLoading(true); setSmokeResult(null); setSmokeError(null);
    try { setSmokeResult(await callOperator({ action: "adw-smoke" })); }
    catch (err) { setSmokeError(err instanceof Error ? err.message : String(err)); }
    finally { setSmokeLoading(false); }
  }

  async function handleQuery() {
    const trimmed = sql.trim();
    if (!trimmed || queryLoading) return;
    setQueryLoading(true); setQueryResult(null); setQueryError(null);
    try { setQueryResult(await callOperator({ action: "adw-query", sql: trimmed })); }
    catch (err) { setQueryError(err instanceof Error ? err.message : String(err)); }
    finally { setQueryLoading(false); }
  }

  async function handleProvision() {
    setProvisionLoading(true); setProvisionResult(null); setProvisionError(null);
    try { setProvisionResult(await callOperator({ action: "adw-provision" })); }
    catch (err) { setProvisionError(err instanceof Error ? err.message : String(err)); }
    finally { setProvisionLoading(false); }
  }

  async function handleListCandidates() {
    setListLoading(true); setListResult(null); setListError(null);
    try { setListResult(await callOperator({ action: "review-candidates" })); }
    catch (err) { setListError(err instanceof Error ? err.message : String(err)); }
    finally { setListLoading(false); }
  }

  async function handleCandidateAction(act: "show" | "approve" | "reject") {
    if (!candidateId.trim() || actionLoading) return;
    setActionLoading(act); setActionResult(null); setActionError(null);
    try {
      setActionResult(await callOperator({
        action: `review-candidate-${act}`,
        candidate_id: candidateId.trim(),
        reviewer: reviewer.trim() || undefined,
        notes: act === "reject" ? rejectNotes.trim() || undefined : undefined,
      }));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(null);
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-border/50 flex items-center gap-3 bg-background/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[oklch(0.82_0.16_80)] to-[oklch(0.78_0.18_55)] flex items-center justify-center">
          <Settings2 className="w-4 h-4 text-white" />
        </div>
        <div>
          <h1 className="text-base font-semibold">Operator Tools</h1>
          <p className="text-sm text-muted-foreground">ADW connectivity · query · provision · candidates</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">

        {/* ADW Smoke Test */}
        <div className="glass rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-semibold">ADW Smoke Test</span>
          </div>
          <p className="text-sm text-muted-foreground">Run a lightweight connectivity check against Oracle ADW</p>
          <Button type="button" aria-label="Run smoke test" onClick={handleSmoke} disabled={smokeLoading} className="gap-2">
            {smokeLoading && <Loader2 className="w-4 h-4 animate-spin" />}
            Run Smoke Test
          </Button>
          {smokeError && <ErrorCard message={smokeError} />}
          {smokeResult && <SmokeResult result={smokeResult} />}
        </div>

        {/* ADW Query */}
        <div className="glass rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-semibold">ADW Query</span>
          </div>
          <Textarea
            aria-label="SQL query input"
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            placeholder="SELECT 1 FROM DUAL"
            className="min-h-[100px] resize-none bg-input/40 border-border/40 font-mono text-sm placeholder:text-muted-foreground/40"
            disabled={queryLoading}
          />
          <Button type="button" aria-label="Execute SQL query" onClick={handleQuery} disabled={!sql.trim() || queryLoading} className="gap-2">
            {queryLoading && <Loader2 className="w-4 h-4 animate-spin" />}
            Execute Query
          </Button>
          {queryError && <ErrorCard message={queryError} />}
          {queryResult && <QueryResult result={queryResult} />}
        </div>

        {/* ADW Provision Working User */}
        <div className="glass rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-semibold">ADW Provision Working User</span>
          </div>
          <p className="text-sm text-muted-foreground">
            Provision <span className="font-mono text-foreground/70">AIAGENT</span> with{" "}
            <span className="font-mono text-foreground/70">prototype-any-table-read</span> grant profile.
            Admin operation — idempotent.
          </p>
          <Button type="button" aria-label="Provision working user" onClick={handleProvision} disabled={provisionLoading} className="gap-2">
            {provisionLoading && <Loader2 className="w-4 h-4 animate-spin" />}
            Provision User
          </Button>
          {provisionError && <ErrorCard message={provisionError} />}
          {provisionResult && <ProvisionResult result={provisionResult} />}
        </div>

        {/* Improvement Candidates */}
        <div className="glass rounded-xl p-5 space-y-5">
          <div className="flex items-center gap-2">
            <ListChecks className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-semibold">Improvement Candidates</span>
          </div>

          {/* List */}
          <div className="space-y-3">
            <div className="text-xs text-muted-foreground uppercase tracking-widest">List</div>
            <Button type="button" aria-label="List improvement candidates" onClick={handleListCandidates} disabled={listLoading} className="gap-2">
              {listLoading && <Loader2 className="w-4 h-4 animate-spin" />}
              List Candidates
            </Button>
            {listError && <ErrorCard message={listError} />}
            {listResult && <CollapsibleJson result={listResult} label="Candidates JSON" />}
          </div>

          <div className="border-t border-border/30" />

          {/* Show / Approve / Reject */}
          <div className="space-y-3">
            <div className="text-xs text-muted-foreground uppercase tracking-widest">Candidate Actions</div>
            <div className="space-y-2">
              <Input
                aria-label="Candidate ID"
                value={candidateId}
                onChange={(e) => setCandidateId(e.target.value)}
                placeholder="candidate-id"
                className="font-mono text-sm bg-input/40 border-border/40 placeholder:text-muted-foreground/40"
              />
              <Input
                aria-label="Reviewer name"
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value)}
                placeholder="reviewer name (required for approve/reject)"
                className="font-mono text-sm bg-input/40 border-border/40 placeholder:text-muted-foreground/40"
              />
              <Textarea
                aria-label="Rejection notes"
                value={rejectNotes}
                onChange={(e) => setRejectNotes(e.target.value)}
                placeholder="rejection notes (optional, reject only)"
                className="min-h-[60px] resize-none bg-input/40 border-border/40 font-mono text-sm placeholder:text-muted-foreground/40"
              />
            </div>
            <div className="flex gap-2 flex-wrap">
              <Button
                type="button"
                aria-label="Show candidate"
                variant="outline"
                onClick={() => handleCandidateAction("show")}
                disabled={!candidateId.trim() || actionLoading !== null}
                className="gap-2 text-sm"
              >
                {actionLoading === "show" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Show
              </Button>
              <Button
                type="button"
                aria-label="Approve candidate"
                onClick={() => handleCandidateAction("approve")}
                disabled={!candidateId.trim() || !reviewer.trim() || actionLoading !== null}
                className="gap-2 text-sm"
                style={{ background: "oklch(0.60 0.18 145 / 0.8)" }}
              >
                {actionLoading === "approve" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Approve
              </Button>
              <Button
                type="button"
                aria-label="Reject candidate"
                variant="destructive"
                onClick={() => handleCandidateAction("reject")}
                disabled={!candidateId.trim() || !reviewer.trim() || actionLoading !== null}
                className="gap-2 text-sm"
              >
                {actionLoading === "reject" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Reject
              </Button>
            </div>
            {actionError && <ErrorCard message={actionError} />}
            {actionResult && (
              <div className="space-y-2">
                {typeof actionResult.state === "string" && <StatusBadge status={actionResult.state} />}
                <CollapsibleJson result={actionResult} />
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
