"""Tests for check_plans_brevity.py — CHU011."""

from __future__ import annotations

import textwrap
from pathlib import Path

from check_plans_brevity import (
    _BULLET_CAP,
    _CHU011,
    _NOW_LINE_CAP,
    _find_bullet_extents,
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
# next-up.md / now.md — bullet cap (CHU011 rule 1)
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

    def test_noqa_marker_suppresses_violation(self, tmp_path: Path) -> None:
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

    def test_done_section_bullets_also_capped(self, tmp_path: Path) -> None:
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
        # Done entries are pointer log — the rule applies there too.
        assert len(check_file(path)) == 1


# ---------------------------------------------------------------------------
# now.md — file line cap (CHU011 rule 2)
# ---------------------------------------------------------------------------


class TestNowMdFileCap:
    """``plans/now.md`` totals at most ``_NOW_LINE_CAP`` lines."""

    def test_under_cap_passes(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "now.md", "snapshot\n" * 10)
        assert check_file(path) == []

    def test_at_cap_passes(self, tmp_path: Path) -> None:
        # Build a file with exactly _NOW_LINE_CAP lines so the
        # boundary is exercised.
        path = _write(tmp_path, "now.md", "line\n" * _NOW_LINE_CAP)
        assert check_file(path) == []

    def test_one_over_cap_fails(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "now.md", "line\n" * (_NOW_LINE_CAP + 1))
        errors = check_file(path)
        assert len(errors) == 1
        assert f"{_NOW_LINE_CAP + 1} lines" in errors[0]
        assert f"cap {_NOW_LINE_CAP}" in errors[0]

    def test_noqa_marker_suppresses_file_cap(self, tmp_path: Path) -> None:
        content = "<!-- noqa: CHU011 -->\n" + "line\n" * (_NOW_LINE_CAP + 10)
        path = _write(tmp_path, "now.md", content)
        assert check_file(path) == []

    def test_bullet_cap_still_applies_to_now_md(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path, "now.md",
            """
            - lead
                - sub
                - sub
                - sub
                - sub
                - sub
            """,
        )
        errors = check_file(path)
        assert len(errors) == 1
        assert "6 bullet markers" in errors[0]

    def test_other_filenames_skip_file_cap(self, tmp_path: Path) -> None:
        # The 25-line cap is only for now.md — a generic markdown file
        # named differently should not trigger the file-line check.
        path = _write(tmp_path, "next-up.md", "line\n" * (_NOW_LINE_CAP + 50))
        # A 75-line plain-prose file with no bullets has no top-level
        # bullets to check, so check_file returns empty.
        assert check_file(path) == []


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMainEntry:
    """``main(argv)`` returns 0 on clean files, 1 with violations."""

    def test_clean_files_return_zero(self, tmp_path: Path) -> None:
        next_up = _write(
            tmp_path, "next-up.md",
            """
            ## Next

            - One-line item.
            """,
        )
        now = _write(tmp_path, "now.md", "snapshot\n" * 5)
        assert main([str(next_up), str(now)]) == 0

    def test_violations_return_one(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "now.md", "line\n" * (_NOW_LINE_CAP + 1))
        assert main([str(path)]) == 1

    def test_repo_plans_files_clean(self) -> None:
        """The actual ``plans/next-up.md`` + ``plans/now.md`` must satisfy CHU011.

        This locks the cleanup pass: anyone who later grows a bullet
        past the cap or now.md past 25 lines fails this test.
        """
        assert main([]) == 0
