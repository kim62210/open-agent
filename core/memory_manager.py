import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from litellm import acompletion

from open_agent.models.memory import MemoryCategory, MemoryItem, MemorySource

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a memory extraction assistant. Analyze the following conversation exchange and extract ONLY long-term, reusable facts worth remembering across multiple future conversations.

## Existing Memories
{existing_memories}

## Rules
1. Only extract NEW information not already covered by existing memories.
2. Each memory should be a single, concise sentence.
3. Categorize each memory as one of: preference, context, pattern, fact
   - preference: PERSISTENT user preferences and style choices (NOT one-time requests)
   - context: STABLE project/work environment context (NOT transient task details)
   - pattern: RECURRING behaviors confirmed across multiple interactions
   - fact: personal facts, technical facts, domain knowledge
4. Return a JSON array of objects with "content", "category", and "confidence" fields.
   - confidence (0.0~1.0): How certain is this information?
     - 0.9~1.0: User explicitly stated (e.g., "나는 Python 3.13을 쓴다")
     - 0.7~0.89: Strongly implied from conversation context
     - 0.5~0.69: Inferred but not explicitly stated
     - below 0.5: Speculative or uncertain — DO NOT include these
5. If there is nothing new worth remembering, return an empty array [].
6. Write memories in the same language the user is using.
7. ONLY extract facts the USER explicitly stated or clearly implied. Do NOT extract the assistant's assumptions, inferences, or recommendations as facts.
8. DO NOT memorize transient task actions or momentary queries. These are NOT memories:
   - "사용자는 X 파일을 수정해달라고 요청했다" (one-time task action)
   - "사용자는 Y를 검색했다" (one-time search query)
   However, DO save:
   - Personal facts: "나는 Python 개발자야", "우리 팀은 5명이야"
   - Technical context: "우리 프로젝트는 React를 사용한다", "백엔드는 FastAPI로 되어 있다"
   - Preferences: "TypeScript를 선호한다", "다크모드를 쓴다"
   - Domain knowledge: "우리 회사는 B2B SaaS를 만든다"
9. DO NOT save file paths, directory listings, or transient workspace state as memories. These change frequently and become stale.

## Conversation
User: {user_message}
Assistant: {assistant_message}

## Response (JSON array only, no markdown fencing):"""

COMPRESSION_PROMPT = """You are a memory compression assistant. Your job is to merge similar or overlapping memories to reduce the total count while preserving all important information.

## Current Memories (JSON)
{memories_json}

## Rules
1. Merge memories that are similar, overlapping, or about the same topic into a single combined memory.
2. Keep memories that are unique and unrelated to others as-is.
3. Each output item must include "source_ids" (array of original memory IDs that were merged into it), "content" (the merged text), "category" (one of: preference, context, pattern, fact), and "confidence" (highest confidence among merged sources).
4. Every original memory ID must appear in exactly one output item's source_ids.
5. If a memory is not merged with anything, still include it with its single source_id and original confidence.
6. Aim for at least 20% reduction in total count.
7. Write merged memories in the same language as the originals.

## Response (JSON array only, no markdown fencing):"""

_COMPRESSION_COOLDOWN = 300  # 5 minutes

SESSION_SUMMARY_PROMPT = """You are a session summary assistant. Summarize the following conversation into a concise session summary.

## Conversation
{conversation}

## Rules
1. Write 3-5 bullet points capturing: key decisions, actions taken, results, and unfinished tasks.
2. Include any failures and how they were resolved (these are valuable lessons).
3. If new skills were created or modified, mention them by name.
4. Write in the same language as the conversation.
5. Be concise — each bullet should be one sentence.
6. Return ONLY the bullet points, no headers or formatting.

## Summary:"""


def _extract_llm_content(response) -> str:
    """Extract content from LLM response, with reasoning model fallback."""
    msg = response.choices[0].message
    content = msg.content
    if content:
        return content.strip()
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        return reasoning.strip()
    return ""


