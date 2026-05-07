"""Tests for check_plans_brevity.py — CHU011."""

from __future__ import annotations

import textwrap
from pathlib import Path

from check_plans_brevity import (
    _BULLET_CAP,
    _CHU011,
    _DONE_SECTION_CAP,
    _find_bullet_extents,
    _find_done_section_top_level_bullets,
    check_file,
    main,
)


def _write(directory: Path, name: str, content: str) -> Path:
    """Write *content* to ``directory/name`` and return the path.

    The leading newline from a triple-quoted string and any common
    indentation are stripped so test bodies can use indented blocks.
    """
    target = directory / name
    target.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# _find_bullet_extents
# ---------------------------------------------------------------------------


class TestFindBulletExtents:
    """Bullet extent boundaries: top-level bullet, heading, or EOF."""

    def test_single_bullet_runs_to_end(self) -> None:
        lines = ["- one", "  details"]
        assert _find_bullet_extents(lines) == [(0, 2)]

    def test_two_bullets_split_at_second_top_level(self) -> None:
        lines = ["- one", "- two"]
        assert _find_bullet_extents(lines) == [(0, 1), (1, 2)]

    def test_heading_closes_extent(self) -> None:
        lines = ["- one", "  detail", "## Next section"]
        assert _find_bullet_extents(lines) == [(0, 2)]

    def test_subsection_lines_belong_to_parent_bullet(self) -> None:
        lines = [
            "- lead",
            "    - sub one",
            "    - sub two",
            "",
            "  paragraph still inside the bullet",
        ]
        assert _find_bullet_extents(lines) == [(0, 5)]

    def test_no_bullets_returns_empty(self) -> None:
        lines = ["# Heading", "", "Just a paragraph."]
        assert _find_bullet_extents(lines) == []


# ---------------------------------------------------------------------------
# _find_done_section_top_level_bullets
# ---------------------------------------------------------------------------


class TestFindDoneSectionBullets:
    """Top-level bullets after a ``## Done`` heading and before the next heading."""

    def test_collects_bullets_under_done_heading(self) -> None:
        lines = [
            "## Next",
            "- pending",
            "## Done (recent)",
            "- shipped one",
            "- shipped two",
        ]
        # Bullet line indices: "- shipped one" at index 3, "- shipped two" at 4.
        assert _find_done_section_top_level_bullets(lines) == [3, 4]

    def test_done_heading_prefix_matches_with_suffix(self) -> None:
        lines = [
            "## Done — last 7 days",
            "- shipped",
        ]
        assert _find_done_section_top_level_bullets(lines) == [1]

    def test_excludes_bullets_before_done_heading(self) -> None:
        lines = [
            "## Next",
            "- pending one",
            "- pending two",
        ]
        assert _find_done_section_top_level_bullets(lines) == []

    def test_subsequent_heading_closes_done_section(self) -> None:
        lines = [
            "## Done",
            "- shipped",
            "## Footer",
            "- not in done",
        ]
        assert _find_done_section_top_level_bullets(lines) == [1]


# ---------------------------------------------------------------------------
# Bullet cap (CHU011 rule 1)
# ---------------------------------------------------------------------------


