#!/usr/bin/env python3
"""Task verification script -- runs lint and tests, then reports results.

Usage:
    python verify_task.py <project_root> [--files file1 file2 ...]

Output:
    JSON-formatted verification result (stdout)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_IS_WIN = sys.platform == "win32"
_PYTHON = sys.executable  # Current interpreter (cross-platform)


def _node_bin(root: Path, name: str) -> str | None:
    """Return executable path from node_modules/.bin (Windows: .cmd first)."""
    bin_dir = root / "node_modules" / ".bin"
    if _IS_WIN:
        cmd_path = bin_dir / f"{name}.cmd"
        if cmd_path.exists():
            return str(cmd_path)
    else:
        path = bin_dir / name
        if path.exists():
            return str(path)
    return None


def run_command(cmd: list[str], cwd: str, timeout: int = 60) -> dict:
    """Execute a command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "command": " ".join(cmd),
            "exit_code": result.returncode,
            "stdout": result.stdout[:5000] if result.stdout else "",
            "stderr": result.stderr[:2000] if result.stderr else "",
            "passed": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "passed": False,
        }
    except FileNotFoundError:
        return {
            "command": " ".join(cmd),
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command not found: {cmd[0]}",
            "passed": False,
        }


def detect_and_run_linters(root: Path, files: list[str] | None = None) -> list[dict]:
    """Detect and run available linters."""
    results = []
    root_str = str(root)

    # Python
    if (root / "pyproject.toml").exists() or next(root.glob("*.py"), None):
        # ruff
        if _command_exists("ruff"):
            target = files if files else ["."]
            results.append(run_command(["ruff", "check"] + target, root_str))

    # JavaScript/TypeScript -- ESLint
    if (root / "package.json").exists():
        eslint = _node_bin(root, "eslint")
        if eslint:
            target = files if files else ["."]
            results.append(run_command(
                [eslint, "--no-error-on-unmatched-pattern"] + target,
                root_str,
            ))

    # TypeScript type check
    tsc = _node_bin(root, "tsc")
    if (root / "tsconfig.json").exists() and tsc:
        results.append(run_command(
            [tsc, "--noEmit", "--pretty"],
            root_str,
            timeout=120,
        ))

    return results


def detect_and_run_tests(root: Path) -> list[dict]:
    """Detect and run available test frameworks."""
    results = []
    root_str = str(root)

    # Python pytest
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        if _command_exists("pytest"):
            results.append(run_command(
                [_PYTHON, "-m", "pytest", "--tb=short", "-q", "--no-header"],
                root_str,
                timeout=120,
            ))

    # Node.js test
    if (root / "package.json").exists():
        try:
            with open(root / "package.json") as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts", {})
            if "test" in scripts and scripts["test"] != 'echo "Error: no test specified" && exit 1':
                # Detect package manager
                if (root / "pnpm-lock.yaml").exists():
                    pm = "pnpm"
                elif (root / "yarn.lock").exists():
                    pm = "yarn"
                else:
                    pm = "npm"
                results.append(run_command([pm, "test"], root_str, timeout=120))
        except (json.JSONDecodeError, OSError):
            pass

    return results


def check_syntax(root: Path, files: list[str]) -> list[dict]:
    """Per-file syntax check."""
    results = []
    for f in files:
        filepath = Path(f) if os.path.isabs(f) else root / f
        if not filepath.exists():
            continue

        ext = filepath.suffix.lower()
        if ext == ".py":
            results.append(run_command(
                [_PYTHON, "-c", "import ast,sys; ast.parse(open(sys.argv[1]).read())", str(filepath)],
                str(root),
            ))
        elif ext in {".ts", ".tsx"}:
            tsc = _node_bin(root, "tsc")
            if tsc:
                results.append(run_command(
                    [tsc, "--noEmit", "--pretty", str(filepath)],
                    str(root),
                ))

    return results


def _command_exists(cmd: str) -> bool:
    """Check if a command exists (cross-platform)."""
    return shutil.which(cmd) is not None


def verify(root: Path, files: list[str] | None = None) -> dict:
    """Run full verification."""
    all_results = []

    # 1. Syntax check (when specific files are specified)
    if files:
        syntax_results = check_syntax(root, files)
        all_results.extend(syntax_results)

    # 2. Run linters
    lint_results = detect_and_run_linters(root, files)
    all_results.extend(lint_results)

    # 3. Run tests
    test_results = detect_and_run_tests(root)
    all_results.extend(test_results)

    passed = all(r["passed"] for r in all_results) if all_results else True
    failed = [r for r in all_results if not r["passed"]]

    return {
        "overall": "PASS" if passed else "FAIL",
        "total_checks": len(all_results),
        "passed_checks": len(all_results) - len(failed),
        "failed_checks": len(failed),
        "results": all_results,
        "failures": failed,
    }


def main():
    parser = argparse.ArgumentParser(description="Task verification (lint + test)")
    parser.add_argument("project_root", help="Project root path")
    parser.add_argument("--files", nargs="*", help="Specific files to verify")
    args = parser.parse_args()

    root = Path(args.project_root)
    if not root.is_dir():
        print(f"Error: '{root}' is not a directory", file=sys.stderr)
        sys.exit(1)

    result = verify(root, args.files)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # Always exit(0): prevent JSON result from being lost by skill_manager
    sys.exit(0)


if __name__ == "__main__":
    main()
