"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { Database, RefreshCw, Table2, Hash, Star, BookOpen, AlertTriangle, Loader2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { TableEntry, GlossaryMatch, SchemaContext } from "@/lib/types";

// Oracle ADW Schema Inspector
// Reads from the last schema inspection stored in the audit log or run artifacts

const MOCK_SCHEMA: SchemaContext = {
  schema_name: "ADWC_PROD",
  query: "sales reconciliation",
  inspected_at: new Date().toISOString(),
  total_tables: 142,
  selected_tables: [
    { name: "SALES_FACT", score: 0.97, columns: ["SALE_ID", "CUSTOMER_ID", "AMOUNT", "SALE_DATE", "REGION"], description: "Core sales transaction fact table", row_count: 14200000 },
    { name: "CUSTOMER_DIM", score: 0.91, columns: ["CUSTOMER_ID", "NAME", "SEGMENT", "COUNTRY"], description: "Customer dimension", row_count: 890000 },
    { name: "PRODUCT_DIM", score: 0.83, columns: ["PRODUCT_ID", "NAME", "CATEGORY", "UNIT_PRICE"], description: "Product catalog", row_count: 45000 },
    { name: "RECONCILIATION_LOG", score: 0.79, columns: ["LOG_ID", "RUN_DATE", "STATUS", "DIFF_AMOUNT"], description: "Reconciliation audit trail", row_count: 8200 },
    { name: "DATE_DIM", score: 0.74, columns: ["DATE_KEY", "CALENDAR_DATE", "FISCAL_YEAR", "QUARTER"], description: "Date dimension", row_count: 3650 },
  ],
  glossary_matches: [
    { term: "Reconciliation", definition: "Process of ensuring two sets of records agree", score: 0.95 },
    { term: "Sales Fact", definition: "Transactional sales data at the line-item level", score: 0.88 },
    { term: "Fiscal Quarter", definition: "Company's 3-month accounting period", score: 0.76 },
    { term: "ADW", definition: "Oracle Autonomous Data Warehouse", score: 0.70 },
  ],
};

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    pct >= 90 ? "bg-[oklch(0.70_0.18_145)]"
    : pct >= 75 ? "bg-[oklch(0.65_0.22_200)]"
    : "bg-[oklch(0.72_0.19_280)]";

  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-1 bg-secondary/50 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className={`h-full rounded-full ${color}`}
        />
      </div>
      <span className="text-[10px] font-mono text-muted-foreground flex-shrink-0 w-7 text-right">{pct}%</span>
    </div>
  );
}

function formatNumber(n?: number) {
  if (n == null) return "—";
  return n.toLocaleString("en-US");
}

