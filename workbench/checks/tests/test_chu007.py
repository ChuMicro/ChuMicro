"""Tests for CHU007: workbench packages must not import library packages."""

from __future__ import annotations

import textwrap
from pathlib import Path

from chumicro_checks.rules.chu007 import CHU007


def _make_library(repo_root: Path, name: str) -> None:
    """Stage ``libraries/<name>/pyproject.toml`` so the rule sees a library."""
    target = repo_root / "libraries" / name / "pyproject.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[project]\nname = 'fake'\n")


def _make_workbench_module(repo_root: Path, package: str, filename: str, body: str) -> Path:
    """Stage ``workbench/<package>/src/<package>/<filename>`` with *body*."""
    target = repo_root / "workbench" / package / "src" / package / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_no_libraries_dir(self, tmp_path: Path) -> None:
        _make_workbench_module(tmp_path, "tool", "x.py", "import chumicro_wifi\n")
        assert CHU007.check(tmp_path) == []

    def test_no_workbench_dir(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        assert CHU007.check(tmp_path) == []

    def test_empty_libraries_yields_no_packages(self, tmp_path: Path) -> None:
        (tmp_path / "libraries").mkdir()
        _make_workbench_module(tmp_path, "tool", "x.py", "import chumicro_wifi\n")
        # No library has a pyproject.toml, so the package set is empty.
        # Nothing to flag.
        assert CHU007.check(tmp_path) == []


class TestImportFlagging:
    def test_plain_import_flagged(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        _make_workbench_module(tmp_path, "tool", "x.py", "import chumicro_wifi\n")
        findings = CHU007.check(tmp_path)
        assert len(findings) == 1
        assert "chumicro_wifi" in findings[0].message

    def test_from_import_flagged(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "sockets")
        _make_workbench_module(
            tmp_path, "tool", "x.py", "from chumicro_sockets import open_tcp\n"
        )
        findings = CHU007.check(tmp_path)
        assert len(findings) == 1

    def test_dotted_submodule_flagged(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        _make_workbench_module(
            tmp_path, "tool", "x.py", "import chumicro_wifi.adapters.cp\n"
        )
        findings = CHU007.check(tmp_path)
        assert len(findings) == 1

    def test_unrelated_import_clean(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        _make_workbench_module(tmp_path, "tool", "x.py", "import pyserial\n")
        assert CHU007.check(tmp_path) == []

    def test_workbench_to_workbench_import_clean(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        _make_workbench_module(
            tmp_path, "tool", "x.py", "from chumicro_deploy import probe\n"
        )
        assert CHU007.check(tmp_path) == []


class TestSuppression:
    def test_noqa_on_import_line(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        _make_workbench_module(
            tmp_path, "tool", "x.py", "import chumicro_wifi  # noqa: CHU007\n"
        )
        assert CHU007.check(tmp_path) == []

    def test_unrelated_noqa_does_not_suppress(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        _make_workbench_module(
            tmp_path, "tool", "x.py", "import chumicro_wifi  # noqa: CHU001\n"
        )
        assert len(CHU007.check(tmp_path)) == 1


class TestEdgeCases:
    def test_syntax_error_reported(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        _make_workbench_module(tmp_path, "tool", "x.py", "def broken(\n")
        # Unparseable file: reported as a finding, not silently skipped.
        findings = CHU007.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU007"
        assert "syntax error" in findings[0].message

    def test_relative_import_with_no_module(self, tmp_path: Path) -> None:
        _make_library(tmp_path, "wifi")
        _make_workbench_module(tmp_path, "tool", "x.py", "from . import sibling\n")
        # `from . import` has node.module is None. No library check applies.
        assert CHU007.check(tmp_path) == []


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU007.code == "CHU007"

    def test_description(self) -> None:
        assert "workbench" in CHU007.description.lower()
