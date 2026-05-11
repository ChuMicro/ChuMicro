"""Tests for chumicro_workspace.example_verify — AST-based example verification."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest
from chumicro_workspace import verify_examples
from chumicro_workspace.example_verify import (
    _check_imports,
    _has_hardware_runtime_marker,
    _is_chumicro_module,
)


class TestIsChuMicroModule:
    """Tests for _is_chumicro_module."""

    def test_chumicro_module(self) -> None:
        assert _is_chumicro_module("chumicro_timing") is True

    def test_chumicro_submodule(self) -> None:
        assert _is_chumicro_module("chumicro_timing.testing") is True

    def test_non_chumicro_module(self) -> None:
        assert _is_chumicro_module("os") is False

    def test_board_module(self) -> None:
        assert _is_chumicro_module("board") is False

    def test_empty_string(self) -> None:
        assert _is_chumicro_module("") is False


class TestHasHardwareRuntimeMarker:
    """Tests for _has_hardware_runtime_marker — AST marker detection."""

    def _parse(self, source: str) -> ast.Module:
        return ast.parse(textwrap.dedent(source))

    def test_marker_with_circuitpython_returns_true(self) -> None:
        tree = self._parse('__chumicro_runtimes__ = ("circuitpython",)\n')
        assert _has_hardware_runtime_marker(tree) is True

    def test_marker_with_micropython_returns_true(self) -> None:
        tree = self._parse('__chumicro_runtimes__ = ("micropython",)\n')
        assert _has_hardware_runtime_marker(tree) is True

    def test_marker_with_both_returns_true(self) -> None:
        tree = self._parse(
            '__chumicro_runtimes__ = ("circuitpython", "micropython")\n',
        )
        assert _has_hardware_runtime_marker(tree) is True

    def test_marker_with_only_cpython_returns_false(self) -> None:
        tree = self._parse('__chumicro_runtimes__ = ("cpython",)\n')
        assert _has_hardware_runtime_marker(tree) is False

    def test_no_marker_returns_false(self) -> None:
        tree = self._parse("x = 1\n")
        assert _has_hardware_runtime_marker(tree) is False

    def test_marker_as_list_works(self) -> None:
        tree = self._parse('__chumicro_runtimes__ = ["circuitpython"]\n')
        assert _has_hardware_runtime_marker(tree) is True


class TestCheckImports:
    """Tests for _check_imports — import resolution checking."""

    def _parse(self, source: str) -> ast.Module:
        return ast.parse(textwrap.dedent(source))

    def test_stdlib_import_passes(self) -> None:
        tree = self._parse("import sys\nimport os\n")
        assert _check_imports(tree, "test.py", hardware=False) is True

    def test_nonexistent_import_fails(self, capsys: pytest.CaptureFixture) -> None:
        tree = self._parse("import totally_fake_module_xyz\n")
        assert _check_imports(tree, "test.py", hardware=False) is False
        assert "FAIL" in capsys.readouterr().out

    def test_hardware_skips_non_chumicro(self) -> None:
        """Hardware mode skips non-chumicro imports like 'board'."""
        tree = self._parse("import board\nimport digitalio\n")
        assert _check_imports(tree, "test.py", hardware=True) is True

    def test_hardware_checks_chumicro_imports(self) -> None:
        """Hardware mode still checks chumicro_* imports."""
        tree = self._parse("import chumicro_nonexistent_fake\n")
        assert _check_imports(tree, "test.py", hardware=True) is False

    def test_from_import_nonexistent_module(self) -> None:
        tree = self._parse("from totally_fake_module_xyz import something\n")
        assert _check_imports(tree, "test.py", hardware=False) is False

    def test_from_import_nonexistent_attribute(self, capsys: pytest.CaptureFixture) -> None:
        tree = self._parse("from os import totally_fake_attribute_xyz\n")
        assert _check_imports(tree, "test.py", hardware=False) is False
        assert "FAIL" in capsys.readouterr().out

    def test_from_import_real_attribute(self) -> None:
        tree = self._parse("from os.path import join\n")
        assert _check_imports(tree, "test.py", hardware=False) is True

    def test_chumicro_import_passes(self) -> None:
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

    def test_clean_examples(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """Directory with valid examples returns 0."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "good.py").write_text(
            "import os\nprint('hello')\n",
        )

        result = verify_examples([package_dir], display_root=tmp_path)

        assert result == 0
        assert "verified" in capsys.readouterr().out

    def test_syntax_error_example(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """Example with syntax error is reported as failure."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "bad.py").write_text("def broken(\n")

        result = verify_examples([package_dir], display_root=tmp_path)

        assert result == 1
        assert "FAIL" in capsys.readouterr().out

    def test_no_examples_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """Package without examples/ returns 0."""
        package_dir = tmp_path / "library"
        package_dir.mkdir()

        result = verify_examples([package_dir], display_root=tmp_path)

        assert result == 0
        assert "No examples" in capsys.readouterr().out

    def test_hardware_example_via_marker(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """``__chumicro_runtimes__`` marker triggers hardware-mode skip."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "circuitpython_blink.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n'
            "import board\nimport digitalio\n",
        )

        result = verify_examples([package_dir], display_root=tmp_path)

        assert result == 0
        assert "hardware" in capsys.readouterr().out

    def test_filename_prefix_no_longer_implies_hardware(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """A ``circuitpython_*.py`` file without the marker is treated as universal.

        The filename prefix is convention only — the explicit
        ``__chumicro_runtimes__`` marker is the contract.  Without
        the marker, ``board`` doesn't resolve on the host and the
        verifier reports a failure.
        """
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "circuitpython_blink.py").write_text(
            "import board\nimport digitalio\n",
        )

        result = verify_examples([package_dir], display_root=tmp_path)

        assert result == 1
        assert "FAIL" in capsys.readouterr().out

    def test_bad_import_example(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """Example with unresolvable import is reported as failure."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "bad_import.py").write_text(
            "import totally_fake_nonexistent_module_xyz\n",
        )

        result = verify_examples([package_dir], display_root=tmp_path)

        assert result == 1

    def test_display_root_defaults_to_cwd(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without display_root, paths default to relative-to-cwd."""
        package_dir = self._make_package(tmp_path)
        (package_dir / "examples" / "good.py").write_text("import os\n")
        monkeypatch.chdir(tmp_path)

        result = verify_examples([package_dir])

        assert result == 0
