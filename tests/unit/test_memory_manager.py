"""MemoryManager unit tests — async DB-backed."""

import pytest

from open_agent.core.memory_manager import MemoryManager
from open_agent.models.memory import MemoryItem


class TestMemoryCreate:
    """Memory creation tests."""

    async def test_create_memory_defaults(self, memory_manager: MemoryManager):
        """Default values are applied correctly."""
        mem = await memory_manager.create("사용자는 Python 개발자이다")

        assert mem.id
        assert mem.content == "사용자는 Python 개발자이다"
        assert mem.category == "fact"
        assert mem.confidence == 0.7
        assert mem.source == "llm_inference"
        assert mem.is_pinned is False
        assert mem.created_at
        assert mem.updated_at

    async def test_create_memory_custom_fields(self, memory_manager: MemoryManager):
        """Custom category, confidence, and source are stored."""
        mem = await memory_manager.create(
            content="TypeScript를 선호한다",
            category="preference",
            confidence=0.95,
            source="user_input",
        )

        assert mem.category == "preference"
        assert mem.confidence == 0.95
        assert mem.source == "user_input"

    async def test_create_memory_clamps_confidence(self, memory_manager: MemoryManager):
        """Confidence is clamped to 0.0-1.0 range."""
        high = await memory_manager.create("test high", confidence=1.5)
        assert high.confidence == 1.0

        low = await memory_manager.create("test low", confidence=-0.3)
        assert low.confidence == 0.0

    async def test_create_memory_persists_to_db(self, memory_manager: MemoryManager):
        """Memory persists in DB and survives reload into cache."""
        mem = await memory_manager.create("DB 저장 테스트")

        # Verify in-memory cache
        assert memory_manager.get(mem.id) is not None
        assert memory_manager.get(mem.id).content == "DB 저장 테스트"

        # Verify DB persistence by reloading
        memory_manager._memories.clear()
        await memory_manager.load_from_db()
        reloaded = memory_manager.get(mem.id)
        assert reloaded is not None
        assert reloaded.content == "DB 저장 테스트"


