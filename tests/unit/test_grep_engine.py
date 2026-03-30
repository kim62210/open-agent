"""Unit tests for core/grep_engine.py — Python fallback grep engine."""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.grep_engine import _grep_python, grep


# ── _grep_python ──────────────────────────────────────────────────────


class TestGrepPython:
    def test_single_file_match(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("hello world\nfoo bar\nhello again\n")
        result = _grep_python(tmp_path, f, "hello", None, False, 0, 50)
        assert "hello" in result
        assert "2 match(es)" in result

    def test_no_matches(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("foo bar baz\n")
        result = _grep_python(tmp_path, f, "nonexistent", None, False, 0, 50)
        assert "No matches" in result

    def test_case_insensitive(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("Hello World\n")
        result = _grep_python(tmp_path, f, "hello", None, True, 0, 50)
        assert "1 match(es)" in result

    def test_invalid_regex(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("content\n")
        result = _grep_python(tmp_path, f, "[invalid", None, False, 0, 50)
        assert "Invalid regex" in result

    def test_context_lines(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("line1\nline2\ntarget\nline4\nline5\n")
        result = _grep_python(tmp_path, f, "target", None, False, 1, 50)
        assert "line2" in result
        assert "line4" in result
        assert "target" in result

    def test_directory_search(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.py").write_text("match here\n")
        (sub / "b.txt").write_text("no match\n")
        result = _grep_python(tmp_path, tmp_path, "match", None, False, 0, 50)
        assert "match" in result

    def test_glob_filter(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("find me\n")
        (tmp_path / "b.txt").write_text("find me\n")
        result = _grep_python(tmp_path, tmp_path, "find", "*.py", False, 0, 50)
        assert "a.py" in result

    def test_limit_matches(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("\n".join(f"match {i}" for i in range(100)))
        result = _grep_python(tmp_path, f, "match", None, False, 0, 3)
        assert "3 match(es)" in result

    def test_ignored_dirs_skipped(self, tmp_path: Path):
        ignored = tmp_path / "node_modules"
        ignored.mkdir()
        (ignored / "test.py").write_text("find me\n")
        (tmp_path / "main.py").write_text("find me\n")
        result = _grep_python(tmp_path, tmp_path, "find", None, False, 0, 50)
        assert "main.py" in result
        # node_modules should be ignored
        assert "node_modules" not in result

    def test_binary_file_skipped(self, tmp_path: Path):
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\x03")
        result = _grep_python(tmp_path, tmp_path, ".", None, False, 0, 50)
        # Should not crash on binary files
        assert isinstance(result, str)


# ── grep (tiered dispatch) ────────────────────────────────────────────


class TestGrepDispatch:
    def test_falls_back_to_python(self, tmp_path: Path):
        """When Rust and ripgrep are unavailable, falls back to Python."""
        f = tmp_path / "test.py"
        f.write_text("hello python fallback\n")

        with patch("core.grep_engine.shutil.which", return_value=None):
            with patch.dict("sys.modules", {"nexus_rust": None}):
                result = grep(tmp_path, f, "hello", limit=10)
        assert "hello" in result

    def test_ripgrep_timeout(self, tmp_path: Path):
        """Test ripgrep timeout handling."""
        import subprocess

        f = tmp_path / "test.py"
        f.write_text("content\n")

        mock_rg = MagicMock()
        with patch("core.grep_engine.shutil.which", return_value="/usr/bin/rg"):
            with patch.dict("sys.modules", {"nexus_rust": None}):
                with patch("core.grep_engine.subprocess.run", side_effect=subprocess.TimeoutExpired("rg", 30)):
                    result = grep(tmp_path, f, "pattern", limit=10)
        assert "timed out" in result
