# Supported Scope

This document defines the intended support boundary for the Open Agent v1.0 release line.

Open Agent is feature-rich enough that unsupported assumptions can become operational bugs very quickly. The goal of this document is to make the supported model explicit.

## Supported in v1.0

### Runtime model

- one FastAPI application process
- one in-memory manager graph loaded during server lifespan
- one scheduler running in-process
- one writable local data directory under `~/.open-agent/`

### Storage model

- SQLite as the default local database
- PostgreSQL through `DATABASE_URL`
- Alembic-driven schema upgrades
- legacy JSON import support during startup migration

### Auth and access

- JWT bearer authentication
- API key authentication through `X-API-Key`
- role-based access control with `admin`, `user`, and `viewer`
- owner-aware access boundaries for sessions, memory, runs, jobs, workspaces, and pages

### API surface

The following route groups are part of the supported surface:

- `/api/auth`
- `/api/chat`
- `/api/mcp`
- `/api/skills`
- `/api/pages`
- `/api/settings`
- `/api/sessions`
- `/api/memory`
- `/api/workspace`
- `/api/jobs`
- `/api/runs`
- `/api/sandbox`

### Operational endpoints

- `/api/settings/health`
- `/api/settings/readiness`
- `/api/settings/version`
- `/api/host-info`

### Hosted content

- hosted pages under `/hosted/*`

## Explicitly not supported in v1.0

### Runtime topologies

- multiple API workers sharing mutable singleton manager state
- distributed scheduler execution
- active-active clustering
- high-availability orchestration guarantees

### Packaging and deployment targets

- Kubernetes as an official reference target
- Docker as the only or primary supported deployment path
- zero-downtime upgrade guarantees

### Product surface

- a bundled private web UI from this repository
- frontend source-level extensibility from this repository
- native acceleration binary distribution from this repository
- a stable plugin marketplace or extension API
- multi-tenant control-plane features beyond current owner-aware data access

## Stability expectations

### Expected to remain stable through v1.x

- core auth API shapes
- current route prefixes
- persistent run/session/memory/workspace/page/job storage model at the HTTP layer
- CLI entrypoints `open-agent start`, `open-agent init`, `open-agent config`, `open-agent update`

### May still evolve during v1.x

- readiness check composition
- internal manager implementations
- release automation details
- deployment guidance documents
- exact observability surface

## Compatibility notes

- Open Agent should be treated as a **single-process service** unless explicit future documentation says otherwise.
- The open-source repository does not include the private web UI build artifacts or native acceleration binaries.
- If a deployment requires stronger guarantees than the above, it should be treated as out of scope for v1.0 rather than assumed to work.
