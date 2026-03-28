---
name: skill-creator
description: >
  효과적인 스킬을 설계하고 생성하기 위한 가이드.
  사용자가 새 스킬을 만들거나 기존 스킬을 수정/개선/병합하려 할 때 사용합니다.
  복합 작업을 다중 모듈로 설계하거나, 기존 스킬을 벤치마크하여 개선할 때도 사용합니다.
  "이걸 스킬로 만들어줘", "스킬 생성해줘", "이 로직을 저장해줘",
  "이 스킬 개선해줘", "스킬 합쳐줘" 등의 요청에 트리거됩니다.
---

# Skill Creator

효과적인 스킬을 만들기 위한 가이드.

## 스킬이란

스킬은 AI 에이전트의 능력을 확장하는 모듈형 패키지다. 특정 도메인의 절차적 지식, 워크플로우, 도구를 제공하여 범용 에이전트를 전문 에이전트로 변환한다. "온보딩 가이드"처럼, 어떤 모델도 완전히 보유할 수 없는 절차적 지식을 AI에게 제공한다.

### 스킬이 제공하는 것

1. **전문 워크플로우** — 특정 도메인의 다단계 절차
2. **도구 통합** — 특정 파일 형식이나 API 작업을 위한 스크립트
3. **도메인 전문성** — 스키마, 비즈니스 로직, 사내 규칙
4. **번들 리소스** — 반복 작업을 위한 스크립트, 참조 문서, 에셋

### 스킬의 구조

```
skill-name/
├── SKILL.md              (필수) YAML frontmatter + Markdown 지시사항
├── scripts/              (선택) 실행 가능한 코드 (Python/Bash/JS 등)
├── references/           (선택) 필요 시 컨텍스트에 로드하는 참조 문서
└── assets/               (선택) 출력에 사용되는 파일 (템플릿, 이미지 등)
```

#### SKILL.md (필수)

- **Frontmatter (YAML)**: `name`과 `description` 필수.
  - `name`: kebab-case (예: `document-reader`)
  - `description`: 스킬의 **트리거 메커니즘** — "무엇을 하며 언제 사용하는지"를 구체적으로 기술. body가 아닌 여기에 작성할 것. body는 트리거 후에만 로드되므로 "When to Use" 섹션을 body에 넣으면 트리거에 도움이 되지 않음.
- **Body (Markdown)**: 스킬 사용을 위한 지시사항. 명령형으로 작성.

#### scripts/ (선택)

같은 코드를 반복 작성하게 되거나 결정론적 정확도가 필요한 경우.

- **예**: `scripts/rotate_pdf.py` — PDF 회전 처리 (이 스킬의 `scripts/json2html.py`도 설계 예시 참조 가능)
- **장점**: 토큰 절약, 결정론적, 컨텍스트에 읽지 않고 실행 가능
- 추가된 스크립트는 반드시 `run_skill_script`로 테스트할 것
- **경로 규칙**: 스크립트는 스킬 디렉토리에서 실행됨. 외부 파일을 참조할 때는 반드시 **절대 경로**를 인자로 받도록 설계할 것
- **내부 모듈 컨벤션**: 다른 스크립트에서 import만 되고 직접 실행하지 않는 지원 모듈은 `_` prefix를 붙일 것 (예: `_utils.py`, `_data_processor.py`). `_` prefix 파일은 시스템 프롬프트의 스크립트 목록에서 자동 제외되어 LLM이 직접 호출하지 않음.

##### 스크립트 필수 지침

스크립트 작성 시 **반드시** 아래 규칙을 따를 것. 상세 보일러플레이트는 `read_skill_reference("skill-creator", "script-boilerplate.md")`를 참조.

