# Open Agent Backend

> AI와 실무를 연결하는 Open Agent 플랫폼의 Python 백엔드.

Python 3.13 + FastAPI 기반. LiteLLM 추상화를 통한 멀티 LLM 지원, MCP(Model Context Protocol) 도구 연동, Agent Skills 실행, Workspace 파일/셸 도구, 장기 기억(Memory) 자동 추출/압축/고정, 세션 관리, SSE 실시간 스트리밍을 제공합니다.

## 설치 및 실행

```bash
# 의존성 설치 (uv 사용)
uv sync

# 개발 환경 (테스트 + lint 포함)
uv sync --group dev

# 개발 모드
uv run open-agent start --dev

# 직접 실행
uv run uvicorn open_agent.server:app --reload --host 127.0.0.1 --port 4821
```

## 테스트

```bash
# 전체 테스트 실행
uv run pytest

# 커버리지 리포트
uv run pytest --cov --cov-report=term-missing
```

## 구조

```
open_agent/
├── __init__.py                 # 패키지 버전 (__version__)
├── __main__.py                 # python -m open_agent 지원
├── cli.py                      # Click CLI 엔트리포인트 (open-agent 명령)
├── server.py                   # FastAPI 앱, 라우터 등록, 정적 파일 서빙, CORS, 라이프사이클
├── config.py                   # ~/.open-agent/ 데이터 디렉토리 경로 관리
├── README.md                   # 이 파일
├── core/                       # 핵심 비즈니스 로직
│   ├── __init__.py
│   ├── agent.py                # AgentOrchestrator — 도구 라우팅, SSE 스트리밍, 멀티턴 실행
│   ├── llm.py                  # LLMClient — LiteLLM acompletion 래퍼, API 키 자동 해석
│   ├── exceptions.py           # OpenAgentError 기반 커스텀 예외 계층 (18개 예외 클래스)
│   ├── logging.py              # structlog 기반 구조화 로깅 설정
│   ├── mcp_manager.py          # MCPClientManager — MCP 서버 연결/재시작/도구 탐색
│   ├── skill_manager.py        # SkillManager — SKILL.md 파싱, 스킬 도구 생성, 스크립트 실행
│   ├── page_manager.py         # PageManager — HTML 페이지/폴더/북마크 트리 관리
│   ├── settings_manager.py     # SettingsManager — LLM/테마/메모리 설정 CRUD
│   ├── session_manager.py      # SessionManager — 대화 세션 히스토리 저장/복원
│   ├── workspace_manager.py    # WorkspaceManager — 워크스페이스 등록/활성화, 파일 트리/내용 조회
│   ├── workspace_tools.py      # Workspace 도구 — 파일 읽기/쓰기/편집/검색/셸 실행 + 보안
│   └── memory_manager.py       # MemoryManager — 추출/압축/고정(Pin)/자동 교체/시스템 프롬프트 주입
├── api/                        # FastAPI 라우터 (REST API)
│   ├── __init__.py
│   ├── middleware.py            # RequestLoggingMiddleware (request_id + 구조화 접근 로그)
│   └── endpoints/
│       ├── __init__.py
│       ├── chat.py             # POST /api/chat/stream — SSE 스트리밍 채팅
│       ├── mcp.py              # /api/mcp/* — MCP 서버 CRUD, 도구 목록
│       ├── skills.py           # /api/skills/* — 스킬 CRUD, ZIP 업로드, 임포트
│       ├── pages.py            # /api/pages/* — 페이지/폴더 CRUD, HTML 업로드, 북마크
│       ├── sessions.py         # /api/sessions/* — 세션 히스토리 CRUD
│       ├── settings.py         # /api/settings/* — LLM/테마/메모리 설정, 헬스체크
│       ├── workspace.py        # /api/workspace/* — 워크스페이스 CRUD, 파일 트리/내용
│       └── memory.py           # /api/memory/* — 메모리 CRUD, 핀 토글, 전체 삭제
├── models/                     # Pydantic V2 데이터 모델
│   ├── __init__.py
│   ├── _base.py                # OpenAgentBase (공통 ConfigDict)
│   ├── error.py                # ErrorResponse, ErrorDetail (표준 에러 스키마)
│   ├── mcp.py                  # MCPServerConfig, MCPServerStatus, MCPTransport
│   ├── skill.py                # SkillMeta, SkillInfo
│   ├── page.py                 # PageItem, FolderItem
│   ├── session.py              # SessionInfo, SessionMessage, MessageRole
│   ├── settings.py             # Settings, LLMSettings, ThemeSettings
│   ├── job.py                  # JobInfo, JobRunStatus, JobScheduleType
│   ├── workspace.py            # WorkspaceInfo, FileTreeNode
│   └── memory.py               # MemoryItem (is_pinned 포함), MemorySettings
├── tests/                      # pytest 테스트 (50개)
│   ├── conftest.py             # 전역 fixture (격리 데이터, manager mock, async_client)
│   ├── unit/                   # 단위 테스트 (SessionManager, MemoryManager)
│   └── integration/            # 통합 테스트 (FastAPI 엔드포인트)
└── static/                     # 빌드된 프론트엔드 (wheel에 포함, git에서 제외)
```

## 핵심 모듈

### AgentOrchestrator (`core/agent.py`)

LLM 호출과 도구 실행을 오케스트레이션합니다.

- 시스템 프롬프트에 활성 스킬 목록(`<available_skills>` XML)과 장기 기억(`<memories>`) 주입
- MCP 도구, 스킬 도구, 워크스페이스 도구를 하나의 도구 목록으로 병합
- SSE 이벤트 스트리밍: `thinking` → `tool_call` → `tool_result` → `content` → `done`
- 도구 호출 시 자동 라우팅: 네임스페이스 기반(`server__tool` → MCP, `skill_*` → Skills, `workspace_*` → Workspace)
- 도구 결과를 메시지에 추가하여 멀티턴 자동 실행

