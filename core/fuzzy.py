"""Fuzzy text matching and patch application for workspace file editing.

Provides 4-pass fuzzy matching (exact, rstrip, trim, unicode) and
unified diff patch application. Uses Rust acceleration when available,
with a Pure Python fallback for environments without the Rust extension.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Rust acceleration (optional) ──────────────────────────────────────

try:
    from nexus_rust import fuzzy_find as _rust_fuzzy_find
    from nexus_rust import find_closest_match as _rust_find_closest
    from nexus_rust import apply_patch as _rust_apply_patch
    from nexus_rust import apply_patch_to_string as _rust_apply_patch_str

    _HAVE_RUST = True
except ImportError:
    _HAVE_RUST = False


# ── Unicode normalization ─────────────────────────────────────────────

_UNICODE_TABLE = str.maketrans(
    {
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
        "\u2014": "-", "\u2015": "-", "\u2212": "-",
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
        "\u00a0": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ",
        "\u2005": " ", "\u2006": " ", "\u2007": " ", "\u2008": " ",
        "\u2009": " ", "\u200a": " ", "\u202f": " ", "\u205f": " ",
        "\u3000": " ",
    }
)


def _normalize_unicode(s: str) -> str:
    return s.translate(_UNICODE_TABLE)


# ── Fuzzy matching ────────────────────────────────────────────────────


def fuzzy_find(text: str, old_content: str) -> tuple[str | None, int, int]:
    """4-pass fuzzy search. Returns (match_mode, byte_position, matched_byte_length).

    Pass 1: Exact match (C-level str.find, fastest)
    Pass 2: Right-trim (trailing whitespace ignored per line)
    Pass 3: Both-sides trim (indentation differences tolerated)
    Pass 4: Unicode normalization + trim (smart quotes/dashes)

    Returns (None, -1, 0) if no match found.
    """
    # Pass 1: Exact match -- Python's C-level str.find is fastest
    pos = text.find(old_content)
    if pos != -1:
        return ("exact", pos, len(old_content))

    # Fuzzy passes: delegate to Rust when available (11x faster)
    if _HAVE_RUST:
        return _rust_fuzzy_find(text, old_content)

    return _py_fuzzy_find(text, old_content)


def find_closest_match(text: str, old_content: str) -> tuple[int, float, str]:
    """Find the closest matching region for error hints.

    Returns (line_number_1based, similarity_ratio_0to1, snippet_text).
    """
    if _HAVE_RUST:
        return _rust_find_closest(text, old_content)
    return _py_find_closest_match(text, old_content)


# ── Pure Python fallback implementations ──────────────────────────────


def _py_fuzzy_find(text: str, old_content: str) -> tuple[str | None, int, int]:
    """Pure Python 4-pass fuzzy search."""
    # Pass 1 already done in caller

    text_lines = text.splitlines(keepends=True)
    old_lines = old_content.splitlines(keepends=True)
    if not old_lines:
        return (None, -1, 0)

    n = len(old_lines)
    if n > len(text_lines):
        return (None, -1, 0)

    # Build line-stripped variants once
    text_rstrip = [l.rstrip() for l in text_lines]
    old_rstrip = [l.rstrip() for l in old_lines]
    text_strip = [l.strip() for l in text_lines]
    old_strip = [l.strip() for l in old_lines]
    text_norm = [_normalize_unicode(l.strip()) for l in text_lines]
    old_norm = [_normalize_unicode(l.strip()) for l in old_lines]

    for pass_name, t_cmp, o_cmp in [
        ("rstrip", text_rstrip, old_rstrip),
        ("trim", text_strip, old_strip),
        ("unicode", text_norm, old_norm),
    ]:
        for i in range(len(t_cmp) - n + 1):
            if t_cmp[i : i + n] == o_cmp:
                pos = sum(len(l) for l in text_lines[:i])
                matched_len = sum(len(l) for l in text_lines[i : i + n])
                return (pass_name, pos, matched_len)

    return (None, -1, 0)


def _py_find_closest_match(text: str, old_content: str) -> tuple[int, float, str]:
    """Pure Python: find the closest matching region for error hints."""
    text_lines = text.splitlines()
    old_lines = old_content.splitlines()
    if not old_lines or not text_lines:
        return (0, 0.0, "")

    n = len(old_lines)
    best_ratio = 0.0
    best_line = 0
    best_snippet = ""

    for i in range(max(1, len(text_lines) - n + 1)):
        chunk = "\n".join(text_lines[i : i + n])
        ratio = SequenceMatcher(None, old_content, chunk).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_line = i + 1
            best_snippet = chunk

    return (best_line, best_ratio, best_snippet)


# ── Fuzzy replace helper ──────────────────────────────────────────────


def fuzzy_replace(
    text: str,
    old_content: str,
    new_content: str,
    match_mode: str,
) -> str:
    """Replace fuzzy-matched region in text with new_content.

    For exact match, uses str.replace. For fuzzy matches (rstrip/trim/unicode),
    locates the matched line range and replaces it.
    """
    if match_mode == "exact":
        return text.replace(old_content, new_content, 1)

    # For fuzzy matches: find the matched line range and replace
    text_lines = text.splitlines(keepends=True)
    old_lines = old_content.splitlines(keepends=True)
    n = len(old_lines)

    if match_mode == "rstrip":

        def cmp_fn(a: str, b: str) -> bool:
            return a.rstrip() == b.rstrip()
    elif match_mode == "trim":

        def cmp_fn(a: str, b: str) -> bool:
            return a.strip() == b.strip()
    else:  # unicode

        def cmp_fn(a: str, b: str) -> bool:
            return _normalize_unicode(a.strip()) == _normalize_unicode(b.strip())

    for i in range(len(text_lines) - n + 1):
        if all(cmp_fn(text_lines[i + j], old_lines[j]) for j in range(n)):
            # Preserve the new_content's line endings
            new_lines = new_content.splitlines(keepends=True)
            # If new_content doesn't end with newline but last matched line did,
            # add it to maintain file structure
            if new_lines and not new_content.endswith(("\n", "\r\n", "\r")):
                if i + n <= len(text_lines) or text.endswith("\n"):
                    new_lines[-1] = new_lines[-1] + "\n"
            replaced = text_lines[:i] + new_lines + text_lines[i + n :]
            return "".join(replaced)

    # Should not reach here if fuzzy_find succeeded
    raise ValueError("Fuzzy match lost during replace")


# ── Patch application ─────────────────────────────────────────────────


def apply_patch_to_string(content: str, patch_text: str) -> tuple[bool, str, str]:
    """Apply a unified diff patch to a string (in-memory, single file).

    Returns (success, message, new_content_or_empty).
    """
    if _HAVE_RUST:
        return _rust_apply_patch_str(content, patch_text)
    return _py_apply_patch_to_string(content, patch_text)


def apply_patch_to_files(
    patch_text: str,
    base_dir: str,
    path_validator: Optional[Callable[[str], Path]] = None,
) -> str:
    """Apply a unified diff patch to files on disk.

    If path_validator is provided, each file path is validated through it
    (e.g., for workspace security path traversal checks).

    Returns a summary string of results.
    """
    if _HAVE_RUST and path_validator is None:
        results = _rust_apply_patch(patch_text, base_dir)
        lines = [r["message"] for r in results]
        return "\n".join(lines) if lines else "[error] No patches found in input."

    return _py_apply_patch(patch_text, base_dir, path_validator)


# ── Pure Python patch fallback ────────────────────────────────────────


def _py_apply_patch_to_string(content: str, patch_text: str) -> tuple[bool, str, str]:
    """Pure Python in-memory patch application for a single file."""
    patches = _parse_patches(patch_text)
    if not patches:
        return (False, "[error] No patches found in input", "")

    path, hunks = patches[0]
    return _apply_hunks_to_content(content, path, hunks)


def _py_apply_patch(
    patch_text: str,
    base_dir: str,
    path_validator: Optional[Callable[[str], Path]] = None,
) -> str:
    """Pure Python unified diff patch application to disk files."""
    patches = _parse_patches(patch_text)
    if not patches:
        return "[error] No patches found in input."

    base = Path(base_dir)
    results: list[str] = []

    for path, hunks in patches:
        # Security: validate path if validator provided
        if path_validator:
            try:
                full_path = path_validator(path)
            except ValueError as e:
                results.append(f"[error] {path}: {e}")
                continue
        else:
            full_path = base / path

        # Read existing content
        if full_path.exists():
            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception as e:
                results.append(f"[error] Cannot read {path}: {e}")
                continue
        else:
            content = ""

        success, message, new_content = _apply_hunks_to_content(content, path, hunks)
        if success:
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(new_content, encoding="utf-8")
                results.append(message)
            except Exception as e:
                results.append(f"[error] Cannot write {path}: {e}")
        else:
            results.append(message)

    return "\n".join(results) if results else "[error] No patches applied."


def _parse_patches(patch_text: str) -> list[tuple[str, list[dict]]]:
    """Parse unified diff text into [(path, [hunk_dicts])]."""
    patches: list[tuple[str, list[dict]]] = []
    lines = patch_text.splitlines()
    i = 0

    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue

        old_path = lines[i].removeprefix("--- ").removeprefix("a/")
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            break

        new_path = lines[i].removeprefix("+++ ").removeprefix("b/")
        path = new_path if new_path != "/dev/null" else old_path
        i += 1

        hunks: list[dict] = []
        while i < len(lines) and lines[i].startswith("@@ "):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
            if not m:
                i += 1
                continue

            old_start = int(m.group(1))
            i += 1

            hunk_lines: list[tuple[str, str]] = []
            while i < len(lines):
                line = lines[i]
                if line.startswith("@@ ") or line.startswith("--- "):
                    break
                if line.startswith(" "):
                    hunk_lines.append(("context", line[1:]))
                elif line.startswith("-"):
                    hunk_lines.append(("remove", line[1:]))
                elif line.startswith("+"):
                    hunk_lines.append(("add", line[1:]))
                elif line.startswith("\\"):
                    pass  # No newline marker
                else:
                    hunk_lines.append(("context", line))
                i += 1

            hunks.append({"old_start": old_start, "lines": hunk_lines})

        patches.append((path, hunks))

    return patches


def _apply_hunks_to_content(
    content: str, path: str, hunks: list[dict]
) -> tuple[bool, str, str]:
    """Apply parsed hunks to content string. Returns (success, message, new_content)."""
    file_lines = content.splitlines()

    # Apply hunks in reverse order (higher line numbers first)
    sorted_hunks = sorted(hunks, key=lambda h: h["old_start"], reverse=True)

    for hunk in sorted_hunks:
        start_idx = hunk["old_start"] - 1  # 0-indexed
        hunk_lines = hunk["lines"]

        # Verify context
        old_idx = start_idx
        matched = True
        for kind, text in hunk_lines:
            if kind in ("context", "remove"):
                if old_idx < len(file_lines):
                    if file_lines[old_idx].strip() != text.strip():
                        matched = False
                        break
                else:
                    matched = False
                    break
                old_idx += 1

        if not matched:
            return (
                False,
                f"[error] Hunk at line {hunk['old_start']} failed in {path}. Context mismatch.",
                "",
            )

        # Build replacement
        new_lines: list[str] = []
        for kind, text in hunk_lines:
            if kind == "context":
                new_lines.append(text)
            elif kind == "add":
                new_lines.append(text)
            # "remove" lines are skipped

        old_count = sum(1 for k, _ in hunk_lines if k in ("context", "remove"))
        end_idx = min(start_idx + old_count, len(file_lines))
        file_lines[start_idx:end_idx] = new_lines

    new_content = "\n".join(file_lines)
    if content.endswith("\n") and not new_content.endswith("\n"):
        new_content += "\n"

    return (
        True,
        f"[ok] Applied {len(hunks)} hunk(s) to {path}",
        new_content,
    )
