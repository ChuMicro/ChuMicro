"""Tests for verify_examples.py — AST-based example verification."""

import ast
import textwrap
from pathlib import Path

from verify_examples import (
    _check_imports,
    _has_hardware_runtime_marker,
    _is_chumicro_module,
    verify_examples,
)


class TestIsChuMicroModule:
    """Tests for _is_chumicro_module."""

    def test_chumicro_module(self):
        """chumicro_ prefix is recognized."""
        assert _is_chumicro_module("chumicro_timing") is True

    def test_chumicro_submodule(self):
        """Nested chumicro import is recognized."""
        assert _is_chumicro_module("chumicro_timing.testing") is True

    def test_non_chumicro_module(self):
        """Standard library module is not chumicro."""
        assert _is_chumicro_module("os") is False

    def test_board_module(self):
        """Hardware module is not chumicro."""
        assert _is_chumicro_module("board") is False

    def test_empty_string(self):
        """Empty string is not chumicro."""
        assert _is_chumicro_module("") is False


class TestHasHardwareRuntimeMarker:
    """Tests for _has_hardware_runtime_marker — AST marker detection."""

    def _parse(self, source: str) -> ast.Module:
        return ast.parse(textwrap.dedent(source))

    def test_marker_with_circuitpython_returns_true(self):
        tree = self._parse('__chumicro_runtimes__ = ("circuitpython",)\n')
        assert _has_hardware_runtime_marker(tree) is True

    def test_marker_with_micropython_returns_true(self):
        tree = self._parse('__chumicro_runtimes__ = ("micropython",)\n')
        assert _has_hardware_runtime_marker(tree) is True

    def test_marker_with_both_returns_true(self):
        tree = self._parse('__chumicro_runtimes__ = ("circuitpython", "micropython")\n')
        assert _has_hardware_runtime_marker(tree) is True

    def test_marker_with_only_cpython_returns_false(self):
        tree = self._parse('__chumicro_runtimes__ = ("cpython",)\n')
        assert _has_hardware_runtime_marker(tree) is False

    def test_no_marker_returns_false(self):
        tree = self._parse("x = 1\n")
        assert _has_hardware_runtime_marker(tree) is False

    def test_marker_as_list_works(self):
        tree = self._parse('__chumicro_runtimes__ = ["circuitpython"]\n')
        assert _has_hardware_runtime_marker(tree) is True


class TestCheckImports:
    """Tests for _check_imports — import resolution checking."""

    def _parse(self, source: str) -> ast.Module:
        """Parse source text into an AST."""
        return ast.parse(textwrap.dedent(source))

    def test_stdlib_import_passes(self):
        """Standard library imports pass verification."""
        tree = self._parse("import sys\nimport os\n")
        assert _check_imports(tree, "test.py", hardware=False) is True

    def test_nonexistent_import_fails(self, capsys):
        """Nonexistent module fails verification."""
        tree = self._parse("import totally_fake_module_xyz\n")
        assert _check_imports(tree, "test.py", hardware=False) is False
        assert "FAIL" in capsys.readouterr().out

    def test_hardware_skips_non_chumicro(self):
        """Hardware mode skips non-chumicro imports like 'board'."""
        tree = self._parse("import board\nimport digitalio\n")
        assert _check_imports(tree, "test.py", hardware=True) is True

    def test_hardware_checks_chumicro_imports(self, capsys):
        """Hardware mode still checks chumicro_* imports."""
        tree = self._parse("import chumicro_nonexistent_fake\n")
        assert _check_imports(tree, "test.py", hardware=True) is False

    def test_from_import_nonexistent_module(self, capsys):
        """from-import of nonexistent module fails."""
        tree = self._parse("from totally_fake_module_xyz import something\n")
        assert _check_imports(tree, "test.py", hardware=False) is False

    def test_from_import_nonexistent_attribute(self, capsys):
        """from-import of nonexistent attribute from a real module fails."""
        tree = self._parse("from os import totally_fake_attribute_xyz\n")
        assert _check_imports(tree, "test.py", hardware=False) is False
        assert "FAIL" in capsys.readouterr().out

    def test_from_import_real_attribute(self):
        """from-import of a real attribute passes."""
        tree = self._parse("from os.path import join\n")
        assert _check_imports(tree, "test.py", hardware=False) is True

    def test_chumicro_import_passes(self):
        """Real chumicro library imports pass."""
        tree = self._parse("import chumicro_timing\n")
        assert _check_imports(tree, "test.py", hardware=False) is True


class TestVerifyExamples:
    """Tests for verify_examples — full example directory verification."""

    def _make_package(self, tmp_path: Path) -> Path:
        """Create a minimal package directory with examples/ and src/."""
        package_dir = tmp_path / "library"
        (package_dir / "examples").mkdir(parents=True)
        (package_dir / "src").mkdir()
        return package_dir

    def test_clean_examples(self, tmp_path: Path, capsys, monkeypatch):
        """Directory with valid examples returns 0."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "good.py").write_text(
            "import os\nprint('hello')\n"
        )
        monkeypatch.setattr("verify_examples.ROOT", tmp_path)

        result = verify_examples([package_dir])
        assert result == 0
        assert "verified" in capsys.readouterr().out

    def test_syntax_error_example(self, tmp_path: Path, capsys, monkeypatch):
        """Example with syntax error is reported as failure."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "bad.py").write_text("def broken(\n")
        monkeypatch.setattr("verify_examples.ROOT", tmp_path)

        result = verify_examples([package_dir])
        assert result == 1
        assert "FAIL" in capsys.readouterr().out

    def test_no_examples_directory(self, tmp_path: Path, capsys):
        """Package without examples/ returns 0."""
        package_dir = tmp_path / "library"
        package_dir.mkdir()

        result = verify_examples([package_dir])
        assert result == 0
        assert "No examples" in capsys.readouterr().out

    def test_hardware_example_prefix(self, tmp_path: Path, capsys, monkeypatch):
        """circuitpython_* examples skip non-chumicro imports."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "circuitpython_blink.py").write_text(
            "import board\nimport digitalio\n"
        )
        monkeypatch.setattr("verify_examples.ROOT", tmp_path)

        result = verify_examples([package_dir])
        assert result == 0
        assert "hardware" in capsys.readouterr().out

    def test_bad_import_example(self, tmp_path: Path, capsys, monkeypatch):
        """Example with unresolvable import is reported as failure."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "bad_import.py").write_text(
            "import totally_fake_nonexistent_module_xyz\n"
        )
        monkeypatch.setattr("verify_examples.ROOT", tmp_path)

        result = verify_examples([package_dir])
        assert result == 1
