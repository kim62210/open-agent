# Contributing to Open Agent

Thanks for considering a contribution to Open Agent.

This project is a local-first AI agent server with a relatively broad surface area: authentication, MCP, persistent memory, hosted pages, workspaces, jobs, streaming chat, and a growing run-control layer all live in the same FastAPI application. Good contributions are therefore small, well-scoped, and grounded in the actual code paths they affect.

## Before you start

- Read [README.md](README.md) for the project overview and quickstart.
- Read [docs/architecture.md](docs/architecture.md) before making structural changes.
- Search existing issues and pull requests before opening a duplicate proposal.
- Prefer opening an issue or discussion before implementing large changes that affect multiple subsystems.

Good first contributions:

- documentation fixes
- targeted endpoint improvements
- manager/repository bug fixes
- tests for uncovered behavior
- auth, migration, or operational hardening with a narrow scope

Changes that should usually start with an issue:

- new storage backends
- major agent-loop redesign
- MCP transport redesign
- frontend rework in the pre-built `static/` output
- large multi-module refactors with unclear migration paths

## Development environment

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Git

### Clone and install

```bash
git clone https://github.com/kim62210/open-agent.git
cd open-agent
uv sync --group dev
```

### Initialize local state

```bash
uv run open-agent init
```

This creates `~/.open-agent/` and the bootstrap files used by the application.

Edit `~/.open-agent/.env` and add provider credentials only for the models you plan to use.

### Run the application locally

```bash
uv run open-agent start --dev
```

Development mode enables permissive local CORS and dev-oriented startup behavior.

### Useful local commands

```bash
# Run the full test suite
uv run pytest

# Run a focused test file
uv run pytest tests/auth/test_auth_api.py -v

# Lint the repository
uv run ruff check .

# Format the repository
uv run ruff format .

# Type-check the repository
uv run mypy .
```

## Repository map

The fastest way to get oriented is to understand the main layers.

| Area | Purpose |
|---|---|
| `server.py` | FastAPI app, lifespan, router registration, hosted pages, static serving |
| `core/agent.py` | Agent orchestrator, workflow routing, streaming loop, tool planning |
| `core/auth/` | JWT, password hashing, auth dependencies, RBAC, rate limiting |
| `core/db/` | Engine, ORM models, repositories, legacy JSON migration |
| `api/endpoints/` | HTTP router files grouped by domain |
| `models/` | Pydantic request/response schemas |
| `tests/` | Unit, integration, and auth tests |
| `bundled_skills/` | Built-in SKILL.md skills shipped with the project |
| `static/` | Pre-built Next.js export served by FastAPI |
| `nexus_rust/` | Native acceleration modules and compatibility layer |

## Coding standards

The project context in `CLAUDE.md` is a good summary of repository rules. The most important ones for contributors are below.

### Required

- Use explicit imports.
- Use `async def` for I/O-bound FastAPI routes and database operations.
- Use `pathlib.Path`, not `os.path`.
- Use project logging, not `print()`.
- Use Pydantic v2 syntax (`ConfigDict`, `field_validator`, `model_config`).
- Prefer small, direct changes that match existing patterns.
- Keep code, comments, and commit messages in English.

### Forbidden

- No `print()` or `console.log()`.
- No bare `except:` blocks.
- No `# type: ignore`, `# noqa`, or similar suppression comments.
- No `exec()`, `eval()`, or `compile()`.
- No committing `.env` files, secrets, or credentials.
- No hardcoded UI secrets or fake environment assumptions in runtime code.

## Testing expectations

Every behavior change should come with tests.

### Test layout

- `tests/auth/` — authentication flows and auth helpers
- `tests/integration/` — API integration tests with `httpx.AsyncClient`
- `tests/unit/` — managers, repositories, helpers, and lower-level units

### Important testing details

- The test suite uses **in-memory SQLite** via fixtures in `tests/conftest.py`.
- Many integration tests override `get_current_user` instead of exercising the full auth flow.
- Auth tests disable the rate limiter explicitly.
- The repository name on disk (`local-agent`) differs from the Python package name (`open_agent`), and `tests/conftest.py` bridges that difference through `sys.modules` setup.

### Migration changes

If you modify ORM models under `core/db/models/`, you should also:

1. add or update an Alembic revision under `alembic/versions/`
2. verify startup behavior with migrations in mind
3. ensure the JSON migration path in `core/db/migrate.py` still behaves safely

## Pull request process

### Scope

- Prefer one logical change per pull request.
- If a change affects multiple subsystems, explain the dependency order in the PR description.
- Avoid mixing refactors, docs rewrites, schema changes, and endpoint behavior changes in one PR unless they are inseparable.

### Commit style

Use conventional commit prefixes that match repository history:

- `feat:`
- `fix:`
- `refactor:`
- `docs:`
- `test:`
- `chore:`

### Pull request checklist

Before opening a PR, make sure you can answer all of these with evidence:

- What behavior changed?
- Which files are the source of truth for that behavior?
- Which tests prove the change?
- Are migrations required?
- Does the change affect auth, persistence, MCP integration, or background execution?

### Recommended PR body structure

```markdown
## Summary
- What changed
- Why it changed

## Implementation notes
- Key files touched
- Migration or compatibility notes

## Verification
- Commands run
- Tests added or updated
```

## Documentation contributions

If your change affects user-facing behavior, also update the relevant documentation:

- `README.md` for first-use flows and major capabilities
- `CHANGELOG.md` for user-visible changes
- `docs/architecture.md` for structural changes
- `CONTRIBUTING.md` when the development workflow itself changes

For diagrams and system flows, use **Mermaid** in Markdown rather than static images.

## Working with generated or non-source assets

Two parts of the repository require extra care:

- `static/` is a **pre-built frontend artifact**, not the source application.
- `nexus_rust/` is a **native extension surface** and should not be modified casually without understanding the compatibility implications.

If a change requires the real frontend source or deep native work, call that out clearly rather than guessing.

## AI-assisted contributions

AI-assisted contributions are acceptable, but the contributor submitting the PR is responsible for:

- verifying every claim with tests or code evidence
- removing generic filler comments and low-signal prose
- ensuring the final diff matches repository conventions
- documenting meaningful architectural or operational trade-offs

## Need help?

If you are unsure whether a change belongs in the repo, open an issue and reference the modules you believe are involved. Concrete file-level questions are much easier to review than vague design proposals.
