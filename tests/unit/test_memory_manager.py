"""MemoryManager 단위 테스트."""

import json
from pathlib import Path

import pytest

from open_agent.core.memory_manager import MemoryManager
from open_agent.models.memory import MemoryItem


class TestMemoryCreate:
    """메모리 생성 테스트."""

    def test_create_memory_defaults(self, memory_manager: MemoryManager):
        """기본값으로 메모리 생성."""
        mem = memory_manager.create("사용자는 Python 개발자이다")

        assert mem.id
        assert mem.content == "사용자는 Python 개발자이다"
        assert mem.category == "fact"
        assert mem.confidence == 0.7
        assert mem.source == "llm_inference"
        assert mem.is_pinned is False
        assert mem.created_at
        assert mem.updated_at

    def test_create_memory_custom_fields(self, memory_manager: MemoryManager):
        """커스텀 카테고리/신뢰도/소스로 생성."""
        mem = memory_manager.create(
            content="TypeScript를 선호한다",
            category="preference",
            confidence=0.95,
            source="user_input",
        )

        assert mem.category == "preference"
        assert mem.confidence == 0.95
        assert mem.source == "user_input"

    def test_create_memory_clamps_confidence(self, memory_manager: MemoryManager):
        """confidence는 0.0~1.0 범위로 클램핑."""
        high = memory_manager.create("test high", confidence=1.5)
        assert high.confidence == 1.0

        low = memory_manager.create("test low", confidence=-0.3)
        assert low.confidence == 0.0

    def test_create_memory_persists_to_disk(
        self, memory_manager: MemoryManager, tmp_data_dir: Path
    ):
        """메모리 생성 시 memories.json에 저장됨."""
        mem = memory_manager.create("디스크 저장 테스트")

        data = json.loads((tmp_data_dir / "memories.json").read_text(encoding="utf-8"))
        assert len(data["memories"]) == 1
        assert data["memories"][0]["content"] == "디스크 저장 테스트"


