import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";

const AGENT_BIN = process.env.AGENT_BIN_PATH ?? "/Users/wylee/WorkspacesV2/AgentFromScratchAdvanced/bin/agent";
const PROJECT_DIR = process.env.AGENT_PROJECT_DIR ?? "/Users/wylee/WorkspacesV2/AgentFromScratchAdvanced";

function runAgent(args: string[]): Promise<string> {
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
      if (code !== 0) { reject(new Error(`Agent exited ${code}: ${stderr || stdout}`)); return; }
      resolve(stdout.trim());
    });
    proc.on("error", (err) => { reject(new Error(`Failed to spawn agent: ${err.message}`)); });
  });
}

// GET /api/agent/tacit?action=list|heuristics|reflect&episode_id=<uuid>
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const action = searchParams.get("action") ?? "list";

  try {
    if (action === "list") {
      const raw = await runAgent(["tacit", "list", "--output", "json"]);
      try {
        const parsed = JSON.parse(raw);
        const episodes = Array.isArray(parsed) ? parsed : parsed.episodes ?? [];
        return NextResponse.json({ episodes });
      } catch {
        // CLI may output plain text lines — return as-is with empty episodes
        return NextResponse.json({ episodes: [], raw });
      }
    }

    if (action === "heuristics") {
      const raw = await runAgent(["tacit", "heuristics", "--output", "json"]);
      try {
        const parsed = JSON.parse(raw);
        const heuristics = Array.isArray(parsed) ? parsed : parsed.heuristics ?? [];
        return NextResponse.json({ heuristics });
      } catch {
        // Parse line-by-line if not JSON
        const heuristics = raw.split("\n").map((l) => l.trim()).filter(Boolean);
        return NextResponse.json({ heuristics });
      }
    }

    if (action === "reflect") {
      const episodeId = searchParams.get("episode_id");
      if (!episodeId || !/^[a-zA-Z0-9_-]+$/.test(episodeId)) {
        return NextResponse.json({ error: "Missing or invalid episode_id" }, { status: 400 });
      }
      const raw = await runAgent(["tacit", "reflect", "--episode-id", episodeId, "--output", "json"]);
      try {
        return NextResponse.json(JSON.parse(raw));
      } catch {
        return NextResponse.json({ raw });
      }
    }

    return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 400 });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
