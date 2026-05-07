"""Tests for check_workbench_no_lib_imports.py — CHU007 Decision 0052."""

from __future__ import annotations

import ast
from pathlib import Path

from check_workbench_no_lib_imports import (
    _RULE_CODE,
    _read_noqa_lines,
    _top_level,
    _violations_in_tree,
    check_file,
    check_paths,
)


class TestTopLevel:
    """The package-name normalizer should strip submodule paths."""

    def test_simple_name(self) -> None:
        """A bare package name is returned unchanged."""
        assert _top_level("chumicro_wifi") == "chumicro_wifi"

    def test_submodule(self) -> None:
        """A submodule path returns just the top-level package."""
        assert _top_level("chumicro_wifi.adapters.cp") == "chumicro_wifi"

    def test_two_levels(self) -> None:
        """Two-level paths return the first segment."""
        assert _top_level("chumicro_mqtt.client") == "chumicro_mqtt"


class TestReadNoqaLines:
    """The noqa scanner should mark lines suppressing CHU007."""

    def test_no_noqa(self) -> None:
        """A plain source has no suppressed lines."""
        assert _read_noqa_lines("import x\n") == set()

    def test_specific_chu007(self) -> None:
        """``# noqa: CHU007`` marks that line."""
        assert _read_noqa_lines("import x  # noqa: CHU007\n") == {1}

    def test_bare_noqa(self) -> None:
        """Bare ``# noqa`` also suppresses CHU007."""
        assert _read_noqa_lines("import x  # noqa\n") == {1}

    def test_unrelated_rule_does_not_suppress(self) -> None:
        """``# noqa: CHU001`` does not silence CHU007."""
        assert _read_noqa_lines("import x  # noqa: CHU001\n") == set()


class TestViolationsInTree:
    """AST-level detection of forbidden imports."""

    def test_plain_import(self) -> None:
        """``import chumicro_wifi`` flags the library when in the package set."""
        tree = ast.parse("import chumicro_wifi\n")
        violations = _violations_in_tree(tree, {"chumicro_wifi"})
        assert violations == [(1, "chumicro_wifi")]

    def test_from_import(self) -> None:
        """``from chumicro_mqtt.client import C`` flags the top-level package."""
        tree = ast.parse("from chumicro_mqtt.client import MqttClient\n")
        violations = _violations_in_tree(tree, {"chumicro_mqtt"})
        assert violations == [(1, "chumicro_mqtt")]

    def test_workbench_import_not_flagged(self) -> None:
        """An import of another workbench package is not in the library set."""
        tree = ast.parse("from chumicro_deploy import Deployer\n")
        violations = _violations_in_tree(tree, {"chumicro_wifi", "chumicro_mqtt"})
        assert violations == []

    def test_support_import_not_flagged(self) -> None:
        """``chumicro_test_harness`` is in support/, not libraries/, so not flagged."""
        tree = ast.parse("from chumicro_test_harness.runner import run_module\n")
        violations = _violations_in_tree(
            tree, {"chumicro_wifi", "chumicro_mqtt"}
        )
        assert violations == []

    def test_multiple_violations(self) -> None:
        """Two forbidden imports yield two violations."""
        tree = ast.parse(
            "import chumicro_wifi\nfrom chumicro_mqtt import client\n"
        )
        violations = _violations_in_tree(
            tree, {"chumicro_wifi", "chumicro_mqtt"}
        )
        assert violations == [(1, "chumicro_wifi"), (2, "chumicro_mqtt")]

    def test_relative_import_no_module(self) -> None:
        """A purely-relative ``from . import x`` has ``module=None`` and is skipped."""
        tree = ast.parse("from . import sibling\n")
        violations = _violations_in_tree(tree, {"chumicro_wifi"})
        assert violations == []


class TestCheckFile:
    """End-to-end behaviour of check_file()."""

    def test_clean_file(self, tmp_path: Path) -> None:
        """A file with only workbench imports returns no errors."""
        target = tmp_path / "f.py"
        target.write_text("from chumicro_deploy import Deployer\n")
        assert check_file(target, {"chumicro_wifi"}) == []

    def test_library_import_flagged(self, tmp_path: Path) -> None:
        """A direct library import emits one error."""
        target = tmp_path / "f.py"
        target.write_text("import chumicro_wifi\n")
        errors = check_file(target, {"chumicro_wifi"})
        assert len(errors) == 1
        assert _RULE_CODE in errors[0]
        assert "chumicro_wifi" in errors[0]

    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        """``# noqa: CHU007`` on the import line silences the lint hit."""
        target = tmp_path / "f.py"
        target.write_text("import chumicro_wifi  # noqa: CHU007\n")
        assert check_file(target, {"chumicro_wifi"}) == []

    def test_syntax_error_returns_no_errors(self, tmp_path: Path) -> None:
        """A file that fails to parse silently returns no errors (ruff handles syntax)."""
        target = tmp_path / "f.py"
        target.write_text("def broken(:\n")
        assert check_file(target, {"chumicro_wifi"}) == []


class TestCheckPaths:
    """End-to-end behaviour of check_paths()."""

    def test_clean_tree(self, tmp_path: Path) -> None:
        """A tree of workbench-only imports returns 0."""
        (tmp_path / "f.py").write_text(
            "from chumicro_deploy import Deployer\n",
        )
        # No libraries/ tree exists under tmp_path, so the package set is empty
        # — exercising the all-clear path.
        assert check_paths([str(tmp_path)]) == 0

    def test_dirty_tree(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """A library import returns 1 + prints the error."""
        (tmp_path / "f.py").write_text("import chumicro_wifi\n")

        # Inject a known library-package set rather than relying on filesystem
        # discovery, which scans the real ``libraries/`` tree of this repo.
        from check_workbench_no_lib_imports import check_file as real_check_file

        def fake_check_file(filepath: Path, _ignored: set[str]) -> list[str]:
            return real_check_file(filepath, {"chumicro_wifi"})

        monkeypatch.setattr(
            "check_workbench_no_lib_imports.check_file", fake_check_file,
        )
        assert check_paths([str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert _RULE_CODE in out
        assert "Found 1 workbench-to-library import" in out
