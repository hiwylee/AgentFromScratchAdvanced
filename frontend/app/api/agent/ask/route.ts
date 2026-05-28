import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";

const AGENT_BIN = process.env.AGENT_BIN_PATH ?? "/Users/wylee/WorkspacesV2/AgentFromScratch/bin/agent";
const RUN_DIR = process.env.AGENT_RUN_DIR ?? "/tmp/afs-runs";
const AUDIT_LOG = process.env.AGENT_AUDIT_LOG ?? "/tmp/afs.jsonl";
const PROJECT_DIR = process.env.AGENT_PROJECT_DIR ?? "/opt/AgentFromScratch";
const MEMORY_DIR = process.env.AGENT_MEMORY_DIR ?? path.join(PROJECT_DIR, "artifacts/memory");

export async function POST(req: NextRequest) {
  try {
    const { query } = await req.json();
    if (!query || typeof query !== "string") {
      return NextResponse.json({ error: "Missing query" }, { status: 400 });
    }

    const result = await runAgent([
      "ask",
      query,
      "--run-dir", RUN_DIR,
      "--audit-log", AUDIT_LOG,
      "--memory-dir", MEMORY_DIR,
    ]);

    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function runAgent(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const agentPath = path.resolve(AGENT_BIN);
    const proc = spawn(agentPath, args, {
      cwd: PROJECT_DIR,
      env: { ...process.env, UV_CACHE_DIR: process.env.UV_CACHE_DIR ?? path.join(PROJECT_DIR, ".uv-cache") },
      timeout: 60000,
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (d) => { stdout += d.toString(); });
    proc.stderr.on("data", (d) => { stderr += d.toString(); });

    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`Agent exited ${code}: ${stderr || stdout}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout.trim()));
      } catch {
        resolve({ raw: stdout, stderr });
      }
    });

    proc.on("error", (err) => {
      reject(new Error(`Failed to spawn agent: ${err.message}`));
    });
  });
}
