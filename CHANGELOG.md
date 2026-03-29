# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Docker containerization and docker-compose for local development
- CI/CD pipeline (GitHub Actions: lint, test, build)
- Observability (metrics, distributed tracing)

---

## [0.8.6] - 2026-03-29

### Added — Sprint 3: Authentication & Authorization
- **JWT authentication** with access tokens (30min) and refresh tokens (7 days) with automatic rotation
- **API key authentication** via `X-API-Key` header for programmatic access (SHA-256 hashed storage)
- **Role-based access control (RBAC)** with three roles: `admin`, `user`, `viewer`
- **Rate limiting** via slowapi — register/login: 5/min, chat: 20/min, stream: 10/min
- **Auth API endpoints** (11 routes): register, login, refresh, logout, profile, API key CRUD, admin user management
- **Password hashing** with Argon2 via pwdlib
- **Auto-admin**: first registered user automatically receives `admin` role
- **JWT secret auto-generation**: persisted to `~/.open-agent/.jwt_secret` if not set via env
- All existing endpoints now require authentication with appropriate role checks
- Health check and version endpoints remain public
- 28 new auth tests: JWT (8), password (5), auth API (15)
- Dependencies: `PyJWT[crypto]>=2.9.0`, `pwdlib[argon2]>=0.2.0`, `slowapi>=0.1.9`

### Added — New ORM Models
- `UserORM` — user accounts with email, username, password hash, role, active status
- `APIKeyORM` — API keys with SHA-256 hash, prefix, name, last_used tracking
- `RefreshTokenORM` — refresh tokens with user association and revocation support

### Added — New Repositories
- `UserRepository` — user CRUD with email lookup
- `APIKeyRepository` — API key CRUD with hash-based lookup
- `RefreshTokenRepository` — token CRUD with cleanup

### Changed
- All API endpoints now require JWT or API key authentication
- `chat.py`: renamed `request` parameter to `body` for slowapi compatibility
- `conftest.py`: added `test_user`, `auth_headers`, `auth_client` fixtures; existing tests use `dependency_overrides` to bypass auth

---

## [0.8.5] - 2026-03-29

### Added — Sprint 2: Database Layer
- **Async SQLAlchemy 2.0** with `aiosqlite` backend (zero-config SQLite default)
- **PostgreSQL support** via `DATABASE_URL` environment variable override
- **SQLite WAL mode** with busy_timeout=5000 for concurrent read/write
- **12 ORM models** mapping all existing Pydantic schemas to database tables
- **Generic `BaseRepository[T]`** with `get_by_id`, `get_all`, `create`, `update`, `delete_by_id`
- **8 domain repositories**: session, memory, settings, job, workspace, page, skill_config, mcp_config
- **JSON → DB migration utility** (`core/db/migrate.py`): one-time, idempotent migration with `.migrated` marker
- Per-file error isolation during migration — individual failures don't block others
- Dependencies: `sqlalchemy[asyncio]>=2.0.36`, `aiosqlite>=0.20.0`

### Changed
- All 8 managers migrated from JSON file I/O to async database repositories
- `settings_manager`: single-row `SettingsORM` with in-memory cache
- `session_manager`: `SessionORM` + `SessionMessageORM`, removed `sessions/` file I/O
- `memory_manager`: `MemoryORM` + `SessionSummaryORM`, LLM logic unchanged
- `workspace_manager`: metadata to DB, filesystem operations unchanged
- `mcp_manager`: config to DB, runtime connections stay in-memory
- `job_manager`: `JobORM` + `JobRunRecordORM`
- `page_manager`: metadata to DB, HTML file operations unchanged
- `skill_manager`: disabled list to DB, filesystem discovery unchanged
- All API endpoints updated for `await` on async manager methods
- `server.py` lifespan: added `init_db()` / `close_db()` calls, JSON migration
- `conftest.py`: rewritten for in-memory SQLite backend (no JSON files)

---

## [0.8.4] - 2026-03-29

### Added — Sprint 1: Foundation
- **`pyproject.toml`** with hatchling build system and PEP 735 dependency-groups
- 13 runtime dependencies declared (fastapi, litellm, mcp, structlog, etc.)
- Separate dependency groups: `dev`, `lint` (ruff, mypy), `test` (pytest, pytest-asyncio, pytest-cov)
- **Structured logging** via structlog: dev mode (colored console), prod mode (JSON)
- `core/logging.py`: `setup_logging()` with environment-based format auto-switching
- `api/middleware.py`: `RequestLoggingMiddleware` with UUID `request_id` and `X-Request-ID` header
- **Custom exception hierarchy** in `core/exceptions.py`: 18 domain exception classes under `OpenAgentError`
- 12 global exception handlers in `server.py` mapping exceptions to HTTP status codes
- **Pydantic V2 type strengthening** across all models:
  - `OpenAgentBase` shared base class with `ConfigDict(from_attributes=True, use_enum_values=True)`
  - `ErrorResponse` standard error schema
  - `JobRunStatus`, `JobScheduleType` enums in `job.py`
  - `MessageRole` enum in `session.py`
  - `MCPTransport` enum in `mcp.py`
  - `Literal` types for `reasoning_effort`, `theme.mode` in `settings.py`
- **Test framework** with 50 tests:
  - `tests/unit/test_session_manager.py` (16 tests)
  - `tests/unit/test_memory_manager.py` (22 tests)
  - `tests/integration/test_sessions_api.py` (12 tests)
  - `conftest.py` with 5 isolated fixtures

### Changed
- Replaced 36 `ValueError` raises with domain-specific exceptions across 8 core modules
- Removed unnecessary `try/except` blocks in 4 API endpoint files
- Added exception chaining (`from e`) to all re-raises

---

## [0.8.0] - 2026-03-29

### Added — Initial Release
- FastAPI async backend with SSE streaming
- Multi-LLM support via LiteLLM (OpenAI, Anthropic, Google, 100+ providers)
- MCP integration (stdio, SSE, streamable-http transports)
- Agent skill system using SKILL.md standard (YAML frontmatter + Markdown)
- Persistent memory (L1 long-term + L2 session summaries)
- Workspace tools (file read/write/edit, regex search, sandboxed shell)
- Cron-based job scheduler with agent execution
- Pre-built Next.js web UI served as static export
- Rust native extensions for grep, fuzzy matching, sandboxing (with Python fallback)
- OS-native sandboxing (macOS Seatbelt, Linux bwrap)
- Click CLI entrypoint (`open-agent start`)
- 8 bundled skills: implementation, test, plan, debug, review, find, coding-pipeline, skill-creator

[Unreleased]: https://github.com/kim62210/open-agent/compare/v0.8.6...HEAD
[0.8.6]: https://github.com/kim62210/open-agent/compare/v0.8.5...v0.8.6
[0.8.5]: https://github.com/kim62210/open-agent/compare/v0.8.4...v0.8.5
[0.8.4]: https://github.com/kim62210/open-agent/compare/v0.8.0...v0.8.4
[0.8.0]: https://github.com/kim62210/open-agent/releases/tag/v0.8.0
