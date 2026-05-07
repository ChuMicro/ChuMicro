"""Tests for check_no_repo_refs.py — CHU006 mono-repo-reference rule."""

from __future__ import annotations

from pathlib import Path

import pytest
from check_no_repo_refs import (
    _PATTERNS,
    _RULE_CODE,
    _is_suppressed,
    _outside_chumicro_workspace,
    check_file,
    check_paths,
)


class TestIsSuppressed:
    """Tests for the noqa-detection helper."""

    def test_no_suppression(self) -> None:
        """A plain line is never suppressed."""
        assert _is_suppressed("Decision 0042 ref") is False

    def test_specific_suppression(self) -> None:
        """``# noqa: CHU006`` suppresses CHU006."""
        assert _is_suppressed("Decision 0042 ref  # noqa: CHU006") is True

    def test_bare_noqa(self) -> None:
        """Bare ``# noqa`` suppresses every rule on the line."""
        assert _is_suppressed("Decision 0042 ref  # noqa") is True

    def test_unrelated_code_not_matched(self) -> None:
        """``# noqa: CHU001`` does not suppress CHU006."""
        assert _is_suppressed("Decision 0042 ref  # noqa: CHU001") is False

    def test_chu002_does_not_suppress(self) -> None:
        """``# noqa: CHU002`` (the whitespace rule's code) does not suppress CHU006."""
        assert _is_suppressed("Decision 0042 ref  # noqa: CHU002") is False

    def test_html_comment_suppression(self) -> None:
        """``<!-- noqa: CHU006 -->`` suppresses CHU006 in markdown."""
        assert _is_suppressed("Decision 0042 ref <!-- noqa: CHU006 -->") is True

    def test_html_comment_bare(self) -> None:
        """Bare ``<!-- noqa -->`` also suppresses every rule."""
        assert _is_suppressed("Decision 0042 ref <!-- noqa -->") is True


class TestPatterns:
    """The regex pattern bank should catch the documented leakage shapes."""

    @pytest.mark.parametrize(
        "text",
        [
            "See Decision 0042 for the rule.",
            "Decision  0001 — extra whitespace still flagged.",
            "Per Decision 0099, the deploy mode flips.",
        ],
    )
    def test_decision_pattern_hits(self, text: str) -> None:
        """The Decision-NNNN pattern catches every ADR-style attribution."""
        decision_re = _PATTERNS[0][0]
        assert decision_re.search(text) is not None

    def test_decision_pattern_misses_three_digit(self) -> None:
        """Decision-N must be at least four digits to avoid generic matches."""
        decision_re = _PATTERNS[0][0]
        assert decision_re.search("Decision 99 was a long time ago") is None

    @pytest.mark.parametrize(
        "text",
        [
            "see plans/learnings.md",
            "details in plans/decisions/0029-project-workspace.md",
            "the plans/workstreams/foo-bar.md doc",
        ],
    )
    def test_plans_md_pattern_hits(self, text: str) -> None:
        """The plans/...md pattern catches inline-doc paths."""
        plans_re = _PATTERNS[1][0]
        assert plans_re.search(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "look in plans/decisions for the ADR",
            "see plans/workstreams/ for context",
            "plans/learnings is internal",
        ],
    )
    def test_plans_dir_pattern_hits(self, text: str) -> None:
        """The plans/<dir> pattern catches directory references."""
        plans_dir_re = _PATTERNS[2][0]
        assert plans_dir_re.search(text) is not None

    def test_scripts_run_py_pattern(self) -> None:
        """The scripts/run.py pattern catches the mono-repo command runner."""
        scripts_re = _PATTERNS[3][0]
        assert scripts_re.search("Run python scripts/run.py setup") is not None

    @pytest.mark.parametrize(
        "text",
        [
            "via your workspace's run.py",
            "Run python run.py deploy",
            "as `run.py setup` does",
        ],
    )
    def test_bare_run_py_pattern_hits(self, text: str) -> None:
        """The bare-run.py pattern catches workspace-shim mentions outside chumicro_workspace."""
        bare_run_py_re = _PATTERNS[4][0]
        assert bare_run_py_re.search(text) is not None

    def test_bare_run_py_pattern_skips_scripts_prefix(self) -> None:
        """``scripts/run.py`` is not double-flagged by the bare-run.py rule."""
        bare_run_py_re = _PATTERNS[4][0]
        assert bare_run_py_re.search("python scripts/run.py setup") is None

    @pytest.mark.parametrize(
        "text",
        [
            "the chumicro mono-repo",
            "Inside the chumicro Mono-Repo",
            "the chumicro monorepo",
        ],
    )
    def test_mono_repo_pattern(self, text: str) -> None:
        """The mono-repo phrasing matches case-insensitively, with or without hyphen."""
        mono_repo_re = _PATTERNS[5][0]
        assert mono_repo_re.search(text) is not None


