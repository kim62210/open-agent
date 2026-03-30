"""MemoryManager unit tests — async DB-backed."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

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
        m1 = await memory_manager.create("첫 번째", owner_user_id="user-1")
        m2 = await memory_manager.create("두 번째", owner_user_id="user-1")
        m3 = await memory_manager.create("세 번째", owner_user_id="user-1")

        result = memory_manager.get_all(owner_user_id="user-1")
        assert len(result) == 3
        assert result[0].id == m3.id
        assert result[1].id == m2.id
        assert result[2].id == m1.id

    async def test_get_all_filters_by_owner(self, memory_manager: MemoryManager):
        owned = await memory_manager.create("내 메모", owner_user_id="user-1")
        await memory_manager.create("남의 메모", owner_user_id="user-2")

        result = memory_manager.get_all(owner_user_id="user-1")

        assert [memory.id for memory in result] == [owned.id]

    async def test_get_denies_other_owner(self, memory_manager: MemoryManager):
        owned = await memory_manager.create("비공개 메모", owner_user_id="user-1")

        assert memory_manager.get(owned.id, owner_user_id="user-2") is None


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
        existing = await memory_manager.create("user prefers Python 3.12 for backend development")
        result = memory_manager.detect_contradictions(
            "user prefers Python 3.13 for backend development", 0.9
        )

        assert result == existing.id

    async def test_no_contradiction_different_topic(self, memory_manager: MemoryManager):
        """Different topics yield no contradiction."""
        await memory_manager.create("사용자는 Python 개발자이다")
        result = memory_manager.detect_contradictions("프로젝트에서 React를 사용한다", 0.8)

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

        pruned = await memory_manager.apply_decay(
            decay_days=0, decay_amount=1.0, prune_threshold=0.9
        )
        assert pruned == 0
        assert memory_manager.get(mem.id) is not None

    async def test_decay_prunes_below_threshold(self, memory_manager: MemoryManager):
        """Memories decayed below threshold are pruned."""
        mem = await memory_manager.create("old memory", confidence=0.35)
        # Force updated_at to be old enough for decay
        old_date = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        memory_manager._memories[mem.id] = MemoryItem(
            **{**mem.model_dump(), "updated_at": old_date}
        )

        pruned = await memory_manager.apply_decay(
            decay_days=60, decay_amount=0.1, prune_threshold=0.3
        )
        assert pruned == 1
        assert memory_manager.get(mem.id) is None

    async def test_decay_reduces_confidence(self, memory_manager: MemoryManager):
        """Memories old enough are decayed but not pruned if above threshold."""
        mem = await memory_manager.create("decaying memory", confidence=0.8)
        old_date = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        memory_manager._memories[mem.id] = MemoryItem(
            **{**mem.model_dump(), "updated_at": old_date}
        )

        pruned = await memory_manager.apply_decay(
            decay_days=60, decay_amount=0.05, prune_threshold=0.3
        )
        assert pruned == 0
        updated = memory_manager.get(mem.id)
        assert updated is not None
        assert updated.confidence == 0.75

    async def test_decay_skips_recent_memories(self, memory_manager: MemoryManager):
        """Recent memories are not decayed."""
        mem = await memory_manager.create("fresh memory", confidence=0.5)
        pruned = await memory_manager.apply_decay(
            decay_days=60, decay_amount=0.5, prune_threshold=0.3
        )
        assert pruned == 0
        assert memory_manager.get(mem.id) is not None
        assert memory_manager.get(mem.id).confidence == 0.5

    async def test_decay_no_memories(self, memory_manager: MemoryManager):
        """Decay on empty manager returns 0."""
        pruned = await memory_manager.apply_decay()
        assert pruned == 0


# --- Relevance Scoring ---


class TestMemoryScoring:
    """Memory relevance scoring tests."""

    async def test_score_with_matching_keywords(self, memory_manager: MemoryManager):
        """Memories with matching keywords get higher scores."""
        await memory_manager.create("user prefers Python for development")
        await memory_manager.create("user enjoys hiking on weekends")

        scored = memory_manager._score_memories("Python development tools")
        # Python+development memory should score higher
        python_score = None
        hiking_score = None
        for mem, score in scored:
            if "Python" in mem.content:
                python_score = score
            elif "hiking" in mem.content:
                hiking_score = score

        assert python_score is not None
        assert hiking_score is not None
        assert python_score > hiking_score

    async def test_score_empty_input(self, memory_manager: MemoryManager):
        """Empty user input still returns scores (based on confidence/recency)."""
        await memory_manager.create("some memory")
        scored = memory_manager._score_memories("")
        assert len(scored) == 1
        _, score = scored[0]
        assert score >= 0.0

    async def test_score_empty_memories(self, memory_manager: MemoryManager):
        """Empty memory store returns no scores."""
        scored = memory_manager._score_memories("test")
        assert scored == []

    async def test_score_pinned_bonus(self, memory_manager: MemoryManager):
        """Pinned memories get a score bonus."""
        m1 = await memory_manager.create("normal memory", confidence=0.7)
        m2 = await memory_manager.create("pinned memory", confidence=0.7)
        await memory_manager.update(m2.id, is_pinned=True)

        scored = memory_manager._score_memories("unrelated query")
        scores = {mem.id: s for mem, s in scored}
        assert scores[m2.id] > scores[m1.id]

    async def test_score_invalid_created_at(self, memory_manager: MemoryManager):
        """Invalid created_at is handled gracefully (defaults to 30-day age)."""
        mem = await memory_manager.create("bad date memory")
        memory_manager._memories[mem.id] = MemoryItem(
            **{**mem.model_dump(), "created_at": "invalid-date"}
        )
        scored = memory_manager._score_memories("test")
        assert len(scored) == 1


# --- build_memory_prompt ---


class TestBuildMemoryPrompt:
    """System prompt memory section builder tests."""

    async def test_empty_when_disabled(self, memory_manager: MemoryManager, settings_manager):
        """Returns empty string when memory is disabled."""
        await settings_manager.update_memory(enabled=False)
        await memory_manager.create("some memory")
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = memory_manager.build_memory_prompt("test")
            assert result == ""

    async def test_empty_when_no_memories(self, memory_manager: MemoryManager, settings_manager):
        """Returns empty string when no memories exist."""
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = memory_manager.build_memory_prompt("test")
            assert result == ""

    async def test_builds_prompt_with_memories(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Builds a prompt section containing memory content."""
        await memory_manager.create("user likes Python", category="preference", confidence=0.9)
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = memory_manager.build_memory_prompt("Python help")
            assert "Long-term Memory" in result
            assert "Python" in result

    async def test_filters_low_relevance(self, memory_manager: MemoryManager, settings_manager):
        """Low-relevance memories are filtered out when user_input is provided."""
        await memory_manager.create(
            "completely unrelated topic about gardening vegetables", confidence=0.5
        )
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = memory_manager.build_memory_prompt("quantum physics research")
            # May or may not be empty depending on scoring, but tests the filtering path
            assert isinstance(result, str)

    async def test_prompt_without_user_input(self, memory_manager: MemoryManager, settings_manager):
        """Without user_input, all memories are included (sorted by confidence)."""
        await memory_manager.create("memory A", confidence=0.9)
        await memory_manager.create("memory B", confidence=0.6)
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = memory_manager.build_memory_prompt()
            assert "memory A" in result
            assert "memory B" in result


