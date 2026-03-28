"""Shared grep engine — 3-tier search (Rust → ripgrep → Python).

Used by unified tools for both workspace and page contexts.
"""

import fnmatch
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from open_agent.core.workspace_manager import IGNORED_DIRS, IGNORED_FILES

logger = logging.getLogger(__name__)

IGNORED_DIRS_LOWER = {d.lower() for d in IGNORED_DIRS}


def grep(
    root: Path,
    target: Path,
    pattern: str,
    glob_filter: Optional[str] = None,
    case_insensitive: bool = False,
    context_lines: int = 0,
    limit: int = 50,
) -> str:
    """3-tier grep: Rust native → ripgrep subprocess → Python fallback.

    Args:
        root: Root directory (for relative path computation).
        target: Search target (file or directory).
        pattern: Regex pattern.
        glob_filter: File filter (e.g. "*.py").
        case_insensitive: Case-insensitive search.
        context_lines: Lines before/after match.
        limit: Max matches.
    """
    # Tier 1: Native Rust grep
    try:
        import nexus_rust
        logger.debug("grep: using native Rust backend")
        return _grep_rust(
            nexus_rust, root, target, pattern, glob_filter,
            case_insensitive, context_lines, limit,
        )
    except ImportError:
        pass
    except Exception as e:
        logger.warning("grep: Rust grep failed (%s), falling back", e)

    # Tier 2: ripgrep subprocess
    rg_path = shutil.which("rg")
    if rg_path:
        logger.debug("grep: using ripgrep subprocess backend")
        return _grep_rg(
            rg_path, root, target, pattern, glob_filter,
            case_insensitive, context_lines, limit,
        )

    # Tier 3: Pure Python fallback
    logger.debug("grep: using Python re backend")
    return _grep_python(
        root, target, pattern, glob_filter,
        case_insensitive, context_lines, limit,
    )


def _grep_rust(
    nexus_rust: Any, root: Path, target: Path, pattern: str,
    glob_filter: Optional[str], case_insensitive: bool,
    context_lines: int, limit: int,
) -> str:
    """Native Rust grep via nexus_rust module."""
    matches = nexus_rust.rust_grep(
        pattern, str(target), glob_filter,
        context_lines, limit, case_insensitive,
    )

    if not matches:
        return f"No matches for pattern '{pattern}'"

    lines: List[str] = []
    root_str = str(root)
    prev_path = None

    for m in matches:
        rel_path = m["path"]
        if rel_path.startswith(root_str):
            rel_path = rel_path[len(root_str):].lstrip("/")

        if context_lines > 0:
            if prev_path is not None and prev_path != rel_path:
                lines.append("--")
            elif prev_path == rel_path and lines:
                lines.append("--")

            for ctx_line in m["context_before"]:
                lines.append(f"{rel_path}-{ctx_line}")
            lines.append(f"{rel_path}:{m['line_number']}:{m['line_content']}")
            for ctx_line in m["context_after"]:
                lines.append(f"{rel_path}-{ctx_line}")
        else:
            lines.append(f"{rel_path}:{m['line_number']}:{m['line_content']}")

        prev_path = rel_path

    header = f"Found {min(len(matches), limit)} match(es) for '{pattern}':\n"
    output = "\n".join(lines)
    if len(output) > 30000:
        output = output[:30000] + "\n... (output truncated)"
    return header + output


def _grep_rg(
    rg_path: str, root: Path, target: Path, pattern: str,
    glob_filter: Optional[str], case_insensitive: bool,
    context_lines: int, limit: int,
) -> str:
    """ripgrep subprocess-based grep."""
    from open_agent.core.workspace_tools import get_sanitized_env

    cmd = [rg_path, "--no-heading", "--line-number", "--color=never"]
    if case_insensitive:
        cmd.append("-i")
    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])
    if glob_filter:
        cmd.extend(["--glob", glob_filter])
    for d in IGNORED_DIRS:
        cmd.extend(["--glob", f"!{d}/"])
    cmd.extend(["--max-count", str(limit)])
    cmd.append(pattern)
    cmd.append(str(target))

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=30, cwd=str(root),
            env=get_sanitized_env(),
        )
    except subprocess.TimeoutExpired:
        return "Error: grep timed out after 30s"
    except Exception as e:
        return f"Error: ripgrep failed: {e}"

    if proc.returncode == 1:
        return f"No matches for pattern '{pattern}'"
    if proc.returncode > 1:
        return f"Error: ripgrep error: {proc.stderr[:500]}"

    output = proc.stdout
    if len(output) > 30000:
        output = output[:30000] + "\n... (output truncated)"

    root_str = str(root) + "/"
    output = output.replace(root_str, "")

    match_count = sum(1 for line in output.splitlines() if line and not line.startswith("--"))
    header = f"Found {min(match_count, limit)} match(es) for '{pattern}':\n"
    return header + output


def _grep_python(
    root: Path, target: Path, pattern: str,
    glob_filter: Optional[str], case_insensitive: bool,
    context_lines: int, limit: int,
) -> str:
    """Pure Python regex grep fallback."""
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    results: List[str] = []
    match_count = 0

    if target.is_file():
        files = [target]
    else:
        files_iter = target.rglob("*") if not glob_filter else target.rglob(glob_filter)
        files = []
        for f in files_iter:
            if not f.is_file():
                continue
            try:
                rel = f.relative_to(root)
            except ValueError:
                rel = f.relative_to(target) if target != root else f
            if any(part.lower() in IGNORED_DIRS_LOWER for part in rel.parts):
                continue
            if f.name in IGNORED_FILES:
                continue
            files.append(f)

    for file_path in sorted(files):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        file_lines = content.split("\n")
        file_matches: List[str] = []

        for i, line in enumerate(file_lines):
            if regex.search(line):
                try:
                    rel = file_path.relative_to(root).as_posix()
                except ValueError:
                    rel = file_path.name
                start = max(0, i - context_lines)
                end = min(len(file_lines), i + context_lines + 1)
                for j in range(start, end):
                    marker = ">" if j == i else " "
                    file_matches.append(f"  {marker} {j + 1:>4}\t{file_lines[j]}")
                match_count += 1
                if match_count >= limit:
                    break

        if file_matches:
            try:
                rel = file_path.relative_to(root).as_posix()
            except ValueError:
                rel = file_path.name
            results.append(f"\n{rel}:")
            results.extend(file_matches)

        if match_count >= limit:
            break

    if not results:
        return f"No matches for pattern '{pattern}'"
    header = f"Found {match_count} match(es) for '{pattern}':"
    return header + "\n".join(results)