class MemoryManager:
    def __init__(self):
        self._memories: Dict[str, MemoryItem] = {}
        self._config_path: Optional[Path] = None
        self._compression_lock = asyncio.Lock()
        self._last_compressed_at: Optional[float] = None

    def load_config(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.is_absolute():
            from open_agent.config import get_config_path
            path = get_config_path(config_path)
        self._config_path = path

        if not path.exists():
            path.write_text(json.dumps({"memories": []}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            self._memories = {}
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("memories", []):
                mem = MemoryItem(**item)
                self._memories[mem.id] = mem
            logger.info(f"Loaded {len(self._memories)} memories from {path}")
        except Exception as e:
            logger.warning(f"Failed to parse memories: {e}, starting fresh")
            self._memories = {}

    def _save_config(self) -> None:
        if not self._config_path:
            return
        data = {"memories": [m.model_dump() for m in self._memories.values()]}
        self._config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # --- CRUD ---

    def get_all(self) -> List[MemoryItem]:
        return sorted(self._memories.values(), key=lambda m: m.created_at, reverse=True)

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        return self._memories.get(memory_id)

    def create(
        self,
        content: str,
        category: MemoryCategory = "fact",
        confidence: float = 0.7,
        source: MemorySource = "llm_inference",
    ) -> MemoryItem:
        now = datetime.now(timezone.utc).isoformat()
        mem = MemoryItem(
            id=uuid.uuid4().hex[:16],
            content=content,
            category=category,
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            created_at=now,
            updated_at=now,
        )
        self._memories[mem.id] = mem
        self._save_config()
        logger.info(f"Created memory [{category}]: {content[:50]}")
        return mem

    def update(self, memory_id: str, **kwargs) -> Optional[MemoryItem]:
        mem = self._memories.get(memory_id)
        if not mem:
            return None
        data = mem.model_dump()
        for k, v in kwargs.items():
            if v is not None:
                data[k] = v
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._memories[memory_id] = MemoryItem(**data)
        self._save_config()
        return self._memories[memory_id]

    def delete(self, memory_id: str) -> bool:
        if memory_id not in self._memories:
            return False
        self._memories.pop(memory_id)
        self._save_config()
        logger.info(f"Deleted memory: {memory_id}")
        return True

    def clear_all(self) -> int:
        unpinned_ids = [mid for mid, m in self._memories.items() if not m.is_pinned]
        for mid in unpinned_ids:
            del self._memories[mid]
        self._save_config()
        logger.info(f"Cleared {len(unpinned_ids)} memories (pinned preserved)")
        return len(unpinned_ids)

    # --- Relevance Scoring ---

    def _score_memories(self, user_input: str) -> List[tuple]:
        """Score memories by relevance to user input.
        Returns list of (MemoryItem, score) tuples.
        """
        input_words = {w.lower() for w in user_input.split() if len(w) >= 2}
        now = datetime.now(timezone.utc)
        results = []

        for mem in self._memories.values():
            # Keyword relevance (0.0~1.0)
            if input_words:
                mem_words = {w.lower() for w in mem.content.split() if len(w) >= 2}
                match_count = len(input_words & mem_words)
                keyword_score = match_count / len(input_words)
            else:
                keyword_score = 0.0

            # Recency (0.0~1.0) — gentle decay over days
            try:
                created = datetime.fromisoformat(mem.created_at)
                age_days = max(0, (now - created).days)
            except Exception:
                age_days = 30
            recency_score = 1.0 / (1.0 + age_days * 0.03)

            # Combined score
            score = keyword_score * 0.5 + mem.confidence * 0.3 + recency_score * 0.2

            # Pinned memories always get a boost
            if mem.is_pinned:
                score += 0.3

            results.append((mem, score))

        return results

    # --- System Prompt ---

    def build_memory_prompt(self, user_input: str = "") -> str:
        """Build a memory section for the system prompt.
        When user_input is provided, memories are ranked by relevance.
        """
        from open_agent.core.settings_manager import settings_manager

        memory_settings = settings_manager.settings.memory
        if not memory_settings.enabled or not self._memories:
            return ""

        # Score and sort memories
        if user_input:
            scored = self._score_memories(user_input)
            scored.sort(key=lambda x: x[1], reverse=True)
        else:
            # Fallback: sort by confidence * recency
            scored = [(m, m.confidence) for m in self.get_all()]

        # Minimum relevance gate — filter out weakly related memories
        _MIN_RELEVANCE = 0.4
        lines = []
        for mem, _score in scored:
            if user_input and _score < _MIN_RELEVANCE:
                break  # sorted descending, rest will be even lower
            conf = f"{mem.confidence:.1f}"
            lines.append(f"- [{mem.category}|{conf}] {mem.content}")
            # Rough token estimate: ~4 chars per token
            if len("\n".join(lines)) > memory_settings.max_injection_tokens * 4:
                lines.pop()  # remove the line that caused overflow
                break

        if not lines:
            return ""

        return (
            "## Long-term Memory\n"
            "아래는 이전 대화에서 기억된 사실과 선호도입니다. "
            "숫자는 신뢰도(0.0~1.0)입니다. "
            "0.7 미만은 불확실한 정보이므로 중요한 판단에 사용하기 전에 사용자에게 확인하세요.\n\n"
            + "\n".join(lines)
        )

    # --- L2: Session Summaries ---

    def _summaries_path(self) -> Optional[Path]:
        if not self._config_path:
            return None
        return self._config_path.parent / "session_summaries.json"

    def _load_summaries(self) -> List[Dict]:
        path = self._summaries_path()
        if not path or not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("summaries", [])
        except Exception:
            return []

    def _save_summaries(self, summaries: List[Dict]) -> None:
        path = self._summaries_path()
        if not path:
            return
        path.write_text(
            json.dumps({"summaries": summaries}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    async def generate_session_summary(
        self, session_id: str, session_title: str, messages: List[Dict]
    ) -> Optional[str]:
        """세션의 대화 내용을 요약하여 L2 저장소에 저장합니다."""
        from open_agent.core.settings_manager import settings_manager

        # 최소 2턴(user+assistant) 이상인 경우만 요약
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if len(user_msgs) < 2:
            return None

        # 대화 텍스트 구성 (tool 메시지 제외, 핵심만)
        conv_parts = []
        for m in messages:
            role = m.get("role", "")
            if role in ("user", "assistant"):
                content = m.get("content", "")
                if isinstance(content, str) and content:
                    conv_parts.append(f"{role}: {content[:300]}")
        conversation = "\n".join(conv_parts[-20:])  # 최근 20개 메시지만

        if not conversation.strip():
            return None

        prompt = SESSION_SUMMARY_PROMPT.format(conversation=conversation)

        try:
            llm = settings_manager.llm
            from open_agent.core.llm import LLMClient
            api_key = llm.api_key or LLMClient._resolve_api_key(llm.model)

            kwargs = {
                "model": llm.model,
                "api_key": api_key,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": LLMClient._safe_temperature(llm.model, 0.3),
                "max_tokens": 512,
            }
            if llm.api_base:
                kwargs["api_base"] = llm.api_base

            response = await acompletion(**kwargs)
            summary = _extract_llm_content(response)

            if not summary:
                return None

            # L2 저장
            summaries = self._load_summaries()
            summaries.append({
                "session_id": session_id,
                "title": session_title,
                "summary": summary,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            # 최대 20개 세션 요약 유지
            if len(summaries) > 20:
                summaries = summaries[-20:]
            self._save_summaries(summaries)

            logger.info(f"Session summary generated for {session_id}: {summary[:80]}...")
            return summary

        except Exception as e:
            logger.warning(f"Session summary generation failed: {e}")
            return None

    def build_session_summary_prompt(
        self, current_session_id: str = "", user_input: str = "", max_summaries: int = 3
    ) -> str:
        """최근 세션 요약을 시스템 프롬프트용으로 구성합니다 (L2 계층).
        user_input이 제공되면 관련성 높은 세션만 포함합니다.
        """
        summaries = self._load_summaries()
        if not summaries:
            return ""

        # 현재 세션 제외
        candidates = [s for s in summaries if s.get("session_id") != current_session_id]
        if not candidates:
            return ""

        # 관련성 필터: user_input과 키워드 겹침이 있는 세션만
        if user_input:
            input_words = {w.lower() for w in user_input.split() if len(w) >= 2}
            scored = []
            for s in candidates:
                text = (s.get("title", "") + " " + s.get("summary", "")).lower()
                summary_words = {w for w in text.split() if len(w) >= 2}
                overlap = len(input_words & summary_words) / max(len(input_words), 1)
                if overlap >= 0.15:  # 최소 15% 키워드 겹침
                    scored.append((s, overlap))
            scored.sort(key=lambda x: x[1], reverse=True)
            recent = [s for s, _ in scored[:max_summaries]]
        else:
            recent = candidates[-max_summaries:]

        if not recent:
            return ""

        lines = []
        for s in reversed(recent):  # 최신순
            title = s.get("title", "세션")
            summary = s.get("summary", "")
            lines.append(f"### {title}\n{summary}")

        return (
            "## Recent Session History (L2)\n"
            "이전 세션의 요약입니다. 이어서 작업하거나 과거 맥락이 필요할 때 참고하세요.\n\n"
            + "\n\n".join(lines)
        )

    # --- Decay & Contradiction ---

    def apply_decay(self, decay_days: int = 60, decay_amount: float = 0.05, prune_threshold: float = 0.3) -> int:
        """장기 미참조 메모리의 confidence를 감쇄하고, 임계값 미만은 삭제합니다.
        Returns number of pruned memories.
        """
        now = datetime.now(timezone.utc)
        pruned = 0
        decayed = 0
        to_delete = []

        for mem in list(self._memories.values()):
            if mem.is_pinned:
                continue
            try:
                updated = datetime.fromisoformat(mem.updated_at)
                age_days = (now - updated).days
            except Exception:
                age_days = 0

            if age_days >= decay_days:
                new_confidence = mem.confidence - decay_amount
                if new_confidence < prune_threshold:
                    to_delete.append(mem.id)
                else:
                    self._memories[mem.id] = MemoryItem(
                        **{**mem.model_dump(), "confidence": round(new_confidence, 2)}
                    )
                    decayed += 1

        for mid in to_delete:
            del self._memories[mid]
            pruned += 1

        if pruned > 0 or decayed > 0:
            self._save_config()
            logger.info(f"Memory decay applied: {decayed} decayed, {pruned} pruned, {len(self._memories)} remaining")

        return pruned

    def detect_contradictions(self, new_content: str, new_confidence: float) -> Optional[str]:
        """새 메모리와 기존 메모리 간 단순 모순을 감지합니다.
        모순 발견 시 기존 메모리 ID 반환, 없으면 None.
        키워드 기반 빠른 검사: 동일 주제에 대해 상반된 내용이 있는지 확인.
        """
        new_words = {w.lower() for w in new_content.split() if len(w) >= 2}
        if not new_words:
            return None

        best_overlap = 0.0
        best_candidate = None

        for mem in self._memories.values():
            mem_words = {w.lower() for w in mem.content.split() if len(w) >= 2}
            if not mem_words:
                continue
            overlap = len(new_words & mem_words) / max(len(new_words | mem_words), 1)
            # 높은 유사도(같은 주제)인데 내용이 다른 경우 = 모순 후보
            if overlap > 0.6 and overlap > best_overlap:
                # 완전 동일이면 모순이 아님 (중복)
                if overlap < 0.9:
                    best_overlap = overlap
                    best_candidate = mem

        if best_candidate:
            return best_candidate.id
        return None

    # --- Compression & Eviction ---

    def _evict_oldest(self) -> Optional[str]:
        """Delete the oldest non-pinned memory by created_at. Returns the deleted ID."""
        candidates = [m for m in self._memories.values() if not m.is_pinned]
        if not candidates:
            return None
        oldest = min(candidates, key=lambda m: m.created_at)
        self.delete(oldest.id)
        logger.info(f"Auto-replaced oldest memory: {oldest.id} ({oldest.content[:40]})")
        return oldest.id

    async def _compress_memories(self) -> int:
        """Merge similar memories via LLM. Returns number of freed slots."""
        async with self._compression_lock:
            # Cooldown check
            now = time.monotonic()
            if self._last_compressed_at and (now - self._last_compressed_at) < _COMPRESSION_COOLDOWN:
                logger.debug("Memory compression skipped: cooldown active")
                return 0

            # Only compress non-pinned memories
            unpinned = [m for m in self._memories.values() if not m.is_pinned]

            # Need at least 4 non-pinned memories to compress
            if len(unpinned) < 4:
                return 0

            from open_agent.core.settings_manager import settings_manager
            llm = settings_manager.llm

            all_mems = sorted(unpinned, key=lambda m: m.created_at, reverse=True)
            memories_data = [
                {"id": m.id, "content": m.content, "category": m.category, "confidence": m.confidence}
                for m in all_mems
            ]
            original_count = len(memories_data)
            original_ids = {m["id"] for m in memories_data}

            prompt = COMPRESSION_PROMPT.format(
                memories_json=json.dumps(memories_data, ensure_ascii=False)
            )

            try:
                from open_agent.core.llm import LLMClient
                api_key = llm.api_key or LLMClient._resolve_api_key(llm.model)

                kwargs = {
                    "model": llm.model,
                    "api_key": api_key,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": LLMClient._safe_temperature(llm.model, 0.2),
                    "max_tokens": 4096,
                }
                if llm.api_base:
                    kwargs["api_base"] = llm.api_base

                response = await acompletion(**kwargs)
                raw = _extract_llm_content(response)

                if not raw:
                    return 0

                # Strip markdown code fencing if present
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                    if raw.endswith("```"):
                        raw = raw[:-3].strip()

                compressed = json.loads(raw)
                if not isinstance(compressed, list):
                    logger.warning("Memory compression: LLM returned non-list")
                    return 0

                # Validate: every original ID must appear exactly once
                seen_ids: set[str] = set()
                for item in compressed:
                    source_ids = item.get("source_ids", [])
                    for sid in source_ids:
                        if sid in seen_ids:
                            logger.warning(f"Memory compression aborted: duplicate source_id {sid}")
                            return 0
                        seen_ids.add(sid)

                if seen_ids != original_ids:
                    missing = original_ids - seen_ids
                    extra = seen_ids - original_ids
                    logger.warning(
                        f"Memory compression aborted: ID mismatch "
                        f"(missing={missing}, extra={extra})"
                    )
                    return 0

                # Apply merges
                freed = 0
                for item in compressed:
                    source_ids = item.get("source_ids", [])
                    if len(source_ids) <= 1:
                        # No merge — keep original as-is
                        continue

                    content = item.get("content", "").strip()
                    category = item.get("category", "fact")
                    # Preserve highest confidence among merged sources
                    source_confidences = [
                        self._memories[sid].confidence
                        for sid in source_ids if sid in self._memories
                    ]
                    merged_confidence = item.get(
                        "confidence",
                        max(source_confidences) if source_confidences else 0.7,
                    )
                    if not content:
                        continue
                    if category not in ("preference", "context", "pattern", "fact"):
                        category = "fact"

                    # Delete originals
                    for sid in source_ids:
                        if sid in self._memories:
                            del self._memories[sid]

                    # Create merged memory
                    now_ts = datetime.now(timezone.utc).isoformat()
                    mem = MemoryItem(
                        id=uuid.uuid4().hex[:16],
                        content=content,
                        category=category,
                        confidence=max(0.0, min(1.0, float(merged_confidence))),
                        source="llm_inference",
                        created_at=now_ts,
                        updated_at=now_ts,
                    )
                    self._memories[mem.id] = mem
                    freed += len(source_ids) - 1

                if freed > 0:
                    self._save_config()
                    new_count = len(self._memories)
                    logger.info(
                        f"Memory compression complete: {original_count} → {new_count} "
                        f"(freed {freed} slots)"
                    )

                self._last_compressed_at = time.monotonic()
                return freed

            except Exception as e:
                logger.warning(f"Memory compression failed: {e}")
                return 0

    # --- Extraction ---

    async def extract_and_save(self, user_message: str, assistant_message: str) -> List[MemoryItem]:
        """Extract memories from a conversation turn using LLM."""
        from open_agent.core.settings_manager import settings_manager

        memory_settings = settings_manager.settings.memory
        if not memory_settings.enabled:
            return []

        # Phase 1: Compress if capacity threshold exceeded
        capacity_ratio = len(self._memories) / max(memory_settings.max_memories, 1)
        if capacity_ratio >= memory_settings.compression_threshold:
            freed = await self._compress_memories()
            if freed > 0:
                logger.info(f"Compression freed {freed} slots before extraction")

        # Build existing memories context
        existing = "\n".join(
            f"- [{m.category}] {m.content}" for m in self.get_all()
        ) or "(none)"

        prompt = EXTRACTION_PROMPT.format(
            existing_memories=existing,
            user_message=user_message,
            assistant_message=assistant_message,
        )

        try:
            llm = settings_manager.llm
            from open_agent.core.llm import LLMClient
            api_key = llm.api_key or LLMClient._resolve_api_key(llm.model)

            kwargs = {
                "model": llm.model,
                "api_key": api_key,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": LLMClient._safe_temperature(llm.model, 0.3),
                "max_tokens": 1024,
            }
            if llm.api_base:
                kwargs["api_base"] = llm.api_base

            response = await acompletion(**kwargs)
            raw = _extract_llm_content(response)

            if not raw:
                logger.info("Memory extraction: LLM returned empty content")
                return []

            # Strip markdown code fencing if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3].strip()

            extracted = json.loads(raw)
            if not isinstance(extracted, list):
                return []

            created = []
            _MIN_CONFIDENCE = 0.5
            for item in extracted:
                content = item.get("content", "").strip()
                category = item.get("category", "fact")
                confidence = item.get("confidence", 0.7)
                if not content:
                    continue
                try:
                    confidence = max(0.0, min(1.0, float(confidence)))
                except (TypeError, ValueError):
                    confidence = 0.7
                if confidence < _MIN_CONFIDENCE:
                    logger.debug(f"Skipping low-confidence memory ({confidence}): {content[:40]}")
                    continue
                if category not in ("preference", "context", "pattern", "fact"):
                    category = "fact"
                # Phase 3: Contradiction check — 같은 주제의 기존 메모리와 모순 시 처리
                contradicting_id = self.detect_contradictions(content, confidence)
                if contradicting_id:
                    existing = self._memories.get(contradicting_id)
                    if existing and confidence > existing.confidence:
                        # 새 메모리가 더 신뢰도 높으면 기존 것을 교체
                        logger.info(
                            f"Contradiction resolved: replacing [{existing.confidence}] "
                            f"'{existing.content[:40]}' with [{confidence}] '{content[:40]}'"
                        )
                        self.delete(contradicting_id)
                    elif existing:
                        # 기존이 더 신뢰도 높으면 새 것을 무시
                        logger.info(
                            f"Contradiction detected, keeping existing [{existing.confidence}] "
                            f"over new [{confidence}]: '{content[:40]}'"
                        )
                        continue

                # Phase 4: Evict oldest if at capacity
                if len(self._memories) >= memory_settings.max_memories:
                    self._evict_oldest()
                mem = self.create(content, category, confidence=confidence, source="llm_inference")
                created.append(mem)

            if created:
                logger.info(f"Extracted {len(created)} new memories from conversation")
            return created

        except Exception as e:
            logger.warning(f"Memory extraction failed: {e}", exc_info=True)
            return []


    async def extract_and_save_batch(self, turns: list[tuple[str, str]]) -> List[MemoryItem]:
        """Extract memories from multiple conversation turns at once.

        Args:
            turns: list of (user_message, assistant_message) tuples
        """
        if not turns:
            return []

        # Filter out trivial turns (both messages < 10 chars)
        meaningful = [
            (u, a) for u, a in turns
            if len(u) >= 10 or len(a) >= 10
        ]
        if not meaningful:
            logger.info(
                "All %d turns trivial (<10 chars), skipping batch extraction. "
                "Samples: %s",
                len(turns),
                [(u[:30], a[:30]) for u, a in turns[:2]],
            )
            return []

        logger.info("Batch extraction: %d/%d meaningful turns", len(meaningful), len(turns))

        # Merge turns into a single extraction call
        combined_user = "\n---\n".join(u for u, _ in meaningful)
        combined_assistant = "\n---\n".join(a for _, a in meaningful)

        try:
            result = await self.extract_and_save(combined_user, combined_assistant)
            logger.info("Batch extraction result: %d memories created", len(result))
            return result
        except Exception as e:
            logger.error("Batch extraction failed: %s", e, exc_info=True)
            return []


memory_manager = MemoryManager()
