"""Tests for check_dated_narration.py — CHU012 dated-narration rule."""

from __future__ import annotations

from pathlib import Path

import pytest
from check_dated_narration import (
    _PATTERNS,
    _RULE_CODE,
    _is_suppressed,
    check_file,
    check_paths,
)


def _any_pattern_matches(text: str) -> bool:
    """Return True when at least one CHU012 pattern fires on *text*.

    Position-independent: tests use this helper rather than indexing
    into ``_PATTERNS[N]`` so adding a pattern doesn't reshuffle every
    test's index.
    """
    return any(pattern.search(text) is not None for pattern, _ in _PATTERNS)


class TestIsSuppressed:
    """Tests for the noqa-detection helper."""

    def test_no_suppression(self) -> None:
        """A plain line is never suppressed."""
        assert _is_suppressed("Surfaced 2026-05-03 during the bake") is False

    def test_specific_suppression(self) -> None:
        """``# noqa: CHU012`` suppresses CHU012."""
        assert _is_suppressed("Surfaced 2026-05-03  # noqa: CHU012") is True

    def test_bare_noqa(self) -> None:
        """Bare ``# noqa`` suppresses every rule on the line."""
        assert _is_suppressed("Surfaced 2026-05-03  # noqa") is True

    def test_unrelated_code_not_matched(self) -> None:
        """``# noqa: CHU001`` does not suppress CHU012."""
        assert _is_suppressed("Surfaced 2026-05-03  # noqa: CHU001") is False

    def test_html_comment_suppression(self) -> None:
        """``<!-- noqa: CHU012 -->`` suppresses CHU012 in markdown."""
        assert _is_suppressed("Surfaced 2026-05-03 <!-- noqa: CHU012 -->") is True


class TestPatternsHit:
    """Each documented violation shape is caught by at least one pattern."""

    @pytest.mark.parametrize(
        "text",
        [
            "Surfaced 2026-05-03 during the post-wedge cleanup bake",
            "Discovered 2026-04-25 while running the suite",
            "Observed 2026-04-26 on the Lolin S2",
            "Captured 2026-05-09 in the deploy session",
            "Caught 2026-05-06 by the verification probe",
            "shipped 2026-04-27 in commit ``139b0ee``",
            "landed 2026-05-09 across all three runtimes",
        ],
    )
    def test_dated_incident(self, text: str) -> None:
        """The dated-incident pattern catches verb + ISO-date shapes."""
        assert _any_pattern_matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "verified live 2026-04-27 against the upstream cert",
            "verified on hardware 2026-05-05 across both runtimes",
            "Verified on hardware 2026-05-05: pi-pico-w-mp",
        ],
    )
    def test_dated_verification(self, text: str) -> None:
        """The dated-verification shape is caught case-insensitively."""
        assert _any_pattern_matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "live-tested on MP 1.28.0 (2026-04-26)",
            "bench-tested on Lolin S2 (2026-05-09)",
        ],
    )
    def test_live_tested(self, text: str) -> None:
        """The live-tested shape is caught."""
        assert _any_pattern_matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Phase 5 of the workspace-ecosystem workstream",
            "Step 3 of the beginner-onramp workstream",
            "Slice 7 of the nested-projects-and-examples workstream",
            "Phase 2d of the workspace-ecosystem workstream",
            "see workstream Phase 3a doc",
        ],
    )
    def test_phase_step_slice_workstream(self, text: str) -> None:
        """The Phase/Step/Slice + workstream shape is caught."""
        assert _any_pattern_matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "F4 of the 2026-05-06 verification pass",
            "F6 of the 2026-05-06 verification finding",
            "F4 of 2026-05-06 verification — ``add-device`` derives",
            "F4 of 2026-05-06 changed ID derivation",
            "(F5, 2026-05-06): synthesised shim",
            "(F4 of the 2026-05-06 verification)",
        ],
    )
    def test_f_numbered_finding(self, text: str) -> None:
        """The F-numbered + dated finding shape is caught (with or without 'verification')."""
        assert _any_pattern_matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "verification finding #5, 2026-05-06",
            "verification finding 5, 2026-05-06",
            "the 2026-05-06 verification pass",
            "during the 2026-05-09 verification finding",
        ],
    )
    def test_verification_pass_or_finding(self, text: str) -> None:
        """The verification-pass / finding shape is caught."""
        assert _any_pattern_matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Regression for 2026-05-06: the all-comments starter",
            "# Regression for 2026-05-09",
        ],
    )
    def test_regression_for(self, text: str) -> None:
        """The ``Regression for YYYY-MM-DD`` shape is caught."""
        assert _any_pattern_matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "in the deploy-audit pass after the wedge",
            "in the post-wedge cleanup bake",
            "removed in the silent-skip audit",
            "in the multi-board sweep",
        ],
    )
    def test_hyphenated_phase(self, text: str) -> None:
        """The hyphenated workstream-phase shape is caught."""
        assert _any_pattern_matches(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Earlier versions of this code did X",
            "Previously this called connect()",
            "Previously, the parser did Y",
            "We used to send Ctrl-C here",
            "Used to be three steps",
        ],
    )
    def test_removed_code_framing(self, text: str) -> None:
        """The removed-code framing shape is caught."""
        assert _any_pattern_matches(text)


