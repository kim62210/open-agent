#!/usr/bin/env python3
"""프로젝트 구조를 분석하여 JSON 요약을 출력하는 스크립트.

Usage:
    python3 analyze_project.py <project_root> [--max-depth N]

Output:
    JSON 형식의 프로젝트 분석 결과 (stdout)
"""

import argparse
import json
import os
import sys
from pathlib import Path

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".next", "dist", "build", ".cache", "target",
    ".idea", ".vscode", ".tox", ".mypy_cache", ".pytest_cache",
    "out", "coverage", ".turbo", ".nuxt", ".output",
}

IGNORE_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
}

LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".jsx": "JavaScript (React)",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".vue": "Vue",
    ".svelte": "Svelte",
}

CONFIG_FILES = {
    "package.json": "Node.js",
    "pyproject.toml": "Python (modern)",
    "setup.py": "Python (legacy)",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java (Gradle)",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "tsconfig.json": "TypeScript",
    "next.config.ts": "Next.js",
    "next.config.js": "Next.js",
    "vite.config.ts": "Vite",
    "tailwind.config.ts": "Tailwind CSS",
    "tailwind.config.js": "Tailwind CSS",
}


def scan_directory(root: Path, max_depth: int = 3) -> dict:
    """디렉토리를 스캔하여 트리 구조를 반환."""
    tree = {}
    file_counts: dict[str, int] = {}
    total_files = 0

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1

        if depth > max_depth:
            dirnames.clear()
            continue

        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in IGNORE_DIRS and not d.startswith(".")
        ]

        for f in filenames:
            if f in IGNORE_FILES:
                continue
            ext = Path(f).suffix.lower()
            if ext:
                file_counts[ext] = file_counts.get(ext, 0) + 1
            total_files += 1

        if depth <= 2:
            key = rel_dir if rel_dir != "." else "."
            tree[key] = {
                "dirs": list(dirnames),
                "files": [f for f in sorted(filenames) if f not in IGNORE_FILES][:20],
            }

    return {
        "tree": tree,
        "file_counts": dict(sorted(file_counts.items(), key=lambda x: -x[1])),
        "total_files": total_files,
    }


def detect_stack(root: Path, file_counts: dict[str, int]) -> dict:
    """프로젝트의 기술 스택을 감지."""
    languages = []
    frameworks = []

    for ext, count in sorted(file_counts.items(), key=lambda x: -x[1]):
        if ext in LANGUAGE_MAP and count >= 2:
            languages.append({"language": LANGUAGE_MAP[ext], "files": count})

    for config_file, framework in CONFIG_FILES.items():
        if (root / config_file).exists():
            frameworks.append(framework)

    return {
        "languages": languages[:5],
        "frameworks": frameworks,
    }


def find_key_files(root: Path) -> list[str]:
    """프로젝트의 핵심 파일을 찾음."""
    key_patterns = [
        "README.md", "README.rst",
        "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "Makefile", "Dockerfile", "docker-compose.yml",
        ".env.example", ".env.sample",
        "tsconfig.json",
    ]
    found = []
    for pattern in key_patterns:
        path = root / pattern
        if path.exists():
            found.append(pattern)
    return found


def find_entry_points(root: Path) -> list[str]:
    """진입점 파일을 찾음."""
    candidates = [
        "src/main.py", "src/app.py", "src/index.ts", "src/index.js",
        "main.py", "app.py", "index.ts", "index.js",
        "src/main.rs", "cmd/main.go", "main.go",
        "src/App.tsx", "src/App.jsx",
        "src/app/page.tsx", "src/app/layout.tsx",
        "server.py", "cli.py",
    ]
    found = []
    for candidate in candidates:
        if (root / candidate).exists():
            found.append(candidate)
    return found


def analyze(root: Path, max_depth: int = 3) -> dict:
    """프로젝트를 분석하여 종합 결과를 반환."""
    scan = scan_directory(root, max_depth)
    stack = detect_stack(root, scan["file_counts"])

    return {
        "project_root": str(root.resolve()),
        "stack": stack,
        "key_files": find_key_files(root),
        "entry_points": find_entry_points(root),
        "structure": {
            "total_files": scan["total_files"],
            "file_types": scan["file_counts"],
            "top_level": scan["tree"].get(".", {}),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="프로젝트 구조 분석")
    parser.add_argument("project_root", help="분석할 프로젝트 루트 경로")
    parser.add_argument("--max-depth", type=int, default=3, help="탐색 최대 깊이 (기본: 3)")
    args = parser.parse_args()

    root = Path(args.project_root)
    if not root.is_dir():
        print(f"Error: '{root}' is not a directory", file=sys.stderr)
        sys.exit(1)

    result = analyze(root, args.max_depth)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
