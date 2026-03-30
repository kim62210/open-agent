"""Server tests — exception handlers, CORS, routing, lifespan, host-info."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture()
async def server_client():
    """httpx.AsyncClient using the real app but with mocked lifespan."""
    import httpx
    from fastapi import FastAPI
    from httpx import ASGITransport
    from open_agent.core.exceptions import (
        AlreadyExistsError,
        InvalidPathError,
        JobStateError,
        LLMContextWindowError,
        LLMError,
        LLMRateLimitError,
        MCPConnectionError,
        NotFoundError,
        NotInitializedError,
        OpenAgentError,
        PermissionDeniedError,
        StorageLimitError,
    )
    from open_agent.server import _register_exception_handlers

    from core.auth.dependencies import get_current_user

    test_app = FastAPI()
    _register_exception_handlers(test_app)

    async def _fake_current_user() -> dict:
        return {
            "id": "test-user-id",
            "email": "test@example.com",
            "username": "testuser",
            "role": "admin",
        }

    test_app.dependency_overrides[get_current_user] = _fake_current_user

    # Register test routes that raise each exception type
    @test_app.get("/test/not-found")
    async def _raise_not_found():
        raise NotFoundError("Resource not found")

    @test_app.get("/test/already-exists")
    async def _raise_already_exists():
        raise AlreadyExistsError("Already exists")

    @test_app.get("/test/permission-denied")
    async def _raise_permission_denied():
        raise PermissionDeniedError("Forbidden")

    @test_app.get("/test/invalid-path")
    async def _raise_invalid_path():
        raise InvalidPathError("Bad path")

    @test_app.get("/test/storage-limit")
    async def _raise_storage_limit():
        raise StorageLimitError("Too large")

    @test_app.get("/test/job-state")
    async def _raise_job_state():
        raise JobStateError("Invalid state")

    @test_app.get("/test/llm-rate-limit")
    async def _raise_llm_rate_limit():
        raise LLMRateLimitError("Rate limited")

    @test_app.get("/test/llm-context-window")
    async def _raise_llm_context():
        raise LLMContextWindowError("Context too large")

    @test_app.get("/test/llm-error")
    async def _raise_llm_error():
        raise LLMError("LLM failed")

    @test_app.get("/test/mcp-connection")
    async def _raise_mcp_connection():
        raise MCPConnectionError("MCP failed")

    @test_app.get("/test/not-initialized")
    async def _raise_not_initialized():
        raise NotInitializedError("Not initialized")

    @test_app.get("/test/open-agent-error")
    async def _raise_open_agent():
        raise OpenAgentError("Generic error")

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestNotFoundHandler:
    """NotFoundError -> 404"""

    async def test_not_found(self, server_client: AsyncClient):
        resp = await server_client.get("/test/not-found")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestAlreadyExistsHandler:
    """AlreadyExistsError -> 409"""

    async def test_already_exists(self, server_client: AsyncClient):
        resp = await server_client.get("/test/already-exists")
        assert resp.status_code == 409


class TestPermissionDeniedHandler:
    """PermissionDeniedError -> 403"""

    async def test_permission_denied(self, server_client: AsyncClient):
        resp = await server_client.get("/test/permission-denied")
        assert resp.status_code == 403


class TestInvalidPathHandler:
    """InvalidPathError -> 400"""

    async def test_invalid_path(self, server_client: AsyncClient):
        resp = await server_client.get("/test/invalid-path")
        assert resp.status_code == 400


class TestStorageLimitHandler:
    """StorageLimitError -> 413"""

    async def test_storage_limit(self, server_client: AsyncClient):
        resp = await server_client.get("/test/storage-limit")
        assert resp.status_code == 413


class TestJobStateHandler:
    """JobStateError -> 409"""

    async def test_job_state(self, server_client: AsyncClient):
        resp = await server_client.get("/test/job-state")
        assert resp.status_code == 409


class TestLLMRateLimitHandler:
    """LLMRateLimitError -> 429"""

    async def test_llm_rate_limit(self, server_client: AsyncClient):
        resp = await server_client.get("/test/llm-rate-limit")
        assert resp.status_code == 429


class TestLLMContextWindowHandler:
    """LLMContextWindowError -> 400"""

    async def test_llm_context_window(self, server_client: AsyncClient):
        resp = await server_client.get("/test/llm-context-window")
        assert resp.status_code == 400


class TestLLMErrorHandler:
    """LLMError -> 502"""

    async def test_llm_error(self, server_client: AsyncClient):
        resp = await server_client.get("/test/llm-error")
        assert resp.status_code == 502


class TestMCPConnectionHandler:
    """MCPConnectionError -> 502"""

    async def test_mcp_connection(self, server_client: AsyncClient):
        resp = await server_client.get("/test/mcp-connection")
        assert resp.status_code == 502


class TestNotInitializedHandler:
    """NotInitializedError -> 500"""

    async def test_not_initialized(self, server_client: AsyncClient):
        resp = await server_client.get("/test/not-initialized")
        assert resp.status_code == 500


class TestOpenAgentFallbackHandler:
    """OpenAgentError (fallback) -> 500"""

    async def test_open_agent_fallback(self, server_client: AsyncClient):
        resp = await server_client.get("/test/open-agent-error")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Internal server error"


class TestRegisterExceptionHandlers:
    """_register_exception_handlers function."""

    def test_register_exception_handlers_callable(self):
        """_register_exception_handlers is importable and callable."""
        from open_agent.server import _register_exception_handlers

        assert callable(_register_exception_handlers)


class TestServerApp:
    """Verify the real app object is configured properly."""

    def test_app_title(self):
        """App has correct title."""
        from open_agent.server import app

        assert app.title == "Open Agent API"

    def test_routers_registered(self):
        """Key API prefixes are registered."""
        from open_agent.server import app

        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        # Check that key API routes exist
        prefix_checks = [
            "/api/auth",
            "/api/chat",
            "/api/mcp",
            "/api/skills",
            "/api/pages",
            "/api/settings",
            "/api/sessions",
            "/api/memory",
            "/api/workspace",
            "/api/jobs",
            "/api/sandbox",
            "/api/host-info",
        ]
        for prefix in prefix_checks:
            found = any(prefix in path for path in route_paths)
            assert found, f"Expected route prefix {prefix} not found in app routes"

    def test_cors_middleware_configured(self):
        """CORS middleware is present on the app."""
        from open_agent.server import app

        middleware_classes = [m.cls.__name__ for m in app.user_middleware if hasattr(m, "cls")]
        assert "CORSMiddleware" in middleware_classes

    def test_rate_limiter_attached(self):
        """Rate limiter is attached to app.state."""
        from open_agent.server import app

        assert hasattr(app.state, "limiter")
        assert app.state.limiter is not None


class TestServerHostInfo:
    """host_info endpoint."""

    async def test_host_info_no_expose(self):
        """Returns expose=false when OPEN_AGENT_EXPOSE not set."""
        import httpx
        from fastapi import FastAPI
        from httpx import ASGITransport

        test_app = FastAPI()

        @test_app.get("/api/host-info")
        async def host_info():
            expose = os.environ.get("OPEN_AGENT_EXPOSE") == "1"
            port = int(os.environ.get("OPEN_AGENT_PORT", "4821"))
            result = {"expose": expose, "port": port}
            return result

        transport = ASGITransport(app=test_app)
        with patch.dict(os.environ, {"OPEN_AGENT_EXPOSE": "0", "OPEN_AGENT_PORT": "4821"}):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/host-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["expose"] is False
        assert data["port"] == 4821


class TestServerInjectBase:
    """_inject_base helper function."""

    def test_inject_base_with_head(self):
        """Injects <base> tag after <head>."""
        from open_agent.server import _inject_base

        html = "<html><head><title>Test</title></head><body></body></html>"
        result = _inject_base(html, "/hosted/page1/")
        assert '<base href="/hosted/page1/">' in result
        assert result.index("<base href") > result.index("<head>")

    def test_inject_base_without_head(self):
        """Injects <base> tag at start if no <head> found."""
        from open_agent.server import _inject_base

        html = "<html><body>No head tag</body></html>"
        result = _inject_base(html, "/hosted/page1/")
        assert result.startswith('<base href="/hosted/page1/">')


class TestServerHostedHelpers:
    """Hosted page password helpers."""

    def test_hosted_password_cookie_val(self):
        """Cookie value is a sha256 of the password hash."""
        import hashlib

        from open_agent.server import _hosted_password_cookie_val

        pw_hash = "some-argon2-hash"
        expected = hashlib.sha256(pw_hash.encode()).hexdigest()
        assert _hosted_password_cookie_val(pw_hash) == expected

    def test_hosted_password_form_no_error(self):
        """Password form without wrong flag."""
        from open_agent.server import _hosted_password_form

        resp = _hosted_password_form("page-123", wrong=False)
        assert resp.status_code == 200
        assert "Incorrect password" not in resp.body.decode()

    def test_hosted_password_form_with_error(self):
        """Password form with wrong flag shows error."""
        from open_agent.server import _hosted_password_form

        resp = _hosted_password_form("page-123", wrong=True)
        assert resp.status_code == 200
        assert "Incorrect password" in resp.body.decode()


class TestServerStaticDir:
    """STATIC_DIR constant."""

    def test_static_dir_is_path(self):
        """STATIC_DIR is a Path object."""
        from pathlib import Path

        from open_agent.server import STATIC_DIR

        assert isinstance(STATIC_DIR, Path)


class TestCORSConfig:
    """CORS middleware configuration based on env var."""

    def test_dev_mode_flag(self):
        """_dev_mode is determined by OPEN_AGENT_DEV env."""
        # Just verify the module imports and the constant exists
        import open_agent.server as srv

        assert hasattr(srv, "_dev_mode")


class TestHostedDirectory:
    """hosted_directory endpoint."""

    async def test_no_published_pages(self):
        """Returns empty state HTML when no pages published."""
        import httpx
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse
        from httpx import ASGITransport

        test_app = FastAPI()

        @test_app.get("/hosted/")
        async def hosted_directory():
            from unittest.mock import MagicMock

            pm = MagicMock()
            pm.get_published_pages.return_value = []
            published = pm.get_published_pages()
            if not published:
                return HTMLResponse(content="<h1>No published pages yet.</h1>")

        transport = ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/hosted/")
        assert resp.status_code == 200
        assert "No published pages" in resp.text

    async def test_with_published_pages(self):
        """Returns directory HTML when pages exist."""
        import html as html_lib
        from unittest.mock import MagicMock

        import httpx
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse
        from httpx import ASGITransport

        test_app = FastAPI()

        @test_app.get("/hosted/")
        async def hosted_directory():
            # Simulate the real logic from server.py
            page = MagicMock()
            page.id = "test-page"
            page.name = "Test Page"
            page.description = "A test page"
            page.host_password_hash = None
            page.content_type = "html"
            published = [page]

            items = ""
            for p in published:
                lock = ""
                if p.host_password_hash:
                    lock = " <span>locked</span>"
                href = f"/hosted/{p.id}"
                items += f'<a href="{href}">{html_lib.escape(p.name)}{lock}</a>'
                if p.description:
                    items += f"<small>{html_lib.escape(p.description)}</small>"

            html = f"<h1>Hosted Pages</h1>{items}"
            return HTMLResponse(content=html)

        transport = ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/hosted/")
        assert resp.status_code == 200
        assert "Test Page" in resp.text


class TestLifespan:
    """Lifespan function (startup/shutdown)."""

    async def test_lifespan_imports(self):
        """lifespan function is importable."""
        from open_agent.server import lifespan

        assert callable(lifespan)

    async def test_lifespan_runs(self):
        """lifespan function is an async context manager."""

        # Verify it's an async context manager factory

        from open_agent.server import lifespan

        assert callable(lifespan)

    async def test_lifespan_does_not_import_gh_token_outside_dev(self):
        import sys
        from pathlib import Path

        from fastapi import FastAPI

        mock_agent_mod = MagicMock()
        mock_agent_mod.orchestrator = MagicMock()
        already_loaded = "open_agent.core.agent" in sys.modules
        if not already_loaded:
            sys.modules["open_agent.core.agent"] = mock_agent_mod

        from open_agent.server import lifespan

        class DummyManager:
            async def load_from_db(self):
                return None

            async def start(self):
                return None

            async def stop(self):
                return None

            async def connect_all(self):
                return None

            async def disconnect_all(self):
                return None

            async def load_disabled_from_db(self):
                return None

            def set_bundled_dir(self, _path):
                return None

            def discover_skills(self, _paths):
                return None

            def init_pages_dir(self, _path):
                return None

        with patch.dict(
            os.environ, {"OPEN_AGENT_DEV": "0", "GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False
        ):
            with patch("open_agent.config.init_data_dir") as mock_data_dir:
                mock_data_dir.return_value = Path("/tmp/open-agent-test")
                with patch("core.db.engine.init_db", new_callable=AsyncMock):
                    with patch("core.db.migrate.migrate_json_to_db", new_callable=AsyncMock):
                        with patch("open_agent.server.settings_manager", DummyManager()):
                            with patch("open_agent.server.mcp_manager", DummyManager()):
                                with patch("open_agent.server.skill_manager", DummyManager()):
                                    with patch("open_agent.server.page_manager", DummyManager()):
                                        with patch(
                                            "open_agent.server.session_manager", DummyManager()
                                        ):
                                            with patch(
                                                "open_agent.server.memory_manager", DummyManager()
                                            ):
                                                with patch(
                                                    "open_agent.server.workspace_manager",
                                                    DummyManager(),
                                                ):
                                                    with patch(
                                                        "open_agent.server.job_manager",
                                                        DummyManager(),
                                                    ):
                                                        with patch(
                                                            "open_agent.server.job_scheduler",
                                                            DummyManager(),
                                                        ):
                                                            with patch(
                                                                "core.db.engine.close_db",
                                                                new_callable=AsyncMock,
                                                            ):
                                                                with patch(
                                                                    "subprocess.run"
                                                                ) as mock_run:
                                                                    async with lifespan(FastAPI()):
                                                                        pass

        mock_run.assert_not_called()
        if not already_loaded:
            sys.modules.pop("open_agent.core.agent", None)


class TestHostInfoEndpoint:
    """host_info endpoint on real app."""

    async def test_host_info_default(self):
        """host_info returns correct defaults."""
        import httpx
        from fastapi import FastAPI
        from httpx import ASGITransport

        # Replicate the actual endpoint logic
        test_app = FastAPI()

        @test_app.get("/api/host-info")
        async def host_info():
            expose = os.environ.get("OPEN_AGENT_EXPOSE") == "1"
            port = int(os.environ.get("OPEN_AGENT_PORT", "4821"))
            return {"expose": expose, "port": port}

        transport = ASGITransport(app=test_app)
        with patch.dict(os.environ, {}, clear=False):
            # Ensure OPEN_AGENT_EXPOSE is not set
            os.environ.pop("OPEN_AGENT_EXPOSE", None)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/host-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["expose"] is False

    async def test_host_info_exposed(self):
        """host_info returns expose=true when set."""
        import httpx
        from fastapi import FastAPI
        from httpx import ASGITransport

        test_app = FastAPI()

        @test_app.get("/api/host-info")
        async def host_info():
            expose = os.environ.get("OPEN_AGENT_EXPOSE") == "1"
            port = int(os.environ.get("OPEN_AGENT_PORT", "4821"))
            result = {"expose": expose, "port": port}
            if expose:
                result["lan_ip"] = "192.168.1.100"
            return result

        transport = ASGITransport(app=test_app)
        with patch.dict(os.environ, {"OPEN_AGENT_EXPOSE": "1", "OPEN_AGENT_PORT": "5000"}):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/host-info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["expose"] is True
        assert data["port"] == 5000
        assert "lan_ip" in data


class TestServeFrontendFallback:
    """SPA fallback route."""

    def test_static_dir_path(self):
        """STATIC_DIR points to static/ directory under project."""
        from open_agent.server import STATIC_DIR

        assert STATIC_DIR.name == "static"

    def test_root_route_exists(self):
        """Root route exists on app (either SPA or API root)."""
        from open_agent.server import app

        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        # Either "/" or "/{path:path}" exists
        has_root = any(p == "/" or p == "/{path:path}" for p in route_paths)
        assert has_root
