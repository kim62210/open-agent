"""Unit tests for core/fuzzy.py — fuzzy matching and patch application."""

import unittest.mock as mock

from core.fuzzy import (
    _normalize_unicode,
    _py_find_closest_match,
    _py_fuzzy_find,
    apply_patch_to_string,
    find_closest_match,
    fuzzy_find,
    fuzzy_replace,
    _parse_patches,
    _apply_hunks_to_content,
)


# ── _normalize_unicode ────────────────────────────────────────────────


class TestNormalizeUnicode:
    def test_smart_quotes_to_ascii(self):
        assert _normalize_unicode("\u201chello\u201d") == '"hello"'
        assert _normalize_unicode("\u2018world\u2019") == "'world'"

    def test_em_dash_to_hyphen(self):
        assert _normalize_unicode("a\u2014b") == "a-b"

    def test_non_breaking_space(self):
        assert _normalize_unicode("a\u00a0b") == "a b"

    def test_cjk_ideographic_space(self):
        assert _normalize_unicode("a\u3000b") == "a b"

    def test_plain_ascii_unchanged(self):
        assert _normalize_unicode("hello world") == "hello world"

    def test_empty_string(self):
        assert _normalize_unicode("") == ""


# ── fuzzy_find ────────────────────────────────────────────────────────


class TestFuzzyFind:
    def test_exact_match(self):
        text = "line one\nline two\nline three\n"
        mode, pos, length = fuzzy_find(text, "line two\n")
        assert mode == "exact"
        assert pos == text.find("line two\n")
        assert length == len("line two\n")

    def test_exact_match_at_start(self):
        text = "first\nsecond\n"
        mode, pos, length = fuzzy_find(text, "first\n")
        assert mode == "exact"
        assert pos == 0

    def test_no_match_returns_none(self):
        text = "alpha\nbeta\ngamma\n"
        mode, pos, length = fuzzy_find(text, "nonexistent\n")
        assert mode is None
        assert pos == -1
        assert length == 0

    def test_empty_old_content(self):
        """Exact match for empty string succeeds at position 0."""
        text = "anything"
        mode, pos, length = fuzzy_find(text, "")
        assert mode == "exact"
        assert pos == 0
        assert length == 0


# ── _py_fuzzy_find ────────────────────────────────────────────────────


class TestPyFuzzyFind:
    def test_rstrip_match(self):
        text = "hello   \nworld\n"
        old = "hello\nworld\n"
        mode, pos, length = _py_fuzzy_find(text, old)
        assert mode == "rstrip"
        assert pos == 0

    def test_trim_match(self):
        text = "  hello\n  world\n"
        old = "hello\nworld\n"
        mode, pos, length = _py_fuzzy_find(text, old)
        assert mode == "trim"
        assert pos == 0

    def test_unicode_match(self):
        text = '\u201chello\u201d\n'
        old = '"hello"\n'
        mode, pos, length = _py_fuzzy_find(text, old)
        assert mode == "unicode"

    def test_empty_old_lines(self):
        mode, pos, length = _py_fuzzy_find("abc\n", "")
        assert mode is None
        assert pos == -1

    def test_old_lines_longer_than_text(self):
        text = "a\n"
        old = "a\nb\nc\n"
        mode, pos, length = _py_fuzzy_find(text, old)
        assert mode is None
        assert pos == -1

    def test_rstrip_match_in_middle(self):
        text = "first\nhello  \nworld  \nlast\n"
        old = "hello\nworld\n"
        mode, pos, length = _py_fuzzy_find(text, old)
        assert mode == "rstrip"
        assert pos == len("first\n")


# ── _py_find_closest_match ────────────────────────────────────────────


class TestPyFindClosestMatch:
    def test_exact_match_high_ratio(self):
        text = "line one\nline two\nline three"
        line_num, ratio, snippet = _py_find_closest_match(text, "line two")
        assert ratio > 0.5
        assert line_num >= 1

    def test_no_match_empty_text(self):
        line_num, ratio, snippet = _py_find_closest_match("", "search")
        assert line_num == 0
        assert ratio == 0.0
        assert snippet == ""

    def test_no_match_empty_old(self):
        line_num, ratio, snippet = _py_find_closest_match("some text", "")
        assert line_num == 0
        assert ratio == 0.0

    def test_single_line(self):
        text = "hello world"
        line_num, ratio, snippet = _py_find_closest_match(text, "hello world")
        assert ratio == 1.0
        assert line_num == 1

    def test_best_snippet_found(self):
        text = "aaa\nbbb\nccc\nddd"
        line_num, ratio, snippet = _py_find_closest_match(text, "bbb\nccc")
        assert ratio > 0.8
        assert "bbb" in snippet
        assert "ccc" in snippet


# ── find_closest_match (delegates to Rust or Python) ─────────────────


class TestFindClosestMatch:
    def test_fallback_to_python(self):
        text = "hello\nworld\n"
        line_num, ratio, snippet = find_closest_match(text, "world")
        assert ratio > 0.0


# ── fuzzy_replace ─────────────────────────────────────────────────────


