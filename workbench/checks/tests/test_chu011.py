"""Tests for CHU011 — plans-doc brevity."""

from __future__ import annotations

import textwrap
from pathlib import Path

from chumicro_checks.rules.chu011 import (
    _BULLET_CAP,
    _DONE_SECTION_CAP,
    CHU011,
    _find_bullet_extents,
    _find_done_section_top_level_bullets,
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
    """Top-level bullets exceeding ``_BULLET_CAP`` markers fire."""

    def test_under_cap_passes(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Now

            - top
              - sub-1
              - sub-2
              - sub-3
              - sub-4
        """)
        assert CHU011.check(tmp_path) == []

    def test_over_cap_fires(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Now

            - top
              - sub-1
              - sub-2
              - sub-3
              - sub-4
              - sub-5
              - sub-6
        """)
        findings = CHU011.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU011"
        assert "7 bullet markers" in findings[0].message
        assert f"cap {_BULLET_CAP}" in findings[0].message

    def test_per_bullet_noqa_suppresses(self, tmp_path: Path) -> None:
        _make_repo_with_next_up(tmp_path, """
            ## Now

            - top  <!-- noqa: CHU011 -->
              - sub-1
              - sub-2
              - sub-3
              - sub-4
              - sub-5
              - sub-6
        """)
        assert CHU011.check(tmp_path) == []

    def test_heading_breaks_extent(self, tmp_path: Path) -> None:
        # The first bullet's extent ends at the heading; only its 2
        # markers are counted, well under the cap.
        _make_repo_with_next_up(tmp_path, """
            ## Now

            - top
              - sub-1

            ## Next

            - other
        """)
        assert CHU011.check(tmp_path) == []


class TestDoneSectionCap:
    """The ``## Done (recent)`` section is capped at 5 entries."""

    def test_at_cap_passes(self, tmp_path: Path) -> None:
        body = "## Done (recent)\n\n" + "\n".join(
            f"- [x] entry {index}" for index in range(_DONE_SECTION_CAP)
        )
        _make_repo_with_next_up(tmp_path, body)
        assert CHU011.check(tmp_path) == []

    def test_over_cap_fires(self, tmp_path: Path) -> None:
        body = "## Done (recent)\n\n" + "\n".join(
            f"- [x] entry {index}" for index in range(_DONE_SECTION_CAP + 3)
        )
        _make_repo_with_next_up(tmp_path, body)
        findings = CHU011.check(tmp_path)
        assert len(findings) == 1
        message = findings[0].message
        assert f"{_DONE_SECTION_CAP + 3} entries" in message
        assert f"cap {_DONE_SECTION_CAP}" in message

    def test_file_scope_noqa_suppresses(self, tmp_path: Path) -> None:
        body = (
            "<!-- noqa: CHU011 -->\n## Done (recent)\n\n"
            + "\n".join(
                f"- [x] entry {index}" for index in range(_DONE_SECTION_CAP + 3)
            )
        )
        _make_repo_with_next_up(tmp_path, body)
        assert CHU011.check(tmp_path) == []


class TestHelpers:
    """Spot-check the internal helpers."""

    def test_find_bullet_extents_with_heading_break(self) -> None:
        lines = ["- a", "  detail", "## section", "- b"]
        assert _find_bullet_extents(lines) == [(0, 2), (3, 4)]

    def test_find_bullet_extents_runs_to_eof(self) -> None:
        lines = ["- only"]
        assert _find_bullet_extents(lines) == [(0, 1)]

    def test_find_done_section_top_level_bullets(self) -> None:
        lines = [
            "## Now",
            "- not-counted",
            "## Done (recent)",
            "- entry-a",
            "  - sub (not counted, not top-level)",
            "- entry-b",
            "## Next-section",
            "- not-counted",
        ]
        assert _find_done_section_top_level_bullets(lines) == [3, 5]


class TestRuleMetadata:
    """The rule advertises its identity correctly."""

    def test_code(self) -> None:
        assert CHU011.code == "CHU011"

    def test_description_mentions_caps(self) -> None:
        # Sanity: the description tells the operator what the rule does.
        assert "bullet" in CHU011.description.lower()