class TestBulletCap:
    """Each top-level bullet may have at most ``_BULLET_CAP`` markers."""

    def test_single_bullet_under_cap_passes(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            """
            ## Next

            - One-liner.
            """,
        )
        assert check_file(path) == []

    def test_lead_plus_four_subbullets_at_cap_passes(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            """
            ## Next

            - Lead
                - sub one
                - sub two
                - sub three
                - sub four
            """,
        )
        assert check_file(path) == []

    def test_lead_plus_five_subbullets_over_cap_fails(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            """
            ## Next

            - Lead
                - sub one
                - sub two
                - sub three
                - sub four
                - sub five
            """,
        )
        errors = check_file(path)
        assert len(errors) == 1
        assert _CHU011 in errors[0]
        assert f"6 bullet markers (cap {_BULLET_CAP})" in errors[0]

    def test_noqa_marker_suppresses_bullet_violation(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            """
            ## Next

            - Lead <!-- noqa: CHU011 -->
                - sub one
                - sub two
                - sub three
                - sub four
                - sub five
                - sub six
            """,
        )
        assert check_file(path) == []

    def test_extent_ends_at_next_top_level_bullet(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            """
            ## Next

            - Item A
                - sub
            - Item B
                - sub
                - sub
                - sub
                - sub
                - sub
            """,
        )
        # Item A has 2 markers (PASS), Item B has 6 markers (FAIL).
        errors = check_file(path)
        assert len(errors) == 1
        assert "6 bullet markers" in errors[0]

    def test_extent_ends_at_heading(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            """
            ## Next

            - Item with five markers
                - sub one
                - sub two
                - sub three
                - sub four

            ## Done
            """,
        )
        # 5 markers exactly, at cap — passes.
        assert check_file(path) == []

    def test_done_section_bullets_also_capped_per_bullet(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            """
            ## Done

            - Shipped
                - sub one
                - sub two
                - sub three
                - sub four
                - sub five
            """,
        )
        # Done entries are pointer log — the per-bullet rule applies there too.
        assert len(check_file(path)) == 1


# ---------------------------------------------------------------------------
# Done-section entry-count cap (CHU011 rule 2)
# ---------------------------------------------------------------------------


class TestDoneSectionCap:
    """``## Done (recent)`` may contain at most ``_DONE_SECTION_CAP`` entries."""

    def _build_done_log(self, count: int) -> str:
        bullets = "\n".join(f"- entry {index}" for index in range(count))
        return f"## Done (recent)\n{bullets}\n"

    def test_under_cap_passes(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "next-up.md", self._build_done_log(10))
        assert check_file(path) == []

    def test_at_cap_passes(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md", self._build_done_log(_DONE_SECTION_CAP),
        )
        assert check_file(path) == []

    def test_one_over_cap_fails(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md", self._build_done_log(_DONE_SECTION_CAP + 1),
        )
        errors = check_file(path)
        assert len(errors) == 1
        assert f"{_DONE_SECTION_CAP + 1} entries" in errors[0]
        assert f"cap {_DONE_SECTION_CAP}" in errors[0]

    def test_noqa_marker_suppresses_section_cap(self, tmp_path: Path) -> None:
        body = self._build_done_log(_DONE_SECTION_CAP + 5)
        content = "<!-- noqa: CHU011 -->\n" + body
        path = _write(tmp_path, "next-up.md", content)
        assert check_file(path) == []

    def test_section_cap_only_applies_to_next_up_md(self, tmp_path: Path) -> None:
        # A different filename gets only the per-bullet check, not the
        # section-cap check.
        path = _write(
            tmp_path, "other.md", self._build_done_log(_DONE_SECTION_CAP + 100),
        )
        # Each entry is a single bullet so the per-bullet check passes;
        # the section cap is gated to next-up.md so it doesn't fire.
        assert check_file(path) == []

    def test_pre_done_bullets_dont_count_toward_cap(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            "## Next\n"
            + "\n".join(f"- pending {index}" for index in range(50))
            + "\n\n"
            + self._build_done_log(_DONE_SECTION_CAP),
        )
        # ## Next bullets exceed the Done cap numerically, but only
        # bullets after the ## Done heading are counted.
        assert check_file(path) == []


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMainEntry:
    """``main(argv)`` returns 0 on clean files, 1 with violations."""

    def test_clean_file_returns_zero(self, tmp_path: Path) -> None:
        next_up = _write(
            tmp_path, "next-up.md",
            """
            ## Next

            - One-line item.

            ## Done

            - Shipped one.
            """,
        )
        assert main([str(next_up)]) == 0

    def test_violations_return_one(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "next-up.md",
            "## Done\n"
            + "\n".join(f"- entry {index}" for index in range(_DONE_SECTION_CAP + 1)),
        )
        assert main([str(path)]) == 1

    def test_repo_next_up_clean(self) -> None:
        """The actual ``plans/next-up.md`` must satisfy CHU011.

        Locks the cleanup pass: anyone who later grows a bullet past
        the cap or lets the Done log accrete past 25 entries fails
        this test.
        """
        assert main([]) == 0