1. **표준 라이브러리만 사용** — pip 설치 불가. `urllib`, `json`, `sys`, `os`, `re`, `pathlib`, `ssl` 등 stdlib만 사용할 것
2. **SSL 인증서 우회 필수** — HTTP 요청 스크립트는 반드시 `ssl.create_default_context()`에 `check_hostname=False`, `verify_mode=ssl.CERT_NONE`을 설정할 것. 기업 프록시/자체 서명 인증서 환경에서 필수
3. **에러를 stderr로 출력** — `print(..., file=sys.stderr)`. 예외를 삼키지 말 것 (`except: pass` 금지). 실패 시 `sys.exit(1)`
4. **인자 검증** — `sys.argv` 길이를 확인하고 부족하면 사용법을 출력 후 `sys.exit(1)`
5. **실행 제한** — 스크립트당 **60초 타임아웃** (초과 시 강제 종료). stdout **100K자** 절삭. 출력은 간결하게 유지
6. **인코딩** — 파일 I/O에 `encoding='utf-8'` 명시. 한글 출력 시 깨짐 방지
7. **환경변수 차단** — API 키 등 민감 변수는 환경에서 자동 제거됨. 필요 시 인자로 전달받을 것

#### references/ (선택)

작업 중 `read_skill_reference`로 참조해야 할 문서.

- **예**: DB 스키마, API 문서, 도메인 지식, 사내 정책
- SKILL.md를 간결하게 유지하면서 상세 정보를 분리
- 10k 단어 이상이면 SKILL.md에 grep 검색 패턴 포함
- **SKILL.md와 references에 같은 내용을 중복하지 말 것** — 상세 정보는 references에, 핵심 절차만 SKILL.md에
- **[핵심] SKILL.md body에서 references를 읽는 시점과 조건을 반드시 명시할 것.** LLM은 references 파일명만으로는 자동으로 읽지 않는다. body에서 "`read_skill_reference`로 X.md를 읽을 것"이라고 명시해야만 실제로 로드된다.

**잘못된 예 (파일명만 나열):**
```markdown
## 참고
- references/schema.md
- references/api-guide.md
```
→ LLM이 이 파일들을 읽지 않을 확률이 높음

**올바른 예 (시점과 조건 명시):**
```markdown
## 절차
1. 데이터 구조 파악: `read_skill_reference("my-skill", "schema.md")`로 스키마 확인
2. API 호출이 필요하면: `read_skill_reference("my-skill", "api-guide.md")`로 엔드포인트 확인
```
→ LLM이 해당 단계에서 자동으로 references를 로드

#### assets/ (선택)

컨텍스트에 로드하지 않고 출력에 사용되는 파일.

- **예**: 로고, 슬라이드 템플릿, 프론트엔드 보일러플레이트, 폰트

#### 포함하지 않을 것

README.md, INSTALLATION_GUIDE.md, CHANGELOG.md 등 부가 문서를 만들지 말 것. 스킬은 AI 에이전트가 작업을 수행하는 데 필요한 정보만 담아야 한다.

## 핵심 원칙

### 간결함이 핵심

컨텍스트 윈도우는 공공재다. 시스템 프롬프트, 대화 히스토리, 다른 스킬의 메타데이터, 사용자 요청이 모두 같은 공간을 나눈다.

**기본 전제: AI는 이미 충분히 똑똑하다.** AI가 이미 아는 것을 다시 설명하지 말 것. 모든 내용에 대해 "이 문단이 토큰 비용을 정당화하는가?" 자문할 것.

장황한 설명보다 간결한 예시를 선호할 것.

### 적절한 자유도 설정

작업의 취약성과 가변성에 맞게 구체성 수준을 결정:

- **높은 자유도 (텍스트 지시사항)**: 여러 접근법이 유효하거나, 맥락에 따라 판단이 달라질 때
- **중간 자유도 (의사코드 또는 파라미터가 있는 스크립트)**: 선호 패턴이 있되, 일부 변형이 허용될 때
- **낮은 자유도 (고정 스크립트)**: 작업이 취약하고 오류에 민감하거나, 일관성이 절대적일 때

좁은 다리 위의 난간(낮은 자유도) vs 열린 들판의 다양한 경로(높은 자유도).

## Progressive Disclosure

스킬은 3단계 로딩으로 컨텍스트를 효율적으로 관리:

1. **메타데이터 (name + description)** — 항상 컨텍스트에 존재 (~100 단어)
2. **SKILL.md body** — 스킬이 트리거될 때 로드 (500줄 이하 권장)
3. **번들 리소스** — 필요 시 로드 (스크립트는 읽지 않고 실행 가능)

### 분할 패턴

SKILL.md body는 500줄 이하로 유지. 이 한도에 근접하면 references/로 분리할 것. 분리 시 SKILL.md에서 반드시 참조하고 언제 읽어야 하는지 명시할 것.

