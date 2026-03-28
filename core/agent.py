import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, AsyncGenerator

from open_agent.core.llm import llm_client
from open_agent.core.job_manager import job_manager, SCHEDULED_TASK_TOOL_NAMES
from open_agent.core.mcp_manager import mcp_manager, parse_namespaced_tool
from open_agent.core.memory_manager import memory_manager
from open_agent.core.settings_manager import settings_manager
from open_agent.core.skill_manager import skill_manager, SKILL_TOOL_NAMES
from open_agent.core.workflow_router import workflow_router
from open_agent.core.tool_errors import format_error_for_llm, is_error_result
from open_agent.core.tool_registry import tool_registry, FIND_TOOLS_TOOL, detect_intent
from open_agent.core.workspace_tools import (
    WORKSPACE_TOOL_NAMES,
    get_workspace_tools,
    handle_workspace_tool_call,
    get_workspace_system_prompt,
)
from open_agent.core.page_tools import (
    PAGE_TOOL_NAMES,
    handle_page_tool_call,
)
from open_agent.core.unified_tools import (
    UNIFIED_TOOL_NAMES,
    get_unified_tools,
    handle_unified_tool_call,
    resolve_legacy_tool,
)

logger = logging.getLogger(__name__)

# 도구 사용 없이 텍스트로 직접 응답하기 위한 이스케이프 도구
_RESPOND_DIRECTLY_TOOL = {
    "type": "function",
    "function": {
        "name": "respond_directly",
        "description": (
            "도구 사용 없이 텍스트로 직접 응답할 때 호출합니다. "
            "일상 대화, 인사, 질문 답변, 개념 설명 등 "
            "도구가 필요 없는 순수 대화에만 사용하세요."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "사용자에게 전달할 응답 메시지",
                }
            },
            "required": ["message"],
        },
    },
}

_FORCE_RESPOND_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": "respond_directly"},
}

_MAX_EMPTY_RETRIES = 1  # vLLM 모델은 빈 응답 반복 경향 → 빠른 복구 우선

## ── 시스템 프롬프트 ─────────────────────────────────────────────
# 워크플로우 매칭 여부와 무관하게 항상 사용되는 기본 프롬프트 (경량)
_BASE_SYSTEM_PROMPT = """당신은 Open Agent 플랫폼의 AI 어시스턴트입니다.

## 핵심 원칙
- 행동 요청(~해줘, ~열어줘, ~만들어줘 등): 도구를 사용하여 실제로 수행
- 일상 대화, 인사, 질문 답변, 개념 설명: 도구 호출 없이 텍스트로 직접 응답
- **후속 질문**: 이전 대화 내용을 참고하여 맥락에 맞게 응답. 동일 답변 반복 금지
- MCP 도구(웹 검색, 뉴스, 날씨 등)로 바로 처리 가능한 요청은 **사고 도구 없이 즉시 MCP 도구 호출**
- 이전 대화에서 사용한 MCP 도구의 후속 질문은 **동일 MCP 도구 즉시 재사용**
- **1회 LLM 호출 → 도구 호출 → 응답**이 이상적인 흐름. 사고(thinking) 도구 남용 금지
- "할 수 없습니다", "AI로서 ~"와 같은 거부 응답은 금지
- **정보 제공 ≠ 해결.** 행동을 요청하면 실제 행동까지 완수
- **대상이 불분명한 요청**("고쳐줘", "해줘" 단독): 먼저 사용자에게 대상을 확인
- **독립적인 도구 호출은 한 번에 묶어서 병렬 실행하세요.** 예: 파일 3개를 읽어야 하면 read_file 3회를 한 응답에 동시 호출
- **도구 결과가 절삭(truncated)된 경우**: JSON 등 구조화된 데이터가 잘린 것이므로, 같은 데이터를 다시 요청하지 말고 필요한 필드만 선택적으로 추출하거나 API 파라미터를 줄여서 재요청하세요
- **도구 우선순위**: **플랫폼 내장 도구(create_scheduled_task 등) > MCP 도구 > 기존 스킬 > 스킬 생성** 순. 예약/스케줄링은 반드시 `create_scheduled_task`를 사용할 것. 기존 도구로 해결 가능한 요청에 스킬을 생성하지 말 것
- **스킬 vs 워크스페이스 도구 구분**:
  - 스킬 읽기: `read_skill` / 스킬 실행: `run_skill_script` / 스킬 수정: `update_skill`, `edit_skill_script`, `add_skill_script`
  - 워크스페이스/페이지 파일: `read_file`, `write_file`, `edit_file`, `list_files`, `search`
  - `read_file`/`list_files`로는 스킬 디렉토리에 접근 불가. 스킬 수정이 필요하면 `skill-creator` 워크플로우 도구를 사용할 것

{available_skills_xml}"""

# 도구 사용이 필요한 작업에서 추가되는 확장 프롬프트
_SKILL_EXTENDED_PROMPT = """## 자기 확장(Self-Extending) 에이전트

내장 도구로 해결할 수 없는 요청은 스킬을 생성하여 해결합니다.
단, 스킬 생성은 **반복적이고 도구가 필요한 작업**에만 적용됩니다.

### 요청 처리 절차
1. **분석**: 단순 작업이면 바로 실행, 복합 작업이면 단계 분해
2. **기존 자원 탐색**: `find_tools`로 MCP 도구 검색 → 스킬 탐색은 MCP로 불가 시만
3. **전략**: 기존 자원 사용 → 기존 스킬 개선(`update_skill`) → 신규 생성 순
4. **실행 및 검증**: 실행→검증→수정 반복
5. **정리**: 결과 보고, 재사용 스킬은 description 보강

### 스킬 자율 조합
복합 작업이 여러 스킬의 조합을 필요로 한다고 판단되면, 자율적으로 조합하여 실행할 것:
1. `available_skills`에서 관련 스킬을 식별
2. `read_skill()`로 각 스킬의 상세 지시사항을 로드
3. 의존성 순서를 결정하고 순차적으로 실행
4. 앞 스킬의 결과를 뒤 스킬의 입력으로 전달
5. 필요한 스킬이 없으면 `read_skill("skill-creator")`로 새 스킬을 생성한 뒤 실행

사용자가 명시적으로 스킬을 지정하지 않아도, 요청 달성에 필요하다면 스킬을 자율적으로 선택·조합·생성할 것

### 스킬 생성 금지 조건
- 후속 질문/맥락 기반 요청, MCP로 해결 가능한 일회성 조회, 단순 텍스트 답변, 정보 수정/보완
- **플랫폼 내장 도구와 중복되는 기능** (예약→create_scheduled_task, 파일관리→read_file/write_file 등)
- 스킬 생성 전 반드시 `find_tools`로 해당 기능의 내장 도구가 있는지 확인할 것

### 스크립트 실행 원칙
`run_skill_script` 호출 시 `<scripts>` 태그의 정확한 파일명만 사용. 추측 금지.
스킬 생성/수정 시 `read_skill("skill-creator")`로 절차 확인 필수."""

