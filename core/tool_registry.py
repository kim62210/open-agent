"""Deferred Tool Loading — ToolRegistry + find_tools meta-tool.

When `deferred_tool_loading=True`, only always-on tools are sent to the LLM initially.
The LLM uses `find_tools` to discover and dynamically load additional tools on demand.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class ToolEntry:
    name: str
    description: str
    category: str  # "skill", "workspace", "mcp", "job", "meta"
    tool_def: Dict[str, Any]
    always_on: bool = False


# Always-on tool names (always sent to LLM regardless of deferred mode)
_ALWAYS_ON_NAMES: Set[str] = {
    "respond_directly",
    # Skill tools — core to self-extending architecture
    "read_skill",
    "run_skill_script",
    "read_skill_reference",
    "create_skill",
    "add_skill_script",
    "update_skill",
    # Job tools — 플랫폼 내장 스케줄러 (항상 사용 가능해야 스킬과 경쟁하지 않음)
    "create_scheduled_task",
    "list_scheduled_tasks",
    "delete_scheduled_task",
}

# find_tools meta-tool definition
FIND_TOOLS_TOOL = {
    "type": "function",
    "function": {
        "name": "find_tools",
        "description": (
            "사용 가능한 도구를 키워드로 검색합니다. "
            "파일 읽기/쓰기, 워크스페이스 탐색, MCP 서버 도구, 예약 작업 등 "
            "특정 기능이 필요할 때 이 도구로 먼저 검색하세요. "
            "검색 결과로 반환된 도구는 이후 라운드에서 즉시 사용할 수 있습니다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "검색 키워드. 예: 'file read', 'workspace', 'bash', "
                        "'sequential thinking', 'scheduled task'"
                    ),
                }
            },
            "required": ["query"],
        },
    },
}


class ToolRegistry:
    def __init__(self):
        self._entries: Dict[str, ToolEntry] = {}

    def register(
        self,
        name: str,
        tool_def: Dict[str, Any],
        category: str,
        always_on: bool = False,
    ) -> None:
        desc = tool_def.get("function", {}).get("description", "")
        self._entries[name] = ToolEntry(
            name=name,
            description=desc,
            category=category,
            tool_def=tool_def,
            always_on=always_on or name in _ALWAYS_ON_NAMES,
        )

    def unregister(self, name: str) -> None:
        self._entries.pop(name, None)

    def clear(self) -> None:
        self._entries.clear()

    def search(self, query: str, max_results: int = 10) -> List[ToolEntry]:
        """Keyword search across tool names and descriptions."""
        if not query.strip():
            return list(self._entries.values())[:max_results]

        keywords = re.split(r"[\s_]+", query.lower())
        scored: List[tuple[float, ToolEntry]] = []

        for entry in self._entries.values():
            searchable = f"{entry.name} {entry.description} {entry.category}".lower()
            score = 0.0
            for kw in keywords:
                if kw in entry.name.lower():
                    score += 3.0  # name match weighted higher
                if kw in entry.description.lower():
                    score += 1.0
                if kw in entry.category.lower():
                    score += 0.5
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        return [entry for _, entry in scored[:max_results]]

    def get_always_on_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions that are always sent to LLM."""
        return [e.tool_def for e in self._entries.values() if e.always_on]

    def get_tools_by_names(self, names: Set[str]) -> List[Dict[str, Any]]:
        """Return tool definitions for specific tool names."""
        return [
            self._entries[n].tool_def
            for n in names
            if n in self._entries
        ]

    def get_all_tool_defs(self) -> List[Dict[str, Any]]:
        """Return all registered tool definitions."""
        return [e.tool_def for e in self._entries.values()]

    def get_category_summary(self) -> Dict[str, int]:
        """Return count of tools per category."""
        summary: Dict[str, int] = {}
        for entry in self._entries.values():
            summary[entry.category] = summary.get(entry.category, 0) + 1
        return summary

    def refresh_all(
        self,
        mcp_tools: List[Dict[str, Any]],
        skill_tools: List[Dict[str, Any]],
        workspace_tools: List[Dict[str, Any]],
        job_tools: List[Dict[str, Any]],
        extra_tools: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Re-register all tools from all sources."""
        self.clear()

        for tool in mcp_tools:
            name = tool["function"]["name"]
            self.register(name, tool, "mcp")

        for tool in skill_tools:
            name = tool["function"]["name"]
            self.register(name, tool, "skill", always_on=True)

        for tool in workspace_tools:
            name = tool["function"]["name"]
            self.register(name, tool, "workspace")

        for tool in job_tools:
            name = tool["function"]["name"]
            self.register(name, tool, "job")

        if extra_tools:
            for tool in extra_tools:
                name = tool["function"]["name"]
                self.register(name, tool, "meta", always_on=True)

        logger.debug(
            "ToolRegistry refreshed: %d tools (%s)",
            len(self._entries),
            ", ".join(f"{k}={v}" for k, v in self.get_category_summary().items()),
        )

    def format_search_result(self, entries: List[ToolEntry]) -> str:
        """Format search results for LLM consumption."""
        if not entries:
            return "검색 결과가 없습니다. 다른 키워드로 시도해 보세요."

        lines = [f"**{len(entries)}개 도구 발견** (이후 라운드에서 사용 가능):\n"]
        for entry in entries:
            desc = entry.description[:120] + "..." if len(entry.description) > 120 else entry.description
            lines.append(f"- `{entry.name}` [{entry.category}]: {desc}")

        return "\n".join(lines)


# Phase 5: Intent → tool category mapping for preloading
_INTENT_KEYWORDS: Dict[str, List[str]] = {
    "workspace": [
        "파일", "읽어", "열어", "코드", "폴더", "디렉토리", "파일을",
        "file", "read", "write", "edit", "code", "directory", "folder",
        "프로젝트", "소스", "경로", "tree",
        "실행", "bash", "터미널", "명령", "shell", "run", "execute",
        "rename", "glob",
    ],
    "job": [
        "예약", "스케줄", "schedule", "cron", "주기", "정기",
        "자동", "반복", "interval", "timer",
        "알림", "알려줘", "재생", "시에", "시쯤", "분에", "매일", "내일",
    ],
    "mcp": [
        "mcp", "서버", "외부", "api", "thinking", "sequential",
        "search", "web", "브라우저",
        "날씨", "weather", "기온", "뉴스", "news", "번역", "translate", "환율", "주가",
        "인보이스", "invoice", "처리", "rpa", "송장",
    ],
}


def detect_intent(user_message: str) -> Set[str]:
    """Detect tool categories relevant to the user's message."""
    msg_lower = user_message.lower()
    categories: Set[str] = set()
    for category, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in msg_lower:
                categories.add(category)
                break
    return categories


tool_registry = ToolRegistry()
