"""세션 API 통합 테스트 — httpx.AsyncClient + FastAPI."""

from httpx import AsyncClient


class TestListSessions:
    """GET /api/sessions/ 엔드포인트."""

    async def test_list_sessions_empty(self, async_client: AsyncClient):
        """초기 상태에서 빈 리스트 반환."""
        resp = await async_client.get("/api/sessions/")

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_sessions_after_create(self, async_client: AsyncClient):
        """세션 생성 후 목록에 포함."""
        await async_client.post("/api/sessions/", json={"title": "API 세션"})
        resp = await async_client.get("/api/sessions/")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "API 세션"


class TestCreateSession:
    """POST /api/sessions/ 엔드포인트."""

    async def test_create_session_with_title(self, async_client: AsyncClient):
        """타이틀 지정하여 세션 생성."""
        resp = await async_client.post("/api/sessions/", json={"title": "새 세션"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "새 세션"
        assert data["id"]
        assert data["message_count"] == 0

    async def test_create_session_empty_title(self, async_client: AsyncClient):
        """빈 타이틀로 생성 시 'New Session' 기본값."""
        resp = await async_client.post("/api/sessions/", json={"title": ""})

        assert resp.status_code == 200
        assert resp.json()["title"] == "New Session"

    async def test_create_session_no_body(self, async_client: AsyncClient):
        """body 없이 생성 시 기본값 적용."""
        resp = await async_client.post("/api/sessions/", json={})

        assert resp.status_code == 200
        assert resp.json()["title"] == "New Session"

    async def test_create_session_registers_summary_task_with_supervisor(
        self, async_client: AsyncClient
    ):
        from unittest.mock import patch

        with patch("open_agent.api.endpoints.sessions.task_supervisor") as mock_supervisor:
            resp = await async_client.post("/api/sessions/", json={"title": "tracked"})

        assert resp.status_code == 200
        mock_supervisor.track.assert_called_once()


class TestGetSession:
    """GET /api/sessions/{id} 엔드포인트."""

    async def test_get_session_detail(self, async_client: AsyncClient):
        """세션 상세 조회 — info + messages."""
        create_resp = await async_client.post("/api/sessions/", json={"title": "상세 조회"})
        session_id = create_resp.json()["id"]

        resp = await async_client.get(f"/api/sessions/{session_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["id"] == session_id
        assert data["info"]["title"] == "상세 조회"
        assert data["messages"] == []

    async def test_get_nonexistent_session_returns_404(self, async_client: AsyncClient):
        """존재하지 않는 세션 조회 시 404."""
        resp = await async_client.get("/api/sessions/nonexistent-id")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestDeleteSession:
    """DELETE /api/sessions/{id} 엔드포인트."""

    async def test_delete_session(self, async_client: AsyncClient):
        """세션 삭제 후 재조회 시 404."""
        create_resp = await async_client.post("/api/sessions/", json={"title": "삭제 대상"})
        session_id = create_resp.json()["id"]

        del_resp = await async_client.delete(f"/api/sessions/{session_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"

        get_resp = await async_client.get(f"/api/sessions/{session_id}")
        assert get_resp.status_code == 404

    async def test_delete_nonexistent_session_returns_404(self, async_client: AsyncClient):
        """존재하지 않는 세션 삭제 시 404."""
        resp = await async_client.delete("/api/sessions/nonexistent-id")
        assert resp.status_code == 404


class TestUpdateSession:
    """PATCH /api/sessions/{id} 엔드포인트."""

    async def test_update_session_title(self, async_client: AsyncClient):
        """세션 타이틀 변경."""
        create_resp = await async_client.post("/api/sessions/", json={"title": "원래 제목"})
        session_id = create_resp.json()["id"]

        resp = await async_client.patch(
            f"/api/sessions/{session_id}", json={"title": "변경된 제목"}
        )

        assert resp.status_code == 200
        assert resp.json()["title"] == "변경된 제목"


class TestSaveMessages:
    """PUT /api/sessions/{id}/messages 엔드포인트."""

    async def test_save_messages(self, async_client: AsyncClient):
        """메시지 저장 후 세션 메타데이터 업데이트 확인."""
        create_resp = await async_client.post("/api/sessions/", json={"title": "메시지 테스트"})
        session_id = create_resp.json()["id"]

        messages = [
            {"role": "user", "content": "안녕하세요"},
            {"role": "assistant", "content": "반갑습니다!"},
        ]
        resp = await async_client.put(
            f"/api/sessions/{session_id}/messages", json={"messages": messages}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["message_count"] == 2
        assert data["preview"] == "반갑습니다!"

    async def test_save_messages_nonexistent_session(self, async_client: AsyncClient):
        """존재하지 않는 세션에 메시지 저장 시 404."""
        messages = [{"role": "user", "content": "test"}]
        resp = await async_client.put(
            "/api/sessions/nonexistent-id/messages", json={"messages": messages}
        )

        assert resp.status_code == 404


class TestUpdateSessionExtended:
    """Extended session update tests."""

    async def test_update_nonexistent_session_returns_404(self, async_client: AsyncClient):
        """Returns 404 when updating non-existent session."""
        resp = await async_client.patch("/api/sessions/nonexistent-id", json={"title": "New Title"})
        assert resp.status_code == 404

    async def test_update_session_preserves_messages(self, async_client: AsyncClient):
        """Updating title does not affect message count."""
        create_resp = await async_client.post("/api/sessions/", json={"title": "Original"})
        session_id = create_resp.json()["id"]

        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        await async_client.put(f"/api/sessions/{session_id}/messages", json={"messages": messages})

        resp = await async_client.patch(
            f"/api/sessions/{session_id}", json={"title": "Updated Title"}
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"
        assert resp.json()["message_count"] == 2


class TestGetSessionMessages:
    """GET /api/sessions/{id} — message content verification."""

    async def test_get_session_with_messages(self, async_client: AsyncClient):
        """Returns session detail with previously saved messages."""
        create_resp = await async_client.post("/api/sessions/", json={"title": "Msg Test"})
        session_id = create_resp.json()["id"]

        messages = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ]
        await async_client.put(f"/api/sessions/{session_id}/messages", json={"messages": messages})

        resp = await async_client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["content"] == "Python is a programming language."


class TestMultipleSessions:
    """Multiple session operations."""

    async def test_create_multiple_sessions(self, async_client: AsyncClient):
        """Multiple sessions are listed in order."""
        await async_client.post("/api/sessions/", json={"title": "Session 1"})
        await async_client.post("/api/sessions/", json={"title": "Session 2"})

        resp = await async_client.get("/api/sessions/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_delete_one_session_keeps_others(self, async_client: AsyncClient):
        """Deleting one session does not affect others."""
        await async_client.post("/api/sessions/", json={"title": "Keep"})
        resp2 = await async_client.post("/api/sessions/", json={"title": "Delete"})

        await async_client.delete(f"/api/sessions/{resp2.json()['id']}")

        resp = await async_client.get("/api/sessions/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Keep"