class TestFuzzyReplace:
    def test_exact_replace(self):
        text = "aaa\nbbb\nccc\n"
        result = fuzzy_replace(text, "bbb\n", "xxx\n", "exact")
        assert "xxx" in result
        assert "bbb" not in result

    def test_rstrip_replace(self):
        text = "aaa\nbbb  \nccc\n"
        old = "bbb\n"
        result = fuzzy_replace(text, old, "xxx\n", "rstrip")
        assert "xxx" in result

    def test_trim_replace(self):
        text = "  aaa\n  bbb\n  ccc\n"
        old = "bbb\n"
        result = fuzzy_replace(text, old, "xxx\n", "trim")
        assert "xxx" in result

    def test_unicode_replace(self):
        text = 'aaa\n\u201chello\u201d\nccc\n'
        old = '"hello"\n'
        result = fuzzy_replace(text, old, '"world"\n', "unicode")
        assert '"world"' in result

    def test_replace_raises_on_lost_match(self):
        text = "aaa\nbbb\nccc\n"
        old = "zzz\n"
        try:
            fuzzy_replace(text, old, "xxx\n", "trim")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Fuzzy match lost" in str(e)

    def test_exact_replace_first_occurrence_only(self):
        text = "aaa\nbbb\naaa\n"
        result = fuzzy_replace(text, "aaa\n", "xxx\n", "exact")
        assert result.count("xxx") == 1
        assert result.count("aaa") == 1

    def test_replace_preserves_newline(self):
        text = "first\nsecond\nthird\n"
        old = "second\n"
        result = fuzzy_replace(text, old, "replaced", "trim")
        assert "replaced" in result


# ── _parse_patches ────────────────────────────────────────────────────


class TestParsePatch:
    def test_simple_patch(self):
        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_modified\n"
            " line3\n"
        )
        patches = _parse_patches(patch)
        assert len(patches) == 1
        path, hunks = patches[0]
        assert path == "file.py"
        assert len(hunks) == 1
        assert hunks[0]["old_start"] == 1

    def test_no_patches(self):
        patches = _parse_patches("no patch content here")
        assert patches == []

    def test_dev_null_old_path(self):
        patch = (
            "--- /dev/null\n"
            "+++ b/newfile.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+new line\n"
        )
        patches = _parse_patches(patch)
        assert len(patches) == 1
        path, hunks = patches[0]
        assert path == "newfile.py"

    def test_backslash_no_newline_marker(self):
        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
        )
        patches = _parse_patches(patch)
        assert len(patches) == 1
        _, hunks = patches[0]
        assert len(hunks) == 1
        lines = hunks[0]["lines"]
        assert ("remove", "old") in lines
        assert ("add", "new") in lines


# ── _apply_hunks_to_content ──────────────────────────────────────────


class TestApplyHunksToContent:
    def test_simple_replacement(self):
        content = "line1\nline2\nline3\n"
        hunks = [
            {
                "old_start": 2,
                "lines": [("remove", "line2"), ("add", "line2_modified")],
            }
        ]
        success, msg, new_content = _apply_hunks_to_content(content, "test.py", hunks)
        assert success is True
        assert "line2_modified" in new_content
        assert "1 hunk(s)" in msg

    def test_context_mismatch_fails(self):
        content = "line1\nline2\nline3\n"
        hunks = [
            {
                "old_start": 2,
                "lines": [("context", "wrong_context"), ("add", "new")],
            }
        ]
        success, msg, new_content = _apply_hunks_to_content(content, "test.py", hunks)
        assert success is False
        assert "Context mismatch" in msg

    def test_preserves_trailing_newline(self):
        content = "line1\nline2\n"
        hunks = [
            {
                "old_start": 1,
                "lines": [("context", "line1"), ("remove", "line2"), ("add", "line2_new")],
            }
        ]
        success, msg, new_content = _apply_hunks_to_content(content, "test.py", hunks)
        assert success is True
        assert new_content.endswith("\n")

    def test_multiple_hunks_reverse_order(self):
        content = "a\nb\nc\nd\n"
        hunks = [
            {
                "old_start": 2,
                "lines": [("remove", "b"), ("add", "B")],
            },
            {
                "old_start": 4,
                "lines": [("remove", "d"), ("add", "D")],
            },
        ]
        success, msg, new_content = _apply_hunks_to_content(content, "test.py", hunks)
        assert success is True
        assert "B" in new_content
        assert "D" in new_content
        assert "2 hunk(s)" in msg


# ── apply_patch_to_string (integration) ──────────────────────────────


class TestApplyPatchToString:
    def test_simple_patch(self):
        content = "line1\nline2\nline3\n"
        patch = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -2,1 +2,1 @@\n"
            "-line2\n"
            "+line2_patched\n"
        )
        success, msg, new_content = apply_patch_to_string(content, patch)
        assert success is True
        assert "line2_patched" in new_content

    def test_no_patches_returns_error(self):
        success, msg, new_content = apply_patch_to_string("content", "no patch")
        assert success is False
        assert "No patches" in msg
