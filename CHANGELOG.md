# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project targets [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Historical entries before formal release tagging were reconstructed from commit history, package metadata, and repository documentation. The repository currently does not publish a complete version tag history for every milestone.

## [Unreleased]

### Added
- Ownership-aware persistence across sessions, memories, jobs, workspaces, and pages via `owner_user_id` columns and repository/manager filtering.
- Run ledger persistence with `RunORM` and `RunEventORM`, plus `/api/runs` endpoints for run inspection.
- Asynchronous run controls:
  - `POST /api/chat/async`
  - `GET /api/runs/{run_id}/status`
  - `POST /api/runs/{run_id}/abort`
- Task supervision infrastructure in `core/task_supervisor.py` for tracked background tasks.
- Readiness reporting via `GET /api/settings/readiness`.

### Changed
- MCP and sandbox mutation endpoints now require stricter admin access.
- MCP server configuration responses redact sensitive header and environment values.
- Chat requests now persist run lifecycle events before and after execution.
- Startup behavior now treats `gh auth token` auto-import as a development-only convenience.

### Fixed
- Refresh token rotation now revokes the old token and issues a new refresh token on refresh.
- Auth dependencies populate `request.state.user` for downstream request context.
- JSON-to-DB migration no longer writes the `.migrated` marker when import steps fail.
- Background session-summary and job-scheduler tasks are now tracked instead of being fire-and-forget.

### Security
- Added risk-based approval primitives for MCP allowlists and tool gating.
- Tightened resource ownership boundaries to prevent cross-user access to persisted records.

### Operations
- `init_db()` now gates `create_all()` behind development/bootstrap flags instead of always executing schema creation in production-style startup paths.

## [0.8.6] - 2026-03-29

### Added
- JWT authentication, API key authentication, refresh tokens, and role-based access control for browser and programmatic clients.
- Async SQLAlchemy persistence with SQLite as the default database and PostgreSQL override support via `DATABASE_URL`.
- JSON-to-database migration support for legacy installs.
- Structured logging via `structlog`, request correlation IDs, and a FastAPI request logging middleware.
- Pydantic v2 model strengthening across auth, sessions, memory, jobs, pages, settings, and MCP models.
- Public health and version endpoints under `/api/settings`.

### Changed
- Core managers moved from JSON-file persistence to async repositories backed by SQLAlchemy models.
- The FastAPI lifespan now initializes the database, migrates legacy JSON state, loads managers from persistence, and starts the scheduler.
- The project standardized on `pyproject.toml`, dependency groups, `ruff`, `pytest`, and `mypy` as the primary development workflow.

### Fixed
- Request-state isolation for workflow routing and other mutable per-request runtime state.
- Silent exception swallowing in several core modules through improved logging and exception handling.
- Concurrency hazards in singleton managers through `asyncio.Lock`-guarded mutation paths.

## [0.8.5] - 2026-03-29

### Added
- Async SQLAlchemy repository layer.
- SQLite WAL mode support and PostgreSQL URL translation.
- Domain repositories for sessions, memory, settings, jobs, workspaces, pages, skills, MCP configuration, and users.

### Changed
- Managers now persist state to the database rather than directly to JSON files.

## [0.8.4] - 2026-03-29

### Added
- `pyproject.toml` packaging and dependency-group setup.
- Structured logging and request logging middleware.
- Initial test and coverage configuration.
- Domain-specific exception hierarchy under `OpenAgentError`.

### Changed
- Error handling paths were normalized across the API and core runtime.

## [0.8.0] - 2026-03-29

### Added
- Initial FastAPI server and static web application serving.
- LiteLLM-backed multi-provider LLM support.
- MCP integration for stdio, SSE, and streamable HTTP servers.
- SKILL.md-based skill discovery and execution.
- Persistent session and memory concepts.
- Workspace tools, hosted pages, and scheduled jobs.

> Release comparison links are intentionally omitted until the repository adopts a stable public tag history.
