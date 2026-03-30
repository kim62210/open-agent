# Script Boilerplate

Standard patterns to use when writing skill scripts.

## HTTP Request Script (Most Common)

```python
#!/usr/bin/env python3
"""Skill name -- Script description."""
import sys
import ssl
import json
import urllib.parse
import urllib.request

# SSL certificate verification bypass (required for corporate proxy/self-signed cert environments)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch_json(url: str):
    """Fetch JSON response from URL. Returns None + stderr output on failure."""
    try:
        with urllib.request.urlopen(url, timeout=15, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def fetch_text(url: str) -> str | None:
    """Fetch text response from URL."""
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

    # API call
    enc = urllib.parse.quote(query)
    data = fetch_json(f"https://api.example.com/search?q={enc}")
    if not data:
        print(f"Failed to query '{query}'.")
        sys.exit(1)

    # Output results (concise, in a format parseable by LLM)
    print(f"Results: {len(data.get('items', []))} items")
    for item in data.get("items", [])[:20]:  # Limit to 20 items
        print(f"  - {item.get('title', '?')}: {item.get('value', '?')}")


if __name__ == "__main__":
    main()
```

## Core Rules Checklist

| Rule | Required Code |
|------|--------------|
| SSL bypass | `_SSL_CTX = ssl.create_default_context()` + `CERT_NONE` |
| Timeout | `urlopen(url, timeout=15, context=_SSL_CTX)` |
| Error output | `print(f"[ERROR] ...", file=sys.stderr)` |
| Argument validation | `if len(sys.argv) < 2: print("Usage: ..."); sys.exit(1)` |
| Failure exit | `sys.exit(1)` |
| Encoding | `decode("utf-8")`, `encoding="utf-8"` for file I/O |
| Output limit | Limit results to 20 items or fewer, summarize large data |

## File Processing Script

```python
#!/usr/bin/env python3
"""File conversion/processing boilerplate."""
import sys
import json
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: script.py <input_file_absolute_path>", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"[ERROR] File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Read file (force UTF-8)
    text = input_path.read_text(encoding="utf-8", errors="replace")

    # Processing logic
    result = text.upper()  # Example

    # Output result or write to file
    output_path = input_path.with_suffix(".out.txt")
    output_path.write_text(result, encoding="utf-8")
    print(f"Processing complete: {output_path}")


if __name__ == "__main__":
    main()
```

## Execution Environment Constraints

- **cwd**: Skill directory (`~/.open-agent/skills/<skill-name>/`)
- **Timeout**: 60 seconds (force-killed with SIGKILL if exceeded)
- **Libraries**: Only Python standard library available (pip install not possible)
- **Environment variables**: Sensitive variables like API keys are automatically removed
- **Output limits**: stdout ~100K chars, stderr ~5K chars truncated
- **Encoding**: UTF-8 is default on macOS/Linux, but always specify explicitly

## Output Format Guide

**When the LLM needs to parse the result**: JSON output
```python
print(json.dumps({"status": "ok", "count": 5, "items": [...]}, ensure_ascii=False))
```

**When displaying directly to the user**: Table/summary format
```python
print(f"{'Time':>5}  {'Weather':<10} {'Temp':>6}")
print("-" * 25)
for item in data:
    print(f"{item['time']:>5}  {item['desc']:<10} {item['temp']:>5}C")
```

**Always**: Limit large results to top N items to prevent truncation
