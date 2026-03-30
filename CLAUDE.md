# Open Agent — Project Context for AI Assistants

This file provides the context needed to contribute to this codebase effectively.

## Project Overview

Open Agent is a **local-first AI agent platform** built with Python/FastAPI. It connects to 100+ LLM providers via LiteLLM, integrates external tools through MCP (Model Context Protocol), and supports an extensible skill system using the SKILL.md standard.

**Current version**: 0.8.6
**Status**: Beta — core features stable, Sprint 4 (Operations) pending

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.13+ |
| Web Framework | FastAPI (async) with uvicorn |
| LLM Abstraction | LiteLLM (100+ providers) |
| Tool Protocol | MCP (stdio, SSE, streamable-http) |
| Database | SQLAlchemy 2.0 async + aiosqlite (default: SQLite WAL) |
| Auth | PyJWT + Argon2 (pwdlib) + slowapi rate limiting |
| Models | Pydantic V2 (ConfigDict, field_validator, Enum, Literal) |
| Logging | structlog (dev: console, prod: JSON) |
| Testing | pytest + pytest-asyncio + httpx |
| Linting | ruff (E, W, F, I, B, C4, UP, ASYNC, RUF, FAST) |
| Build | hatchling with PEP 735 dependency-groups |
| Frontend | Pre-built Next.js static export (source not yet open) |
| Native Extensions | Rust CPython module (nexus_rust/) with Python fallback |

## Architecture Decisions

### Database
- **SQLite is the default** — zero configuration, WAL mode for concurrency, single-connection pool
- PostgreSQL via `DATABASE_URL` env var for multi-user deployments
- All managers use the Repository pattern (`BaseRepository[T]`) — never raw SQL in business logic
- **Alembic** for schema migrations — run `uv run alembic upgrade head` after model changes
- Legacy JSON files are auto-migrated on first startup (one-time, idempotent)

### Concurrency
- All 7 manager singletons protected with `asyncio.Lock` on mutation paths
- Per-request state isolation via `_RequestState` dataclass in `core/agent.py`
- Deadlock-safe pattern: internal calls use `_*_unlocked()` private methods

### Authentication
- **Dual auth**: JWT Bearer tokens (browser) + `X-API-Key` header (programmatic)
- Three roles: `admin`, `user`, `viewer` — enforced via `RoleChecker` dependency
- First registered user auto-gets `admin` role
- JWT secret auto-generated and persisted to `~/.open-agent/.jwt_secret`
- Refresh token rotation: old token revoked on each refresh

### Agent Loop
- ReAct pattern (Reason + Act) in `core/agent.py`
- Deferred tool loading via `find_tools` meta-tool (saves LLM context window)
- L1/L2 memory: L1 = long-term extracted facts, L2 = session summaries (LLM-compressed)

### Error Handling
- 18 domain exceptions under `OpenAgentError` (see `core/exceptions.py`)
- 12 global exception handlers in `server.py` map exceptions → HTTP status codes
- Exception chaining required (`from e`)
- No bare `except:` — always specify exception type

## Coding Rules

### Must Do
- `async def` for all I/O-bound operations (routes, DB queries)
- Type hints on all function signatures
- `logger` (structlog) for all output — never `print()`
- `pathlib.Path` — never `os.path`
- Pydantic V2 syntax: `ConfigDict`, `field_validator`, `model_config` dict
- `Annotated[T, Depends(...)]` for FastAPI dependency injection
- Explicit imports only — no wildcard imports
- Early return pattern preferred
- All code, comments, and commits in **English**

### Must Not Do
- No `print()`, `console.log()` — use `logger`
- No bare `except:` — specify exception type
- No `# type: ignore`, `# noqa`, or lint suppression
- No `exec()`, `eval()`, or `compile()`
- No `sys.path` manipulation
- No `.env` files or secrets in commits
- No Pydantic V1 syntax (`@validator`, `class Config`)
- No hardcoded config values — use `pydantic-settings` (`BaseSettings`)

### Style
- Line length: 100 (ruff)
- Quote style: double
- Indent: spaces
- Test marker format: `@pytest.mark.<marker>`

## Directory Conventions

```
core/           → Business logic (managers, services, auth, db)
core/auth/      → Authentication (JWT, password, RBAC, rate limiting)
core/db/        → Database (engine, models, repositories, migration)
api/endpoints/  → FastAPI routers (one file per domain)
api/middleware.py → Request logging middleware
models/         → Pydantic V2 request/response schemas
tests/unit/     → Unit tests (managers)
tests/integration/ → API integration tests (httpx.AsyncClient)
tests/auth/     → Auth-specific tests (JWT, password, API)
bundled_skills/ → Built-in SKILL.md skills
nexus_rust/     → Rust native extensions (do not modify without Rust toolchain)
static/         → Pre-built Next.js frontend (do not modify)
```

## Running Tests

```bash
# All tests (1365 passing, 79% coverage)
uv run pytest

# With coverage
uv run pytest --cov --cov-report=term-missing

# Specific test file
uv run pytest tests/auth/test_auth_api.py -v

# Only unit tests
uv run pytest tests/unit/ -v
```

Tests use an **in-memory SQLite** database. No external services needed.
Auth tests disable rate limiting via `limiter.enabled = False`.
Integration tests override `get_current_user` dependency for auth bypass.

## Key Files to Read First

| Purpose | File |
|---------|------|
| App entrypoint & lifespan | `server.py` |
| Agent orchestration | `core/agent.py` |
| Auth flow | `core/auth/dependencies.py` → `core/auth/service.py` |
| DB setup | `core/db/engine.py` |
| Exception definitions | `core/exceptions.py` |
| Test fixtures | `tests/conftest.py` |

## Common Tasks

### Add a new API endpoint
1. Create or edit router in `api/endpoints/<domain>.py`
2. Add Pydantic models in `models/<domain>.py`
3. Add auth dependency (`require_admin`, `require_user`, or `require_any`)
4. Register router in `server.py` if new file
5. Add tests in `tests/integration/` or `tests/auth/`

### Add a new DB model
1. Create ORM model in `core/db/models/<name>.py`
2. Import in `core/db/models/__init__.py` → `register_all_models()`
3. Create repository in `core/db/repositories/<name>_repo.py` extending `BaseRepository[T]`
4. Add Pydantic schema in `models/<name>.py`

### Add a new exception
1. Add class to `core/exceptions.py` under appropriate category
2. Add exception handler in `server.py` if it needs a custom HTTP status code

## Git Conventions

- Branch naming: `feature/<name>`, `fix/<name>`, `refactor/<name>`
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- All commits in English
- Squash merge preferred
- Cherry-pick over merge (linear history)

## Environment

- Data directory: `~/.open-agent/`
- Default port: 4821
- Package name: `open_agent` (hatchling maps project root)
- CLI command: `open-agent` (via `cli.py:main`)

## Known Quirks

- `nexus_rust/` is a pre-compiled Rust module — the `nexus_rust` name is legacy but kept for binary compatibility
- `conftest.py` manually registers `open_agent` in `sys.modules` because the directory name (`local-agent`) differs from the package name (`open_agent`)
- Some Korean comments remain in `core/exceptions.py` and `core/logging.py` — these should be translated to English when touched
- `server.py` has some Korean comments in the lifespan function — same applies
