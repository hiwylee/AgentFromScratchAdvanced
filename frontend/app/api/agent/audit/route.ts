import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const AUDIT_LOG = process.env.AGENT_AUDIT_LOG ?? "/tmp/afs.jsonl";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const eventFilter = searchParams.get("event") ?? "";
    const limit = parseInt(searchParams.get("limit") ?? "200", 10);

    const logPath = path.resolve(AUDIT_LOG);

    if (!fs.existsSync(logPath)) {
      return NextResponse.json({ entries: [], total: 0 });
    }

    const raw = fs.readFileSync(logPath, "utf-8");
    const lines = raw.trim().split("\n").filter(Boolean);

    const entries = lines
      .map((line, idx) => {
        try {
          return { ...JSON.parse(line), _line: idx + 1 };
        } catch {
          return { _line: idx + 1, _raw: line, event: "parse_error" };
        }
      })
      .filter((e) => !eventFilter || e.event === eventFilter)
      .slice(-limit)
      .reverse();

    const eventTypes = [...new Set(lines.map((l) => {
      try { return JSON.parse(l).event ?? "unknown"; } catch { return "unknown"; }
    }))];

    return NextResponse.json({ entries, total: lines.length, eventTypes });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message, entries: [] }, { status: 200 });
  }
}
