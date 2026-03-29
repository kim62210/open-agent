import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from open_agent.core.llm import llm_client
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


class MemoryManager:
    def __init__(self):
        self._memories: Dict[str, MemoryItem] = {}
        self._compression_lock = asyncio.Lock()
        self._last_compressed_at: Optional[float] = None

    async def load_from_db(self) -> None:
        """Load all memories from database into in-memory cache."""
        from core.db.engine import async_session_factory
        from core.db.repositories.memory_repo import MemoryRepository

        async with async_session_factory() as session:
            repo = MemoryRepository(session)
            rows = await repo.get_all()
            self._memories.clear()
            for row in rows:
                self._memories[row.id] = MemoryItem(
                    id=row.id,
                    content=row.content,
                    category=row.category,
                    confidence=row.confidence,
                    source=row.source,
                    is_pinned=row.is_pinned,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            logger.info(f"Loaded {len(self._memories)} memories from database")

    async def _persist_memory(self, mem: MemoryItem) -> None:
        """Write a single memory to database."""
        from core.db.engine import async_session_factory
        from core.db.models.memory import MemoryORM
        from core.db.repositories.memory_repo import MemoryRepository

        async with async_session_factory() as session:
            repo = MemoryRepository(session)
            orm = MemoryORM(
                id=mem.id,
                content=mem.content,
                category=mem.category,
                confidence=mem.confidence,
                source=mem.source,
                is_pinned=mem.is_pinned,
                access_count=0,
                created_at=mem.created_at,
                updated_at=mem.updated_at,
            )
            await repo.update(orm)
            await session.commit()

    async def _delete_from_db(self, memory_id: str) -> None:
        """Delete a single memory from database."""
        from core.db.engine import async_session_factory
        from core.db.repositories.memory_repo import MemoryRepository

        async with async_session_factory() as session:
            repo = MemoryRepository(session)
            await repo.delete_by_id(memory_id)
            await session.commit()

    # --- CRUD ---

    def get_all(self) -> List[MemoryItem]:
        return sorted(self._memories.values(), key=lambda m: m.created_at, reverse=True)

    def get(self, memory_id: str) -> Optional[MemoryItem]:
        return self._memories.get(memory_id)

    async def create(
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
        await self._persist_memory(mem)
        logger.info(f"Created memory [{category}]: {content[:50]}")
        return mem

    async def update(self, memory_id: str, **kwargs) -> Optional[MemoryItem]:
        mem = self._memories.get(memory_id)
        if not mem:
            return None
        data = mem.model_dump()
        for k, v in kwargs.items():
            if v is not None:
                data[k] = v
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._memories[memory_id] = MemoryItem(**data)
        await self._persist_memory(self._memories[memory_id])
        return self._memories[memory_id]

    async def delete(self, memory_id: str) -> bool:
        if memory_id not in self._memories:
            return False
        self._memories.pop(memory_id)
        await self._delete_from_db(memory_id)
        logger.info(f"Deleted memory: {memory_id}")
        return True

    async def clear_all(self) -> int:
        from core.db.engine import async_session_factory
        from core.db.repositories.memory_repo import MemoryRepository

        unpinned_ids = [mid for mid, m in self._memories.items() if not m.is_pinned]
        for mid in unpinned_ids:
            del self._memories[mid]

        async with async_session_factory() as session:
            repo = MemoryRepository(session)
            await repo.clear_non_pinned()
            await session.commit()

        logger.info(f"Cleared {len(unpinned_ids)} memories (pinned preserved)")
        return len(unpinned_ids)

    # --- Relevance Scoring ---

    def _score_memories(self, user_input: str) -> List[tuple]:
        """Score memories by relevance to user input."""
        input_words = {w.lower() for w in user_input.split() if len(w) >= 2}
        now = datetime.now(timezone.utc)
        results = []

        for mem in self._memories.values():
            if input_words:
                mem_words = {w.lower() for w in mem.content.split() if len(w) >= 2}
                match_count = len(input_words & mem_words)
                keyword_score = match_count / len(input_words)
            else:
                keyword_score = 0.0

            try:
                created = datetime.fromisoformat(mem.created_at)
                age_days = max(0, (now - created).days)
            except Exception:
                age_days = 30
            recency_score = 1.0 / (1.0 + age_days * 0.03)

            score = keyword_score * 0.5 + mem.confidence * 0.3 + recency_score * 0.2

            if mem.is_pinned:
                score += 0.3

            results.append((mem, score))

        return results

    # --- System Prompt ---

    def build_memory_prompt(self, user_input: str = "") -> str:
        """Build a memory section for the system prompt."""
        from open_agent.core.settings_manager import settings_manager

        memory_settings = settings_manager.settings.memory
        if not memory_settings.enabled or not self._memories:
            return ""

        if user_input:
            scored = self._score_memories(user_input)
            scored.sort(key=lambda x: x[1], reverse=True)
        else:
            scored = [(m, m.confidence) for m in self.get_all()]

        _MIN_RELEVANCE = 0.4
        lines = []
        for mem, _score in scored:
            if user_input and _score < _MIN_RELEVANCE:
                break
            conf = f"{mem.confidence:.1f}"
            lines.append(f"- [{mem.category}|{conf}] {mem.content}")
            if len("\n".join(lines)) > memory_settings.max_injection_tokens * 4:
                lines.pop()
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

    async def _load_summaries(self) -> List[Dict]:
        from core.db.engine import async_session_factory
        from core.db.repositories.memory_repo import MemoryRepository
        from sqlalchemy import select
        from core.db.models.memory import SessionSummaryORM

        async with async_session_factory() as session:
            result = await session.execute(
                select(SessionSummaryORM).order_by(SessionSummaryORM.created_at.desc()).limit(20)
            )
            rows = list(result.scalars().all())
            return [
                {
                    "session_id": r.session_id,
                    "title": "",  # title not stored in ORM; use session_id context
                    "summary": r.summary,
                    "created_at": r.created_at,
                }
                for r in reversed(rows)  # oldest first
            ]

    async def _save_summary(self, session_id: str, summary: str) -> None:
        from core.db.engine import async_session_factory
        from core.db.models.memory import SessionSummaryORM
        from core.db.repositories.memory_repo import MemoryRepository

        async with async_session_factory() as session:
            repo = MemoryRepository(session)
            orm = SessionSummaryORM(
                session_id=session_id,
                summary=summary,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            await repo.save_summary(orm)
            await session.commit()

    async def generate_session_summary(
        self, session_id: str, session_title: str, messages: List[Dict]
    ) -> Optional[str]:
        """Generate and save a session summary (L2 layer)."""
        from open_agent.core.settings_manager import settings_manager

        user_msgs = [m for m in messages if m.get("role") == "user"]
        if len(user_msgs) < 2:
            return None

        conv_parts = []
        for m in messages:
            role = m.get("role", "")
            if role in ("user", "assistant"):
                content = m.get("content", "")
                if isinstance(content, str) and content:
                    conv_parts.append(f"{role}: {content[:300]}")
        conversation = "\n".join(conv_parts[-20:])

        if not conversation.strip():
            return None

        prompt = SESSION_SUMMARY_PROMPT.format(conversation=conversation)

        try:
            summary = await llm_client.simple_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=512,
            )

            if not summary:
                return None

            await self._save_summary(session_id, summary)

            logger.info(f"Session summary generated for {session_id}: {summary[:80]}...")
            return summary

        except Exception as e:
            logger.warning(f"Session summary generation failed: {e}")
            return None

    async def build_session_summary_prompt(
        self, current_session_id: str = "", user_input: str = "", max_summaries: int = 3
    ) -> str:
        """Build session summary prompt for system prompt (L2 layer)."""
        summaries = await self._load_summaries()
        if not summaries:
            return ""

        candidates = [s for s in summaries if s.get("session_id") != current_session_id]
        if not candidates:
            return ""

        if user_input:
            input_words = {w.lower() for w in user_input.split() if len(w) >= 2}
            scored = []
            for s in candidates:
                text = (s.get("title", "") + " " + s.get("summary", "")).lower()
                summary_words = {w for w in text.split() if len(w) >= 2}
                overlap = len(input_words & summary_words) / max(len(input_words), 1)
                if overlap >= 0.15:
                    scored.append((s, overlap))
            scored.sort(key=lambda x: x[1], reverse=True)
            recent = [s for s, _ in scored[:max_summaries]]
        else:
            recent = candidates[-max_summaries:]

        if not recent:
            return ""

        lines = []
        for s in reversed(recent):
            title = s.get("title", "세션")
            summary = s.get("summary", "")
            lines.append(f"### {title}\n{summary}")

        return (
            "## Recent Session History (L2)\n"
            "이전 세션의 요약입니다. 이어서 작업하거나 과거 맥락이 필요할 때 참고하세요.\n\n"
            + "\n\n".join(lines)
        )

    # --- Decay & Contradiction ---

    async def apply_decay(self, decay_days: int = 60, decay_amount: float = 0.05, prune_threshold: float = 0.3) -> int:
        """Decay old memories and prune below threshold."""
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
            # Batch persist changes to DB
            from core.db.engine import async_session_factory
            from core.db.models.memory import MemoryORM
            from core.db.repositories.memory_repo import MemoryRepository

            async with async_session_factory() as session:
                repo = MemoryRepository(session)
                for mid in to_delete:
                    await repo.delete_by_id(mid)
                for mem in self._memories.values():
                    if not mem.is_pinned:
                        orm = await repo.get_by_id(mem.id)
                        if orm:
                            orm.confidence = mem.confidence
                await session.commit()

            logger.info(f"Memory decay applied: {decayed} decayed, {pruned} pruned, {len(self._memories)} remaining")

        return pruned

    def detect_contradictions(self, new_content: str, new_confidence: float) -> Optional[str]:
        """Detect simple contradictions between new and existing memories."""
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
            if overlap > 0.6 and overlap > best_overlap:
                if overlap < 0.9:
                    best_overlap = overlap
                    best_candidate = mem

        if best_candidate:
            return best_candidate.id
        return None

    # --- Compression & Eviction ---

    async def _evict_oldest(self) -> Optional[str]:
        """Delete the oldest non-pinned memory by created_at."""
        candidates = [m for m in self._memories.values() if not m.is_pinned]
        if not candidates:
            return None
        oldest = min(candidates, key=lambda m: m.created_at)
        await self.delete(oldest.id)
        logger.info(f"Auto-replaced oldest memory: {oldest.id} ({oldest.content[:40]})")
        return oldest.id

    async def _compress_memories(self) -> int:
        """Merge similar memories via LLM."""
        async with self._compression_lock:
            now = time.monotonic()
            if self._last_compressed_at and (now - self._last_compressed_at) < _COMPRESSION_COOLDOWN:
                logger.debug("Memory compression skipped: cooldown active")
                return 0

            unpinned = [m for m in self._memories.values() if not m.is_pinned]

            if len(unpinned) < 4:
                return 0

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
                raw = await llm_client.simple_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=4096,
                )

                if not raw:
                    return 0

                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                    if raw.endswith("```"):
                        raw = raw[:-3].strip()

                compressed = json.loads(raw)
                if not isinstance(compressed, list):
                    logger.warning("Memory compression: LLM returned non-list")
                    return 0

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

                freed = 0
                for item in compressed:
                    source_ids = item.get("source_ids", [])
                    if len(source_ids) <= 1:
                        continue

                    content = item.get("content", "").strip()
                    category = item.get("category", "fact")
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

                    # Delete originals from cache
                    for sid in source_ids:
                        if sid in self._memories:
                            del self._memories[sid]

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
                    # Batch persist: delete old, create new
                    from core.db.engine import async_session_factory
                    from core.db.models.memory import MemoryORM
                    from core.db.repositories.memory_repo import MemoryRepository

                    async with async_session_factory() as session:
                        repo = MemoryRepository(session)
                        for sid in original_ids:
                            await repo.delete_by_id(sid)
                        for mem in self._memories.values():
                            if not mem.is_pinned or mem.id not in original_ids:
                                orm = MemoryORM(
                                    id=mem.id,
                                    content=mem.content,
                                    category=mem.category,
                                    confidence=mem.confidence,
                                    source=mem.source,
                                    is_pinned=mem.is_pinned,
                                    access_count=0,
                                    created_at=mem.created_at,
                                    updated_at=mem.updated_at,
                                )
                                await session.merge(orm)
                        await session.commit()

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

        capacity_ratio = len(self._memories) / max(memory_settings.max_memories, 1)
        if capacity_ratio >= memory_settings.compression_threshold:
            freed = await self._compress_memories()
            if freed > 0:
                logger.info(f"Compression freed {freed} slots before extraction")

        existing = "\n".join(
            f"- [{m.category}] {m.content}" for m in self.get_all()
        ) or "(none)"

        prompt = EXTRACTION_PROMPT.format(
            existing_memories=existing,
            user_message=user_message,
            assistant_message=assistant_message,
        )

        try:
            raw = await llm_client.simple_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
            )

            if not raw:
                logger.info("Memory extraction: LLM returned empty content")
                return []

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
                contradicting_id = self.detect_contradictions(content, confidence)
                if contradicting_id:
                    existing_mem = self._memories.get(contradicting_id)
                    if existing_mem and confidence > existing_mem.confidence:
                        logger.info(
                            f"Contradiction resolved: replacing [{existing_mem.confidence}] "
                            f"'{existing_mem.content[:40]}' with [{confidence}] '{content[:40]}'"
                        )
                        await self.delete(contradicting_id)
                    elif existing_mem:
                        logger.info(
                            f"Contradiction detected, keeping existing [{existing_mem.confidence}] "
                            f"over new [{confidence}]: '{content[:40]}'"
                        )
                        continue

                if len(self._memories) >= memory_settings.max_memories:
                    await self._evict_oldest()
                mem = await self.create(content, category, confidence=confidence, source="llm_inference")
                created.append(mem)

            if created:
                logger.info(f"Extracted {len(created)} new memories from conversation")
            return created

        except Exception as e:
            logger.warning(f"Memory extraction failed: {e}", exc_info=True)
            return []


    async def extract_and_save_batch(self, turns: list[tuple[str, str]]) -> List[MemoryItem]:
        """Extract memories from multiple conversation turns at once."""
        if not turns:
            return []

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