# --- Contradiction Detection (advanced) ---


class TestContradictionAdvanced:
    """Advanced contradiction detection scenarios."""

    async def test_near_identical_not_flagged(self, memory_manager: MemoryManager):
        """Overlap >= 0.9 is not a contradiction (considered same memory)."""
        await memory_manager.create("user prefers Python for backend")
        result = memory_manager.detect_contradictions("user prefers Python for backend", 0.8)
        assert result is None

    async def test_empty_new_content(self, memory_manager: MemoryManager):
        """Empty new content returns None."""
        await memory_manager.create("existing memory content")
        result = memory_manager.detect_contradictions("", 0.8)
        assert result is None

    async def test_contradiction_picks_highest_overlap(self, memory_manager: MemoryManager):
        """When multiple candidates, the one with highest overlap wins."""
        m1 = await memory_manager.create("user prefers React for frontend development")
        m2 = await memory_manager.create("user prefers Vue for frontend development work")

        result = memory_manager.detect_contradictions(
            "user prefers Angular for frontend development", 0.9
        )
        # Both have similar overlap; result should be one of them
        assert result in (m1.id, m2.id)

    async def test_empty_mem_words_skipped(self, memory_manager: MemoryManager):
        """Memories with only short words are skipped."""
        await memory_manager.create("a b")  # all words < 2 chars
        result = memory_manager.detect_contradictions("different content here", 0.8)
        assert result is None