**핵심 원칙:** 스킬이 여러 변형/프레임워크/옵션을 지원할 때, 핵심 워크플로우와 선택 가이드만 SKILL.md에 남기고 변형별 상세 내용은 references/로 이동할 것.

**패턴 1: 상위 가이드 + 참조 문서**
```markdown
# PDF Processing
## Quick start
[핵심 예제]
## Advanced features
- **Form filling**: references/forms.md 참조
- **API reference**: references/api.md 참조
```

**패턴 2: 도메인별 분리**
```
bigquery-skill/
├── SKILL.md (개요 + 네비게이션)
└── references/
    ├── finance.md
    ├── sales.md
    └── product.md
```
→ 사용자가 sales를 물으면 sales.md만 로드.

**패턴 3: 조건부 상세**
```markdown
## Creating documents
docx-js 사용. references/docx-js.md 참조.
## Editing documents
간단한 편집은 XML 직접 수정.
**tracked changes가 필요하면**: references/redlining.md 참조
```

**가이드라인:**
- 참조는 SKILL.md에서 1단계 깊이로만 연결
- 100줄 이상의 참조 파일은 상단에 목차 포함
- **모든 references는 SKILL.md body에서 `read_skill_reference` 호출 시점을 명시할 것** — 단순 나열은 죽은 문서가 됨

## 스킬 생성 프로세스

순서대로 진행. 해당하지 않는 단계만 건너뛸 것.

**[중요] 경로 및 도구 제약:**
- 스킬은 `~/.open-agent/skills/`에 생성됨. 이 경로는 `create_skill` 도구가 자동으로 관리한다.
- **절대 `workspace_write_file`, `workspace_edit_file` 등 워크스페이스 도구로 스킬 파일을 생성하거나 수정하지 말 것.** 워크스페이스에 만들면 스킬 시스템에 등록되지 않아 목록에 나타나지 않는다.
- 스킬 생성은 반드시 `create_skill` 도구를 사용할 것.
- 스크립트 추가는 반드시 `add_skill_script` 도구를 사용할 것.
- 스킬 수정은 반드시 `update_skill` 도구를 사용할 것.

### 1단계: 구체적 예시로 이해

이미 사용 패턴이 명확한 경우에만 건너뛸 것.

스킬이 어떻게 사용될지 구체적 예시를 파악:
- "이 스킬이 어떤 기능을 지원해야 하나요?"
- "이 스킬이 사용되는 예시를 들어주세요."
- "어떤 말을 했을 때 이 스킬이 트리거되어야 하나요?"

한 번에 너무 많은 질문을 하지 말 것. 핵심 질문부터 시작.

### 2단계: 재사용 가능한 리소스 계획

각 예시를 분석:
1. 이 작업을 처음부터 수행하려면?
2. 반복 실행 시 어떤 scripts, references, assets가 유용한가?

**자유도 판단 기준:**

| 조건 | 순수 지시사항 (SKILL.md만) | 스크립트 필요 (scripts/) |
|------|--------------------------|------------------------|
| AI가 직접 수행 가능 | O | - |
| 외부 라이브러리 필요 | - | O |
| 파일 변환/파싱이 핵심 | - | O |
| 프롬프트 엔지니어링이 핵심 | O | - |
| 결정론적 정확도 필요 | - | O |

**리소스 계획 예시:**

- `pdf-editor` 스킬 — "PDF 회전해줘" → 같은 코드를 매번 작성 → `scripts/rotate_pdf.py` 스크립트 필요
- `big-query` 스킬 — "오늘 접속 유저 수는?" → 테이블 스키마를 매번 탐색 → `references/schema.md` 참조 문서 필요
- `frontend-builder` 스킬 — "TODO 앱 만들어줘" → 매번 같은 보일러플레이트 → `assets/template/` 에셋 필요

### 3단계: 스킬 생성

`create_skill` 도구로 생성:

```
create_skill(
  name="my-skill",
  description="무엇을 하며 언제 사용하는 스킬인지 구체적으로 기술",
  instructions="# My Skill\n\n## 절차\n1. ...\n2. ..."
)
```

