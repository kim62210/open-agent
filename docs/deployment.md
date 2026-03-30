# Deployment Guide

This document describes the currently supported deployment path for Open Agent.

Open Agent is not yet a multi-process or clustered product. The supported deployment model for v1.0 is a **single-process self-hosted instance** using either:

- SQLite for low-friction local or single-user deployment, or
- PostgreSQL for multi-user deployments that need an external database.

## Supported deployment model

### What is supported

- one FastAPI process started via `open-agent start` or `uvicorn`
- one writable data directory under `~/.open-agent/`
- one database backend per instance
- outbound access to configured LLM providers and MCP servers

### What is not yet supported as a first-class deployment target

- multiple API workers sharing in-memory singleton state
- distributed scheduler execution
- active-active clustering
- container orchestration as the official reference deployment

## Prerequisites

- Python 3.13+
- `uv`
- Git
- a writable filesystem for `~/.open-agent/`

Optional:

- PostgreSQL if you do not want to run on SQLite

## Installation

```bash
git clone https://github.com/kim62210/open-agent.git
cd open-agent
uv sync --group dev
uv run open-agent init
```

## Environment configuration

Edit `~/.open-agent/.env`.

At minimum, configure one provider key that matches your selected model.

Example:

```bash
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/open_agent
```

If `DATABASE_URL` is omitted, Open Agent defaults to SQLite at:

```text
~/.open-agent/open_agent.db
```

## Database preparation

Open Agent now uses Alembic revisions under `alembic/versions/` and also retains legacy JSON import support.

Before a production-style start, run:

```bash
uv run alembic upgrade head
```

This is the preferred schema path for existing or externally managed databases.

## Starting the service

### Development mode

```bash
uv run open-agent start --dev
```

Use this only for local development. It enables development-oriented behavior such as permissive CORS and other convenience flows.

### Production-style single-process mode

```bash
uv run open-agent start
```

### Direct uvicorn invocation

```bash
uv run uvicorn open_agent.server:app --host 127.0.0.1 --port 4821
```

If you want LAN exposure:

```bash
uv run open-agent start --expose
```

Be aware that this changes host binding behavior and broadens access to the API surface.

## Post-start verification

### Health

```bash
curl http://127.0.0.1:4821/api/settings/health
```

### Readiness

```bash
curl http://127.0.0.1:4821/api/settings/readiness
```

Readiness currently checks:

- settings initialized
- MCP config object loaded
- scheduler task running

### Auth bootstrap

Create the first user:

```bash
curl -X POST http://127.0.0.1:4821/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "username": "admin",
    "password": "change-me-now"
  }'
```

## Operational notes

### Scheduler

The job scheduler is started during FastAPI lifespan startup and stopped during shutdown. If readiness is false because the scheduler is not running, treat that as an operational fault.

### MCP

MCP configs are loaded at startup. An empty or broken MCP config changes readiness semantics, so validate MCP setup before putting the instance behind automated health checks.

### Data directory

The following should be backed up together:

- `~/.open-agent/.env`
- the database (`open_agent.db` or external DB)
- hosted page assets under `~/.open-agent/pages/`
- user-created skills under `~/.open-agent/skills/`

## Rollback model

The safest rollback model today is:

1. stop the application
2. restore the previous database state or external DB snapshot
3. restore `~/.open-agent/` assets if they changed
4. restart and re-check `/health` and `/readiness`

Open Agent does not yet provide first-class in-app rollback orchestration.
