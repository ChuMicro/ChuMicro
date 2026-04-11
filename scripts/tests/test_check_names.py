"""Tests for check_names.py — CHU001 naming rule enforcement."""

import ast
import textwrap
from pathlib import Path

from check_names import _collect_names, _read_noqa_lines, check_file, check_paths, main


class TestReadNoqaLines:
    """Tests for _read_noqa_lines."""

    def test_no_suppressions(self):
        """File with no noqa comments returns empty set."""
        source = "x = 1\ny = 2\n"
        assert _read_noqa_lines(source) == set()

    def test_specific_suppression(self):
        """# noqa: CHU001 suppresses the specific line."""
        source = "x = 1  # noqa: CHU001\ny = 2\n"
        assert _read_noqa_lines(source) == {1}

    def test_bare_noqa(self):
        """Bare # noqa suppresses the line (covers all rules)."""
        source = "x = 1  # noqa\ny = 2\n"
        assert _read_noqa_lines(source) == {1}

    def test_multiple_suppressions(self):
        """Multiple suppressed lines are all captured."""
        source = "x = 1  # noqa: CHU001\ny = 2\nz = 3  # noqa: CHU001\n"
        assert _read_noqa_lines(source) == {1, 3}

    def test_other_noqa_code_not_matched(self):
        """# noqa: E501 does not suppress CHU001."""
        source = "x = 1  # noqa: E501\n"
        assert _read_noqa_lines(source) == set()

    def test_noqa_with_multiple_codes(self):
        """# noqa: E501,CHU001 suppresses the line."""
        source = "x = 1  # noqa: E501,CHU001\n"
        assert _read_noqa_lines(source) == {1}


class TestCollectNames:
    """Tests for _collect_names — AST-based name collection."""

    def _parse(self, source: str) -> ast.Module:
        """Parse source text into an AST."""
        return ast.parse(textwrap.dedent(source))

    def test_single_letter_variable(self):
        """Single-letter assignment is flagged."""
        tree = self._parse("x = 1\n")
        hits = _collect_names(tree)
        names = [name for _, name, _ in hits]
        assert "x" in names

    def test_underscore_is_allowed(self):
        """The _ variable is not flagged."""
        tree = self._parse("_ = 1\n")
        hits = _collect_names(tree)
        names = [name for _, name, _ in hits]
        assert "_" not in names

    def test_banned_abbreviation(self):
        """Banned abbreviation 'msg' is flagged."""
        tree = self._parse("msg = 'hello'\n")
        hits = _collect_names(tree)
        names = [name for _, name, _ in hits]
        assert "msg" in names

    def test_banned_abbreviation_as_suffix(self):
        """Variable ending with banned suffix '_buf' is flagged."""
        tree = self._parse("data_buf = bytearray(10)\n")
        hits = _collect_names(tree)
        names = [name for _, name, _ in hits]
        assert "data_buf" in names

    def test_clean_code(self):
        """Descriptive names produce no flags."""
        tree = self._parse("message = 'hello'\nindex = 0\n")
        hits = _collect_names(tree)
        assert hits == []

    def test_function_parameter(self):
        """Single-letter function parameter is flagged."""
        tree = self._parse("def foo(x):\n    pass\n")
        hits = _collect_names(tree)
        names = [name for _, name, _ in hits]
        assert "x" in names

    def test_except_handler_name(self):
        """Single-letter exception name is flagged."""
        tree = self._parse("try:\n    pass\nexcept Exception as e:\n    pass\n")
        hits = _collect_names(tree)
        names = [name for _, name, _ in hits]
        assert "e" in names

    def test_all_banned_abbreviations(self):
        """All banned abbreviations are caught."""
        banned = ["env", "buf", "src", "cmd", "msg", "err", "ref", "addr", "exc", "exec"]
        source = "\n".join(f"{name} = None" for name in banned) + "\n"
        tree = self._parse(source)
        hits = _collect_names(tree)
        flagged = {name for _, name, _ in hits}
        assert flagged == set(banned)

    def test_function_name_single_letter(self):
        """Single-letter function name is flagged."""
        tree = self._parse("def f():\n    pass\n")
        hits = _collect_names(tree)
        names = [name for _, name, _ in hits]
        assert "f" in names


