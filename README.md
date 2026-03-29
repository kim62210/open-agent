<p align="center">
  <img src="static/icon.svg" width="80" height="80" alt="Open Agent">
  <h1 align="center">Open Agent</h1>
</p>

<p align="center">
  <strong>A local-first AI agent platform with multi-LLM support, MCP tool integration, and persistent memory.</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quickstart">Quickstart</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#api-reference">API Reference</a> •
  <a href="#contributing">Contributing</a> •
  <a href="#license">License</a>
</p>

---

## Features

- **Multi-LLM Support** — Connect to OpenAI, Anthropic, Google, Groq, Ollama, vLLM, and 100+ providers through [LiteLLM](https://github.com/BerriAI/litellm)
- **MCP Integration** — First-class [Model Context Protocol](https://modelcontextprotocol.io/) support with stdio, SSE, and streamable-http transports
- **Agent Skills** — Extensible skill system using the open [SKILL.md](https://agentskills.io/) standard (YAML frontmatter + Markdown)
- **Persistent Memory** — Automatic extraction, compression, and pinning of long-term memories across sessions
- **Workspace Tools** — File read/write/edit, regex search, directory listing, and sandboxed shell execution
- **Job Scheduler** — Cron-based background task scheduling with agent-powered execution
- **Web UI** — Built-in Next.js frontend served as static export
- **Rust-Accelerated** — Native Rust extensions for grep, fuzzy matching, and sandboxing with Python fallback
- **SSE Streaming** — Real-time streaming of agent reasoning, tool calls, and responses
- **Structured Logging** — [structlog](https://www.structlog.org/) with request correlation IDs and dev/prod format switching

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

### Development Setup

```bash
# Install with dev dependencies (test + lint)
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

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────┐
│                      Web UI (Next.js)                   │
│                   served as static export               │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼──────────────────────────────┐
│                    FastAPI Server                        │
│  ┌─────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐  │
│  │  Chat   │ │ Sessions │ │  Memory   │ │ Settings  │  │
│  │ (SSE)   │ │  CRUD    │ │  CRUD     │ │  CRUD     │  │
│  └────┬────┘ └──────────┘ └───────────┘ └───────────┘  │
│       │                                                  │
│  ┌────▼─────────────────────────────────────────────┐   │
│  │            AgentOrchestrator (ReAct Loop)         │   │
│  │  LLM Call → Tool Execution → Result → Repeat     │   │
│  └──┬──────────┬──────────────┬─────────────────┬───┘   │
│     │          │              │                 │        │
│  ┌──▼───┐  ┌──▼────┐  ┌─────▼──────┐  ┌──────▼─────┐  │
│  │ LLM  │  │ Tool  │  │  Skill     │  │  Memory    │  │
│  │Client│  │Registry│  │  Manager   │  │  Manager   │  │
│  └──┬───┘  └──┬────┘  └─────┬──────┘  └──────┬─────┘  │
│     │         │              │                 │        │
└─────┼─────────┼──────────────┼─────────────────┼────────┘
      │         │              │                 │
  ┌───▼───┐ ┌──▼───┐   ┌──────▼──────┐  ┌──────▼──────┐
  │LiteLLM│ │ MCP  │   │  SKILL.md   │  │  SQLite/    │
  │ Proxy │ │Servers│   │  (YAML+MD)  │  │  PostgreSQL │
  └───────┘ └──────┘   └─────────────┘  └─────────────┘
```

### Project Structure

```
open-agent/
├── pyproject.toml              # Build config (hatchling), dependencies, tool settings
├── __init__.py                 # Package version (__version__)
├── __main__.py                 # python -m support
├── cli.py                      # Click CLI entrypoint (open-agent command)
├── server.py                   # FastAPI app, router registration, static serving, CORS
├── config.py                   # ~/.open-agent/ data directory management
│
├── core/                       # Business logic
│   ├── agent.py                # AgentOrchestrator — ReAct loop, tool routing, SSE streaming
│   ├── llm.py                  # LLMClient — LiteLLM wrapper, API key resolution, token management
│   ├── exceptions.py           # OpenAgentError hierarchy (18 domain exception classes)
│   ├── logging.py              # structlog setup (dev console / prod JSON)
│   ├── tool_registry.py        # Deferred tool loading with find_tools meta-tool
│   ├── tool_errors.py          # Error classification and LLM-friendly formatting
│   ├── unified_tools.py        # Context-aware tool routing (workspace/page/skill)
│   ├── mcp_manager.py          # MCP server lifecycle (stdio/SSE/streamable-http)
│   ├── skill_manager.py        # SKILL.md parsing, skill tools, script execution
│   ├── memory_manager.py       # L1 long-term memory + L2 session summary
│   ├── session_manager.py      # Conversation session persistence
│   ├── settings_manager.py     # Application settings CRUD
│   ├── workspace_manager.py    # Workspace registration and file tree
│   ├── workspace_tools.py      # File/shell tools with security guards
│   ├── page_manager.py         # HTML page/folder/bookmark management
│   ├── job_manager.py          # Job CRUD and LLM tool schema builder
│   ├── job_scheduler.py        # asyncio-based cron scheduler
│   ├── job_executor.py         # Job execution adapter
│   ├── sandbox.py              # OS-native sandboxing (macOS Seatbelt / Linux bwrap)
│   ├── grep_engine.py          # 3-tier search: Rust native → ripgrep → Python
│   ├── fuzzy.py                # Fuzzy matching with Rust acceleration
│   └── workflow_router.py      # LLM-based skill auto-routing
│
├── api/                        # FastAPI routers
│   ├── middleware.py            # RequestLoggingMiddleware (request_id + structured access logs)
│   └── endpoints/
│       ├── chat.py             # POST /api/chat — SSE streaming chat
│       ├── sessions.py         # /api/sessions — Session history CRUD
│       ├── memory.py           # /api/memory — Memory CRUD, pin toggle
│       ├── settings.py         # /api/settings — LLM/theme/memory settings
│       ├── skills.py           # /api/skills — Skill CRUD, ZIP upload, import
│       ├── mcp.py              # /api/mcp — MCP server management
│       ├── workspace.py        # /api/workspace — Workspace CRUD, file operations
│       ├── pages.py            # /api/pages — Page/folder CRUD, HTML upload
│       ├── jobs.py             # /api/jobs — Job scheduling CRUD
│       └── sandbox.py          # /api/sandbox — Sandbox policy management
│
├── models/                     # Pydantic V2 data models
│   ├── _base.py                # OpenAgentBase (shared ConfigDict)
│   ├── error.py                # ErrorResponse, ErrorDetail
│   ├── session.py              # SessionInfo, SessionMessage, MessageRole
│   ├── memory.py               # MemoryItem, MemorySettings
│   ├── settings.py             # AppSettings, LLMSettings, ThemeSettings
│   ├── skill.py                # SkillMeta, SkillInfo, SkillDetail
│   ├── mcp.py                  # MCPServerConfig, MCPServerStatus, MCPTransport
│   ├── job.py                  # JobInfo, JobRunStatus, JobScheduleType
│   ├── page.py                 # PageItem, FolderItem
│   └── workspace.py            # WorkspaceInfo, FileTreeNode
│
├── bundled_skills/             # Built-in agent skills
│   ├── impl/SKILL.md           # Implementation skill
│   ├── test/SKILL.md           # Test generation skill
│   ├── plan/SKILL.md           # Planning skill
│   ├── debug/SKILL.md          # Debugging skill
│   ├── review/SKILL.md         # Code review skill
│   ├── find/SKILL.md           # Code search skill
│   ├── coding-pipeline/        # Multi-step coding workflow
│   └── skill-creator/          # Skill authoring tool
│
├── nexus_rust/                 # Rust native extensions (CPython)
│   ├── __init__.py             # Python wrapper with fallback
│   └── nexus_rust.cpython-*.so # Compiled binary
│
├── tests/                      # Test suite (50 tests)
│   ├── conftest.py             # Shared fixtures (isolated data dir, manager mocks, async client)
│   ├── unit/                   # Unit tests (SessionManager, MemoryManager)
│   └── integration/            # Integration tests (FastAPI endpoints)
│
└── static/                     # Pre-built Next.js frontend (served by FastAPI)
```

### Key Design Patterns

| Pattern | Implementation | Purpose |
|---------|---------------|---------|
| **Deferred Tool Loading** | `tool_registry.py` | Loads tools on-demand via `find_tools` meta-tool to save context window |
| **3-Tier Fallback** | `grep_engine.py`, `fuzzy.py` | Rust native → subprocess (ripgrep) → pure Python |
| **Progressive Disclosure** | `skill_manager.py` | Skills load in 3 stages: metadata → body → references |
| **ReAct Loop** | `agent.py` | Reason + Act loop with configurable max rounds |
| **L1/L2 Memory** | `memory_manager.py` | L1: long-term facts, L2: session summaries |
| **Singleton + Per-Request State** | `agent.py` | Global orchestrator with `_RequestState` for concurrency safety |

## API Reference

### Chat

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Single-turn chat completion |
| POST | `/api/chat/stream` | SSE streaming chat (recommended) |

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sessions/` | List all sessions |
| POST | `/api/sessions/` | Create a new session |
| GET | `/api/sessions/{id}` | Get session detail with messages |
| PATCH | `/api/sessions/{id}` | Update session title |
| DELETE | `/api/sessions/{id}` | Delete a session |

### Memory

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/memory/` | List all memories |
| POST | `/api/memory/` | Create a memory manually |
| PATCH | `/api/memory/{id}` | Update memory content |
| PATCH | `/api/memory/{id}/pin` | Toggle pin status |
| DELETE | `/api/memory/{id}` | Delete a memory |
| DELETE | `/api/memory/` | Clear all non-pinned memories |

### MCP Servers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/mcp/servers` | List MCP server configurations |
| POST | `/api/mcp/servers` | Add a new MCP server |
| PATCH | `/api/mcp/servers/{name}` | Update server config |
| DELETE | `/api/mcp/servers/{name}` | Remove a server |
| POST | `/api/mcp/servers/{name}/restart` | Restart a server connection |
| GET | `/api/mcp/servers/{name}/tools` | List tools from a server |

### Skills

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/skills/` | List all skills |
| POST | `/api/skills/` | Create a new skill |
| PATCH | `/api/skills/{id}` | Update skill metadata |
| DELETE | `/api/skills/{id}` | Delete a skill |
| POST | `/api/skills/upload` | Upload skill as ZIP |
| POST | `/api/skills/import` | Import skill from local path |
| POST | `/api/skills/reload` | Reload all skills from disk |

### Workspace

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workspace/` | List workspaces |
| POST | `/api/workspace/` | Register a workspace |
| POST | `/api/workspace/{id}/activate` | Set active workspace |
| POST | `/api/workspace/deactivate` | Deactivate current workspace |
| GET | `/api/workspace/{id}/tree` | Get file tree |
| GET | `/api/workspace/{id}/file` | Read file content |

### Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings/` | Get all settings |
| PATCH | `/api/settings/llm` | Update LLM settings |
| PATCH | `/api/settings/memory` | Update memory settings |
| PATCH | `/api/settings/theme` | Update theme settings |
| GET | `/api/settings/health` | Health check (LLM connectivity) |

### Jobs

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/jobs/` | List scheduled jobs |
| POST | `/api/jobs/` | Create a new job |
| PATCH | `/api/jobs/{id}` | Update job config |
| DELETE | `/api/jobs/{id}` | Delete a job |
| POST | `/api/jobs/{id}/run` | Trigger immediate execution |
| POST | `/api/jobs/{id}/stop` | Stop a running job |

## Security

### Path Traversal Prevention

All workspace file operations pass through `_resolve_safe_path()`, which resolves symlinks and verifies the target is within the workspace root. Attempts like `../../etc/passwd` are blocked with `InvalidPathError`.

### Dangerous Command Blocking

The `workspace_bash` tool blocks 10 categories of destructive shell patterns before execution:

| Pattern | Description |
|---------|-------------|
| `rm -rf /` | Recursive root deletion |
| `:(){ :\|:& };:` | Fork bomb |
| `dd if=/dev/zero of=/dev/sda` | Disk overwrite |
| `mkfs.*` | Filesystem format |
| `> /dev/sda` | Block device write |
| `curl \| sh`, `wget \| sh` | Pipe-to-shell |
| `chmod -R 777 /` | Root permission change |
| `chown -R ... /` | Root ownership change |

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

## Data Storage

All runtime data is stored in `~/.open-agent/`:

| Resource | Storage | Description |
|----------|---------|-------------|
| `open_agent.db` | **SQLite** (default) | All structured data (sessions, memories, jobs, settings, etc.) |
| `.env` | File | API keys (dotenv) |
| `skills/` | Filesystem | User-created skill directories (SKILL.md + scripts) |
| `pages/` | Filesystem | Uploaded HTML files and bundles |

### Database Backend

By default, Open Agent uses **SQLite with WAL mode** — zero configuration required. For multi-user deployments, set the `DATABASE_URL` environment variable to use PostgreSQL:

```bash
# Default: SQLite (automatic)
# ~/.open-agent/open_agent.db

# PostgreSQL override
export DATABASE_URL=postgresql://user:pass@localhost:5432/open_agent
```

### Migration from JSON

Existing installations using JSON files (`settings.json`, `sessions.json`, etc.) are **automatically migrated** to the database on first startup. Original JSON files are preserved as backups.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `GOOGLE_API_KEY` | Google AI API key | — |
| `OPEN_AGENT_DEV` | Enable dev mode (`1` = colored logs, CORS `*`) | `0` |
| `OPEN_AGENT_LOG_LEVEL` | Log level override | `INFO` |
| `OPEN_AGENT_ENV` | Environment name (`dev` / `prod`) | `prod` |

## Contributing

We welcome contributions! Please see our development workflow:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with tests
4. Run the test suite (`uv run pytest`)
5. Run linting (`uv run ruff check . && uv run ruff format --check .`)
6. Commit with conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`)
7. Push and open a Pull Request

### Development Guidelines

- All code, comments, and commits must be in **English**
- Use `logger` (not `print()`) for all output
- Type hints required on function signatures
- No bare `except:` — always specify exception type
- Use domain exceptions from `core/exceptions.py` instead of `ValueError`
- Tests required for new features (`tests/unit/` or `tests/integration/`)

## Roadmap

- [x] **Sprint 2**: Database layer (SQLite default + PostgreSQL optional, async repositories)
- [ ] **Sprint 3**: Authentication (JWT + RBAC + rate limiting)
- [ ] **Sprint 4**: Operations (Docker, CI/CD, observability)
- [ ] Frontend source code open-sourcing (currently pre-built only)
- [ ] Plugin marketplace for community skills
- [ ] Multi-agent orchestration

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
