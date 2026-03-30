"""Auth API endpoint integration tests."""

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from open_agent.api.middleware import RequestLoggingMiddleware

from core.auth.dependencies import get_current_user


class TestRegister:
    """POST /api/auth/register"""

    async def test_register_new_user(self, auth_client: AsyncClient):
        """Register a new user returns 201 with user data."""
        resp = await auth_client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "username": "newuser", "password": "password123"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "new@example.com"
        assert data["username"] == "newuser"
        assert data["is_active"] is True
        assert "id" in data

    async def test_register_duplicate_email(self, auth_client: AsyncClient):
        """Registering with an existing email returns 409."""
        payload = {"email": "dup@example.com", "username": "user1", "password": "password123"}
        resp1 = await auth_client.post("/api/auth/register", json=payload)
        assert resp1.status_code == 201

        payload2 = {"email": "dup@example.com", "username": "user2", "password": "password123"}
        resp2 = await auth_client.post("/api/auth/register", json=payload2)
        assert resp2.status_code == 409

    async def test_register_duplicate_username(self, auth_client: AsyncClient):
        """Registering with an existing username returns 409."""
        await auth_client.post(
            "/api/auth/register",
            json={"email": "a@example.com", "username": "taken", "password": "password123"},
        )
        resp = await auth_client.post(
            "/api/auth/register",
            json={"email": "b@example.com", "username": "taken", "password": "password123"},
        )
        assert resp.status_code == 409

    async def test_register_first_user_is_admin(self, auth_client: AsyncClient):
        """First registered user automatically gets admin role."""
        resp = await auth_client.post(
            "/api/auth/register",
            json={"email": "first@example.com", "username": "firstuser", "password": "password123"},
        )

        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"


class TestLogin:
    """POST /api/auth/login"""

    async def test_login_success(self, auth_client: AsyncClient):
        """Valid credentials return 200 with access + refresh tokens."""
        await auth_client.post(
            "/api/auth/register",
            json={"email": "login@example.com", "username": "loginuser", "password": "password123"},
        )

        resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "password123"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, auth_client: AsyncClient):
        """Wrong password returns 401."""
        await auth_client.post(
            "/api/auth/register",
            json={"email": "wp@example.com", "username": "wpuser", "password": "password123"},
        )

        resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "wp@example.com", "password": "wrongpassword"},
        )

        assert resp.status_code == 401

    async def test_login_nonexistent_email(self, auth_client: AsyncClient):
        """Login with unregistered email returns 401."""
        resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "password123"},
        )

        assert resp.status_code == 401


class TestMe:
    """GET /api/auth/me"""

    async def test_me_with_valid_token(self, auth_client: AsyncClient):
        """Authenticated user can access /me endpoint."""
        await auth_client.post(
            "/api/auth/register",
            json={"email": "me@example.com", "username": "meuser", "password": "password123"},
        )
        login_resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "me@example.com", "password": "password123"},
        )
        token = login_resp.json()["access_token"]

        resp = await auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "me@example.com"
        assert data["username"] == "meuser"

    async def test_me_without_token(self, auth_client: AsyncClient):
        """Accessing /me without token returns 401."""
        resp = await auth_client.get("/api/auth/me")

        assert resp.status_code == 401

    async def test_authenticated_request_populates_request_state_user(
        self,
        auth_client: AsyncClient,
        _patch_db_factory,
    ):
        await auth_client.post(
            "/api/auth/register",
            json={"email": "state@example.com", "username": "stateuser", "password": "password123"},
        )
        login_resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "state@example.com", "password": "password123"},
        )
        token = login_resp.json()["access_token"]

        test_app = FastAPI()
        test_app.add_middleware(RequestLoggingMiddleware)

        @test_app.get("/whoami")
        async def whoami(
            request: Request,
            current_user: Annotated[dict, Depends(get_current_user)],
        ) -> dict:
            return {
                "current_user": current_user,
                "state_user": getattr(request.state, "user", None),
            }

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/whoami",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["state_user"] == data["current_user"]


class TestRefresh:
    async def test_refresh_rotates_refresh_token_and_revokes_old_one(
        self, auth_client: AsyncClient
    ):
        await auth_client.post(
            "/api/auth/register",
            json={
                "email": "refresh@example.com",
                "username": "refreshuser",
                "password": "password123",
            },
        )
        login_resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "refresh@example.com", "password": "password123"},
        )
        original_refresh_token = login_resp.json()["refresh_token"]

        refresh_resp = await auth_client.post(
            "/api/auth/refresh",
            json={"refresh_token": original_refresh_token},
        )

        assert refresh_resp.status_code == 200
        refreshed_token = refresh_resp.json()["refresh_token"]
        assert refreshed_token != original_refresh_token

        reused_resp = await auth_client.post(
            "/api/auth/refresh",
            json={"refresh_token": original_refresh_token},
        )
        assert reused_resp.status_code == 401

        latest_resp = await auth_client.post(
            "/api/auth/refresh",
            json={"refresh_token": refreshed_token},
        )
        assert latest_resp.status_code == 200