class TestOutsideChumicroWorkspace:
    """The bare-run.py predicate exempts the chumicro_workspace package."""

    def test_inside_workspace_src_is_exempt(self) -> None:
        """Files inside ``workbench/workspace/src/`` are exempt from bare-run.py."""
        path = Path("workbench/workspace/src/chumicro_workspace/cli.py")
        assert _outside_chumicro_workspace(path) is False

    def test_other_workbench_packages_not_exempt(self) -> None:
        """Other workbench packages still get the bare-run.py rule applied."""
        path = Path("workbench/deploy/src/chumicro_deploy/cli.py")
        assert _outside_chumicro_workspace(path) is True

    def test_libraries_not_exempt(self) -> None:
        """Library packages still get the bare-run.py rule applied."""
        path = Path("libraries/wifi/src/chumicro_wifi/__init__.py")
        assert _outside_chumicro_workspace(path) is True

    def test_absolute_path_inside_workspace_is_exempt(self) -> None:
        """Absolute paths into workspace src/ are also exempt."""
        path = Path("/Users/foo/chumicro/workbench/workspace/src/chumicro_workspace/cli.py")
        assert _outside_chumicro_workspace(path) is False


class TestCheckFile:
    """End-to-end behaviour of check_file()."""

    def test_clean_file(self, tmp_path: Path) -> None:
        """A file with no flagged refs returns no errors."""
        target = tmp_path / "src.py"
        target.write_text("def add(left, right):\n    return left + right\n")
        assert check_file(target) == []

    def test_decision_ref_in_docstring(self, tmp_path: Path) -> None:
        """A docstring naming an ADR is flagged."""
        target = tmp_path / "src.py"
        target.write_text('"""Per Decision 0042, this ships."""\n')
        errors = check_file(target)
        assert len(errors) == 1
        assert _RULE_CODE in errors[0]
        assert "Decision NNNN" in errors[0]

    def test_plans_md_in_comment(self, tmp_path: Path) -> None:
        """A comment pointing into ``plans/learnings.md`` is flagged."""
        target = tmp_path / "src.py"
        target.write_text("# see plans/learnings.md for the rationale\n")
        errors = check_file(target)
        assert len(errors) == 1
        assert "plans/...md" in errors[0]

    def test_scripts_run_py_in_error_message(self, tmp_path: Path) -> None:
        """An error string naming ``scripts/run.py`` is flagged."""
        target = tmp_path / "src.py"
        target.write_text(
            "raise RuntimeError('Run python scripts/run.py setup')\n",
        )
        errors = check_file(target)
        assert len(errors) == 1
        assert "scripts/run.py" in errors[0]

    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        """``# noqa: CHU006`` on the same line silences the lint hit."""
        target = tmp_path / "src.py"
        target.write_text(
            '"""Per Decision 0042, this ships."""  # noqa: CHU006\n',
        )
        assert check_file(target) == []

    def test_one_error_per_line_even_if_two_patterns_hit(
        self, tmp_path: Path,
    ) -> None:
        """A line that triggers two rules emits one error so output isn't doubled."""
        target = tmp_path / "src.py"
        target.write_text(
            "# Decision 0042 lives in plans/decisions/0042.md\n",
        )
        errors = check_file(target)
        assert len(errors) == 1

    def test_bare_run_py_outside_workspace_flagged(self, tmp_path: Path) -> None:
        """A bare ``run.py`` reference outside chumicro_workspace is flagged."""
        target = tmp_path / "src.py"
        target.write_text("# tell users to invoke via run.py setup\n")
        errors = check_file(target)
        assert len(errors) == 1
        assert "bare run.py" in errors[0]

    def test_bare_run_py_inside_workspace_exempt(self, tmp_path: Path) -> None:
        """A bare ``run.py`` reference inside chumicro_workspace src/ is exempt."""
        workspace_dir = tmp_path / "workbench" / "workspace" / "src" / "chumicro_workspace"
        workspace_dir.mkdir(parents=True)
        target = workspace_dir / "cli.py"
        target.write_text("# this package owns the run.py shim and writes it\n")
        assert check_file(target) == []


class TestCheckPaths:
    """End-to-end behaviour of check_paths()."""

    def test_returns_zero_on_clean_tree(self, tmp_path: Path, capsys) -> None:
        """A directory with no leakage returns 0."""
        (tmp_path / "src.py").write_text("OK = 1\n")
        assert check_paths([str(tmp_path)]) == 0

    def test_returns_one_on_dirty_tree(self, tmp_path: Path, capsys) -> None:
        """A directory with at least one hit returns 1 + prints the lint output."""
        (tmp_path / "src.py").write_text(
            '"""See Decision 0042 for the rule."""\n',
        )
        assert check_paths([str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert _RULE_CODE in out
        assert "Found 1 mono-repo reference" in out
