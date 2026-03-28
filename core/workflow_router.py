"""LLM 기반 워크플로우 라우팅 모듈.

경량 LLM 호출로 사용자 메시지를 적합한 워크플로우 스킬에 매칭합니다.
하드코딩된 키워드 매칭 대신 모델의 시맨틱 이해력을 활용합니다.
"""

import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_ROUTING_PROMPT_TEMPLATE = """당신은 사용자 요청을 분류하는 라우터입니다.
워크플로우 이름 하나만 답하세요. 해당하는 워크플로우가 없으면 "none"이라고 답하세요.

## none을 반환해야 하는 경우 (중요)
- 일상 대화, 인사, 감사, 잡담
- 의미 없는 입력: ?, !, ㅋㅋ, ㅎㅎ, ㅇㅇ 등
- 지식/설명 질문: ~설명해줘, ~알려줘, ~뭐야, ~에 대해 (도구 없이 텍스트로 답변 가능)
- MCP 도구로 해결 가능한 일회성 조회: 검색, 날씨, 뉴스, 번역 등
- 이전 대화의 단순 후속: "더 알려줘", "자세히", "내일은?" (이전 맥락 기반 텍스트 응답)

## 워크플로우를 선택하는 경우
- 후속 요청("다시해", "더 해줘", "계속")이면서 직전 대화가 특정 작업이면 → 그 작업의 워크플로우 유지
- "고쳐줘", "수정해줘", "버그" 등 오류 수정 성격이면 → debug
- "다시해"는 직전 작업을 반복하라는 뜻 → 직전 대화 맥락의 워크플로우 유지
- "설계해줘", "계획 세워줘", "어떻게 구현", "아키텍처", "방법 제안" 등 구현 전 계획 수립 → plan
- coding-pipeline은 "대규모", "마이그레이션", "리팩토링", "전체 재설계", "여러 파일", "다수 모듈", "전체적으로 변경" 등 대규모 작업을 언급할 때 선택
- skill-creator는 스킬 생성/수정/개선/병합에 선택. "스킬 만들어줘", "스킬 수정", "스킬 개선", "스킬 업데이트" 등. 기존 스킬을 수정하는 구현 요청도 skill-creator가 담당
- impl은 워크스페이스/페이지의 새 기능 추가, 기존 기능 확장/변경, 문서 작성/편집에 선택. 스킬 수정은 impl이 아닌 skill-creator를 사용. "추가해줘", "만들어줘", "바꿔줘", "변경해줘" 등
- debug는 오류/버그 수정에만 선택. "에러", "버그", "안 돼", "왜 이래", "고장" 등
- test는 테스트 작성/실행 요청에 선택. "테스트", "커버리지"
- review는 코드/문서 검토 요청에 선택. "리뷰", "검토", "PR"
- find는 코드 탐색/분석 요청에 선택. "찾아줘", "어디에", "사용처", "분석해줘"
{context_section}
## 워크플로우 목록
{skill_list}"""

# 대화 맥락이 있을 때 추가되는 섹션
_CONTEXT_SECTION_TEMPLATE = """
## 대화 맥락
- 현재 대화 턴 수: {turn_count}
- 이전 활성 워크플로우: {prev_workflow}
- 이전 도구 사용 여부: {has_tool_results}
- 직전 대화 요약: {recent_context}
"""


class WorkflowRouter:
    """LLM 기반 워크플로우 라우팅."""

    def __init__(self):
        self._skill_summaries: Dict[str, str] = {}

    def update_skills(self, skills: Dict[str, str]):
        """스킬 요약 업데이트. {name: 1줄 설명}"""
        self._skill_summaries = skills
        logger.info("Workflow router updated: %d skills", len(skills))

    @staticmethod
    def _extract_recent_context(messages: List[Dict]) -> str:
        """대화 이력에서 직전 user+assistant 쌍의 요약을 추출."""
        if not messages:
            return ""
        # 마지막 assistant 응답과 그 이전 user 메시지를 찾음
        recent_pairs = []
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            if role in ("user", "assistant") and content:
                recent_pairs.append(f"{role}: {content[:100]}")
            if len(recent_pairs) >= 4:  # 최대 2쌍
                break
        if not recent_pairs:
            return ""
        recent_pairs.reverse()
        return " → ".join(recent_pairs)

    def _build_routing_prompt(
        self,
        prev_workflow: str | None = None,
        turn_count: int = 0,
        has_tool_results: bool = False,
        recent_context: str = "",
    ) -> str:
        if not self._skill_summaries:
            return ""
        skill_list = "\n".join(
            f"- {name}: {summary}"
            for name, summary in self._skill_summaries.items()
        )
        # 대화 맥락이 있으면 컨텍스트 섹션 추가
        context_section = ""
        if turn_count > 1 or prev_workflow or recent_context:
            context_section = _CONTEXT_SECTION_TEMPLATE.format(
                turn_count=turn_count,
                prev_workflow=prev_workflow or "없음",
                has_tool_results="있음" if has_tool_results else "없음",
                recent_context=recent_context or "없음",
            )
        return _ROUTING_PROMPT_TEMPLATE.format(
            skill_list=skill_list,
            context_section=context_section,
        )

    async def route(
        self,
        user_message: str,
        *,
        messages: List[Dict] | None = None,
        prev_workflow: str | None = None,
    ) -> Optional[str]:
        """사용자 메시지에 적합한 워크플로우 이름 반환. 없으면 None.

        Args:
            user_message: 현재 사용자 메시지
            messages: 전체 대화 이력 (맥락 파악용)
            prev_workflow: 이전에 활성화되었던 워크플로우 이름
        """
        if not self._skill_summaries or not user_message or not user_message.strip():
            return None

        # 대화 맥락 추출
        turn_count = 0
        has_tool_results = False
        recent_context = ""
        if messages:
            turn_count = sum(1 for m in messages if m.get("role") == "user")
            has_tool_results = any(m.get("role") == "tool" for m in messages)
            recent_context = self._extract_recent_context(messages)

        routing_prompt = self._build_routing_prompt(
            prev_workflow=prev_workflow,
            turn_count=turn_count,
            has_tool_results=has_tool_results,
            recent_context=recent_context,
        )
        if not routing_prompt:
            return None

        from open_agent.core.llm import llm_client

        start = time.perf_counter()
        result = await llm_client.classify(
            prompt=routing_prompt,
            choices=list(self._skill_summaries.keys()) + ["none"],
            user_message=user_message,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Workflow routing: %s → %s (%.0fms, ctx: turn=%d, prev=%s)",
            user_message[:40], result or "none", elapsed_ms,
            turn_count, prev_workflow or "-",
        )

        if result is None or result == "none":
            return None
        return result


workflow_router = WorkflowRouter()
