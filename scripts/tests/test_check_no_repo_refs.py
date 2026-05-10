"""Tests for check_no_repo_refs.py — CHU006 mono-repo-reference rule."""

from __future__ import annotations

from pathlib import Path

import pytest
from check_no_repo_refs import (
    _PATTERNS,
    _RULE_CODE,
    _everywhere_outside_chumicro_workspace,
    _is_suppressed,
    _outside_chumicro_checks,
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

    @pytest.mark.parametrize(
        "text",
        [
            "enforced by CHU009 / CHU010",
            "see CHU001 for naming",
            "the workspace's CHU011 lint",
        ],
    )
    def test_chu_code_in_prose_pattern_hits(self, text: str) -> None:
        """The CHU0NN-prose pattern catches workspace-internal lint codes in prose."""
        chu_prose_re = _PATTERNS[6][0]
        assert chu_prose_re.search(text) is not None

    def test_chu_code_pattern_misses_partial_match(self) -> None:
        """``CHU01`` (2 digits) is not matched — must be exactly three digits after CHU."""
        chu_prose_re = _PATTERNS[6][0]
        assert chu_prose_re.search("CHU01 mentioned") is None


class TestEverywhereOutsideChumicroWorkspace:
    """The bare-run.py predicate: every file EXCEPT chumicro_workspace.

    The ``chumicro_workspace`` package owns the workspace-template's
    ``run.py`` shim and legitimately mentions it everywhere — src,
    docs, tests, pyproject.  Every other package mentioning bare
    ``run.py`` is flagged.
    """

    def test_inside_workspace_src_is_exempt(self) -> None:
        """Files inside ``workbench/workspace/src/`` are exempt."""
        path = Path("workbench/workspace/src/chumicro_workspace/cli.py")
        assert _everywhere_outside_chumicro_workspace(path) is False

    def test_workspace_docs_also_exempt(self) -> None:
        """Workspace docs / README are exempt (they document the run.py shim)."""
        path = Path("workbench/workspace/docs/guide.md")
        assert _everywhere_outside_chumicro_workspace(path) is False

    def test_workspace_tests_also_exempt(self) -> None:
        """Workspace tests are exempt (test data may include the run.py shim)."""
        path = Path("workbench/workspace/tests/test_cli.py")
        assert _everywhere_outside_chumicro_workspace(path) is False

    def test_other_workbench_src_not_exempt(self) -> None:
        """Other workbench packages still get the bare-run.py rule applied."""
        path = Path("workbench/deploy/src/chumicro_deploy/cli.py")
        assert _everywhere_outside_chumicro_workspace(path) is True

    def test_other_workbench_docs_not_exempt(self) -> None:
        """Other workbench packages' docs still get the rule applied."""
        path = Path("workbench/deploy/docs/guide.md")
        assert _everywhere_outside_chumicro_workspace(path) is True

    def test_libraries_src_not_exempt(self) -> None:
        """Library packages' src/ still get the bare-run.py rule applied."""
        path = Path("libraries/wifi/src/chumicro_wifi/__init__.py")
        assert _everywhere_outside_chumicro_workspace(path) is True

    def test_libraries_docs_not_exempt(self) -> None:
        """Library packages' docs/ still get the bare-run.py rule applied."""
        path = Path("libraries/wifi/docs/guide.md")
        assert _everywhere_outside_chumicro_workspace(path) is True

    def test_absolute_path_inside_workspace_is_exempt(self) -> None:
        """Absolute paths into workspace are also exempt."""
        path = Path("/Users/foo/chumicro/workbench/workspace/src/chumicro_workspace/cli.py")
        assert _everywhere_outside_chumicro_workspace(path) is False


class TestOutsideChumicroChecksPredicate:
    """Verify the ``chumicro_checks`` package exemption.

    The ``chumicro_checks`` package legitimately documents CHU code
    identifiers, the mono-repo's ``plans/`` tree, and ``scripts/run.py``
    in its README, source docstrings, and tests — that's its purpose.
    Every other tree is still subject to those patterns.
    """

    def test_inside_checks_src_is_exempt(self) -> None:
        path = Path("workbench/checks/src/chumicro_checks/cli.py")
        assert _outside_chumicro_checks(path) is False

    def test_checks_readme_is_exempt(self) -> None:
        path = Path("workbench/checks/README.md")
        assert _outside_chumicro_checks(path) is False

    def test_checks_tests_are_exempt(self) -> None:
        path = Path("workbench/checks/tests/test_cli.py")
        assert _outside_chumicro_checks(path) is False

    def test_other_workbench_src_not_exempt(self) -> None:
        path = Path("workbench/deploy/src/chumicro_deploy/cli.py")
        assert _outside_chumicro_checks(path) is True

    def test_libraries_src_not_exempt(self) -> None:
        path = Path("libraries/wifi/src/chumicro_wifi/__init__.py")
        assert _outside_chumicro_checks(path) is True

    def test_absolute_path_inside_checks_is_exempt(self) -> None:
        path = Path("/Users/foo/chumicro/workbench/checks/src/chumicro_checks/cli.py")
        assert _outside_chumicro_checks(path) is False


def _make_src_file(tmp_path: Path, name: str, body: str) -> Path:
    """Create ``tmp_path/libraries/foo/src/foo/<name>`` with *body*.

    The CHU006 patterns now fire across every scanned location, but
    test fixtures still live under a ``libraries/<pkg>/src/`` shape
    by convention so they exercise the path the lint actually walks.
    """
    src_dir = tmp_path / "libraries" / "foo" / "src" / "foo"
    src_dir.mkdir(parents=True, exist_ok=True)
    target = src_dir / name
    target.write_text(body)
    return target


class TestCheckFile:
    """End-to-end behaviour of check_file()."""

    def test_clean_file(self, tmp_path: Path) -> None:
        """A file with no flagged refs returns no errors."""
        target = _make_src_file(
            tmp_path, "src.py", "def add(left, right):\n    return left + right\n",
        )
        assert check_file(target) == []

    def test_decision_ref_in_docstring(self, tmp_path: Path) -> None:
        """A docstring naming an ADR is flagged."""
        target = _make_src_file(tmp_path, "src.py", '"""Per Decision 0042, this ships."""\n')
        errors = check_file(target)
        assert len(errors) == 1
        assert _RULE_CODE in errors[0]
        assert "Decision NNNN" in errors[0]

    def test_decision_ref_outside_src_also_fires(self, tmp_path: Path) -> None:
        """``Decision NNNN`` fires EVERYWHERE — docs, tests, pyproject.

        The cleanup pass that inlined every existing leak finished
        before this test was written; the predicate widened from
        ``_src_only`` to ``_everywhere`` so future leaks in published
        docs / tests / examples are caught at lint time.
        """
        docs_dir = tmp_path / "libraries" / "foo" / "docs"
        docs_dir.mkdir(parents=True)
        target = docs_dir / "guide.md"
        target.write_text("Per Decision 0042, this ships.\n")
        errors = check_file(target)
        assert len(errors) == 1
        assert "Decision NNNN" in errors[0]

    def test_plans_md_in_comment(self, tmp_path: Path) -> None:
        """A comment pointing into ``plans/learnings.md`` is flagged."""
        target = _make_src_file(tmp_path, "src.py", "# see plans/learnings.md for the rationale\n")
        errors = check_file(target)
        assert len(errors) == 1
        assert "plans/...md" in errors[0]

    def test_plans_md_outside_src_also_flagged(self, tmp_path: Path) -> None:
        """``plans/...md`` references fire EVERYWHERE — docs, tests, pyproject.

        This is the user-facing reason the lint widened beyond ``src/``:
        published docs that link into the mono-repo's planning tree
        leak the directory shape to consumers who don't have it.
        """
        docs_dir = tmp_path / "libraries" / "foo" / "docs"
        docs_dir.mkdir(parents=True)
        target = docs_dir / "guide.md"
        target.write_text("See `plans/next-up.md` for follow-ups.\n")
        errors = check_file(target)
        assert len(errors) == 1
        assert "plans/...md" in errors[0]

    def test_scripts_run_py_in_error_message(self, tmp_path: Path) -> None:
        """An error string naming ``scripts/run.py`` is flagged."""
        target = _make_src_file(
            tmp_path, "src.py",
            "raise RuntimeError('Run python scripts/run.py setup')\n",
        )
        errors = check_file(target)
        assert len(errors) == 1
        assert "scripts/run.py" in errors[0]

    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        """``# noqa: CHU006`` on the same line silences the lint hit."""
        target = _make_src_file(
            tmp_path, "src.py",
            '"""Per Decision 0042, this ships."""  # noqa: CHU006\n',
        )
        assert check_file(target) == []

    def test_one_error_per_line_even_if_two_patterns_hit(
        self, tmp_path: Path,
    ) -> None:
        """A line that triggers two rules emits one error so output isn't doubled."""
        target = _make_src_file(
            tmp_path, "src.py",
            "# Decision 0042 lives in plans/decisions/0042.md\n",
        )
        errors = check_file(target)
        assert len(errors) == 1

    def test_bare_run_py_outside_workspace_flagged(self, tmp_path: Path) -> None:
        """A bare ``run.py`` reference outside chumicro_workspace is flagged."""
        target = _make_src_file(
            tmp_path, "src.py", "# tell users to invoke via run.py setup\n",
        )
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

    def test_chu_code_in_prose_flagged(self, tmp_path: Path) -> None:
        """A CHU0NN code mentioned in prose (not a noqa) is flagged."""
        target = _make_src_file(
            tmp_path, "src.py",
            '"""Enforced by the workspace\'s CHU009 lint."""\n',
        )
        errors = check_file(target)
        assert len(errors) == 1
        assert "CHU0NN" in errors[0]

    def test_chu_code_inside_noqa_directive_not_flagged(self, tmp_path: Path) -> None:
        """``# noqa: CHU001`` text doesn't trigger the prose-CHU0NN rule.

        The noqa directive's own rule code is not "prose"; the
        scrubbing-then-pattern-match flow strips it before checking.
        """
        target = _make_src_file(
            tmp_path, "src.py",
            "def exec(self):  # noqa: CHU001 — match upstream API\n",
        )
        assert check_file(target) == []

    def test_chu_code_in_html_noqa_directive_not_flagged(self, tmp_path: Path) -> None:
        """``<!-- noqa: CHU011 -->`` text doesn't trigger the prose-CHU0NN rule."""
        target = _make_src_file(
            tmp_path, "src.md",
            "# Heading\n\nLong prose <!-- noqa: CHU011 -->\n",
        )
        assert check_file(target) == []

    def test_chu_code_outside_noqa_on_same_noqa_line_flagged(
        self, tmp_path: Path,
    ) -> None:
        """A line with ``# noqa: CHU001`` and a separate prose CHU010 in trailing text fails.

        The noqa directive is scrubbed; the trailing prose mention
        of an unrelated rule code remains and triggers the rule.
        """
        target = _make_src_file(
            tmp_path, "src.py",
            "def exec(self):  # noqa: CHU001 — see CHU010 for related rule\n",
        )
        errors = check_file(target)
        assert len(errors) == 1
        assert "CHU0NN" in errors[0]


class TestCheckPaths:
    """End-to-end behaviour of check_paths()."""

    def test_returns_zero_on_clean_tree(self, tmp_path: Path, capsys) -> None:
        """A directory with no leakage returns 0."""
        _make_src_file(tmp_path, "src.py", "OK = 1\n")
        assert check_paths([str(tmp_path)]) == 0

    def test_returns_one_on_dirty_tree(self, tmp_path: Path, capsys) -> None:
        """A directory with at least one hit returns 1 + prints the lint output."""
        _make_src_file(tmp_path, "src.py", '"""See Decision 0042 for the rule."""\n')
        assert check_paths([str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert _RULE_CODE in out
        assert "Found 1 mono-repo reference" in out
