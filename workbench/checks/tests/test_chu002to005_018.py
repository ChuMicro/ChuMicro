"""Tests for CHU002–CHU005 + CHU018: newline and whitespace rules."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu002to005_018 import (
    CHU002,
    CHU003,
    CHU004,
    CHU005,
    CHU018,
)


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        for rule in (CHU002, CHU003, CHU004, CHU005, CHU018):
            assert rule.check(tmp_path) == []

    def test_files_outside_scope_ignored(self, tmp_path: Path) -> None:
        # libraries/<pkg>/pyproject.toml is OUT of scope.
        # Only src/tests/functional_tests/examples are scanned per package.
        _stage(tmp_path, "libraries/foo/pyproject.toml", "# x\n\n")
        for rule in (CHU002, CHU003, CHU004, CHU005, CHU018):
            assert rule.check(tmp_path) == []


class TestCHU002:
    def test_missing_trailing_newline_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1")
        findings = CHU002.check(tmp_path)
        assert len(findings) == 1
        assert "does not end with a newline" in findings[0].message

    def test_double_trailing_newline_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\n\n")
        findings = CHU002.check(tmp_path)
        assert len(findings) == 1
        assert "2 newlines instead of 1" in findings[0].message

    def test_correct_trailing_newline_clean(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\n")
        assert CHU002.check(tmp_path) == []

    def test_empty_file_clean(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "")
        assert CHU002.check(tmp_path) == []


class TestCHU003:
    def test_three_blank_lines_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\n\n\n\ny = 2\n")
        findings = CHU003.check(tmp_path)
        assert len(findings) == 1
        assert "consecutive blank lines" in findings[0].message

    def test_two_blank_lines_clean(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\n\n\ny = 2\n")
        assert CHU003.check(tmp_path) == []


class TestCHU004:
    def test_trailing_whitespace_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1   \ny = 2\n")
        findings = CHU004.check(tmp_path)
        assert len(findings) == 1
        assert "trailing whitespace" in findings[0].message

    def test_no_trailing_clean(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\ny = 2\n")
        assert CHU004.check(tmp_path) == []

    def test_noqa_suppresses_in_python(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "x = 1   # noqa: CHU004  trailing space is intentional\n",
        )
        assert CHU004.check(tmp_path) == []


class TestCHU005:
    def test_blank_after_def_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "def func():\n\n    return 1\n",
        )
        findings = CHU005.check(tmp_path)
        assert len(findings) == 1
        assert "blank line after block opener" in findings[0].message

    def test_no_blank_after_def_clean(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "def func():\n    return 1\n",
        )
        assert CHU005.check(tmp_path) == []

    def test_nested_def_after_blank_clean(self, tmp_path: Path) -> None:
        # Idiomatic exception: blank line before a nested ``def``/``class``.
        _stage(
            tmp_path,
            "scripts/foo.py",
            "if True:\n\n    def func():\n        return 1\n",
        )
        assert CHU005.check(tmp_path) == []

    def test_noqa_on_opener_suppresses(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "def func():  # noqa: CHU005\n\n    return 1\n",
        )
        assert CHU005.check(tmp_path) == []

    def test_non_python_file_skipped(self, tmp_path: Path) -> None:
        # CHU005 is Python-only.  Even if the markdown file looks like
        # a block opener, it's never a violation.
        _stage(tmp_path, "scripts/notes.md", "for the record:\n\n    indented\n")
        assert CHU005.check(tmp_path) == []


class TestPackageScope:
    def test_libraries_src_in_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "libraries/foo/src/foo/x.py", "x = 1")
        assert len(CHU002.check(tmp_path)) == 1

    def test_workbench_examples_in_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "workbench/foo/examples/blink.py", "x = 1")
        assert len(CHU002.check(tmp_path)) == 1

    def test_libraries_root_files_out_of_scope(self, tmp_path: Path) -> None:
        # Top-level package files like pyproject.toml or mkdocs.yml are
        # NOT scanned.
        _stage(tmp_path, "libraries/foo/pyproject.toml", "x = 1\n\n")
        assert CHU002.check(tmp_path) == []


class TestTemplateShapeScope:
    """Template / workspace top-level trees are walked too."""

    def test_packages_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "packages/foo/bar.py", "x = 1")
        assert len(CHU002.check(tmp_path)) == 1

    def test_projects_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "projects/wifi/app.py", "x = 1")
        assert len(CHU002.check(tmp_path)) == 1

    def test_shared_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "shared/util.py", "x = 1")
        assert len(CHU002.check(tmp_path)) == 1

    def test_examples_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "examples/blink.py", "x = 1")
        assert len(CHU002.check(tmp_path)) == 1

    def test_root_tests_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "tests/test_foo.py", "x = 1")
        assert len(CHU002.check(tmp_path)) == 1


class TestRuleMetadata:
    def test_codes(self) -> None:
        assert CHU002.code == "CHU002"
        assert CHU003.code == "CHU003"
        assert CHU004.code == "CHU004"
        assert CHU005.code == "CHU005"
        assert CHU018.code == "CHU018"

    def test_descriptions_distinct(self) -> None:
        descriptions = {
            CHU002.description,
            CHU003.description,
            CHU004.description,
            CHU005.description,
            CHU018.description,
        }
        assert len(descriptions) == 5


class TestCHU018:
    def test_crlf_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\r\ny = 2\r\n")
        findings = CHU018.check(tmp_path)
        assert len(findings) == 1
        assert "CR / CRLF" in findings[0].message

    def test_lone_cr_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\ry = 2\n")
        findings = CHU018.check(tmp_path)
        assert len(findings) == 1

    def test_one_finding_per_file_not_per_line(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "a\r\nb\r\nc\r\nd\r\n")
        assert len(CHU018.check(tmp_path)) == 1

    def test_lf_clean(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\ny = 2\n")
        assert CHU018.check(tmp_path) == []


class TestScanScope:
    """plans/ and docs/ are in scope. The gitignored-prone repo root is not."""

    def test_plans_markdown_in_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "plans/next-up.md", "# x\n\n\n\n")
        assert len(CHU002.check(tmp_path)) == 1

    def test_docs_markdown_in_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/guide.md", "trailing  \nok\n")
        assert len(CHU004.check(tmp_path)) == 1

    def test_repo_root_loose_file_not_scanned(self, tmp_path: Path) -> None:
        # Root mixes gitignored user-local files with tracked ones and
        # the walker reads the filesystem, not git. Root stays out of
        # scope so a per-user devices.yml can't false-positive.
        _stage(tmp_path, "devices.yml", "bad: 1\n\n\n")
        _stage(tmp_path, "README.md", "no final newline")
        for rule in (CHU002, CHU003, CHU004, CHU018):
            assert rule.check(tmp_path) == []
