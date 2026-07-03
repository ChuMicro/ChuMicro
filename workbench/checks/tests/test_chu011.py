"""Tests for CHU011: plans-doc brevity."""

from __future__ import annotations

import textwrap
from pathlib import Path

from chumicro_checks.rules.chu011 import (
    _BULLET_CAP,
    CHU011,
    _find_bullet_extents,
    _find_done_heading_indices,
)


def _make_repo_with_next_up(repo_root: Path, content: str) -> Path:
    """Stage a ``plans/next-up.md`` under *repo_root* with the given body.

    Leading newline and common indentation are stripped from *content*
    so test bodies can write indented heredocs.
    """
    plans_dir = repo_root / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    target = plans_dir / "next-up.md"
    target.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return target


class TestSilentNoOp:
    """When plans/next-up.md is absent, the rule emits no findings."""

    def test_missing_file_returns_no_findings(self, tmp_path: Path) -> None:
        # tmp_path has no plans/ directory at all.
        assert CHU011.check(tmp_path) == []

    def test_missing_only_plans_dir(self, tmp_path: Path) -> None:
        (tmp_path / "plans").mkdir()
        assert CHU011.check(tmp_path) == []


class TestBulletCap:
    """Top-level bullets with sub-bullets fire (cap of 1)."""

    def test_one_bullet_passes(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Next

            - lone top-level bullet
            - another lone bullet
        """)
        assert CHU011.check(tmp_path) == []

    def test_sub_bullet_fires(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Next

            - top
              - sub-1
        """)
        findings = CHU011.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU011"
        assert "2 bullet markers" in findings[0].message
        assert f"cap {_BULLET_CAP}" in findings[0].message
        assert "no sub-bullets" in findings[0].message

    def test_numbered_sub_list_fires(self, tmp_path: Path) -> None:
        # Ordered sub-items are the same "needs structure" shape as
        # dash sub-bullets and must count toward the cap.
        _make_repo_with_next_up(tmp_path, """
            ## Next

            - big item with hidden structure:
              1. sub-step one
              2. sub-step two
              3. sub-step three
        """)
        findings = CHU011.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU011"
        assert "4 bullet markers" in findings[0].message

    def test_paren_ordered_sub_list_fires(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Next

            - item
              1) first
              2) second
        """)
        assert len(CHU011.check(tmp_path)) == 1

    def test_star_sub_bullet_fires(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Next

            - item
              * sub with a star marker
        """)
        assert len(CHU011.check(tmp_path)) == 1

    def test_version_number_in_bullet_body_does_not_count(
        self, tmp_path: Path,
    ) -> None:
        # ``1.2.3`` mid-line is not a list marker (no space after the
        # first dot), so a bullet mentioning a version stays clean.
        _make_repo_with_next_up(tmp_path, """
            ## Next

            - bump chumicro-checks to 1.2.3 before the release
        """)
        assert CHU011.check(tmp_path) == []

    def test_per_bullet_noqa_suppresses(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Next

            - top  <!-- noqa: CHU011 -->
              - sub-1
              - sub-2
        """)
        assert CHU011.check(tmp_path) == []

    def test_heading_breaks_extent(self, tmp_path: Path) -> None:
        # Each bullet has only its own marker since the heading splits them.
        _make_repo_with_next_up(tmp_path, """
            ## Now

            - first

            ## Next

            - second
        """)
        assert CHU011.check(tmp_path) == []


class TestDoneHeadingAbsent:
    """The ``## Done`` heading is forbidden. Recent landings live in git log."""

    def test_no_done_heading_passes(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Now

            - one

            ## Next

            - two
        """)
        assert CHU011.check(tmp_path) == []

    def test_done_heading_fires(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Done (recent)

            - [x] shipped thing
        """)
        findings = CHU011.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU011"
        assert "`## Done` heading is not allowed" in findings[0].message
        assert "git log" in findings[0].message

    def test_done_bare_also_fires(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Done

            - [x] shipped thing
        """)
        findings = CHU011.check(tmp_path)
        assert len(findings) == 1
        assert "`## Done` heading is not allowed" in findings[0].message

    def test_heading_line_noqa_suppresses(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Done (recent) <!-- noqa: CHU011 -->

            - [x] shipped thing
        """)
        assert CHU011.check(tmp_path) == []


class TestHelpers:
    """Spot-check the internal helpers."""

    def test_find_bullet_extents_with_heading_break(self) -> None:
        lines = ["- a", "  detail", "## section", "- b"]
        assert _find_bullet_extents(lines) == [(0, 2), (3, 4)]

    def test_find_bullet_extents_runs_to_eof(self) -> None:
        lines = ["- only"]
        assert _find_bullet_extents(lines) == [(0, 1)]

    def test_find_done_heading_indices_matches_recent_variant(self) -> None:
        lines = [
            "## Now",
            "- one",
            "## Done (recent)",
            "- [x] two",
            "## Next-section",
            "- three",
        ]
        assert _find_done_heading_indices(lines) == [2]

    def test_find_done_heading_indices_matches_bare(self) -> None:
        lines = ["## Done", "- [x] one"]
        assert _find_done_heading_indices(lines) == [0]


class TestRuleMetadata:
    """The rule advertises its identity correctly."""

    def test_code(self) -> None:
        assert CHU011.code == "CHU011"

    def test_description_mentions_caps(self) -> None:
        assert "bullet" in CHU011.description.lower()