class TestProtectedEndpoints:
    """Auth enforcement on protected endpoints."""

    async def test_protected_endpoint_without_auth(self, auth_client: AsyncClient):
        """Accessing sessions without auth returns 401."""
        resp = await auth_client.get("/api/sessions/")

        assert resp.status_code == 401

    async def test_viewer_role_on_write_endpoint(self, auth_client: AsyncClient):
        """Viewer role cannot access write endpoints (require_user)."""
        # Register first user (admin)
        await auth_client.post(
            "/api/auth/register",
            json={"email": "admin@example.com", "username": "adminuser", "password": "password123"},
        )
        admin_login = await auth_client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "password123"},
        )
        admin_token = admin_login.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Register second user (regular user)
        reg_resp = await auth_client.post(
            "/api/auth/register",
            json={
                "email": "viewer@example.com",
                "username": "vieweruser",
                "password": "password123",
            },
        )
        viewer_user_id = reg_resp.json()["id"]

        # Admin downgrades to viewer via API
        await auth_client.patch(
            f"/api/auth/users/{viewer_user_id}/role",
            json={"role": "viewer"},
            headers=admin_headers,
        )

        # Login as viewer
        viewer_login = await auth_client.post(
            "/api/auth/login",
            json={"email": "viewer@example.com", "password": "password123"},
        )
        viewer_token = viewer_login.json()["access_token"]

        # Viewer tries to create a session (require_user = admin + user only)
        resp = await auth_client.post(
            "/api/sessions/",
            json={"title": "should fail"},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )

        assert resp.status_code == 403


class TestAPIKey:
    """API key creation and usage."""

    async def test_create_and_use_api_key(self, auth_client: AsyncClient):
        """API key can be created and used for authentication."""
        # Register and login
        await auth_client.post(
            "/api/auth/register",
            json={
                "email": "apikey@example.com",
                "username": "apikeyuser",
                "password": "password123",
            },
        )
        login_resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "apikey@example.com", "password": "password123"},
        )
        token = login_resp.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Create API key
        key_resp = await auth_client.post(
            "/api/auth/api-keys",
            json={"name": "test-key"},
            headers=auth_headers,
        )
        assert key_resp.status_code == 201
        api_key = key_resp.json()["key"]
        assert api_key.startswith("oa-")

        # Use API key to access /me
        resp = await auth_client.get("/api/auth/me", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
        assert resp.json()["email"] == "apikey@example.com"

    async def test_list_api_keys(self, auth_client: AsyncClient):
        """Created API keys appear in the listing."""
        await auth_client.post(
            "/api/auth/register",
            json={
                "email": "listkey@example.com",
                "username": "listkeyuser",
                "password": "password123",
            },
        )
        login_resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "listkey@example.com", "password": "password123"},
        )
        token = login_resp.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        await auth_client.post("/api/auth/api-keys", json={"name": "key1"}, headers=auth_headers)

        resp = await auth_client.get("/api/auth/api-keys", headers=auth_headers)
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) == 1
        assert keys[0]["name"] == "key1"
        assert "key" not in keys[0]  # plaintext key is never in listing


class TestAdminEndpoints:
    """Admin-only endpoint access control."""

    async def test_admin_list_users(self, auth_client: AsyncClient):
        """Admin can access user listing."""
        await auth_client.post(
            "/api/auth/register",
            json={"email": "admin2@example.com", "username": "admin2", "password": "password123"},
        )
        login_resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "admin2@example.com", "password": "password123"},
        )
        token = login_resp.json()["access_token"]

        resp = await auth_client.get(
            "/api/auth/users", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_non_admin_cannot_list_users(self, auth_client: AsyncClient):
        """Non-admin user gets 403 on admin-only endpoints."""
        # First user becomes admin
        await auth_client.post(
            "/api/auth/register",
            json={"email": "admin3@example.com", "username": "admin3", "password": "password123"},
        )
        # Second user is regular user
        await auth_client.post(
            "/api/auth/register",
            json={"email": "regular@example.com", "username": "regular", "password": "password123"},
        )
        login_resp = await auth_client.post(
            "/api/auth/login",
            json={"email": "regular@example.com", "password": "password123"},
        )
        token = login_resp.json()["access_token"]

        resp = await auth_client.get(
            "/api/auth/users", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403
