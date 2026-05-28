# Frontend Architecture

## Overview

`frontend/` is a Next.js 14 App Router application that provides a web UI for the agent runtime backend. It communicates exclusively via `bin/agent` CLI subprocess calls — no direct Python or database connections from the browser layer.

**Stack:** Next.js 14 · TypeScript · Tailwind CSS · shadcn/ui · Dark terminal-aesthetic

---

## Directory Structure

```
frontend/
  app/
    page.tsx                      # Chat — agent ask (natural-language query)
    status/page.tsx               # Run status monitor (live polling)
    audit/page.tsx                # Audit log viewer (JSONL table)
    workflow/page.tsx             # Workflow runner + human gate
    memory/page.tsx               # Memory record viewer
    operator/page.tsx             # Operator controls
    schema/page.tsx               # Oracle ADW schema inspector
    layout.tsx                    # Sidebar nav + global layout
    globals.css                   # Tailwind base + dark theme tokens

    api/agent/
      ask/route.ts                # POST → spawns bin/agent ask
      status/route.ts             # GET  → reads run status JSON
      audit/route.ts              # GET  → reads audit JSONL
      workflow/route.ts           # POST → spawns bin/agent workflow
      workflow/approve/route.ts   # POST → workflow resume (human gate decision)
      memory/route.ts             # GET  → reads artifacts/memory
      operator/route.ts           # POST → operator commands

  components/
    Sidebar.tsx                   # Navigation sidebar
    StatusBadge.tsx               # Run/step status indicator
    ui/                           # shadcn/ui components (button, input, table, etc.)

  lib/
    types.ts                      # TypeScript types for agent API responses
    auditColors.ts                # Event-type → color mapping for audit log
    errors.ts                     # Typed error helpers
    utils.ts                      # cn() class merge helper
```

---

## API Route Design

All API routes follow the same pattern:
1. Read environment variables (`AGENT_BIN_PATH`, `AGENT_PROJECT_DIR`, etc.)
2. Spawn `bin/agent` CLI subprocess with appropriate arguments
3. Parse stdout as JSON
4. Return structured response

No route connects directly to Oracle ADW, Python modules, or the filesystem outside the run/audit directories.

### Key Routes

| Route | Method | Backend Command |
|---|---|---|
| `/api/agent/ask` | POST | `bin/agent ask "<query>"` |
| `/api/agent/status` | GET | reads `{run_dir}/latest/status.json` |
| `/api/agent/audit` | GET | reads `{audit_log}` JSONL |
| `/api/agent/workflow` | POST | `bin/agent workflow "<query>"` |
| `/api/agent/workflow/approve` | POST | `bin/agent workflow resume --decision ...` |
| `/api/agent/memory` | GET | reads `artifacts/memory/*.json` |
| `/api/agent/operator` | POST | `bin/agent operator <cmd>` |

---

## Environment Configuration

`frontend/.env.local` (git-ignored, copy from `.env.local.example`):

```bash
AGENT_BIN_PATH=/path/to/AgentFromScratchAdvanced/bin/agent
AGENT_PROJECT_DIR=/path/to/AgentFromScratchAdvanced
AGENT_RUN_DIR=/tmp/afs-runs
AGENT_AUDIT_LOG=/tmp/afs.jsonl
AGENT_WORKFLOW_RUN_DIR=/tmp/afs-wf
AGENT_WORKFLOW_AUDIT_LOG=/tmp/afs-wf.jsonl
AGENT_MEMORY_DIR=/path/to/AgentFromScratchAdvanced/artifacts/memory
```

---

## Development

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run build    # production build
npm run lint
```

---

## Deployment

A `Dockerfile` and `docker-swarm.yml` are provided for containerized deployment. The container expects environment variables to be injected at runtime. The `bin/agent` binary and its Python dependencies must be accessible at `AGENT_BIN_PATH`.

---

## Design Decisions

**CLI subprocess over API**: The frontend calls `bin/agent` as a subprocess rather than importing Python modules or exposing a REST API. This keeps the UI layer fully decoupled from backend implementation details and means any backend refactor that keeps the CLI interface stable requires zero frontend changes.

**No direct DB access**: Oracle ADW credentials never reach the Next.js process. All sensitive operations go through the Python backend's `redact()` layer.

**Polling for status**: The status page polls `/api/agent/status` on a short interval rather than using WebSockets. This is intentional simplicity — the agent runs are short-lived and the added complexity of a persistent connection is not justified.