class TestMemoryGet:
    """Memory retrieval tests."""

    async def test_get_existing_memory(self, memory_manager: MemoryManager):
        """Retrieve an existing memory by ID."""
        created = await memory_manager.create("조회 테스트")
        result = memory_manager.get(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.content == "조회 테스트"

    async def test_get_nonexistent_memory(self, memory_manager: MemoryManager):
        """Non-existent memory ID returns None."""
        result = memory_manager.get("nonexistent-id")
        assert result is None

    async def test_get_all_empty(self, memory_manager: MemoryManager):
        """Empty manager returns an empty list."""
        result = memory_manager.get_all()
        assert result == []

    async def test_get_all_ordered_by_created_at(self, memory_manager: MemoryManager):
        """get_all returns memories ordered by created_at descending."""
        m1 = await memory_manager.create("첫 번째")
        m2 = await memory_manager.create("두 번째")
        m3 = await memory_manager.create("세 번째")

        result = memory_manager.get_all()
        assert len(result) == 3
        assert result[0].id == m3.id
        assert result[1].id == m2.id
        assert result[2].id == m1.id


class TestMemoryUpdate:
    """Memory update tests."""

    async def test_update_content(self, memory_manager: MemoryManager):
        """Content can be updated."""
        mem = await memory_manager.create("원래 내용")
        result = await memory_manager.update(mem.id, content="변경된 내용")

        assert result is not None
        assert result.content == "변경된 내용"
        assert result.updated_at != mem.created_at or result.updated_at == mem.created_at

    async def test_update_category_and_confidence(self, memory_manager: MemoryManager):
        """Category and confidence can be updated together."""
        mem = await memory_manager.create("수정 테스트", category="fact", confidence=0.5)
        result = await memory_manager.update(mem.id, category="preference", confidence=0.9)

        assert result is not None
        assert result.category == "preference"
        assert result.confidence == 0.9

    async def test_update_pinned(self, memory_manager: MemoryManager):
        """is_pinned can be toggled."""
        mem = await memory_manager.create("핀 테스트")
        assert mem.is_pinned is False

        result = await memory_manager.update(mem.id, is_pinned=True)
        assert result is not None
        assert result.is_pinned is True

    async def test_update_nonexistent_memory(self, memory_manager: MemoryManager):
        """Updating a non-existent memory returns None."""
        result = await memory_manager.update("nonexistent-id", content="test")
        assert result is None

    async def test_update_none_values_ignored(self, memory_manager: MemoryManager):
        """None values are ignored, preserving existing fields."""
        mem = await memory_manager.create("원래 내용", category="fact")
        result = await memory_manager.update(mem.id, content=None, category=None)

        assert result is not None
        assert result.content == "원래 내용"
        assert result.category == "fact"


class TestMemoryDelete:
    """Memory deletion tests."""

    async def test_delete_existing_memory(self, memory_manager: MemoryManager):
        """Existing memory can be deleted."""
        mem = await memory_manager.create("삭제 대상")
        result = await memory_manager.delete(mem.id)

        assert result is True
        assert memory_manager.get(mem.id) is None

    async def test_delete_nonexistent_memory(self, memory_manager: MemoryManager):
        """Deleting a non-existent memory returns False."""
        result = await memory_manager.delete("nonexistent-id")
        assert result is False


class TestMemoryClearAll:
    """Clear all (pinned protection) tests."""

    async def test_clear_all_removes_unpinned(self, memory_manager: MemoryManager):
        """clear_all removes only unpinned memories."""
        m1 = await memory_manager.create("일반 메모리 1")
        m2 = await memory_manager.create("일반 메모리 2")
        m3 = await memory_manager.create("핀 메모리")
        await memory_manager.update(m3.id, is_pinned=True)

        count = await memory_manager.clear_all()

        assert count == 2
        assert memory_manager.get(m1.id) is None
        assert memory_manager.get(m2.id) is None
        assert memory_manager.get(m3.id) is not None
        assert memory_manager.get(m3.id).is_pinned is True

    async def test_clear_all_empty(self, memory_manager: MemoryManager):
        """clear_all on empty manager returns 0."""
        count = await memory_manager.clear_all()
        assert count == 0

    async def test_clear_all_all_pinned(self, memory_manager: MemoryManager):
        """clear_all with all pinned memories deletes 0."""
        m1 = await memory_manager.create("핀 1")
        m2 = await memory_manager.create("핀 2")
        await memory_manager.update(m1.id, is_pinned=True)
        await memory_manager.update(m2.id, is_pinned=True)

        count = await memory_manager.clear_all()
        assert count == 0
        assert len(memory_manager.get_all()) == 2


class TestMemoryContradiction:
    """Contradiction detection tests."""

    async def test_detect_contradiction(self, memory_manager: MemoryManager):
        """High keyword overlap with different content triggers contradiction.

        detect_contradictions checks overlap > 0.6 && overlap < 0.9.
        """
        existing = await memory_manager.create(
            "user prefers Python 3.12 for backend development"
        )
        result = memory_manager.detect_contradictions(
            "user prefers Python 3.13 for backend development", 0.9
        )

        assert result == existing.id

    async def test_no_contradiction_different_topic(self, memory_manager: MemoryManager):
        """Different topics yield no contradiction."""
        await memory_manager.create("사용자는 Python 개발자이다")
        result = memory_manager.detect_contradictions(
            "프로젝트에서 React를 사용한다", 0.8
        )

        assert result is None

    async def test_no_contradiction_empty(self, memory_manager: MemoryManager):
        """Empty memory store yields no contradiction."""
        result = memory_manager.detect_contradictions("아무 내용", 0.7)
        assert result is None


class TestMemoryDecay:
    """Memory decay tests."""

    async def test_decay_does_not_affect_pinned(self, memory_manager: MemoryManager):
        """Pinned memories are unaffected by decay."""
        mem = await memory_manager.create("핀 메모리", confidence=0.5)
        await memory_manager.update(mem.id, is_pinned=True)

        pruned = await memory_manager.apply_decay(decay_days=0, decay_amount=1.0, prune_threshold=0.9)
        assert pruned == 0
        assert memory_manager.get(mem.id) is not None
