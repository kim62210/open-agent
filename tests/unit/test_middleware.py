"""Middleware tests — RequestLoggingMiddleware."""

import pytest
from httpx import AsyncClient


@pytest.fixture()
async def middleware_client():
    """httpx.AsyncClient with middleware attached."""
    import httpx
    from httpx import ASGITransport

    from fastapi import FastAPI
    from open_agent.api.middleware import RequestLoggingMiddleware

    test_app = FastAPI()
    test_app.add_middleware(RequestLoggingMiddleware)

    @test_app.get("/test-endpoint")
    async def test_endpoint():
        return {"status": "ok"}

    @test_app.get("/test-error")
    async def test_error():
        raise ValueError("test error")

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestRequestLoggingMiddleware:
    """RequestLoggingMiddleware behavior."""

    async def test_adds_request_id_header(self, middleware_client: AsyncClient):
        """Response includes X-Request-ID header."""
        resp = await middleware_client.get("/test-endpoint")
        assert resp.status_code == 200
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) == 8

    async def test_successful_request(self, middleware_client: AsyncClient):
        """Successful request returns proper response."""
        resp = await middleware_client.get("/test-endpoint")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_error_propagates(self, middleware_client: AsyncClient):
        """Errors propagate through middleware and result in 500."""
        with pytest.raises(ValueError, match="test error"):
            await middleware_client.get("/test-error")

    async def test_static_paths_not_logged(self, middleware_client: AsyncClient):
        """Static paths (/_next) skip detailed logging (no side-effects to test,
        but verifying they don't crash)."""
        resp = await middleware_client.get("/_next/something")
        # 404 is expected since there's no static handler
        assert resp.status_code in (404, 405)