### MemoryManager (`core/memory_manager.py`)

대화에서 장기 기억을 자동 추출하고 관리합니다.

- **자동 추출**: 대화 완료 후 LLM으로 새로운 사실/선호/패턴/맥락 추출
- **자동 압축**: 용량 임계치(`compression_threshold`) 도달 시 LLM으로 유사 메모리 병합
- **메모리 고정(Pin)**: `is_pinned=True`인 메모리는 자동 삭제 및 압축 대상에서 제외
- **자동 교체**: 최대 용량 초과 시 가장 오래된 비핀(non-pinned) 메모리 삭제
- **시스템 프롬프트 주입**: `build_memory_prompt()`로 LLM 컨텍스트에 자동 포함
- 카테고리: preference, context, pattern, fact

### WorkspaceTools (`core/workspace_tools.py`)

활성 워크스페이스에서 AI가 사용하는 파일/셸 도구를 제공합니다.

- `workspace_read_file` — 파일 읽기 (라인 범위 지정 가능)
- `workspace_write_file` — 파일 쓰기 (생성/덮어쓰기)
- `workspace_edit_file` — 문자열 치환 편집
- `workspace_search` — 정규식 파일 내용 검색
- `workspace_list_files` — 디렉토리 트리 조회
- `workspace_bash` — 셸 명령 실행 (타임아웃, 위험 명령 차단)

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/chat/stream` | SSE 스트리밍 채팅 |
| GET | `/api/mcp/servers` | MCP 서버 목록 |
| POST | `/api/mcp/servers` | MCP 서버 추가 |
| PATCH | `/api/mcp/servers/{name}` | MCP 서버 수정 |
| DELETE | `/api/mcp/servers/{name}` | MCP 서버 삭제 |
| POST | `/api/mcp/servers/{name}/restart` | MCP 서버 재시작 |
| GET | `/api/skills/` | 스킬 목록 |
| POST | `/api/skills/` | 스킬 생성 |
| POST | `/api/skills/upload` | 스킬 ZIP 업로드 |
| POST | `/api/skills/import` | 스킬 경로 임포트 |
| GET | `/api/pages/` | 페이지 목록 |
| POST | `/api/pages/upload` | HTML 업로드 |
| POST | `/api/pages/bookmark` | URL 북마크 추가 |
| GET | `/api/workspace/` | 워크스페이스 목록 |
| POST | `/api/workspace/` | 워크스페이스 등록 |
| POST | `/api/workspace/{id}/activate` | 활성화 |
| GET | `/api/workspace/{id}/tree` | 파일 트리 조회 |
| GET | `/api/workspace/{id}/file` | 파일 내용 조회 |
| GET | `/api/memory/` | 메모리 목록 |
| POST | `/api/memory/` | 메모리 생성 |
| PATCH | `/api/memory/{id}` | 메모리 수정 |
| PATCH | `/api/memory/{id}/pin` | 메모리 핀 토글 |
| DELETE | `/api/memory/{id}` | 메모리 삭제 |
| DELETE | `/api/memory/` | 전체 메모리 삭제 |
| GET | `/api/sessions/` | 세션 목록 |
| GET | `/api/sessions/{id}` | 세션 상세 |
| DELETE | `/api/sessions/{id}` | 세션 삭제 |
| GET | `/api/settings/` | 설정 조회 |
| PATCH | `/api/settings/llm` | LLM 설정 수정 |
| PATCH | `/api/settings/memory` | 메모리 설정 수정 |
| GET | `/api/settings/health` | 연결 상태 헬스체크 |

## 보안

### 경로 순회 방지

모든 워크스페이스 파일 작업은 `_resolve_safe_path()`로 루트 내부만 접근 가능. `../../etc/passwd` 등 차단.

### 위험 셸 명령 차단 (10종)

`workspace_bash` 도구에서 아래 패턴 매칭 시 실행 전 즉시 차단:

- `rm -rf /` / `rm -fr /` — 루트 재귀 삭제
- Fork bomb `:(){ :|:& };` — 무한 프로세스 생성
- `dd if=/dev/zero of=/dev/sda` — 디스크 덮어쓰기
- `mkfs.*` — 파일시스템 포맷
- `> /dev/sda` — 블록 디바이스 직접 쓰기
- `curl ... | sh` / `wget ... | sh` — 원격 스크립트 pipe-to-shell
- `chmod -R 777 /` — 루트 전체 권한 변경
- `chown -R ... /` — 루트 전체 소유자 변경

### 셸 실행 제한

- 타임아웃: 기본 30초, 최대 120초
- 출력 절삭: stdout 30,000자, stderr 5,000자
- 작업 디렉토리: 워크스페이스 루트 내부만 허용

### 파일 편집 안전장치

- 빈 `old_string` 거부
- `old_string` 다중 매치 시 `replace_all=false`면 거부 (매치 수 안내)

## 데이터 저장

모든 런타임 데이터는 `~/.open-agent/`에 JSON 파일로 저장됩니다:

| 파일 | 설명 |
|------|------|
| `.env` | API 키 (dotenv) |
| `settings.json` | LLM, 테마, 메모리 설정 |
| `mcp.json` | MCP 서버 설정 |
| `skills.json` | 스킬 활성화 상태 |
| `pages.json` | 페이지/폴더 메타데이터 |
| `workspaces.json` | 워크스페이스 등록 정보 |
| `memories.json` | 장기 기억 데이터 (`is_pinned` 포함) |
| `sessions/` | 세션 히스토리 (세션별 JSON) |
| `skills/` | Agent Skills 디렉토리 |
| `pages/` | 업로드된 HTML 파일 |