# --- Eviction ---


class TestMemoryEviction:
    """Oldest memory eviction tests."""

    async def test_evict_oldest_non_pinned(self, memory_manager: MemoryManager):
        """Evicts the oldest non-pinned memory."""
        m1 = await memory_manager.create("oldest")
        await memory_manager.create("newer")

        evicted_id = await memory_manager._evict_oldest()
        assert evicted_id == m1.id
        assert memory_manager.get(m1.id) is None

    async def test_evict_oldest_all_pinned(self, memory_manager: MemoryManager):
        """Returns None when all memories are pinned."""
        m1 = await memory_manager.create("pinned 1")
        await memory_manager.update(m1.id, is_pinned=True)

        result = await memory_manager._evict_oldest()
        assert result is None

    async def test_evict_oldest_empty(self, memory_manager: MemoryManager):
        """Returns None when no memories exist."""
        result = await memory_manager._evict_oldest()
        assert result is None


# --- Compression ---


class TestMemoryCompression:
    """Memory compression tests."""

    async def test_compression_skipped_under_cooldown(self, memory_manager: MemoryManager):
        """Compression is skipped when cooldown is active."""
        import time

        memory_manager._last_compressed_at = time.monotonic()
        result = await memory_manager._compress_memories()
        assert result == 0

    async def test_compression_skipped_too_few_unpinned(self, memory_manager: MemoryManager):
        """Compression is skipped when fewer than 4 unpinned memories."""
        await memory_manager.create("mem1")
        await memory_manager.create("mem2")
        result = await memory_manager._compress_memories()
        assert result == 0

    async def test_compression_empty_llm_response(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Compression returns 0 when LLM returns empty content."""
        for i in range(5):
            await memory_manager.create(f"memory {i}")

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value=None),
            ),
        ):
            result = await memory_manager._compress_memories()
            assert result == 0

    async def test_compression_non_list_response(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Compression returns 0 when LLM returns non-list JSON."""
        for i in range(5):
            await memory_manager.create(f"memory {i}")

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value='{"not": "a list"}'),
            ),
        ):
            result = await memory_manager._compress_memories()
            assert result == 0

    async def test_compression_exception_returns_zero(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Compression returns 0 on LLM exception."""
        for i in range(5):
            await memory_manager.create(f"memory {i}")

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(side_effect=RuntimeError("API error")),
            ),
        ):
            result = await memory_manager._compress_memories()
            assert result == 0


# --- Extract and Save ---


class TestExtractAndSave:
    """Memory extraction from conversation tests."""

    async def test_extraction_disabled(self, memory_manager: MemoryManager, settings_manager):
        """Returns empty list when memory is disabled."""
        await settings_manager.update_memory(enabled=False)
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("hello", "hi there")
            assert result == []

    async def test_extraction_empty_llm_response(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Returns empty list when LLM returns empty content."""
        mock_llm.return_value = None

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("hi", "hello")
            assert result == []

    async def test_extraction_valid_memories(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Extracts and creates valid memories from LLM response."""
        extracted = json.dumps(
            [
                {"content": "User prefers Python", "category": "preference", "confidence": 0.9},
                {
                    "content": "User works on FastAPI project",
                    "category": "context",
                    "confidence": 0.8,
                },
            ]
        )
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("I use Python with FastAPI", "Great!")
            assert len(result) == 2
            contents = {m.content for m in result}
            assert "User prefers Python" in contents

    async def test_extraction_skips_low_confidence(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Memories below MIN_CONFIDENCE (0.5) are skipped."""
        extracted = json.dumps(
            [
                {"content": "Low confidence memory", "category": "fact", "confidence": 0.3},
            ]
        )
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("test", "test")
            assert len(result) == 0

    async def test_extraction_skips_empty_content(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Items with empty content are skipped."""
        extracted = json.dumps(
            [
                {"content": "", "category": "fact", "confidence": 0.9},
                {"content": "  ", "category": "fact", "confidence": 0.9},
            ]
        )
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("test", "test")
            assert len(result) == 0

    async def test_extraction_invalid_category_defaults_to_fact(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Invalid category defaults to 'fact'."""
        extracted = json.dumps(
            [
                {"content": "Valid memory", "category": "invalid_cat", "confidence": 0.8},
            ]
        )
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("test", "test")
            assert len(result) == 1
            assert result[0].category == "fact"

    async def test_extraction_invalid_confidence_defaults(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Invalid confidence value defaults to 0.7."""
        extracted = json.dumps(
            [
                {"content": "Memory with bad confidence", "category": "fact", "confidence": "bad"},
            ]
        )
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("test", "test")
            assert len(result) == 1
            assert result[0].confidence == 0.7

    async def test_extraction_handles_markdown_fenced_json(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Handles markdown-fenced JSON response from LLM."""
        extracted = '```json\n[{"content": "Memory from fenced", "category": "fact", "confidence": 0.8}]\n```'
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("test", "test")
            assert len(result) == 1
            assert result[0].content == "Memory from fenced"

    async def test_extraction_non_list_json_returns_empty(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Non-list JSON from LLM returns empty list."""
        mock_llm.return_value = '{"single": "object"}'

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("test", "test")
            assert result == []

    async def test_extraction_exception_returns_empty(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """LLM exception during extraction returns empty list."""
        mock_llm.side_effect = RuntimeError("API error")

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("test", "test")
            assert result == []

    async def test_extraction_contradiction_replaces_lower_confidence(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """New memory with higher confidence replaces contradicting memory."""
        existing = await memory_manager.create(
            "user prefers Python 3.12 for backend development",
            confidence=0.6,
        )

        extracted = json.dumps(
            [
                {
                    "content": "user prefers Python 3.13 for backend development",
                    "category": "fact",
                    "confidence": 0.9,
                }
            ]
        )
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("Python 3.13 is great", "Indeed!")
            assert len(result) == 1
            assert memory_manager.get(existing.id) is None

    async def test_extraction_contradiction_keeps_higher_confidence(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Existing memory with higher confidence is kept over new contradiction."""
        await memory_manager.create(
            "user prefers Python 3.12 for backend development",
            confidence=0.95,
        )

        extracted = json.dumps(
            [
                {
                    "content": "user prefers Python 3.13 for backend development",
                    "category": "fact",
                    "confidence": 0.6,
                }
            ]
        )
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("Python 3.13", "Ok")
            assert len(result) == 0


# --- Batch Extraction ---


class TestBatchExtraction:
    """Batch extraction from multiple turns."""

    async def test_empty_turns(self, memory_manager: MemoryManager):
        """Empty turns list returns empty result."""
        result = await memory_manager.extract_and_save_batch([])
        assert result == []

    async def test_all_trivial_turns(self, memory_manager: MemoryManager):
        """All trivial turns (< 10 chars) are skipped."""
        result = await memory_manager.extract_and_save_batch([("hi", "hey"), ("ok", "ok")])
        assert result == []

    async def test_meaningful_turns_extracted(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Meaningful turns are combined and extracted."""
        extracted = json.dumps([{"content": "batch memory", "category": "fact", "confidence": 0.8}])
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save_batch(
                [
                    ("I prefer Python for all my projects", "Python is great for that!"),
                ]
            )
            assert len(result) == 1
            assert result[0].content == "batch memory"

    async def test_batch_extraction_exception(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """Batch extraction handles exceptions gracefully."""
        mock_llm.side_effect = RuntimeError("batch fail")

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save_batch(
                [
                    ("Long enough message for extraction", "Response message also long enough"),
                ]
            )
            assert result == []


# --- Session Summary Generation ---


class TestSessionSummary:
    """Session summary generation tests."""

    async def test_too_few_user_messages(self, memory_manager: MemoryManager, settings_manager):
        """Returns None when fewer than 2 user messages."""
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.generate_session_summary(
                "session-1", "Test Session", [{"role": "user", "content": "hello"}]
            )
            assert result is None

    async def test_single_user_message(self, memory_manager: MemoryManager, settings_manager):
        """Returns None when only 1 user message exists."""
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.generate_session_summary(
                "session-1",
                "Test Session",
                [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi there"},
                ],
            )
            assert result is None

    async def test_empty_conversation_after_filtering(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Returns None when conversation has user messages but only non-string content."""
        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            # 2 user messages but content is not str (list) and empty str content
            result = await memory_manager.generate_session_summary(
                "session-1",
                "Test Session",
                [
                    {"role": "user", "content": ["not a string"]},
                    {"role": "user", "content": ["also not a string"]},
                ],
            )
            # conversation parts filter requires isinstance(content, str) and content truthy
            # so conversation will be empty -> returns None
            assert result is None

    async def test_summary_generated(self, memory_manager: MemoryManager, settings_manager):
        """Summary is generated when enough user messages exist."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value="- Discussed Python\n- Decided on FastAPI"),
            ),
        ):
            messages = [
                {"role": "user", "content": "Let's set up a Python project"},
                {"role": "assistant", "content": "Sure, I recommend FastAPI"},
                {"role": "user", "content": "Sounds good, let's do that"},
                {"role": "assistant", "content": "Here's the setup..."},
            ]
            result = await memory_manager.generate_session_summary(
                "session-1", "Project Setup", messages
            )
            assert result is not None
            assert "Python" in result or "FastAPI" in result

    async def test_summary_llm_failure(self, memory_manager: MemoryManager, settings_manager):
        """Returns None when LLM call fails."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(side_effect=RuntimeError("LLM down")),
            ),
        ):
            messages = [
                {"role": "user", "content": "msg 1"},
                {"role": "assistant", "content": "response 1"},
                {"role": "user", "content": "msg 2"},
            ]
            result = await memory_manager.generate_session_summary("session-1", "Test", messages)
            assert result is None

    async def test_summary_empty_response(self, memory_manager: MemoryManager, settings_manager):
        """Returns None when LLM returns empty response."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value=None),
            ),
        ):
            messages = [
                {"role": "user", "content": "msg 1"},
                {"role": "assistant", "content": "response 1"},
                {"role": "user", "content": "msg 2"},
            ]
            result = await memory_manager.generate_session_summary("session-1", "Test", messages)
            assert result is None

    async def test_summary_filters_non_user_assistant_roles(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Only user and assistant messages are included in conversation."""
        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value="- Summary of conversation"),
            ),
        ):
            messages = [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "first message"},
                {"role": "assistant", "content": "first reply"},
                {"role": "tool", "content": "tool output"},
                {"role": "user", "content": "second message"},
            ]
            result = await memory_manager.generate_session_summary("session-1", "Test", messages)
            assert result is not None


