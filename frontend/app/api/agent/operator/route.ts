import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";

const AGENT_BIN = process.env.AGENT_BIN_PATH ?? "/Users/wylee/WorkspacesV2/AgentFromScratch/bin/agent";
const AUDIT_LOG = process.env.AGENT_AUDIT_LOG ?? "/tmp/afs.jsonl";
const PROJECT_DIR = process.env.AGENT_PROJECT_DIR ?? "/opt/AgentFromScratch";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { action, sql, candidate_id, reviewer, notes } = body as {
      action: string;
      sql?: string;
      candidate_id?: string;
      reviewer?: string;
      notes?: string;
    };

    const VALID_ACTIONS = [
      "adw-smoke", "adw-query", "adw-provision",
      "review-candidates", "review-candidate-show",
      "review-candidate-approve", "review-candidate-reject",
    ];
    if (!VALID_ACTIONS.includes(action)) {
      return NextResponse.json({ error: "Unknown action" }, { status: 400 });
    }

    if (action === "adw-query") {
      if (!sql || typeof sql !== "string") {
        return NextResponse.json({ error: "Missing sql" }, { status: 400 });
      }
      if (!/^\s*SELECT\b/i.test(sql)) {
        return NextResponse.json({ error: "Only SELECT queries are allowed" }, { status: 400 });
      }
      const result = await runAgent(
        ["operator", "adw-query", "--sql", sql, "--confirm-live-adw-query", "--audit-log", AUDIT_LOG],
        60000
      );
      return NextResponse.json(result);
    }

    if (action === "adw-smoke") {
      const result = await runAgent(
        ["operator", "adw-smoke", "--confirm-live-adw-smoke", "--audit-log", AUDIT_LOG],
        60000
      );
      return NextResponse.json(result);
    }

    if (action === "adw-provision") {
      const result = await runAgent(
        ["operator", "adw-provision-working-user",
         "--grant-profile", "prototype-any-table-read",
         "--confirm-live-adw-admin-provision",
         "--audit-log", AUDIT_LOG],
        90000
      );
      return NextResponse.json(result);
    }

    if (action === "review-candidates") {
      const result = await runAgent(
        ["operator", "review-candidate", "list", "--audit-log", AUDIT_LOG],
        15000
      );
      return NextResponse.json(result);
    }

    // validate candidate_id for show/approve/reject
    if (!candidate_id || !/^[a-zA-Z0-9._-]+$/.test(candidate_id)) {
      return NextResponse.json({ error: "Invalid or missing candidate_id" }, { status: 400 });
    }

    if (action === "review-candidate-show") {
      const result = await runAgent(
        ["operator", "review-candidate", "show", "--candidate-id", candidate_id, "--audit-log", AUDIT_LOG],
        15000
      );
      return NextResponse.json(result);
    }

    if (!reviewer || typeof reviewer !== "string" || !reviewer.trim()) {
      return NextResponse.json({ error: "Missing reviewer" }, { status: 400 });
    }

    if (action === "review-candidate-approve") {
      const result = await runAgent(
        ["operator", "review-candidate", "approve",
         "--candidate-id", candidate_id, "--reviewer", reviewer.trim(),
         "--audit-log", AUDIT_LOG],
        15000
      );
      return NextResponse.json(result);
    }

    // review-candidate-reject
    const args = ["operator", "review-candidate", "reject",
      "--candidate-id", candidate_id, "--reviewer", reviewer.trim(),
      "--audit-log", AUDIT_LOG];
    if (notes && notes.trim()) args.push("--notes", notes.trim());
    const result = await runAgent(args, 15000);
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function runAgent(args: string[], timeout: number): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const agentPath = path.resolve(AGENT_BIN);
    const proc = spawn(agentPath, args, {
      cwd: PROJECT_DIR,
      env: { ...process.env, UV_CACHE_DIR: process.env.UV_CACHE_DIR ?? path.join(PROJECT_DIR, ".uv-cache") },
      timeout,
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