**frontmatter 작성 규칙:**
- `name`: kebab-case (예: `document-reader`)
- `description`: 트리거 메커니즘. "무엇을 하고 언제 사용하는지" 모두 포함. body가 아닌 여기에 기술.
  - 예: "문서 생성, 편집, 분석을 위한 스킬. 사용자가 .docx 파일을 만들거나 수정하거나, 트래킹 변경 사항을 다루거나, 코멘트를 추가하거나, 기타 문서 작업을 요청할 때 사용합니다."

**body 작성 규칙:**
- 명령형으로 작성 ("~할 것", "~하세요")
- 스크립트가 외부 파일을 인자로 받는 경우, "절대 경로를 전달할 것"이라고 반드시 명시
- 간결한 예시 > 장황한 설명
- **references가 있으면 body에서 `read_skill_reference` 호출 시점을 명시** (시점 미명시 시 LLM이 읽지 않음)
- **scripts가 있으면 body에서 `run_skill_script` 호출 시점, 인자, 예상 결과를 명시**

### 4단계: 리소스 추가 및 편집

#### 스크립트 추가

`add_skill_script` 도구로 추가:

```
add_skill_script(
  skill_name="my-skill",
  filename="process.py",
  content="#!/usr/bin/env python3\n..."
)
```

- 추가 후 반드시 `run_skill_script`로 테스트 실행
- 유사한 스크립트가 여러 개면 대표 샘플만 테스트하여 시간 절약
- 사용자 입력이 필요한 경우 확인 (예: 브랜드 에셋, 템플릿 파일 등)

#### 스킬 수정

`update_skill` 도구로 수정:

```
update_skill(
  name="my-skill",
  description="개선된 설명",
  instructions="# 개선된 지시사항\n..."
)
```

불필요한 예시 파일이나 디렉토리는 삭제할 것.

#### 디자인 패턴 참조

스킬에 아래 패턴이 필요하면 해당 참조를 **반드시 `read_skill_reference`로 읽고** 적용할 것:

- **다단계 프로세스가 있으면**: `read_skill_reference("skill-creator", "workflows.md")` — 순차·조건부 워크플로우 설계 패턴
- **출력 형식이 중요하면**: `read_skill_reference("skill-creator", "output-patterns.md")` — 템플릿·예시 패턴
- **스크립트 실패 대응이 필요하면**: `read_skill_reference("skill-creator", "error-handling.md")` — 에러 처리·폴백 패턴
- **사용자 확인이 필요한 작업이면**: `read_skill_reference("skill-creator", "interaction-patterns.md")` — 자동 진행 vs 사용자 확인 기준
- **복잡한 멀티스텝 스킬을 설계할 때**: `read_skill_reference("skill-creator", "bundled-patterns.md")` — 번들 워크플로우 기반 구조 패턴

### 5단계: 검증

1. `read_skill`로 저장된 내용 확인
2. 스크립트가 있다면 `run_skill_script`로 테스트
3. **references가 있다면 body에서 로딩 시점이 명시되어 있는지 확인** — 누락 시 `update_skill`로 보완
4. **에러 시나리오 확인**: 스크립트 실패 시 body에 폴백 지시가 있는지 점검
5. 사용자에게 결과 보고: 스킬 이름, 설명, 포함 파일, 사용 방법

### 6단계: 반복 개선

실사용 후 개선:
1. 실제 작업에 스킬 사용
2. 비효율이나 문제 발견
3. `update_skill`로 SKILL.md 수정, `add_skill_script`로 스크립트 추가/수정
4. 다시 테스트

## 기존 스킬 수정

아래 ReAct 루프를 따를 것 (Reason → Act → Observe → 반복):

1. **분석(Reason)**: `read_skill`로 현재 내용 확인. 변경 범위 파악 (설명? 지시사항? 스크립트?)
2. **수정 전 테스트(Observe)**: 스크립트가 있으면 `run_skill_script`로 현재 동작을 확인하고 입력/출력을 기록 (수정 전 베이스라인)
3. **수정(Act)**: `update_skill`로 instructions 수정, `add_skill_script`로 스크립트 수정/추가. "스크립트 필수 지침" 적용
4. **검증(Observe)**: `run_skill_script`로 동일 입력으로 테스트. 수정 전 결과와 비교
5. **반복(Loop)**: 테스트 실패 시 → 에러 분석 → 3단계로 돌아가 재수정. **최대 3회 반복**. 3회 초과 시 사용자에게 보고
6. **회귀 확인**: 수정 대상 외 기존 기능이 정상 동작하는지 다른 입력으로도 테스트
7. **완료**: `read_skill`로 최종 상태 확인 후 사용자에게 변경 내역 보고