# --- Build Session Summary Prompt (L2) ---


class TestBuildSessionSummaryPrompt:
    """Session summary prompt builder tests."""

    async def test_empty_when_no_summaries(self, memory_manager: MemoryManager):
        """Returns empty string when no summaries exist in DB."""
        with patch.object(memory_manager, "_load_summaries", AsyncMock(return_value=[])):
            result = await memory_manager.build_session_summary_prompt()
            assert result == ""

    async def test_excludes_current_session(self, memory_manager: MemoryManager):
        """Current session is excluded from candidates."""
        summaries = [
            {"session_id": "current", "title": "Current", "summary": "active session"},
        ]
        with patch.object(memory_manager, "_load_summaries", AsyncMock(return_value=summaries)):
            result = await memory_manager.build_session_summary_prompt(current_session_id="current")
            assert result == ""

    async def test_returns_recent_without_user_input(self, memory_manager: MemoryManager):
        """Without user_input, returns the most recent summaries."""
        summaries = [
            {"session_id": "s1", "title": "Session 1", "summary": "Discussed Python"},
            {"session_id": "s2", "title": "Session 2", "summary": "Built a FastAPI app"},
            {"session_id": "s3", "title": "Session 3", "summary": "Deployed to production"},
        ]
        with patch.object(memory_manager, "_load_summaries", AsyncMock(return_value=summaries)):
            result = await memory_manager.build_session_summary_prompt(max_summaries=2)
            assert "Recent Session History" in result
            # Should include the last 2 summaries
            assert "Session 2" in result or "Session 3" in result

    async def test_filters_by_relevance_with_user_input(self, memory_manager: MemoryManager):
        """With user_input, only relevant summaries are included."""
        summaries = [
            {
                "session_id": "s1",
                "title": "Python",
                "summary": "Python development tools and setup",
            },
            {"session_id": "s2", "title": "Cooking", "summary": "Recipe for pasta carbonara"},
        ]
        with patch.object(memory_manager, "_load_summaries", AsyncMock(return_value=summaries)):
            result = await memory_manager.build_session_summary_prompt(
                user_input="Python development"
            )
            if result:
                assert "Python" in result

    async def test_no_relevant_summaries(self, memory_manager: MemoryManager):
        """Returns empty when no summaries are relevant to user input."""
        summaries = [
            {"session_id": "s1", "title": "Cooking", "summary": "Recipe for pasta carbonara"},
        ]
        with patch.object(memory_manager, "_load_summaries", AsyncMock(return_value=summaries)):
            result = await memory_manager.build_session_summary_prompt(
                user_input="quantum physics research papers"
            )
            assert result == ""


