<p align="center">
  <img src="static/icon.svg" width="80" height="80" alt="Open Agent">
  <h1 align="center">Open Agent</h1>
</p>

<p align="center">
  <strong>A local-first AI agent platform with multi-LLM support, MCP tool integration, and persistent memory.</strong>
</p>

<p align="center">
  <a href="#features">Features</a> &bull;
  <a href="#quickstart">Quickstart</a> &bull;
  <a href="#architecture">Architecture</a> &bull;
  <a href="#authentication">Authentication</a> &bull;
  <a href="#api-reference">API Reference</a> &bull;
  <a href="#configuration">Configuration</a> &bull;
  <a href="#development">Development</a> &bull;
  <a href="#contributing">Contributing</a> &bull;
  <a href="#license">License</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.13%2B-blue" alt="Python 3.13+">
  <img src="https://img.shields.io/badge/framework-FastAPI-009688" alt="FastAPI">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/tests-78%20passing-brightgreen" alt="Tests">
</p>

---

## Features

- **Multi-LLM Support** — Connect to OpenAI, Anthropic, Google, Groq, Ollama, vLLM, and 100+ providers through [LiteLLM](https://github.com/BerriAI/litellm)
- **MCP Integration** — First-class [Model Context Protocol](https://modelcontextprotocol.io/) support with stdio, SSE, and streamable-http transports
- **Agent Skills** — Extensible skill system using the open [SKILL.md](https://agentskills.io/) standard (YAML frontmatter + Markdown)
- **Persistent Memory** — Automatic extraction, compression, and pinning of long-term memories across sessions
- **Workspace Tools** — File read/write/edit, regex search, directory listing, and sandboxed shell execution
- **Job Scheduler** — Cron-based background task scheduling with agent-powered execution
- **Authentication & RBAC** — JWT + API key dual authentication with role-based access control (admin/user/viewer)
- **Database Backend** — Async SQLAlchemy with SQLite (zero-config default) or PostgreSQL for multi-user deployments
- **Structured Logging** — [structlog](https://www.structlog.org/) with request correlation IDs and dev/prod format auto-switching
- **Web UI** — Built-in Next.js frontend served as static export
- **Rust-Accelerated** — Native Rust extensions for grep, fuzzy matching, and sandboxing with Python fallback
- **SSE Streaming** — Token-level streaming of agent reasoning, tool calls, and responses with `content_delta` events for real-time delivery
- **Rate Limiting** — Configurable per-endpoint rate limits via [slowapi](https://github.com/laurentS/slowapi)

## Quickstart

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Installation

```bash
# Clone the repository
git clone https://github.com/kim62210/open-agent.git
cd open-agent

# Install dependencies
uv sync

# Create environment file
cp ~/.open-agent/.env.example ~/.open-agent/.env
# Edit .env and add your API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
```

### Running

```bash
# Start in development mode (hot reload, colored logs)
uv run open-agent start --dev

# Production mode (JSON logs)
uv run open-agent start

# Direct uvicorn invocation
uv run uvicorn open_agent.server:app --host 127.0.0.1 --port 4821
```

The web UI is available at `http://localhost:4821` once the server starts.

### First-Time Setup

1. Start the server
2. Register the first user account via `POST /api/auth/register` — the first user automatically gets `admin` role
3. Use the returned JWT tokens or create an API key for programmatic access

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────┐
│                      Web UI (Next.js)                   │
│                   served as static export               │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼──────────────────────────────┐
│               FastAPI Server (async)                     │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Middleware: RequestLogging · CORS · RateLimiter  │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  ┌───────────┐ ┌──────┐ ┌────────┐ ┌──────┐ ┌──────┐  │
│  │   Auth    │ │ Chat │ │Sessions│ │Memory│ │ ...  │  │
│  │(JWT+Key)  │ │(SSE) │ │ CRUD   │ │ CRUD │ │      │  │
│  └─────┬─────┘ └──┬───┘ └────────┘ └──────┘ └──────┘  │
│        │          │                                      │
│  ┌─────▼──────────▼────────────────────────────────┐   │
│  │           AgentOrchestrator (ReAct Loop)         │   │
│  │   LLM Call → Tool Execution → Result → Repeat   │   │
│  └──┬──────────┬──────────────┬────────────────┬───┘   │
│     │          │              │                │        │
│  ┌──▼───┐  ┌──▼────┐  ┌─────▼──────┐  ┌─────▼──────┐ │
│  │ LLM  │  │ Tool  │  │  Skill     │  │  Memory    │ │
│  │Client│  │Registry│  │  Manager   │  │  Manager   │ │
│  └──┬───┘  └──┬────┘  └─────┬──────┘  └─────┬──────┘ │
└─────┼─────────┼──────────────┼───────────────┼─────────┘
      │         │              │               │
  ┌───▼───┐ ┌──▼───┐   ┌──────▼──────┐ ┌─────▼────────┐
  │LiteLLM│ │ MCP  │   │  SKILL.md   │ │  SQLite /    │
  │ Proxy │ │Servers│   │  (YAML+MD)  │ │  PostgreSQL  │
  └───────┘ └──────┘   └─────────────┘ └──────────────┘
```

### Project Structure

```
open-agent/
├── pyproject.toml              # Build config (hatchling), dependencies, tool settings
├── __init__.py                 # Package version (__version__ = "0.8.6")
├── __main__.py                 # python -m support
├── cli.py                      # Click CLI entrypoint (open-agent command)
├── server.py                   # FastAPI app, lifespan, router registration, static serving
├── config.py                   # ~/.open-agent/ data directory management
│
├── core/                       # Business logic layer
│   ├── agent.py                # AgentOrchestrator — ReAct loop, tool routing, token-level SSE streaming
│   ├── llm.py                  # LLMClient — LiteLLM wrapper, API key resolution
│   ├── exceptions.py           # OpenAgentError hierarchy (18 domain exception classes)
│   ├── logging.py              # structlog setup (dev console / prod JSON auto-switch)
│   │
│   ├── auth/                   # Authentication & authorization
│   │   ├── config.py           # AuthSettings (pydantic-settings, env_prefix=OPEN_AGENT_)
│   │   ├── password.py         # Argon2 hashing (pwdlib)
│   │   ├── jwt.py              # JWT token creation / validation (PyJWT)
│   │   ├── dependencies.py     # FastAPI deps: get_current_user, RoleChecker
│   │   ├── service.py          # AuthService (register, login, refresh, API key mgmt)
│   │   └── rate_limit.py       # slowapi limiter with user_id/IP key function
│   │
│   ├── db/                     # Database layer (async SQLAlchemy 2.0)
│   │   ├── engine.py           # Engine factory (SQLite default / PostgreSQL override)
│   │   ├── base.py             # DeclarativeBase
│   │   ├── migrate.py          # One-time JSON → DB migration utility
│   │   ├── models/             # 12 ORM models
│   │   │   ├── session.py      # SessionORM, SessionMessageORM
│   │   │   ├── memory.py       # MemoryORM, SessionSummaryORM
│   │   │   ├── settings.py     # SettingsORM
│   │   │   ├── job.py          # JobORM, JobRunRecordORM
│   │   │   ├── workspace.py    # WorkspaceORM
│   │   │   ├── page.py         # PageORM
│   │   │   ├── skill_config.py # SkillConfigORM
│   │   │   ├── mcp_config.py   # MCPConfigORM
│   │   │   └── user.py         # UserORM, APIKeyORM, RefreshTokenORM
│   │   └── repositories/       # Generic BaseRepository[T] + 11 domain repos
│   │       ├── base.py         # get_by_id, get_all, create, update, delete_by_id
│   │       ├── session_repo.py
│   │       ├── memory_repo.py
│   │       ├── settings_repo.py
│   │       ├── job_repo.py
│   │       ├── workspace_repo.py
│   │       ├── page_repo.py
│   │       ├── skill_config_repo.py
│   │       ├── mcp_config_repo.py
│   │       └── user_repo.py    # UserRepository, APIKeyRepository, RefreshTokenRepository
│   │
│   ├── tool_registry.py        # Deferred tool loading with find_tools meta-tool
│   ├── unified_tools.py        # Context-aware tool routing
│   ├── mcp_manager.py          # MCP server lifecycle (stdio/SSE/streamable-http)
│   ├── skill_manager.py        # SKILL.md parsing and execution
│   ├── memory_manager.py       # L1 long-term memory + L2 session summaries
│   ├── session_manager.py      # Conversation session persistence
│   ├── settings_manager.py     # Application settings CRUD
│   ├── workspace_manager.py    # Workspace registration and file tree
│   ├── workspace_tools.py      # File/shell tools with security guards
│   ├── page_manager.py         # HTML page/folder management
│   ├── job_manager.py          # Job CRUD and LLM tool schema
│   ├── job_scheduler.py        # asyncio-based cron scheduler
│   ├── job_executor.py         # Job execution adapter
│   ├── sandbox.py              # OS-native sandboxing (macOS Seatbelt / Linux bwrap)
│   ├── grep_engine.py          # 3-tier: Rust native → ripgrep → Python
│   └── fuzzy.py                # Fuzzy matching with Rust acceleration
│
├── api/                        # HTTP layer
│   ├── middleware.py            # RequestLoggingMiddleware (UUID + structured logs)
│   └── endpoints/
│       ├── auth.py             # Authentication (register, login, refresh, API keys, admin)
│       ├── chat.py             # SSE streaming chat
│       ├── sessions.py         # Session history CRUD
│       ├── memory.py           # Memory CRUD
│       ├── settings.py         # Application settings
│       ├── skills.py           # Skill management
│       ├── mcp.py              # MCP server management
│       ├── workspace.py        # Workspace and file operations
│       ├── pages.py            # Page/folder CRUD
│       ├── jobs.py             # Job scheduling
│       └── sandbox.py          # Sandbox policy management
│
├── models/                     # Pydantic V2 schemas
│   ├── _base.py                # OpenAgentBase (shared ConfigDict)
│   ├── auth.py                 # Auth request/response models
│   ├── error.py                # ErrorResponse, ErrorDetail
│   ├── session.py              # SessionInfo, MessageRole enum
│   ├── memory.py               # MemoryItem, MemorySettings
│   ├── settings.py             # AppSettings, LLMSettings
│   ├── skill.py                # SkillMeta, SkillInfo
│   ├── mcp.py                  # MCPServerConfig, MCPTransport enum
│   ├── job.py                  # JobInfo, JobRunStatus enum
│   ├── page.py                 # PageItem, FolderItem
│   └── workspace.py            # WorkspaceInfo, FileTreeNode
│
├── bundled_skills/             # Built-in agent skills (SKILL.md standard)
├── nexus_rust/                 # Rust native extensions (CPython)
├── static/                     # Pre-built Next.js frontend
│
├── tests/                      # Test suite (78 tests)
│   ├── conftest.py             # Shared fixtures (in-memory SQLite, auth, managers)
│   ├── unit/
│   │   ├── test_session_manager.py   # 16 tests
│   │   └── test_memory_manager.py    # 22 tests
│   ├── integration/
│   │   └── test_sessions_api.py      # 12 tests
│   └── auth/
│       ├── test_jwt.py               # 8 tests
│       ├── test_password.py          # 5 tests
│       └── test_auth_api.py          # 15 tests
│
├── CHANGELOG.md                # Release history
├── CLAUDE.md                   # AI assistant project context
├── LICENSE                     # MIT License
└── .gitignore
```

### Key Design Patterns

| Pattern | Location | Purpose |
|---------|----------|---------|
| **Repository Pattern** | `core/db/repositories/` | Generic `BaseRepository[T]` abstracts DB CRUD operations |
| **Concurrency Safety** | `core/*_manager.py` | `asyncio.Lock` on all mutation paths in singleton managers |
| **Deferred Tool Loading** | `core/tool_registry.py` | Tools loaded on-demand via `find_tools` to save LLM context |
| **3-Tier Fallback** | `core/grep_engine.py` | Rust native → subprocess (ripgrep) → pure Python |
| **ReAct Loop** | `core/agent.py` | Reason + Act loop with configurable max rounds |
| **L1/L2 Memory** | `core/memory_manager.py` | L1: long-term facts, L2: session summaries with LLM compression |
| **Dual Authentication** | `core/auth/dependencies.py` | JWT Bearer token or `X-API-Key` header — both paths validate user |
| **Role-Based Access** | `core/auth/dependencies.py` | `RoleChecker` class with pre-built `require_admin`, `require_user`, `require_any` |
| **Structured Logging** | `core/logging.py` | Dev: colored console, Prod: JSON — auto-detected from `OPEN_AGENT_ENV` |

## Authentication

Open Agent uses a dual authentication system: **JWT tokens** for browser sessions and **API keys** for programmatic access.

### Authentication Flow

```
┌─────────┐       POST /api/auth/register        ┌──────────┐
│  Client  │ ──────────────────────────────────► │  Server  │
│          │ ◄────────────────────────────────── │          │
│          │       UserResponse (201)             │          │
│          │                                      │          │
│          │       POST /api/auth/login           │          │
│          │ ──────────────────────────────────► │          │
│          │ ◄────────────────────────────────── │          │
│          │   { access_token, refresh_token }    │          │
│          │                                      │          │
│          │   GET /api/chat (Authorization:      │          │
│          │       Bearer <access_token>)          │          │
│          │ ──────────────────────────────────► │          │
│          │ ◄────────────────────────────────── │          │
│          │       SSE stream response            │          │
│          │                                      │          │
│          │   POST /api/auth/refresh             │          │
│          │   { refresh_token }                  │          │
│          │ ──────────────────────────────────► │          │
│          │ ◄────────────────────────────────── │          │
│          │   { new_access_token,                │          │
│          │     new_refresh_token }              │          │
└─────────┘                                      └──────────┘
```

### JWT Tokens

| Token | Lifetime | Purpose |
|-------|----------|---------|
| Access Token | 30 minutes | Short-lived, used in `Authorization: Bearer` header |
| Refresh Token | 7 days | Long-lived, used to obtain new access tokens with rotation |

### API Keys

For scripts, CI/CD, or programmatic access:

```bash
# Create an API key (authenticated)
curl -X POST http://localhost:4821/api/auth/api-keys \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-script"}'

# Use the API key
curl http://localhost:4821/api/sessions/ \
  -H "X-API-Key: oagent_xxxxxxxxxxxxxxxx"
```

The plaintext key is returned **only once** on creation. Store it securely.

### Roles & Permissions

| Role | Scope |
|------|-------|
| `admin` | Full access: user management, settings, all CRUD operations |
| `user` | Standard access: chat, sessions, memory, skills, API keys |
| `viewer` | Read-only access: view sessions, memory, settings |

The **first registered user** is automatically assigned the `admin` role.

### Rate Limits

| Endpoint | Limit |
|----------|-------|
| `POST /api/auth/register` | 5/minute |
| `POST /api/auth/login` | 5/minute |
| `POST /api/auth/refresh` | 10/minute |
| `POST /api/chat` | 20/minute |
| `POST /api/chat/stream` | 10/minute |
| All other endpoints | 60/minute (default) |

## API Reference

All endpoints require authentication unless noted. Pass `Authorization: Bearer <token>` or `X-API-Key: <key>`.

### Auth

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | Public | Create a new user account |
| POST | `/api/auth/login` | Public | Authenticate and get tokens |
| POST | `/api/auth/refresh` | Public | Refresh access token |
| POST | `/api/auth/logout` | Required | Revoke refresh token |
| GET | `/api/auth/me` | Required | Get current user profile |
| POST | `/api/auth/api-keys` | User+ | Create an API key |
| GET | `/api/auth/api-keys` | User+ | List API keys |
| DELETE | `/api/auth/api-keys/{id}` | User+ | Revoke an API key |
| GET | `/api/auth/users` | Admin | List all users |
| PATCH | `/api/auth/users/{id}/role` | Admin | Change user role |
| PATCH | `/api/auth/users/{id}/active` | Admin | Toggle user active status |

### Chat

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/chat` | User+ | Single-turn chat completion |
| POST | `/api/chat/stream` | User+ | SSE streaming chat (recommended) |

### Sessions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/sessions/` | Any | List all sessions |
| POST | `/api/sessions/` | User+ | Create a new session |
| GET | `/api/sessions/{id}` | Any | Get session with messages |
| PATCH | `/api/sessions/{id}` | User+ | Update session title |
| DELETE | `/api/sessions/{id}` | User+ | Delete a session |

### Memory

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/memory/` | Any | List all memories |
| POST | `/api/memory/` | User+ | Create a memory |
| PATCH | `/api/memory/{id}` | User+ | Update memory content |
| PATCH | `/api/memory/{id}/pin` | User+ | Toggle pin status |
| DELETE | `/api/memory/{id}` | User+ | Delete a memory |
| DELETE | `/api/memory/` | User+ | Clear all non-pinned memories |

### Settings

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/settings/` | Any | Get all settings |
| PATCH | `/api/settings/llm` | Admin | Update LLM settings |
| PATCH | `/api/settings/memory` | Admin | Update memory settings |
| PATCH | `/api/settings/theme` | Any | Update theme settings |
| GET | `/api/settings/health` | Public | Health check (LLM connectivity) |
| GET | `/api/settings/version` | Public | Get server version |

### Skills

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/skills/` | Any | List all skills |
| POST | `/api/skills/` | User+ | Create a new skill |
| PATCH | `/api/skills/{id}` | User+ | Update skill metadata |
| DELETE | `/api/skills/{id}` | User+ | Delete a skill |
| POST | `/api/skills/upload` | User+ | Upload skill as ZIP |
| POST | `/api/skills/import` | User+ | Import skill from local path |
| POST | `/api/skills/reload` | User+ | Reload all skills from disk |

### MCP Servers

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/mcp/servers` | Any | List MCP server configurations |
| POST | `/api/mcp/servers` | User+ | Add a new MCP server |
| PATCH | `/api/mcp/servers/{name}` | User+ | Update server config |
| DELETE | `/api/mcp/servers/{name}` | User+ | Remove a server |
| POST | `/api/mcp/servers/{name}/restart` | User+ | Restart a connection |
| GET | `/api/mcp/servers/{name}/tools` | Any | List tools from a server |

### Workspace

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/workspace/` | Any | List workspaces |
| POST | `/api/workspace/` | User+ | Register a workspace |
| POST | `/api/workspace/{id}/activate` | User+ | Set active workspace |
| POST | `/api/workspace/deactivate` | User+ | Deactivate current |
| GET | `/api/workspace/{id}/tree` | Any | Get file tree |
| GET | `/api/workspace/{id}/file` | Any | Read file content |

### Pages

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/pages/` | Any | List pages and folders |
| POST | `/api/pages/` | User+ | Create a page |
| PATCH | `/api/pages/{id}` | User+ | Update page metadata |
| DELETE | `/api/pages/{id}` | User+ | Delete a page |
| POST | `/api/pages/upload` | User+ | Upload HTML file |

### Jobs

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/jobs/` | User+ | List scheduled jobs |
| POST | `/api/jobs/` | User+ | Create a new job |
| PATCH | `/api/jobs/{id}` | User+ | Update job config |
| DELETE | `/api/jobs/{id}` | User+ | Delete a job |
| POST | `/api/jobs/{id}/run` | User+ | Trigger immediate execution |
| POST | `/api/jobs/{id}/stop` | User+ | Stop a running job |

### Sandbox

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/sandbox/policy` | User+ | Get sandbox policy |
| PATCH | `/api/sandbox/policy` | User+ | Update sandbox policy |

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| **LLM Providers** | | |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `GOOGLE_API_KEY` | Google AI API key | — |
| `XAI_API_KEY` | xAI (Grok) API key | — |
| `OPENROUTER_API_KEY` | OpenRouter API key | — |
| `GROQ_API_KEY` | Groq API key | — |
| `DEEPSEEK_API_KEY` | DeepSeek API key | — |
| `MISTRAL_API_KEY` | Mistral AI API key | — |
| `COHERE_API_KEY` | Cohere API key | — |
| `TOGETHERAI_API_KEY` | Together AI API key | — |
| `PERPLEXITYAI_API_KEY` | Perplexity AI API key | — |
| `FIREWORKS_AI_API_KEY` | Fireworks AI API key | — |
| `AZURE_API_KEY` | Azure OpenAI API key | — |
| `HUGGINGFACE_API_KEY` | Hugging Face API key | — |
| **Database** | | |
| `DATABASE_URL` | PostgreSQL connection URL | SQLite (auto) |
| `OPEN_AGENT_DB_ECHO` | Enable SQL query logging (`1`) | `0` |
| **Authentication** | | |
| `OPEN_AGENT_JWT_SECRET_KEY` | JWT signing secret | Auto-generated |
| `OPEN_AGENT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL | `30` |
| `OPEN_AGENT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | `7` |
| `OPEN_AGENT_REGISTRATION_ENABLED` | Allow user registration | `true` |
| **Server** | | |
| `OPEN_AGENT_DEV` | Dev mode (`1` = colored logs, CORS `*`) | `0` |
| `OPEN_AGENT_ENV` | Environment (`dev` / `prod`) | `prod` |
| `OPEN_AGENT_LOG_LEVEL` | Log level override | `INFO` |

### Data Storage

All runtime data is stored in `~/.open-agent/`:

| Resource | Storage | Description |
|----------|---------|-------------|
| `open_agent.db` | **SQLite** (default) | All structured data |
| `.jwt_secret` | File | Auto-generated JWT signing key |
| `.env` | File | API keys (dotenv) |
| `skills/` | Filesystem | User-created skill directories |
| `pages/` | Filesystem | Uploaded HTML files |

### Database Backend

By default, Open Agent uses **SQLite with WAL mode** — zero configuration required.

For multi-user or production deployments, set `DATABASE_URL` for PostgreSQL:

```bash
# Default: SQLite (automatic)
# ~/.open-agent/open_agent.db

# PostgreSQL
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/open_agent
```

SQLite settings: WAL journal mode, 5s busy timeout, single-connection pool.
PostgreSQL settings: pool_size=5, max_overflow=10.

### Schema Migrations (Alembic)

Open Agent uses [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations. When upgrading, run:

```bash
uv run alembic upgrade head
```

To generate a new migration after modifying ORM models:

```bash
uv run alembic revision --autogenerate -m "description of change"
```

### Migration from JSON

Existing installations using JSON files are **automatically migrated** to the database on first startup. Original JSON files are preserved. A `.migrated` marker prevents re-migration.

## Security

### Path Traversal Prevention

All workspace file operations pass through `_resolve_safe_path()`, which resolves symlinks and verifies the target is within the workspace root. Attempts like `../../etc/passwd` are blocked with `InvalidPathError`.

### Dangerous Command Blocking

The `workspace_bash` tool blocks destructive shell patterns before execution:

- `rm -rf /` — recursive root deletion
- `:(){ :|:& };:` — fork bomb
- `dd if=/dev/zero` — disk overwrite
- `mkfs.*` — filesystem format
- `curl | sh`, `wget | sh` — pipe-to-shell
- `chmod -R 777 /`, `chown -R ... /` — root permission/ownership changes

### Shell Execution Limits

- **Timeout**: 30s default, 120s maximum
- **Output truncation**: stdout 30,000 chars, stderr 5,000 chars
- **Working directory**: Restricted to workspace root

### OS-Native Sandboxing

| Platform | Technology | Isolation |
|----------|-----------|-----------|
| macOS | Seatbelt (`sandbox-exec`) | Filesystem + network policies |
| Linux | bubblewrap (`bwrap`) | Namespace isolation |
| Windows | Job Objects | Process resource limits |

### Password Security

Passwords are hashed with **Argon2** via [pwdlib](https://github.com/frankie567/pwdlib). Plaintext passwords are never stored or logged.

## Development

### Setup

```bash
# Install with all dev dependencies (test + lint)
uv sync --group dev

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov --cov-report=term-missing

# Lint and format
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy .
```

### Test Structure

```
tests/
├── conftest.py              # In-memory SQLite engine, auth fixtures, manager mocks
├── unit/
│   ├── test_session_manager.py   # 16 tests — CRUD, message append, ordering
│   └── test_memory_manager.py    # 22 tests — CRUD, compression, conflict, pins
├── integration/
│   └── test_sessions_api.py      # 12 tests — HTTP endpoints via httpx.AsyncClient
└── auth/
    ├── test_jwt.py               # 8 tests — create, decode, expiry, tampering
    ├── test_password.py          # 5 tests — hash, verify, rejection
    └── test_auth_api.py          # 15 tests — register, login, RBAC, API keys
```

All tests use an **in-memory SQLite** database via pytest fixtures. No external services required.

### Exception Hierarchy

```
OpenAgentError
├── NotFoundError              # 404
├── AlreadyExistsError         # 409
├── PermissionDeniedError      # 403
├── InvalidPathError           # 400
├── NotInitializedError        # 500
├── ConfigError                # 500
├── StorageLimitError          # 413
├── LLMError                   # 502
│   ├── LLMRateLimitError      # 429
│   └── LLMContextWindowError  # 400
├── JobError
│   ├── JobNotFoundError       # 404
│   └── JobStateError          # 409
├── MCPError
│   └── MCPConnectionError     # 502
└── SkillError
    ├── SkillNotFoundError     # 404
    └── SkillValidationError   # 400
```

## Contributing

We welcome contributions! Please follow this workflow:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with tests
4. Run the full test suite (`uv run pytest`)
5. Run linting (`uv run ruff check . && uv run ruff format --check .`)
6. Commit with conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)
7. Push and open a Pull Request

### Guidelines

- All code, comments, and commits must be in **English**
- Use `logger` (not `print()`) for all output
- Type hints required on function signatures
- No bare `except:` — always specify exception type
- Use domain exceptions from `core/exceptions.py`
- Tests required for new features
- Pydantic V2 syntax only (`ConfigDict`, `field_validator`)
- Async-first: `async def` for I/O-bound operations

## Roadmap

- [x] Sprint 1: Foundation (pyproject.toml, structured logging, exceptions, Pydantic V2, tests)
- [x] Sprint 2: Database layer (SQLite/PostgreSQL, async repositories, JSON migration)
- [x] Sprint 3: Authentication (JWT + RBAC + API keys + rate limiting)
- [x] Sprint 4a: P0 Critical Fixes (Alembic, concurrency safety, race conditions, exception handling)
- [ ] Sprint 4b: Operations (Docker, CI/CD, observability)
- [ ] Frontend source code open-sourcing
- [ ] Plugin marketplace for community skills
- [ ] Multi-agent orchestration

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
