import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const AGENT_BIN = process.env.AGENT_BIN_PATH ?? "/Users/wylee/WorkspacesV2/AgentFromScratch/bin/agent";
const PROJECT_DIR = process.env.AGENT_PROJECT_DIR ?? "/opt/AgentFromScratch";

const ALLOWED_DIR = path.resolve(PROJECT_DIR, "artifacts/memory");

function safeAbsPath(relPath: string): string | null {
  const abs = path.resolve(PROJECT_DIR, relPath);
  if (abs !== ALLOWED_DIR && !abs.startsWith(ALLOWED_DIR + path.sep)) return null;
  return abs;
}

export async function GET() {
  try {
    const memDir = ALLOWED_DIR;
    let files: string[] = [];
    try {
      files = fs.readdirSync(memDir).filter((f) => f.endsWith(".json"));
    } catch {
      return NextResponse.json({ records: [] });
    }

    const records = files.flatMap((f) => {
      const relPath = path.join("artifacts/memory", f);
      const absPath = path.join(PROJECT_DIR, relPath);
      try {
        const parsed = JSON.parse(fs.readFileSync(absPath, "utf-8"));
        return [{ ...parsed, _path: relPath }];
      } catch {
        return [];
      }
    });

    return NextResponse.json({ records });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ records: [], error: message }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const { path: relPath, status } = await req.json();
    if (!["active", "proposed"].includes(status)) {
      return NextResponse.json({ error: "status must be 'active' or 'proposed'" }, { status: 400 });
    }
    const absPath = safeAbsPath(relPath);
    if (!absPath) return NextResponse.json({ error: "Invalid path" }, { status: 403 });
    const parsed = JSON.parse(fs.readFileSync(absPath, "utf-8"));
    parsed.status = status;
    fs.writeFileSync(absPath, JSON.stringify(parsed, null, 2), "utf-8");
    return NextResponse.json({ ok: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const { path: relPath } = await req.json();
    const absPath = safeAbsPath(relPath);
    if (!absPath) return NextResponse.json({ error: "Invalid path" }, { status: 403 });
    fs.unlinkSync(absPath);
    return NextResponse.json({ ok: true });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