_WORKFLOW_INJECTION_TEMPLATE = """## 활성 워크플로우: {skill_name}

이 요청에는 **{skill_name}** 워크플로우가 적합합니다.
`read_skill("{skill_name}")`로 절차를 로드하고 1단계부터 순서대로 따르세요.
{resources_hint}"""

# Phase 6: 읽기 전용 도구 — 동일 인자 호출 시 캐시 히트
_CACHEABLE_TOOLS = {
    "read_file",
    "list_files",
    "search",
    "workspace_glob",
    # Legacy names (backward compat)
    "workspace_read_file",
    "workspace_list_dir",
    "workspace_grep",
    # Skill & job tools
    "read_skill",
    "read_skill_reference",
    "list_scheduled_tasks",
}

_SELF_ASSESSMENT_INTERVAL = 8  # 매 N 라운드마다 자기 점검 주입
_TOOL_RESULT_COMPACT_LEN = 800  # 축소 시 도구 결과 최대 길이
_COMPACT_KEEP_RECENT_TURNS = 4  # 압축 시 원본 보존할 최근 턴 수 (기본값, 동적 스케일링됨)
_COMPACT_KEEP_RECENT_TOOLS = 4  # 압축 시 원본 보존할 최근 tool 결과 수 (기본값, 동적 스케일링됨)

# 컨텍스트 윈도우 비례 상수 — _scale_to_context()로 동적 계산
_REFERENCE_CONTEXT_WINDOW = 131_072  # 기준 모델 (Gemini Flash 128K)


def _scale_to_context(base_value: int, context_window: int) -> int:
    """기준 모델(131K) 대비 비례 스케일링. 최소값은 base_value의 50%."""
    ratio = context_window / _REFERENCE_CONTEXT_WINDOW
    return max(int(base_value * 0.5), int(base_value * ratio))
_SELF_ASSESSMENT_PROMPT = (
    "[시스템 점검] 내부적으로 진행 상황을 점검하세요: "
    "①원래 목표 ②완료된 단계 ③남은 단계 ④접근 방식 수정 필요 여부. "
    "점검 후 작업이 아직 완료되지 않았다면 다음 도구를 호출하여 작업을 이어가세요. "
    "작업이 완료되었다면 사용자에게 최종 결과를 정리하여 보여주세요."
)

CONTEXT_SUMMARY_PROMPT = """이전 대화를 구조화된 요약으로 압축하세요. 이 요약은 이전 대화 대신 LLM에 주입됩니다.

## 이전 대화
{conversation}

## 요약 규칙
1. 아래 섹션 구조를 반드시 따르세요:
2. 대화 언어와 동일한 언어로 작성하세요.
3. 파일 경로, 코드 조각, 에러 메시지 등 구체적 정보를 보존하세요.
4. 실패한 접근법과 그 이유도 반드시 포함하세요.

## 응답 형식 (마크다운, 헤더 포함):
### 작업 개요
사용자의 핵심 요청, 성공 기준, 제약 조건

### 현재 상태
- 완료된 작업 목록
- 수정/생성된 파일 경로
- 생성된 결과물

### 핵심 발견
- 기술적 제약 사항
- 내린 결정과 근거
- 에러와 해결 방법
- 실패한 접근법과 원인

### 다음 단계
- 남은 구체적 작업
- 차단 요인
- 우선순위

### 보존할 컨텍스트
- 사용자 선호도
- 도메인 특화 정보
- 약속한 사항"""

ERROR_HANDLING_PROMPT = """## 도구 오류 대응 원칙
- 도구 호출이 [TOOL_ERROR] 블록을 반환하면 error type과 recovery_hint를 참고하여 대응하세요.
- **동일한 방법으로 재시도하지 마세요.** 같은 도구를 같은 인자로 다시 호출하는 것은 금지입니다.
- 오류 유형별 전략:
  - module_not_found → 표준 라이브러리 대안 사용 또는 설치 명령 실행
  - command_not_found → 대체 명령어 탐색
  - file_not_found → list_files로 실제 경로 확인
  - timeout → 작업을 작은 단위로 분할
  - server_disconnected → 해당 서버의 도구 대신 다른 방법 사용
  - env_restricted → uv 또는 pipx 사용
  - ssl_error → 환경변수 설정 또는 우회 방법 안내
- 2~3회 연속 실패하면 사용자에게 상황을 설명하고 수동 개입을 요청하세요."""


@dataclass
class _RequestState:
    """Per-request mutable state — 싱글톤 경합 조건 방지."""
    session_tools: set = field(default_factory=set)
    tool_result_cache: dict = field(default_factory=dict)