class TestPatternsMiss:
    """Lines that look superficially similar but aren't violations are passed."""

    @pytest.mark.parametrize(
        "text",
        [
            "in the same pass as the deploy",
            "rsync ships them in the same pass",
            "the security audit found no issues",
            "Surfaced 26-05-03 during the bake",  # two-digit year
            'MicroPython v1.28.0 on 2026-04-06\\r\\n',  # fixture string
            "Adafruit CircuitPython 10.2.0 on 2026-01-02; Foo Board",  # fixture
            "the FAT was reformatted on 2021-01-01 by boot",  # technical fact
            "F4: chip variants with hyphens must be normalised",  # F-prefix without date
        ],
    )
    def test_no_match(self, text: str) -> None:
        """The pattern bank does not flag these false-positive shapes."""
        assert not _any_pattern_matches(text)


def _make_src_file(tmp_path: Path, name: str, body: str) -> Path:
    """Create ``tmp_path/libraries/foo/src/foo/<name>`` with *body*."""
    src_dir = tmp_path / "libraries" / "foo" / "src" / "foo"
    src_dir.mkdir(parents=True, exist_ok=True)
    target = src_dir / name
    target.write_text(body)
    return target


class TestCheckFile:
    """End-to-end behaviour of check_file()."""

    def test_clean_file(self, tmp_path: Path) -> None:
        """A file with no flagged comments returns no errors."""
        target = _make_src_file(
            tmp_path, "src.py", "def add(left, right):\n    return left + right\n",
        )
        assert check_file(target) == []

    def test_dated_incident_in_docstring(self, tmp_path: Path) -> None:
        """A docstring with ``Surfaced YYYY-MM-DD`` is flagged."""
        target = _make_src_file(
            tmp_path, "src.py", '"""Surfaced 2026-05-03 during the bake."""\n',
        )
        errors = check_file(target)
        assert len(errors) == 1
        assert _RULE_CODE in errors[0]
        assert "dated incident" in errors[0]

    def test_workstream_pointer_in_module_docstring(self, tmp_path: Path) -> None:
        """A module docstring naming a workstream phase is flagged."""
        target = _make_src_file(
            tmp_path, "src.py",
            '"""Module docstring.\n\nPhase 5 of the workspace-ecosystem workstream.\n"""\n',
        )
        errors = check_file(target)
        assert len(errors) == 1
        assert "workstream-phase pointer" in errors[0]

    def test_f_numbered_in_test_comment(self, tmp_path: Path) -> None:
        """An F-numbered finding in a test-body comment is flagged."""
        target = _make_src_file(
            tmp_path, "test_foo.py",
            "# F6 — port-holder diagnosis (2026-05-06 verification finding)\n",
        )
        errors = check_file(target)
        assert len(errors) == 1
        assert "verification" in errors[0]

    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        """``# noqa: CHU012`` on the same line silences the lint hit."""
        target = _make_src_file(
            tmp_path, "src.py",
            '"""Surfaced 2026-05-03 (workaround for firmware bug)."""  # noqa: CHU012\n',
        )
        assert check_file(target) == []

    def test_one_error_per_line(self, tmp_path: Path) -> None:
        """A line that triggers two patterns emits one error so output isn't doubled."""
        target = _make_src_file(
            tmp_path, "src.py",
            "# Phase 5 of the workspace-ecosystem workstream — Surfaced 2026-05-03\n",
        )
        errors = check_file(target)
        assert len(errors) == 1

    def test_self_exempt_lint_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The lint's own source file is exempt (carries the patterns as regexes)."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        target = scripts_dir / "check_dated_narration.py"
        target.write_text("# Surfaced 2026-05-03\n")
        monkeypatch.setattr("check_dated_narration.ROOT", tmp_path)
        assert check_file(target) == []

    def test_self_exempt_lint_tests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The lint's own test file is exempt (carries the patterns as fixtures)."""
        tests_dir = tmp_path / "scripts" / "tests"
        tests_dir.mkdir(parents=True)
        target = tests_dir / "test_check_dated_narration.py"
        target.write_text("# Surfaced 2026-05-03\n")
        monkeypatch.setattr("check_dated_narration.ROOT", tmp_path)
        assert check_file(target) == []


class TestCheckPaths:
    """End-to-end check_paths() behaviour."""

    def test_clean_directory(self, tmp_path: Path) -> None:
        """A directory with only clean files returns 0."""
        _make_src_file(
            tmp_path, "src.py", "def add(left, right):\n    return left + right\n",
        )
        assert check_paths([str(tmp_path)]) == 0

    def test_directory_with_violation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A directory with one violation returns 1 and prints the error."""
        _make_src_file(
            tmp_path, "src.py", '"""Phase 5 of the workspace-ecosystem workstream."""\n',
        )
        result = check_paths([str(tmp_path)])
        captured = capsys.readouterr()
        assert result == 1
        assert _RULE_CODE in captured.out
        assert "workstream-phase pointer" in captured.out

    def test_excluded_directories_not_scanned(self, tmp_path: Path) -> None:
        """Files inside ``__pycache__`` and ``.venv`` are not scanned."""
        for excluded in ("__pycache__", ".venv", ".pytest_cache"):
            cache_dir = tmp_path / "libraries" / "foo" / excluded
            cache_dir.mkdir(parents=True)
            (cache_dir / "leak.py").write_text(
                '"""Surfaced 2026-05-03 during the bake."""\n',
            )
        assert check_paths([str(tmp_path)]) == 0