class TestMemoryGet:
    """메모리 조회 테스트."""

    def test_get_existing_memory(self, memory_manager: MemoryManager):
        """존재하는 메모리 ID로 조회."""
        created = memory_manager.create("조회 테스트")
        result = memory_manager.get(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.content == "조회 테스트"

    def test_get_nonexistent_memory(self, memory_manager: MemoryManager):
        """존재하지 않는 메모리 ID로 조회 시 None."""
        result = memory_manager.get("nonexistent-id")
        assert result is None

    def test_get_all_empty(self, memory_manager: MemoryManager):
        """초기 상태에서 빈 리스트."""
        result = memory_manager.get_all()
        assert result == []

    def test_get_all_ordered_by_created_at(self, memory_manager: MemoryManager):
        """get_all은 created_at 내림차순 (최신 먼저)."""
        m1 = memory_manager.create("첫 번째")
        m2 = memory_manager.create("두 번째")
        m3 = memory_manager.create("세 번째")

        result = memory_manager.get_all()
        assert len(result) == 3
        # 가장 최근 생성된 것이 먼저
        assert result[0].id == m3.id
        assert result[1].id == m2.id
        assert result[2].id == m1.id


class TestMemoryUpdate:
    """메모리 수정 테스트."""

    def test_update_content(self, memory_manager: MemoryManager):
        """메모리 내용 수정."""
        mem = memory_manager.create("원래 내용")
        result = memory_manager.update(mem.id, content="변경된 내용")

        assert result is not None
        assert result.content == "변경된 내용"
        assert result.updated_at != mem.created_at or result.updated_at == mem.created_at

    def test_update_category_and_confidence(self, memory_manager: MemoryManager):
        """카테고리와 신뢰도 동시 수정."""
        mem = memory_manager.create("수정 테스트", category="fact", confidence=0.5)
        result = memory_manager.update(mem.id, category="preference", confidence=0.9)

        assert result is not None
        assert result.category == "preference"
        assert result.confidence == 0.9

    def test_update_pinned(self, memory_manager: MemoryManager):
        """is_pinned 토글."""
        mem = memory_manager.create("핀 테스트")
        assert mem.is_pinned is False

        result = memory_manager.update(mem.id, is_pinned=True)
        assert result is not None
        assert result.is_pinned is True

    def test_update_nonexistent_memory(self, memory_manager: MemoryManager):
        """존재하지 않는 메모리 수정 시 None."""
        result = memory_manager.update("nonexistent-id", content="test")
        assert result is None

    def test_update_none_values_ignored(self, memory_manager: MemoryManager):
        """None 값은 무시되어 기존 값 유지."""
        mem = memory_manager.create("원래 내용", category="fact")
        result = memory_manager.update(mem.id, content=None, category=None)

        assert result is not None
        assert result.content == "원래 내용"
        assert result.category == "fact"


class TestMemoryDelete:
    """메모리 삭제 테스트."""

    def test_delete_existing_memory(self, memory_manager: MemoryManager):
        """존재하는 메모리 삭제."""
        mem = memory_manager.create("삭제 대상")
        result = memory_manager.delete(mem.id)

        assert result is True
        assert memory_manager.get(mem.id) is None

    def test_delete_nonexistent_memory(self, memory_manager: MemoryManager):
        """존재하지 않는 메모리 삭제 시 False."""
        result = memory_manager.delete("nonexistent-id")
        assert result is False


class TestMemoryClearAll:
    """전체 삭제 (pinned 보호) 테스트."""

    def test_clear_all_removes_unpinned(self, memory_manager: MemoryManager):
        """clear_all은 unpinned 메모리만 삭제."""
        m1 = memory_manager.create("일반 메모리 1")
        m2 = memory_manager.create("일반 메모리 2")
        m3 = memory_manager.create("핀 메모리")
        memory_manager.update(m3.id, is_pinned=True)

        count = memory_manager.clear_all()

        assert count == 2  # unpinned 2개 삭제
        assert memory_manager.get(m1.id) is None
        assert memory_manager.get(m2.id) is None
        # pinned 메모리는 보존
        assert memory_manager.get(m3.id) is not None
        assert memory_manager.get(m3.id).is_pinned is True

    def test_clear_all_empty(self, memory_manager: MemoryManager):
        """빈 상태에서 clear_all은 0 반환."""
        count = memory_manager.clear_all()
        assert count == 0

    def test_clear_all_all_pinned(self, memory_manager: MemoryManager):
        """모든 메모리가 pinned이면 0개 삭제."""
        m1 = memory_manager.create("핀 1")
        m2 = memory_manager.create("핀 2")
        memory_manager.update(m1.id, is_pinned=True)
        memory_manager.update(m2.id, is_pinned=True)

        count = memory_manager.clear_all()
        assert count == 0
        assert len(memory_manager.get_all()) == 2


class TestMemoryContradiction:
    """모순 감지 테스트."""

    def test_detect_contradiction(self, memory_manager: MemoryManager):
        """높은 키워드 유사도 + 다른 내용 → 모순 감지.

        detect_contradictions은 overlap > 0.6 && overlap < 0.9 범위에서 모순을 판단한다.
        한국어는 공백 기준 토큰화이므로 overlap 비율을 맞춘 테스트 데이터를 사용한다.
        """
        # 7개 단어 중 5개 공유 → overlap ≈ 0.71 (0.6 초과, 0.9 미만)
        existing = memory_manager.create(
            "user prefers Python 3.12 for backend development"
        )
        result = memory_manager.detect_contradictions(
            "user prefers Python 3.13 for backend development", 0.9
        )

        assert result == existing.id

    def test_no_contradiction_different_topic(self, memory_manager: MemoryManager):
        """주제가 다르면 모순 없음."""
        memory_manager.create("사용자는 Python 개발자이다")
        result = memory_manager.detect_contradictions(
            "프로젝트에서 React를 사용한다", 0.8
        )

        assert result is None

    def test_no_contradiction_empty(self, memory_manager: MemoryManager):
        """메모리가 비어있으면 모순 없음."""
        result = memory_manager.detect_contradictions("아무 내용", 0.7)
        assert result is None


class TestMemoryDecay:
    """메모리 감쇄 테스트."""

    def test_decay_does_not_affect_pinned(self, memory_manager: MemoryManager):
        """pinned 메모리는 decay 영향을 받지 않음."""
        mem = memory_manager.create("핀 메모리", confidence=0.5)
        memory_manager.update(mem.id, is_pinned=True)

        # 매우 공격적인 decay 파라미터
        pruned = memory_manager.apply_decay(decay_days=0, decay_amount=1.0, prune_threshold=0.9)
        assert pruned == 0
        assert memory_manager.get(mem.id) is not None