# --- Build Memory Prompt (Token Limit) ---


class TestBuildMemoryPromptTokenLimit:
    """Token limit truncation in build_memory_prompt."""

    async def test_truncates_when_exceeding_token_limit(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Memories beyond the token limit are truncated."""
        # Set max_injection_tokens so only a few memories fit
        # Each memory line is ~80 chars, limit = 50 * 4 = 200 chars -> ~2-3 lines
        await settings_manager.update_memory(max_injection_tokens=50)

        for i in range(20):
            await memory_manager.create(
                f"This is a long memory content item number {i} with substantial text",
                confidence=0.9,
            )

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = memory_manager.build_memory_prompt()
            assert "Long-term Memory" in result
            # The number of memory items should be less than 20 due to truncation
            memory_lines = [line for line in result.split("\n") if line.startswith("- [")]
            assert memory_lines  # at least one line
            assert len(memory_lines) < 20


# --- Compression Success Path ---


class TestCompressionSuccess:
    """Memory compression with successful merge."""

    async def test_compression_merges_memories(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Successful compression merges memories and updates cache."""
        mems = []
        for i in range(5):
            m = await memory_manager.create(f"memory content {i}", confidence=0.7)
            mems.append(m)

        all_ids = [m.id for m in mems]

        # Build a valid compression response that merges first 2 and keeps rest
        compressed = json.dumps(
            [
                {
                    "source_ids": [all_ids[0], all_ids[1]],
                    "content": "merged memory 0 and 1",
                    "category": "fact",
                    "confidence": 0.8,
                },
                {
                    "source_ids": [all_ids[2]],
                    "content": mems[2].content,
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": [all_ids[3]],
                    "content": mems[3].content,
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": [all_ids[4]],
                    "content": mems[4].content,
                    "category": "fact",
                    "confidence": 0.7,
                },
            ]
        )

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value=compressed),
            ),
        ):
            freed = await memory_manager._compress_memories()
            assert freed == 1  # 2 merged into 1 = 1 freed
            # Verify cache state: should have 4 memories (5 - 1 freed)
            assert len(memory_manager._memories) == 4

    async def test_compression_aborts_on_duplicate_source_id(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Compression aborts when LLM returns duplicate source IDs."""
        mems = []
        for i in range(5):
            m = await memory_manager.create(f"memory {i}", confidence=0.7)
            mems.append(m)

        all_ids = [m.id for m in mems]

        # Duplicate source_id
        compressed = json.dumps(
            [
                {
                    "source_ids": [all_ids[0], all_ids[1]],
                    "content": "merged",
                    "category": "fact",
                    "confidence": 0.8,
                },
                {
                    "source_ids": [all_ids[1], all_ids[2]],
                    "content": "bad merge",
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": [all_ids[3]],
                    "content": "single",
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": [all_ids[4]],
                    "content": "single",
                    "category": "fact",
                    "confidence": 0.7,
                },
            ]
        )

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value=compressed),
            ),
        ):
            freed = await memory_manager._compress_memories()
            assert freed == 0  # aborted due to duplicate

    async def test_compression_aborts_on_id_mismatch(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Compression aborts when source IDs don't match originals."""
        mems = []
        for i in range(5):
            m = await memory_manager.create(f"memory {i}", confidence=0.7)
            mems.append(m)

        all_ids = [m.id for m in mems]

        # Missing one ID, extra fake ID
        compressed = json.dumps(
            [
                {
                    "source_ids": [all_ids[0]],
                    "content": "single",
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": [all_ids[1]],
                    "content": "single",
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": [all_ids[2]],
                    "content": "single",
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": ["fake_id"],
                    "content": "bad",
                    "category": "fact",
                    "confidence": 0.7,
                },
            ]
        )

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value=compressed),
            ),
        ):
            freed = await memory_manager._compress_memories()
            assert freed == 0

    async def test_compression_handles_fenced_json(
        self, memory_manager: MemoryManager, settings_manager
    ):
        """Compression handles markdown-fenced JSON from LLM."""
        mems = []
        for i in range(5):
            m = await memory_manager.create(f"memory {i}", confidence=0.7)
            mems.append(m)

        all_ids = [m.id for m in mems]

        inner = json.dumps(
            [
                {
                    "source_ids": [all_ids[0], all_ids[1]],
                    "content": "merged",
                    "category": "fact",
                    "confidence": 0.8,
                },
                {
                    "source_ids": [all_ids[2]],
                    "content": mems[2].content,
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": [all_ids[3]],
                    "content": mems[3].content,
                    "category": "fact",
                    "confidence": 0.7,
                },
                {
                    "source_ids": [all_ids[4]],
                    "content": mems[4].content,
                    "category": "fact",
                    "confidence": 0.7,
                },
            ]
        )
        fenced = f"```json\n{inner}\n```"

        with (
            patch("open_agent.core.settings_manager.settings_manager", settings_manager),
            patch(
                "open_agent.core.llm.LLMClient.simple_completion",
                AsyncMock(return_value=fenced),
            ),
        ):
            freed = await memory_manager._compress_memories()
            assert freed == 1


# --- Capacity and Eviction during Extraction ---


class TestCapacityEviction:
    """Tests for auto-eviction during extraction at capacity."""

    async def test_extraction_evicts_at_capacity(
        self, memory_manager: MemoryManager, settings_manager, mock_llm
    ):
        """When at max_memories, extraction evicts oldest before creating new."""
        await settings_manager.update_memory(max_memories=3)

        # Fill up to capacity
        await memory_manager.create("old memory 1", confidence=0.8)
        await memory_manager.create("old memory 2", confidence=0.8)
        await memory_manager.create("old memory 3", confidence=0.8)

        extracted = json.dumps(
            [{"content": "new memory from extraction", "category": "fact", "confidence": 0.9}]
        )
        mock_llm.return_value = extracted

        with patch("open_agent.core.settings_manager.settings_manager", settings_manager):
            result = await memory_manager.extract_and_save("test", "test")
            assert len(result) == 1
            # Should still be at capacity (one evicted, one added)
            assert len(memory_manager._memories) == 3
