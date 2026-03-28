# 스크립트 보일러플레이트

스킬 스크립트 작성 시 사용할 표준 패턴.

## HTTP 요청 스크립트 (가장 일반적)

```python
#!/usr/bin/env python3
"""스킬명 — 스크립트 설명."""
import sys
import ssl
import json
import urllib.parse
import urllib.request

# SSL 인증서 검증 우회 (기업 프록시/자체 서명 인증서 환경 필수)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch_json(url: str):
    """URL에서 JSON 응답을 가져옵니다. 실패 시 None + stderr 출력."""
    try:
        with urllib.request.urlopen(url, timeout=15, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def fetch_text(url: str) -> str | None:
    """URL에서 텍스트 응답을 가져옵니다."""
    try:
        with urllib.request.urlopen(url, timeout=15, context=_SSL_CTX) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: script.py <arg1> [arg2]", file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1]

    # API 호출
    enc = urllib.parse.quote(query)
    data = fetch_json(f"https://api.example.com/search?q={enc}")
    if not data:
        print(f"'{query}' 조회에 실패했습니다.")
        sys.exit(1)

    # 결과 출력 (간결하게, LLM이 파싱 가능한 형태)
    print(f"결과: {len(data.get('items', []))}건")
    for item in data.get("items", [])[:20]:  # 20건으로 제한
        print(f"  - {item.get('title', '?')}: {item.get('value', '?')}")


if __name__ == "__main__":
    main()
```

## 핵심 규칙 체크리스트

| 규칙 | 필수 코드 |
|------|-----------|
| SSL 우회 | `_SSL_CTX = ssl.create_default_context()` + `CERT_NONE` |
| 타임아웃 | `urlopen(url, timeout=15, context=_SSL_CTX)` |
| 에러 출력 | `print(f"[ERROR] ...", file=sys.stderr)` |
| 인자 검증 | `if len(sys.argv) < 2: print("Usage: ..."); sys.exit(1)` |
| 실패 종료 | `sys.exit(1)` |
| 인코딩 | `decode("utf-8")`, 파일 I/O 시 `encoding="utf-8"` |
| 출력 제한 | 결과를 20건 이하로 제한, 큰 데이터는 요약 |

## 파일 처리 스크립트

```python
#!/usr/bin/env python3
"""파일 변환/처리 보일러플레이트."""
import sys
import json
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: script.py <input_file_absolute_path>", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"[ERROR] 파일을 찾을 수 없습니다: {input_path}", file=sys.stderr)
        sys.exit(1)

    # 파일 읽기 (UTF-8 강제)
    text = input_path.read_text(encoding="utf-8", errors="replace")

    # 처리 로직
    result = text.upper()  # 예시

    # 결과 출력 또는 파일 쓰기
    output_path = input_path.with_suffix(".out.txt")
    output_path.write_text(result, encoding="utf-8")
    print(f"처리 완료: {output_path}")


if __name__ == "__main__":
    main()
```

## 실행 환경 제약 사항

- **cwd**: 스킬 디렉토리 (`~/.open-agent/skills/<skill-name>/`)
- **타임아웃**: 60초 (초과 시 SIGKILL로 강제 종료)
- **라이브러리**: Python 표준 라이브러리만 사용 가능 (pip 설치 불가)
- **환경변수**: API 키 등 민감 변수는 자동 제거됨
- **출력 제한**: stdout ~100K자, stderr ~5K자에서 절삭
- **인코딩**: macOS/Linux에서 UTF-8이 기본이지만, 명시적으로 지정할 것

## 출력 포맷 가이드

**LLM이 결과를 파싱해야 하는 경우**: JSON 출력
```python
print(json.dumps({"status": "ok", "count": 5, "items": [...]}, ensure_ascii=False))
```

**사용자에게 직접 보여줄 경우**: 테이블/요약 형식
```python
print(f"{'시간':>5}  {'날씨':<10} {'기온':>6}")
print("-" * 25)
for item in data:
    print(f"{item['time']:>5}  {item['desc']:<10} {item['temp']:>5}°C")
```

**항상**: 큰 결과는 상위 N건으로 제한하여 절삭 방지
