# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS ui-deps
WORKDIR /src/ui

COPY package.json package-lock.json .env.local.example ./
RUN npm ci

FROM ui-deps AS ui-build
WORKDIR /src/ui
COPY . .
RUN npm run build

FROM node:22-bookworm-slim AS node-runtime

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    AGENT_BIN_PATH=/opt/AgentFromScratch/bin/agent \
    AGENT_PROJECT_DIR=/opt/AgentFromScratch \
    AGENT_RUN_DIR=/data/afs-runs \
    AGENT_AUDIT_LOG=/data/afs.jsonl \
    AGENT_WORKFLOW_RUN_DIR=/data/afs-wf \
    AGENT_WORKFLOW_AUDIT_LOG=/data/afs-wf.jsonl \
    AGENT_MEMORY_DIR=/opt/AgentFromScratch/artifacts/memory \
    UV_CACHE_DIR=/data/uv-cache

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=ui-build /src/ui/.next/standalone ./
COPY --from=ui-build /src/ui/.next/static ./.next/static
COPY --from=ui-build /src/ui/public ./public

COPY --from=agent-src /agent_runtime /opt/AgentFromScratch/agent_runtime
COPY --from=agent-src /artifacts /opt/AgentFromScratch/artifacts
COPY --from=agent-src /bin /opt/AgentFromScratch/bin
COPY --from=agent-src /docs /opt/AgentFromScratch/docs
COPY --from=agent-src /pyproject.toml /opt/AgentFromScratch/pyproject.toml
COPY --from=agent-src /uv.lock /opt/AgentFromScratch/uv.lock
COPY --from=agent-src /README.md /opt/AgentFromScratch/README.md

RUN chmod +x /opt/AgentFromScratch/bin/agent \
    && mkdir -p /data/afs-runs /data/afs-wf /data/uv-cache \
    && cd /opt/AgentFromScratch \
    && uv sync --frozen

EXPOSE 3000

CMD ["node", "server.js"]
