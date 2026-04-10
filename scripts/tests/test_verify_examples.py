"""Tests for verify_examples.py — AST-based example verification."""

import ast
import textwrap

from verify_examples import _check_imports, _is_chumicro_module


class TestIsChumicroModule:
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