export default function SchemaPage() {
  const [schema, setSchema] = useState<SchemaContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedTable, setSelectedTable] = useState<TableEntry | null>(null);
  const [useMock, setUseMock] = useState(false);
  const [smokeLoading, setSmokeLoading] = useState(false);
  const [smokeOk, setSmokeOk] = useState<boolean | null>(null);

  const fetchSchema = useCallback(async () => {
    setLoading(true);
    try {
      // Try to read schema context from audit log entries
      const res = await fetch("/api/agent/audit?event=schema_inspected&limit=1");
      const data = await res.json();
      if (data.entries && data.entries.length > 0) {
        const entry = data.entries[0];
        setSchema({
          selected_tables: entry.selected_tables ?? entry.tables,
          glossary_matches: entry.glossary_matches ?? entry.glossary,
          query: entry.query,
          schema_name: entry.schema_name ?? "ADWC",
          inspected_at: entry.ts ?? entry.timestamp,
          total_tables: entry.total_tables,
        });
        setUseMock(false);
      } else {
        // Fallback to mock data
        setSchema(MOCK_SCHEMA);
        setUseMock(true);
      }
    } catch {
      setSchema(MOCK_SCHEMA);
      setUseMock(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSmokeAndRefresh = useCallback(async () => {
    setSmokeLoading(true);
    setSmokeOk(null);
    try {
      const res = await fetch("/api/agent/operator", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "adw-smoke" }),
      });
      const data = await res.json();
      const ok = data.status === "ok" || data.status === "passed";
      setSmokeOk(ok);
      if (ok) await fetchSchema();
    } catch {
      setSmokeOk(false);
    } finally {
      setSmokeLoading(false);
    }
  }, [fetchSchema]);

  useEffect(() => { fetchSchema(); }, [fetchSchema]);

  const tables = schema?.selected_tables ?? [];
  const glossary = schema?.glossary_matches ?? [];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border/50 flex items-center justify-between bg-background/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[oklch(0.80_0.18_80)] to-[oklch(0.65_0.22_200)] flex items-center justify-center">
            <Database className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold">Oracle ADW Schema Inspector</h1>
            <p className="text-xs text-muted-foreground">
              {schema?.schema_name && <span className="font-mono">{schema.schema_name} · </span>}
              {schema?.total_tables && <span>{formatNumber(schema.total_tables)} tables total · </span>}
              {useMock && <span className="text-[oklch(0.80_0.18_80)]">preview data</span>}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label="스키마 갱신 요청"
            onClick={handleSmokeAndRefresh}
            disabled={smokeLoading || loading}
            className="gap-1.5 text-xs"
            style={smokeOk === true ? { borderColor: "oklch(0.70 0.18 145 / 0.5)", color: "oklch(0.70 0.18 145)" }
                 : smokeOk === false ? { borderColor: "oklch(0.65 0.22 25 / 0.5)", color: "oklch(0.65 0.22 25)" }
                 : {}}
          >
            {smokeLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
            스키마 갱신
          </Button>
          <Button type="button" variant="outline" size="sm" aria-label="Refresh" onClick={() => { setSmokeOk(null); fetchSchema(); }} disabled={loading} className="gap-1.5 text-xs">
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {useMock && (
        <div role="alert" className="px-6 py-2 flex items-center gap-2 text-xs border-b border-[oklch(0.78_0.18_80/0.3)] bg-[oklch(0.78_0.18_80/0.06)]" style={{ color: "oklch(0.80 0.18 80)" }}>
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>실제 스키마 데이터 없음 — 미리보기 데이터 표시 중. &quot;스키마 갱신&quot;을 실행하면 실제 ADW 연결을 시도합니다.</span>
        </div>
      )}

      <div className="flex-1 overflow-hidden flex">
        {/* Left: Tables */}
        <div className="flex-1 flex flex-col border-r border-border/40">
          <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
            <Table2 className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-widest">
              Selected Tables ({tables.length})
            </span>
            {schema?.query && (
              <span className="ml-auto text-xs text-muted-foreground/50 font-mono truncate max-w-[180px]">
                query: &quot;{schema.query}&quot;
              </span>
            )}
          </div>
          <ScrollArea className="flex-1">
            <div className="p-4 space-y-2">
              {tables.map((table, idx) => (
                <motion.div
                  key={table.name}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.06 }}
                  onClick={() => setSelectedTable(selectedTable?.name === table.name ? null : table)}
                  className={`rounded-lg border p-3 cursor-pointer transition-all duration-150 ${
                    selectedTable?.name === table.name
                      ? "border-primary/40 bg-primary/8 glass-strong"
                      : "border-border/30 bg-card/50 hover:border-border/60 hover:bg-card/80"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <Hash className="w-3.5 h-3.5 text-muted-foreground/60 flex-shrink-0" />
                      <span className="text-sm font-mono font-semibold text-foreground truncate">{table.name}</span>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <Star className="w-3 h-3 text-[oklch(0.80_0.18_80)]" />
                      <span className="text-xs font-mono text-[oklch(0.80_0.18_80)]">
                        {((table.score ?? 0) * 100).toFixed(0)}
                      </span>
                    </div>
                  </div>
                  <ScoreBar score={table.score ?? 0} />
                  {table.description && (
                    <p className="text-xs text-muted-foreground mt-2">{table.description}</p>
                  )}
                  {table.row_count != null && (
                    <div className="text-[10px] font-mono text-muted-foreground/50 mt-1">
                      {formatNumber(table.row_count)} rows
                    </div>
                  )}
                  {selectedTable?.name === table.name && table.columns && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      className="mt-3 pt-3 border-t border-border/30"
                    >
                      <div className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2">Columns</div>
                      <div className="flex flex-wrap gap-1">
                        {table.columns.map((col) => (
                          <span key={col} className="text-xs font-mono px-2 py-0.5 rounded-md bg-secondary/60 border border-border/30 text-muted-foreground">
                            {col}
                          </span>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </motion.div>
              ))}
              {tables.length === 0 && !loading && (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  No schema inspection data found. Run an agent query to populate.
                </div>
              )}
            </div>
          </ScrollArea>
        </div>

        {/* Right: Glossary */}
        <div className="w-72 flex flex-col">
          <div className="px-4 py-2.5 border-b border-border/30 flex items-center gap-2">
            <BookOpen className="w-3.5 h-3.5 text-muted-foreground" />
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-widest">
              Glossary ({glossary.length})
            </span>
          </div>
          <ScrollArea className="flex-1">
            <div className="p-4 space-y-2">
              {glossary.map((item, idx) => (
                <motion.div
                  key={item.term}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.07 }}
                  className="rounded-lg border border-border/30 bg-card/40 p-3 space-y-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-[oklch(0.72_0.19_280)]">{item.term}</span>
                    {item.score != null && (
                      <span className="text-[10px] font-mono text-muted-foreground/50">
                        {((item.score) * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                  {item.score != null && <ScoreBar score={item.score} />}
                  {item.definition && (
                    <p className="text-xs text-muted-foreground leading-relaxed">{item.definition}</p>
                  )}
                </motion.div>
              ))}
              {glossary.length === 0 && (
                <div className="text-center py-8 text-muted-foreground text-sm">No glossary matches</div>
              )}
            </div>
          </ScrollArea>
        </div>
      </div>
    </div>
  );
}