class AgentOrchestrator:
    def __init__(self):
        self.llm = llm_client
        # 이전 요청에서 활성화된 워크플로우 (대화 맥락 라우팅용)
        self._prev_workflow: str | None = None

    @staticmethod
    def _build_workflow_resources_section(skill_name, scripts, references):
        parts = []
        if scripts:
            items = "\n".join(f"  - `{s}`" for s in scripts)
            parts.append(
                f"### 스크립트 (정확한 파일명)\n{items}\n"
                f"`run_skill_script(\"{skill_name}\", \"파일명\")` 으로 실행\n"
                f"**위 목록에 없는 파일명을 추측하여 호출하지 마세요.**"
            )
        if references:
            items = "\n".join(f"  - `{r}`" for r in references)
            parts.append(
                f"### 참조 문서\n{items}\n"
                f"`read_skill_reference(\"{skill_name}\", \"파일명\")` 으로 참조"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _resolve_tool_choice(
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        round_num: int,
    ) -> str | None:
        """tool_choice 전략을 결정합니다.

        항상 "auto"를 반환하여 LLM이 도구 사용 여부를 자율 판단하도록 합니다.
        이전에는 round 0에서 "required"를 반환했으나, 이로 인해 단순 대화에도
        불필요한 스킬 생성이 발생하는 문제가 있어 제거되었습니다.
        """
        if not tools:
            return None
        return "auto"

    @staticmethod
    def _compact_old_tool_results(messages: List[Dict[str, Any]], keep_recent: int = 6) -> None:
        """오래된 tool 결과 메시지를 축소하여 컨텍스트 윈도우를 절약합니다.
        마지막 keep_recent개의 tool 메시지는 원본 유지.
        """
        tool_indices = [
            i for i, m in enumerate(messages) if m.get("role") == "tool"
        ]
        # 축소 대상: keep_recent개를 제외한 앞쪽 tool 메시지들
        to_compact = tool_indices[:-keep_recent] if len(tool_indices) > keep_recent else []
        for idx in to_compact:
            content = messages[idx].get("content", "")
            if len(content) > _TOOL_RESULT_COMPACT_LEN:
                tool_name = messages[idx].get("name", "tool")
                messages[idx]["content"] = (
                    content[:_TOOL_RESULT_COMPACT_LEN]
                    + f"\n... [{tool_name} 결과 축소됨: 원본 {len(content)}자]"
                )

    def _get_context_status(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """현재 컨텍스트 사용 상태를 계산합니다."""
        context_window = self.llm.get_context_window()
        used_tokens = self.llm.count_tokens(messages, tools)
        usage_ratio = used_tokens / context_window if context_window > 0 else 0
        return {
            "context_window": context_window,
            "used_tokens": used_tokens,
            "available_tokens": max(0, context_window - used_tokens),
            "usage_ratio": round(usage_ratio, 4),
            "compact_threshold": settings_manager.llm.compact_threshold,
        }

    @staticmethod
    def _observation_mask(messages: List[Dict[str, Any]], keep_recent_tools: int = _COMPACT_KEEP_RECENT_TOOLS) -> int:
        """1단계 압축: 오래된 tool 결과를 플레이스홀더로 교체합니다.
        반환값: 절약된 문자 수
        """
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        to_mask = tool_indices[:-keep_recent_tools] if len(tool_indices) > keep_recent_tools else []
        saved_chars = 0
        for idx in to_mask:
            content = messages[idx].get("content", "")
            if len(content) > 100:  # 너무 짧은 건 마스킹 불필요
                tool_name = messages[idx].get("name", "tool")
                # C12: 도구 인자 + 결과 첫 100자를 placeholder에 포함
                preview = content[:100].replace("\n", " ").strip()
                placeholder = f"[{tool_name} 완료: \"{preview}...\" ({len(content)}자 생략)]"
                saved_chars += len(content) - len(placeholder)
                messages[idx]["content"] = placeholder
        return saved_chars

    @staticmethod
    def _truncate_large_tool_results(messages: List[Dict[str, Any]], max_chars: int = 3200) -> int:
        """모든 tool 결과를 max_chars 이하로 절삭합니다 (최근 포함)."""
        saved = 0
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if len(content) > max_chars:
                tool_name = msg.get("name", "tool")
                original_len = len(content)
                msg["content"] = (
                    f"{content[:max_chars]}\n\n"
                    f"... [{tool_name}: {original_len:,}자 → {max_chars:,}자 절삭]"
                )
                saved += original_len - len(msg["content"])
        return saved

    async def _summarize_context(
        self,
        messages: List[Dict[str, Any]],
        keep_recent_turns: int = _COMPACT_KEEP_RECENT_TURNS,
    ) -> List[Dict[str, Any]]:
        """2단계 압축: LLM을 사용하여 오래된 대화를 구조화된 요약으로 압축합니다.
        시스템 메시지와 최근 N턴은 원본 유지. 나머지를 요약으로 교체.
        """
        # 시스템 메시지 분리
        sys_msg = None
        work_messages = messages
        if messages and messages[0].get("role") == "system":
            sys_msg = messages[0]
            work_messages = messages[1:]

        # 최근 턴 보존 범위 계산 (user/assistant 쌍 기준)
        keep_count = 0
        turn_pairs_found = 0
        for msg in reversed(work_messages):
            keep_count += 1
            if msg.get("role") == "user":
                turn_pairs_found += 1
                if turn_pairs_found >= keep_recent_turns:
                    break

        # 분할: 요약 대상 / 보존 대상
        split_point = len(work_messages) - keep_count
        if split_point <= 2:
            # 요약할 내용이 너무 적음
            return messages

        to_summarize = work_messages[:split_point]
        to_keep = work_messages[split_point:]

        # 요약 대상을 텍스트로 변환
        conversation_lines = []
        tool_result_count = 0
        for msg in to_summarize:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            if role == "tool":
                name = msg.get("name", "tool")
                tool_result_count += 1
                conversation_lines.append(f"[tool:{name}] {content}")
            else:
                conversation_lines.append(f"[{role}] {content}")

        # 컨텍스트 윈도우 비례 요약기 입력 캡
        context_window = self.llm.get_context_window()
        summarizer_cap = min(int(context_window * 2), 60_000)  # C10: 동적 캡

        # C2: 도구 결과 예산을 총 캡에서 균등 배분
        if tool_result_count > 0:
            per_tool_budget = max(500, summarizer_cap // max(tool_result_count, 1))
            trimmed_lines = []
            for line in conversation_lines:
                if line.startswith("[tool:") and len(line) > per_tool_budget:
                    line = line[:per_tool_budget] + f"... [{len(line)}자 중 {per_tool_budget}자]"
                trimmed_lines.append(line)
            conversation_lines = trimmed_lines

        conversation_text = "\n".join(conversation_lines)
        if len(conversation_text) > summarizer_cap:
            conversation_text = conversation_text[:summarizer_cap] + "\n... [이후 생략됨]"

        prompt = CONTEXT_SUMMARY_PROMPT.format(conversation=conversation_text)

        try:
            response = await self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
            )
            summary_content = response["choices"][0]["message"].get("content", "")
        except Exception as e:
            logger.error("Context summarization failed: %s", e)
            # 실패 시 observation masking만 적용된 원본 반환
            return messages

        # 요약 메시지로 교체
        summary_msg = {
            "role": "user",
            "content": (
                f"[시스템: 이전 대화 요약 — 원본 {len(to_summarize)}개 메시지가 "
                f"아래 요약으로 압축되었습니다]\n\n{summary_content}"
            ),
        }

        result = []
        if sys_msg:
            result.append(sys_msg)
        result.append(summary_msg)
        result.extend(to_keep)

        logger.info(
            "Context summarized: %d messages → %d messages (summary + %d recent)",
            len(messages), len(result), len(to_keep),
        )
        return result

    async def _maybe_compact_context(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any] | None]:
        """컨텍스트 사용률을 확인하고 필요 시 압축을 수행합니다.
        반환: (압축된 메시지 목록, compact_event 또는 None)
        """
        status = self._get_context_status(messages, tools)
        threshold = status["compact_threshold"]

        if status["usage_ratio"] <= threshold:
            return messages, None

        logger.info(
            "Context usage %.1f%% exceeds threshold %.0f%%, starting compaction",
            status["usage_ratio"] * 100, threshold * 100,
        )

        # C8/C9: 동적 keep_recent 계산
        context_window = status["context_window"]
        total_tool_msgs = sum(1 for m in messages if m.get("role") == "tool")
        total_turns = sum(1 for m in messages if m.get("role") == "user")
        dynamic_keep_tools = max(_COMPACT_KEEP_RECENT_TOOLS, total_tool_msgs // 4)
        dynamic_keep_turns = max(_COMPACT_KEEP_RECENT_TURNS, min(8, total_turns // 3))

        # 1단계: Observation Masking (비용 0)
        # Phase 2 진행 시 원본 내용이 필요하므로 마스킹 전 내용을 보존
        import copy
        pre_mask_snapshot = [(i, messages[i].get("content", ""))
                             for i in range(len(messages)) if messages[i].get("role") == "tool"]
        saved_chars = self._observation_mask(messages, keep_recent_tools=dynamic_keep_tools)
        saved_tokens_est = saved_chars // 4
        logger.info("Phase 1 (observation masking): ~%d tokens freed", saved_tokens_est)

        # 마스킹 후 재측정
        status_after_mask = self._get_context_status(messages, tools)
        if status_after_mask["usage_ratio"] <= threshold:
            compact_event = {
                "type": "context_compact",
                "phase": "observation_masking",
                "freed_tokens": saved_tokens_est,
                "status": status_after_mask,
            }
            return messages, compact_event

        # 2단계: LLM 요약 — 마스킹 전 원본 복원 후 요약 (정보 손실 방지)
        logger.info("Phase 1 insufficient (%.1f%%), proceeding to Phase 2 (LLM summarization)",
                     status_after_mask["usage_ratio"] * 100)
        for idx, original_content in pre_mask_snapshot:
            if idx < len(messages):
                messages[idx]["content"] = original_content
        before_count = len(messages)
        messages = await self._summarize_context(messages, keep_recent_turns=dynamic_keep_turns)
        # 요약 후 남은 오래된 tool 결과에 대해 Phase 1 재적용
        self._observation_mask(messages, keep_recent_tools=dynamic_keep_tools)
        status_after_summary = self._get_context_status(messages, tools)

        total_freed = status["used_tokens"] - status_after_summary["used_tokens"]
        compact_event = {
            "type": "context_compact",
            "phase": "summarization",
            "freed_tokens": max(0, total_freed),
            "messages_before": before_count,
            "messages_after": len(messages),
            "status": status_after_summary,
        }
        logger.info(
            "Phase 2 complete: %d→%d messages, ~%d tokens freed, usage %.1f%%",
            before_count, len(messages), max(0, total_freed),
            status_after_summary["usage_ratio"] * 100,
        )

        # 3단계: Phase 1+2 후에도 임계값 초과 시 최근 도구 결과도 강제 절삭
        if status_after_summary["usage_ratio"] > threshold:
            logger.warning(
                "Phase 1+2 insufficient (%.1f%%), Phase 3: truncating recent tool results",
                status_after_summary["usage_ratio"] * 100,
            )
            # C4: 적응형 Phase 3 — 남은 예산을 도구 결과 수로 균등 분배
            tool_msgs = [m for m in messages if m.get("role") == "tool" and len(m.get("content", "")) > 800]
            num_tool_msgs = max(len(tool_msgs), 1)
            available_tokens = int(status_after_summary["context_window"] * (1 - threshold))
            phase3_limit = max(800, int(available_tokens * 2 // num_tool_msgs))  # 토큰→문자 *2
            saved = self._truncate_large_tool_results(messages, max_chars=phase3_limit)
            if saved > 0:
                status_after_phase3 = self._get_context_status(messages, tools)
                logger.info(
                    "Phase 3: truncated recent tools, ~%d chars freed, usage %.1f%%",
                    saved, status_after_phase3["usage_ratio"] * 100,
                )
                compact_event["phase"] = "emergency_truncation"
                compact_event["status"] = status_after_phase3
                compact_event["freed_tokens"] = status["used_tokens"] - status_after_phase3["used_tokens"]

        return messages, compact_event

    @staticmethod
    def _extract_last_user_message(messages: List[Dict[str, Any]]) -> str:
        """메시지 목록에서 마지막 사용자 메시지 텍스트를 추출합니다."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
        return ""

    def _build_system_prompt(
        self,
        user_input: str = "",
        workflow_match: Dict[str, Any] | None = None,
    ) -> str | None:
        """Build system prompt with priority-based budget control.

        Priority (lower = higher priority, always included first):
          P0: Custom system prompt
          P1: Base system prompt (경량) + Skill extended (워크플로우 매칭 시만)
          P2: Workspace context
          P4: Memory
          P5: Session summary

        에러 핸들링은 런타임에 시스템 프롬프트에 append됩니다.
        """
        # Collect all parts with priorities
        prioritized: list[tuple[int, str]] = []

        # P0: 현재 날짜 (항상 포함 — 사용자 로컬 PC 시간대 자동 적용)
        now = datetime.now().astimezone()
        date_block = f"현재 날짜: {now.strftime('%Y-%m-%d %A')} (시각: {now.strftime('%H:%M %Z')})"
        prioritized.append((0, date_block))

        # P0: Custom system prompt
        custom = self.llm.get_system_prompt()
        if custom:
            prioritized.append((0, custom))

        # P1: 기본 시스템 프롬프트 (항상 포함, 경량)
        skills_xml = skill_manager.generate_skills_xml()
        prioritized.append((1, _BASE_SYSTEM_PROMPT.format(available_skills_xml=skills_xml)))

        # P1.5: 워크플로우 자동 트리거 — 경량 힌트만 주입 (body는 read_skill로 로드)
        self._last_workflow_match = None
        if workflow_match:
            self._last_workflow_match = workflow_match
            # 스크립트/참조가 있으면 힌트에 포함
            resources_hint = ""
            if workflow_match.get("scripts"):
                scripts_str = ", ".join(workflow_match["scripts"])
                resources_hint += f"사용 가능한 스크립트: {scripts_str}\n"
            prompt = _WORKFLOW_INJECTION_TEMPLATE.format(
                skill_name=workflow_match["name"],
                resources_hint=resources_hint,
            )
            # 워크플로우 매칭 시 확장 스킬 프롬프트도 함께 주입
            prioritized.append((1, _SKILL_EXTENDED_PROMPT))
            prioritized.append((1, prompt))
            logger.info("Workflow hint injected: %s (LLM routing, lazy body load)", workflow_match["name"])

        # P2: Workspace context
        workspace_prompt = get_workspace_system_prompt()
        if workspace_prompt:
            prioritized.append((2, workspace_prompt))

        # P2.1: Reference file guidance
        if "[참조파일:" in user_input:
            ref_prompt = (
                "## 참조파일\n"
                "사용자가 [참조파일: 경로] 형식으로 특정 파일을 지정했습니다.\n"
                "반드시 read_file로 해당 파일을 읽고 답변하세요. "
                "다른 파일을 읽거나 폴더 전체를 탐색하지 마세요."
            )
            prioritized.append((2, ref_prompt))

        # P2.5: Active page context
        from open_agent.core.page_tools import get_page_system_prompt
        page_prompt = get_page_system_prompt()
        if page_prompt:
            prioritized.append((2, page_prompt))

        # P4: Memory
        memory_prompt = memory_manager.build_memory_prompt(user_input=user_input)
        if memory_prompt:
            prioritized.append((4, memory_prompt))

        # P5: Session summary
        session_summary_prompt = memory_manager.build_session_summary_prompt(user_input=user_input)
        if session_summary_prompt:
            prioritized.append((5, session_summary_prompt))

        if not prioritized:
            return None

        # Sort by priority (ascending = highest priority first)
        prioritized.sort(key=lambda x: x[0])

        budget = settings_manager.llm.system_prompt_budget
        if budget > 0:
            parts = []
            used = 0
            for priority, text in prioritized:
                cost = len(text) + 2  # +2 for "\n\n" separator
                if used + cost <= budget:
                    parts.append(text)
                    used += cost
                else:
                    logger.debug(
                        "System prompt budget exceeded: dropping P%d (%d chars, budget=%d, used=%d)",
                        priority, len(text), budget, used,
                    )
        else:
            parts = [text for _, text in prioritized]

        full_prompt = "\n\n".join(parts) if parts else None
        if full_prompt:
            logger.debug("=== FULL SYSTEM PROMPT (len=%d) ===", len(full_prompt))
        return full_prompt

    def _get_dynamic_tool_result_limit(self, messages: list, tools: list | None = None) -> int:
        """컨텍스트 사용률에 따라 도구 결과 절삭 한도를 동적 결정합니다.

        컨텍스트 윈도우의 5%를 단일 도구 결과 상한으로 사용.
        사용률이 compact_threshold의 절반 미만이면 상한 적용, 이상이면 기본값.
        """
        try:
            from open_agent.core.settings_manager import settings_manager
            context_window = self.llm.get_context_window()
            input_tokens = self.llm.count_tokens(messages, tools)
            usage_ratio = input_tokens / context_window if context_window > 0 else 1.0
            compact_threshold = settings_manager.llm.compact_threshold
            # 상한: 컨텍스트 윈도우의 5% (토큰→문자 변환 *2)
            high_limit = max(30_000, int(context_window * 0.05 * 2))
            base_limit = _scale_to_context(30_000, context_window)
            if usage_ratio < compact_threshold * 0.5:
                return high_limit
            return base_limit
        except Exception:
            return 30_000

    def _process_tool_result(self, result: str, max_chars: int = 30_000) -> tuple[str, bool]:
        """도구 결과를 분석하여 (LLM에 전달할 내용, 성공여부)를 반환합니다."""
        result_str = str(result)
        if is_error_result(result_str):
            formatted = format_error_for_llm(result_str)
            # C16: 에러 결과도 5K 한도 적용 (스택 트레이스 폭발 방지)
            if len(formatted) > 5000:
                formatted = formatted[:5000] + "\n... [에러 메시지 절삭됨]"
            return formatted, False
        if len(result_str) > max_chars:
            result_str = (
                f"{result_str[:max_chars]}\n\n"
                f"... [결과가 {max_chars:,}자에서 절삭됨. 원본 {len(str(result)):,}자. "
                f"더 구체적인 쿼리를 사용하세요.]"
            )
        return result_str, True

    async def _build_tools(self, user_message: str = "", state: _RequestState | None = None) -> List[Dict[str, Any]]:
        """Build the tool list, respecting deferred_tool_loading setting."""
        st = state or _RequestState()
        mcp_tools = await mcp_manager.get_all_tools()
        skill_tools = skill_manager.get_skill_tools()
        unified_tools = get_unified_tools()
        # Workspace-only extras: rename, glob (not unified)
        from open_agent.core.workspace_tools import get_workspace_extra_tools
        workspace_extra = get_workspace_extra_tools()
        from open_agent.core.page_tools import get_page_management_tools
        page_mgmt_tools = get_page_management_tools()
        job_tools = await job_manager.get_job_tools()

        deferred = settings_manager.llm.deferred_tool_loading

        # 도구 수 임계값 기반 자동 deferred 전환
        if not deferred:
            threshold = settings_manager.llm.deferred_tool_threshold
            if threshold > 0:
                total_count = len(mcp_tools) + len(skill_tools) + len(unified_tools) + len(workspace_extra) + len(page_mgmt_tools) + len(job_tools) + 1  # +1 for respond_directly
                if total_count > threshold:
                    deferred = True
                    logger.info("Auto-enabling deferred tool loading: %d tools > threshold %d", total_count, threshold)

        if deferred:
            # Register all tools but only send always-on + session tools + find_tools
            tool_registry.refresh_all(
                mcp_tools=mcp_tools,
                skill_tools=skill_tools,
                workspace_tools=workspace_extra,
                job_tools=job_tools,
                extra_tools=unified_tools + page_mgmt_tools + [_RESPOND_DIRECTLY_TOOL],
            )

            # Phase 5: Intent preloading — auto-add tools by detected category
            if user_message:
                intents = detect_intent(user_message)
                if intents:
                    for entry in tool_registry._entries.values():
                        if entry.category in intents:
                            st.session_tools.add(entry.name)
                    logger.debug("Intent preloaded categories: %s", intents)

            always_on = tool_registry.get_always_on_tools()
            session = tool_registry.get_tools_by_names(st.session_tools)
            # Deduplicate (always_on names take priority)
            always_on_names = {t["function"]["name"] for t in always_on}
            session_unique = [t for t in session if t["function"]["name"] not in always_on_names]
            all_tools = always_on + session_unique + [FIND_TOOLS_TOOL]

            summary = tool_registry.get_category_summary()
            logger.debug(
                "Deferred tool loading: %d/%d tools active (session=%d, registry=%s)",
                len(all_tools), len(tool_registry._entries),
                len(st.session_tools), summary,
            )
        else:
            all_tools = (
                mcp_tools + skill_tools + unified_tools + workspace_extra
                + page_mgmt_tools + job_tools + [_RESPOND_DIRECTLY_TOOL]
            )

        return all_tools

    def _handle_find_tools(self, query: str, state: _RequestState | None = None) -> str:
        """Handle find_tools meta-tool: search registry and add to session."""
        st = state or _RequestState()
        results = tool_registry.search(query)
        for entry in results:
            st.session_tools.add(entry.name)
        return tool_registry.format_search_result(results)

    async def _execute_tool_call(self, tool_call: Dict[str, Any], state: _RequestState | None = None) -> str:
        """단일 도구 호출 실행 및 결과 반환"""
        function_name = tool_call["function"]["name"]
        arguments_str = tool_call["function"]["arguments"]

        args = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str

        # Backward compatibility: legacy tool names → unified + context hint
        function_name, args = resolve_legacy_tool(function_name, args)

        if function_name == "find_tools":
            return self._handle_find_tools(args.get("query", ""), state=state)
        elif function_name == "respond_directly":
            return args.get("message", "")
        elif function_name in UNIFIED_TOOL_NAMES:
            return await handle_unified_tool_call(function_name, args)
        elif function_name in SKILL_TOOL_NAMES:
            return await skill_manager.handle_tool_call(function_name, args)
        elif function_name in PAGE_TOOL_NAMES:
            return await handle_page_tool_call(function_name, args)
        elif function_name in WORKSPACE_TOOL_NAMES:
            return await handle_workspace_tool_call(function_name, args)
        elif function_name in SCHEDULED_TASK_TOOL_NAMES:
            return await job_manager.handle_tool_call(function_name, args)
        else:
            try:
                server_name, tool_name = parse_namespaced_tool(function_name)
                return await mcp_manager.call_tool(server_name, tool_name, args)
            except ValueError:
                return f"Error: Invalid tool name format '{function_name}'"

    async def _execute_tool_call_safe(self, tool_call: Dict[str, Any], state: _RequestState | None = None) -> "str | Dict[str, Any]":
        """_execute_tool_call을 감싸서 예외를 문자열로 변환 + 캐시 적용"""
        st = state or _RequestState()
        function_name = tool_call["function"]["name"]
        args_str = tool_call["function"].get("arguments", "{}")

        # Phase 6: 캐시 체크 (읽기 전용 도구만)
        if function_name in _CACHEABLE_TOOLS:
            try:
                normalized_args = json.dumps(json.loads(args_str), sort_keys=True)
            except (json.JSONDecodeError, TypeError):
                normalized_args = args_str
            cache_key = (function_name, normalized_args)
            if cache_key in st.tool_result_cache:
                logger.debug("Tool result cache hit: %s", function_name)
                return st.tool_result_cache[cache_key]

        try:
            result = await self._execute_tool_call(tool_call, state=st)
            # 에스컬레이션 dict는 캐시하지 않고 그대로 반환
            if isinstance(result, dict) and result.get("__escalation__"):
                return result
            # 캐시 저장 (읽기 전용 도구, 성공 시만)
            if function_name in _CACHEABLE_TOOLS and isinstance(result, str) and not result.startswith("Error"):
                st.tool_result_cache[cache_key] = result
            return result
        except Exception as e:
            logger.error("Tool call error (%s): %s", function_name, e)
            return f"Error: {e}"

    async def run(self, messages: List[Dict[str, Any]], *, skip_routing: bool = False, forced_workflow: str | None = None) -> Dict[str, Any]:
        # Shallow copy to avoid mutating the caller's list
        messages = list(messages)
        # Per-request local state (싱글톤 경합 조건 방지)
        state = _RequestState()
        response = None  # H-10: UnboundLocalError 방지

        # Inject system prompt with skill metadata + relevance-filtered memory
        last_user_msg = self._extract_last_user_message(messages)
        has_error = False
        empty_retries = 0
        error_guide_injected = False

        # 워크플로우 라우팅: 명시적 선택 우선, 없으면 LLM 라우팅 (대화 맥락 포함)
        workflow_match = None
        if forced_workflow:
            workflow_match = skill_manager.get_workflow_body(forced_workflow)
        elif last_user_msg and not skip_routing:
            routed_name = await workflow_router.route(
                last_user_msg,
                messages=messages,
                prev_workflow=self._prev_workflow,
            )
            if routed_name:
                workflow_match = skill_manager.get_workflow_body(routed_name)

        # 이전 워크플로우 갱신
        self._prev_workflow = workflow_match["name"] if workflow_match else None

        system_prompt = self._build_system_prompt(
            user_input=last_user_msg, workflow_match=workflow_match,
        )
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        all_tools = await self._build_tools(user_message=last_user_msg, state=state)

        # Multi-round tool call loop
        max_rounds = max(settings_manager.llm.max_tool_rounds, 0)  # H-10: 음수 방지
        _tool_choice_override = None  # 빈 응답 재시도 시 다음 라운드 tool_choice 오버라이드
        # 워크플로우 활성화 시 reasoning_effort 상향 (복잡한 작업은 더 깊은 추론 필요)
        _effort = "high" if workflow_match else None
        for round_num in range(max_rounds + 1):
            # 적응형 컨텍스트 압축: 사용률 기반 (레거시 고정 라운드 대체)
            messages, _ = await self._maybe_compact_context(messages, all_tools)

            tool_choice = _tool_choice_override or self._resolve_tool_choice(messages, all_tools, round_num)
            _tool_choice_override = None  # 사용 후 리셋

            response = await self.llm.chat_completion(
                messages,
                tools=all_tools if all_tools else None,
                tool_choice=tool_choice,
                reasoning_effort=_effort,
            )

            choices = response.get("choices") or []
            if not choices:
                logger.warning("LLM returned empty choices list")
                break
            message = choices[0]["message"]

            # No tool calls — return final response
            if not message.get("tool_calls"):
                content = (message.get("content") or "").strip()
                # LLM이 빈 응답을 반환한 경우 — 점진적 재시도
                if not content and empty_retries < _MAX_EMPTY_RETRIES:
                    empty_retries += 1
                    # 이전 라운드에서 이미 도구를 사용했으면 데이터 충분 → 바로 respond_directly 강제
                    has_prior_tools = any(m.get("role") == "tool" for m in messages)
                    if has_prior_tools:
                        logger.warning("LLM returned empty after tool results on round %d, forcing respond_directly (%d/%d)", round_num, empty_retries, _MAX_EMPTY_RETRIES)
                        _tool_choice_override = _FORCE_RESPOND_TOOL_CHOICE
                    elif empty_retries == 1:
                        # 도구 미사용 상태 1차: tool_choice="required" — 모델이 도구를 자율 선택
                        logger.warning("LLM returned empty on round %d, retrying with tool_choice=required (%d/%d)", round_num, empty_retries, _MAX_EMPTY_RETRIES)
                        _tool_choice_override = "required"
                    else:
                        # 2차: respond_directly 강제
                        logger.warning("LLM returned empty on round %d, forcing respond_directly (%d/%d)", round_num, empty_retries, _MAX_EMPTY_RETRIES)
                        _tool_choice_override = _FORCE_RESPOND_TOOL_CHOICE
                    continue

                # 재시도 소진 후에도 빈 응답 — 도구 결과가 있으면 도구 없이 최종 호출
                if not content and any(m.get("role") == "tool" for m in messages):
                    logger.warning("All empty retries exhausted with tool results present, recovery call without tools")
                    messages.append({"role": "user", "content": "위 도구 결과를 바탕으로 사용자의 질문에 답변해주세요."})
                    recovery = await self.llm.chat_completion(messages, tools=None)
                    recovery_content = (recovery["choices"][0]["message"].get("content") or "").strip()
                    if recovery_content:
                        return recovery
                return response

            tool_calls = message["tool_calls"]

            # respond_directly 이스케이프: 텍스트 응답으로 변환하여 즉시 반환
            if len(tool_calls) == 1 and tool_calls[0]["function"]["name"] == "respond_directly":
                try:
                    args = json.loads(tool_calls[0]["function"]["arguments"]) if isinstance(tool_calls[0]["function"]["arguments"], str) else tool_calls[0]["function"]["arguments"]
                except (json.JSONDecodeError, TypeError):
                    args = {}
                return {"choices": [{"message": {"role": "assistant", "content": args.get("message", "")}}]}

            # Safety: max rounds reached
            if round_num >= max_rounds:
                logger.warning("Max tool call rounds (%d) reached, returning last response", max_rounds)
                return response

            # Process tool calls — 병렬 실행 후 순서대로 메시지 추가
            messages.append(message)

            results = await asyncio.gather(
                *(self._execute_tool_call_safe(tc, state=state) for tc in tool_calls)
            )

            # C14: 라운드별 총합 예산을 도구 수로 균등 분배
            round_budget = self._get_dynamic_tool_result_limit(messages, all_tools)
            per_tool_limit = max(5000, round_budget // max(len(tool_calls), 1))

            for tool_call, result in zip(tool_calls, results):
                # C-00c: 에스컬레이션 dict 처리 (run_stream과 동일)
                if isinstance(result, dict) and result.get("__escalation__"):
                    content_for_llm = f"[권한 요청] {result.get('description', 'escalation')}"
                    success = True
                else:
                    content_for_llm, success = self._process_tool_result(result, max_chars=per_tool_limit)
                if not success:
                    has_error = True
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": tool_call["function"]["name"],
                    "content": content_for_llm,
                })

            logger.debug("Tool round %d complete, %d tool(s) executed (parallel)", round_num + 1, len(tool_calls))

            # 첫 에러 발생 시 에러 가이드를 시스템 프롬프트에 추가 (전체 재구축 대신 append)
            if has_error and not error_guide_injected and messages[0].get("role") == "system":
                messages[0]["content"] += "\n\n" + ERROR_HANDLING_PROMPT
                error_guide_injected = True

            # find_tools 호출 시 도구 목록 갱신 (deferred mode)
            if any(tc["function"]["name"] == "find_tools" for tc in tool_calls):
                all_tools = await self._build_tools(state=state)

            # 주기적 자기 점검: 장기 루프에서 방향을 잃지 않도록 진행 상황 정리 유도
            if (round_num + 1) % _SELF_ASSESSMENT_INTERVAL == 0 and round_num + 1 < max_rounds:
                messages.append({"role": "system", "content": _SELF_ASSESSMENT_PROMPT})
                logger.debug("Self-assessment injected at round %d", round_num + 1)

        if response is None:
            return {"choices": [{"message": {"role": "assistant", "content": "응답을 생성할 수 없습니다."}}]}
        return response

    async def run_stream(self, messages: List[Dict[str, Any]], *, skip_routing: bool = False, forced_workflow: str | None = None) -> AsyncGenerator[Dict[str, Any], None]:
        """run()과 동일한 로직이지만 각 단계를 SSE 이벤트로 yield하는 제너레이터."""
        messages = list(messages)
        # Per-request local state (싱글톤 경합 조건 방지)
        state = _RequestState()

        last_user_msg = self._extract_last_user_message(messages)
        has_error = False
        empty_retries = 0
        error_guide_injected = False

        # 워크플로우 라우팅: 명시적 선택 우선, 없으면 LLM 라우팅 (대화 맥락 포함)
        workflow_match = None
        if forced_workflow:
            workflow_match = skill_manager.get_workflow_body(forced_workflow)
        elif last_user_msg and not skip_routing:
            yield {"type": "thinking", "content": "요청 분석 중..."}
            routed_name = await workflow_router.route(
                last_user_msg,
                messages=messages,
                prev_workflow=self._prev_workflow,
            )
            if routed_name:
                workflow_match = skill_manager.get_workflow_body(routed_name)

        # 이전 워크플로우 갱신
        self._prev_workflow = workflow_match["name"] if workflow_match else None

        system_prompt = self._build_system_prompt(
            user_input=last_user_msg, workflow_match=workflow_match,
        )
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        all_tools = await self._build_tools(user_message=last_user_msg, state=state)

        # 워크플로우 활성화 이벤트
        if workflow_match:
            yield {"type": "workflow_activated", "skill_name": workflow_match["name"]}

        max_rounds = max(settings_manager.llm.max_tool_rounds, 0)  # H-10: 음수 방지
        _tool_choice_override = None  # 빈 응답 재시도 시 다음 라운드 tool_choice 오버라이드
        # 워크플로우 활성화 시 reasoning_effort 상향
        _effort = "high" if workflow_match else None

        # 초기 컨텍스트 상태 전송
        initial_status = self._get_context_status(messages, all_tools)
        yield {"type": "context_status", **initial_status}

        for round_num in range(max_rounds + 1):
            # 적응형 컨텍스트 압축: 사용률 기반
            messages, compact_event = await self._maybe_compact_context(messages, all_tools)
            if compact_event:
                yield compact_event
                # 압축 후 상태 재전송
                yield {"type": "context_status", **compact_event["status"]}

            tool_choice = _tool_choice_override or self._resolve_tool_choice(messages, all_tools, round_num)
            _tool_choice_override = None  # 사용 후 리셋
            yield {"type": "thinking", "content": f"LLM 호출 중... (라운드 {round_num + 1})"}

            response = await self.llm.chat_completion(
                messages,
                tools=all_tools if all_tools else None,
                tool_choice=tool_choice,
                reasoning_effort=_effort,
            )

            choices = response.get("choices") or []
            if not choices:
                logger.warning("LLM returned empty choices list")
                yield {"type": "content", "content": "응답을 생성할 수 없습니다."}
                break
            message = choices[0]["message"]

            if not message.get("tool_calls"):
                content = (message.get("content") or "").strip()
                # LLM이 빈 응답을 반환한 경우 — 점진적 재시도
                if not content and empty_retries < _MAX_EMPTY_RETRIES:
                    empty_retries += 1
                    # 이전 라운드에서 이미 도구를 사용했으면 데이터 충분 → 바로 respond_directly 강제
                    has_prior_tools = any(m.get("role") == "tool" for m in messages)
                    if has_prior_tools:
                        logger.warning("LLM returned empty after tool results on round %d, forcing respond_directly (%d/%d)", round_num, empty_retries, _MAX_EMPTY_RETRIES)
                        yield {"type": "thinking", "content": f"빈 응답 감지, 수집된 데이터 기반 응답 생성 중... ({empty_retries}/{_MAX_EMPTY_RETRIES})"}
                        _tool_choice_override = _FORCE_RESPOND_TOOL_CHOICE
                    elif empty_retries == 1:
                        # 도구 미사용 상태 1차: tool_choice="required" — 모델이 도구를 자율 선택
                        logger.warning("LLM returned empty on round %d, retrying with tool_choice=required (%d/%d)", round_num, empty_retries, _MAX_EMPTY_RETRIES)
                        yield {"type": "thinking", "content": f"빈 응답 감지, 도구 사용 필수로 재시도 중... ({empty_retries}/{_MAX_EMPTY_RETRIES})"}
                        _tool_choice_override = "required"
                    else:
                        # 2차: respond_directly 강제
                        logger.warning("LLM returned empty on round %d, forcing respond_directly (%d/%d)", round_num, empty_retries, _MAX_EMPTY_RETRIES)
                        yield {"type": "thinking", "content": f"빈 응답 감지, respond_directly 강제 호출 중... ({empty_retries}/{_MAX_EMPTY_RETRIES})"}
                        _tool_choice_override = _FORCE_RESPOND_TOOL_CHOICE
                    continue

                # 재시도 소진 후에도 빈 응답 — 도구 결과가 있으면 도구 없이 최종 호출
                if not content and any(m.get("role") == "tool" for m in messages):
                    logger.warning("All empty retries exhausted with tool results present, recovery call without tools")
                    yield {"type": "thinking", "content": "수집된 데이터 기반 최종 응답 생성 중..."}
                    messages.append({"role": "user", "content": "위 도구 결과를 바탕으로 사용자의 질문에 답변해주세요."})
                    recovery = await self.llm.chat_completion(messages, tools=None)
                    recovery_content = (recovery["choices"][0]["message"].get("content") or "").strip()
                    if recovery_content:
                        content = recovery_content
                        response = recovery

                # 최종 컨텍스트 상태 전송
                final_status = self._get_context_status(messages, all_tools)
                yield {"type": "context_status", **final_status}
                yield {"type": "content", "content": content}
                yield {"type": "done", "full_response": response}
                return

            tool_calls = message["tool_calls"]

            # respond_directly 이스케이프: 텍스트 응답으로 변환하여 즉시 반환
            if len(tool_calls) == 1 and tool_calls[0]["function"]["name"] == "respond_directly":
                try:
                    args = json.loads(tool_calls[0]["function"]["arguments"]) if isinstance(tool_calls[0]["function"]["arguments"], str) else tool_calls[0]["function"]["arguments"]
                except (json.JSONDecodeError, TypeError):
                    args = {}
                direct_content = args.get("message") or ""
                final_status = self._get_context_status(messages, all_tools)
                yield {"type": "context_status", **final_status}
                yield {"type": "content", "content": direct_content}
                # 메모리 추출이 작동하도록 content를 채운 합성 응답 전달
                yield {"type": "done", "full_response": {"choices": [{"message": {"role": "assistant", "content": direct_content}}]}}
                return

            if round_num >= max_rounds:
                logger.warning("Max tool call rounds (%d) reached, returning last response", max_rounds)
                final_content = message.get("content") or "최대 도구 호출 횟수에 도달했습니다. 다시 시도해 주세요."
                yield {"type": "content", "content": final_content}
                yield {"type": "done", "full_response": response}
                return

            messages.append(message)

            # 1) 모든 tool_call 이벤트를 먼저 yield (UI에 즉시 표시)
            for tool_call in tool_calls:
                yield {
                    "type": "tool_call",
                    "name": tool_call["function"]["name"],
                    "arguments": tool_call["function"]["arguments"],
                }

            # 2) 모든 도구를 병렬 실행
            results = await asyncio.gather(
                *(self._execute_tool_call_safe(tc, state=state) for tc in tool_calls)
            )

            # C14: 라운드별 총합 예산을 도구 수로 균등 분배
            round_budget = self._get_dynamic_tool_result_limit(messages, all_tools)
            per_tool_limit = max(5000, round_budget // max(len(tool_calls), 1))

            # 3) 결과를 순서대로 메시지에 추가하고 tool_result 이벤트 yield
            for tool_call, result in zip(tool_calls, results):
                # 에스컬레이션 요청 감지
                if isinstance(result, dict) and result.get("__escalation__"):
                    esc = result["escalation"]
                    # LLM에게는 승인 대기 메시지 전달
                    llm_msg = (
                        f"[sandbox] 이 명령은 네트워크 접근 권한이 필요합니다. "
                        f"사용자에게 권한 승인을 요청했습니다. 승인 결과를 기다려주세요.\n"
                        f"명령: {result['command']}\n"
                        f"오류: {result.get('stderr_preview', '')[:200]}"
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "content": llm_msg,
                    })
                    yield {
                        "type": "escalation_request",
                        "name": tool_call["function"]["name"],
                        "command": result["command"],
                        "workspace_id": result["workspace_id"],
                        "cwd": result["cwd"],
                        "timeout": result["timeout"],
                        "violation": result["violation"],
                        "stderr_preview": result.get("stderr_preview", ""),
                        "description": esc.get("description", ""),
                        "requested_policy": esc.get("requested_policy", ""),
                        "current_policy": esc.get("current_policy", ""),
                        "message": esc.get("message", ""),
                    }
                    # 에스컬레이션 요청 후 스트림 즉시 종료 — 프론트엔드가 승인/거부 처리
                    return

                content_for_llm, success = self._process_tool_result(result, max_chars=per_tool_limit)
                if not success:
                    has_error = True
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": tool_call["function"]["name"],
                    "content": content_for_llm,
                })
                yield {
                    "type": "tool_result",
                    "name": tool_call["function"]["name"],
                    "result": str(result)[:500],
                    "success": success,
                }

            logger.debug("Tool round %d complete, %d tool(s) executed (parallel)", round_num + 1, len(tool_calls))

            # 라운드 완료 후 컨텍스트 상태 업데이트 전송
            round_status = self._get_context_status(messages, all_tools)
            yield {"type": "context_status", **round_status}

            # 첫 에러 발생 시 에러 가이드를 시스템 프롬프트에 추가 (전체 재구축 대신 append)
            if has_error and not error_guide_injected and messages[0].get("role") == "system":
                messages[0]["content"] += "\n\n" + ERROR_HANDLING_PROMPT
                error_guide_injected = True

            # find_tools 호출 시 도구 목록 갱신 (deferred mode)
            if any(tc["function"]["name"] == "find_tools" for tc in tool_calls):
                all_tools = await self._build_tools(state=state)

            # 주기적 자기 점검: 장기 루프에서 방향을 잃지 않도록 진행 상황 정리 유도
            if (round_num + 1) % _SELF_ASSESSMENT_INTERVAL == 0 and round_num + 1 < max_rounds:
                messages.append({"role": "system", "content": _SELF_ASSESSMENT_PROMPT})
                logger.debug("Self-assessment injected at round %d", round_num + 1)


orchestrator = AgentOrchestrator()