class TestCheckFile:
    """Tests for check_file — full file checking with noqa support."""

    def test_clean_file(self, tmp_path: Path):
        """File with descriptive names produces no errors."""
        source = 'message = "hello"\nindex = 0\n'
        filepath = tmp_path / "clean.py"
        filepath.write_text(source)
        errors = check_file(filepath, source)
        assert errors == []

    def test_violation_detected(self, tmp_path: Path):
        """File with single-letter name produces an error."""
        source = "x = 1\n"
        filepath = tmp_path / "bad.py"
        filepath.write_text(source)
        errors = check_file(filepath, source)
        assert len(errors) == 1
        assert "CHU001" in errors[0]
        assert "'x'" in errors[0]

    def test_suppressed_violation(self, tmp_path: Path):
        """Suppressed violation produces no error."""
        source = "x = 1  # noqa: CHU001\n"
        filepath = tmp_path / "suppressed.py"
        filepath.write_text(source)
        errors = check_file(filepath, source)
        assert errors == []

    def test_syntax_error_is_skipped(self, tmp_path: Path):
        """Files with syntax errors produce no errors (don't crash)."""
        source = "def broken(\n"
        filepath = tmp_path / "broken.py"
        filepath.write_text(source)
        errors = check_file(filepath, source)
        assert errors == []

    def test_multiple_violations(self, tmp_path: Path):
        """Multiple violations in one file are all reported."""
        source = "x = 1\ny = 2\nmsg = 'hi'\n"
        filepath = tmp_path / "multi.py"
        filepath.write_text(source)
        errors = check_file(filepath, source)
        assert len(errors) == 3

    def test_reads_source_from_file(self, tmp_path: Path):
        """check_file reads source from disk when source is None."""
        filepath = tmp_path / "auto_read.py"
        filepath.write_text("x = 1\n")
        errors = check_file(filepath)
        assert len(errors) == 1
        assert "CHU001" in errors[0]


class TestCheckPaths:
    """Tests for check_paths — directory and file scanning."""

    def test_clean_directory(self, tmp_path: Path):
        """Directory with clean files returns 0."""
        (tmp_path / "good.py").write_text("message = 'hello'\n")
        assert check_paths([str(tmp_path)]) == 0

    def test_directory_with_violations(self, tmp_path: Path, capsys):
        """Directory with violations returns 1 and prints errors."""
        (tmp_path / "bad.py").write_text("x = 1\n")
        assert check_paths([str(tmp_path)]) == 1
        captured = capsys.readouterr().out
        assert "CHU001" in captured
        assert "naming violation" in captured

    def test_single_file(self, tmp_path: Path):
        """Can check a single .py file directly."""
        filepath = tmp_path / "single.py"
        filepath.write_text("message = 'ok'\n")
        assert check_paths([str(filepath)]) == 0

    def test_skips_pycache(self, tmp_path: Path):
        """__pycache__ directories are skipped."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "bad.py").write_text("x = 1\n")
        assert check_paths([str(tmp_path)]) == 0

    def test_skips_site_directory(self, tmp_path: Path):
        """site/ directories are skipped."""
        site_dir = tmp_path / "site"
        site_dir.mkdir()
        (site_dir / "bad.py").write_text("x = 1\n")
        assert check_paths([str(tmp_path)]) == 0

    def test_non_python_files_ignored(self, tmp_path: Path):
        """Non-.py files are ignored."""
        (tmp_path / "readme.md").write_text("x = 1\n")
        assert check_paths([str(tmp_path)]) == 0


class TestMain:
    """Tests for the main entry point."""

    def test_default_paths(self, monkeypatch):
        """main() with no args uses discover_ruff_paths."""
        # Just verify it runs without error — the real workspace is clean.
        result = main()
        assert result == 0

    def test_custom_paths(self, tmp_path: Path):
        """main() with explicit paths checks those paths."""
        (tmp_path / "clean.py").write_text("value = 42\n")
        result = main([str(tmp_path)])
        assert result == 0