## 다중 모듈 설계

복잡한 작업은 단일 거대 스크립트 대신 **여러 모듈로 분리**한다. 각 모듈은 독립 실행·테스트 가능해야 한다.

### 파이프라인 패턴

단계별로 데이터를 변환하는 작업에 적합:

```
my-pipeline-skill/
├── SKILL.md
└── scripts/
    ├── step1_collect.py     # 데이터 수집 → stdout 또는 파일 출력
    ├── step2_process.py     # step1 결과를 입력으로 처리
    └── step3_report.py      # 최종 결과물 생성
```

**SKILL.md에 실행 순서 명시:**
```markdown
## 실행 절차
1. `run_skill_script("my-pipeline", "step1_collect.py", [인자])` → 중간 결과 확인
2. `run_skill_script("my-pipeline", "step2_process.py", [인자])` → 처리 결과 확인
3. `run_skill_script("my-pipeline", "step3_report.py", [인자])` → 최종 결과물
각 단계 실행 후 결과를 검증하고, 문제가 있으면 해당 스크립트만 수정하여 재실행.
```

**설계 원칙:**
- 모듈 간 데이터 전달은 파일 경로(인자) 또는 stdout으로 연결
- 각 모듈에 `--help` 플래그 추가하여 사용법 확인 가능하게 설계
- 문제 발생 시 해당 모듈만 `add_skill_script`로 수정 → 전체를 다시 만들 필요 없음

### 유틸리티 패턴

공통 로직을 공유하는 여러 기능을 하나의 스킬에 모을 때:

```
data-utils/
├── SKILL.md
└── scripts/
    ├── csv_to_json.py
    ├── json_to_csv.py
    └── validate.py
```

## 기존 스킬 개선 및 병합

### 개선 (Improve)

기존 스킬이 70% 이상 요구사항을 충족하면 **새로 만들지 말고 개선**. "기존 스킬 수정"의 ReAct 루프를 따르되, 추가로:

1. `read_skill`로 현재 스킬의 instructions와 scripts 확인
2. 부족한 부분 분석 (기능 추가? 버그 수정? 성능 개선?)
3. **스크립트 수정 시 "스크립트 필수 지침" 적용** — SSL 우회, stderr 에러 출력, 인자 검증 등이 누락된 기존 스크립트는 개선 시 함께 보강
4. `run_skill_script`로 수정 전 베이스라인 기록
5. `update_skill` + `add_skill_script`로 수정
6. `run_skill_script`로 동일 입력 테스트 → 실패 시 분석 후 재수정 (최대 3회)
7. 개선 전·후 결과 비교 (벤치마크)

### 병합 (Merge)

유사한 스킬 2개 이상을 하나로 통합할 때:

1. 대상 스킬들을 `read_skill`로 모두 읽기
2. 공통 로직과 고유 로직 분리
3. 통합 스킬 생성: 공통 로직은 하나로, 고유 기능은 별도 모듈로
4. 원본 스킬의 description을 통합 스킬로 업데이트하여 검색 가능하게

### 참고 활용 (Reference)

기존 스킬이 30% 정도만 관련 있어도 **힌트로 활용**:

1. `read_skill`로 관련 스킬의 코드·패턴 확인
2. 재사용할 수 있는 코드, 라이브러리, 접근 방식 파악
3. 새 스킬 생성 시 검증된 패턴을 차용

## 벤치마크

스킬을 개선할 때는 개선 전·후 결과를 비교:

1. **기존 스크립트 실행** → 결과(출력, 실행 시간, 정확도) 기록
2. **개선된 스크립트 실행** → 동일 조건으로 실행
3. **비교**: 출력 품질, 에러 유무, 실행 시간 등
4. **판단**: 개선이 확인되면 적용, 아니면 롤백

벤치마크는 스크립트가 있는 스킬에서만 적용. 지시사항만 있는 스킬은 실사용 피드백으로 개선.
