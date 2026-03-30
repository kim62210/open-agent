# Upgrade Guide

This document describes the safest currently supported upgrade path for Open Agent.

## Supported upgrade scenarios

- `v0.8.x` to a newer `v0.8.x` or `v1.0.x`
- local SQLite deployment
- PostgreSQL deployment with explicit Alembic upgrade

## Before upgrading

1. note the currently running version
2. stop any background operational changes (manual job edits, MCP config churn, hosted page maintenance)
3. back up:
   - database
   - `~/.open-agent/.env`
   - hosted page files
   - user-created skills

## Upgrade procedure

### 1. Fetch the new code or release

If you are upgrading from git:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
```

If you are upgrading through the CLI helper:

```bash
uv run open-agent update
```

## 2. Reinstall the environment

```bash
uv sync --group dev
```

## 3. Apply schema upgrades

```bash
uv run alembic upgrade head
```

This step should be treated as mandatory for production-style upgrades.

## 4. Start the service

```bash
uv run open-agent start
```

## 5. Verify runtime health

```bash
curl http://127.0.0.1:4821/api/settings/health
curl http://127.0.0.1:4821/api/settings/readiness
```

## Legacy JSON migration note

Open Agent still includes `core/db/migrate.py` to import legacy JSON state into the database on startup.

Current behavior:

- migration is idempotent
- `.migrated` is only written when import steps complete successfully
- failed migration steps should be investigated before retrying startup at scale

For existing installs that already migrated, the normal path is:

1. Alembic upgrade
2. startup
3. readiness verification

## Upgrade smoke checklist

After upgrade, verify at least the following:

- login works
- `/api/chat` returns a valid response
- `/api/chat/async` creates a run and `/api/runs/{id}/status` works
- workspace listing works
- MCP server listing works
- jobs can still be listed and toggled

## If the upgrade fails

### SQLite rollback

1. stop the process
2. restore the previous `~/.open-agent/open_agent.db`
3. restore the previous application code version
4. restart and re-check health/readiness

### PostgreSQL rollback

Use your database snapshot or backup strategy, then restore the prior application version.

## Known limitations

- Open Agent does not yet provide zero-downtime upgrade orchestration.
- The reference deployment remains single-process.
- Major version jump guarantees are not yet documented beyond the repository changelog and migration revisions.
