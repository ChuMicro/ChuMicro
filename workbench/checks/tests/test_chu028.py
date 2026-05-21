"""Tests for CHU028: cross-ADR principle duplication."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu028 import CHU028

#: Long enough to clear the 20-token floor.
_LONG_PARAGRAPH = (
    "This invariant binds every device library in the workspace and "
    "is enforced by the deploy walker before any stage primitive runs. "
    "Violations surface at deploy time rather than at first boot, which "
    "matters because first-boot failures cost a recovery cycle."
)


def _stage_adr(repo_root: Path, slug: str, body: str) -> Path:
    decisions = repo_root / "plans" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    target = decisions / f"{slug}.md"
    target.write_text(body, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_no_decisions_dir(self, tmp_path: Path) -> None:
        assert CHU028.check(tmp_path) == []

    def test_single_adr(self, tmp_path: Path) -> None:
        _stage_adr(
            tmp_path,
            "0042-foo",
            "# Decision 0042\n\nStatus: `accepted`\n\n## Context\n\n"  # noqa: CHU006  fixture: ADR-body data
            + _LONG_PARAGRAPH + "\n",
        )
        assert CHU028.check(tmp_path) == []

    def test_distinct_paragraphs_pass(self, tmp_path: Path) -> None:
        _stage_adr(
            tmp_path, "0042-foo",
            "## Context\n\n" + _LONG_PARAGRAPH + "\n",
        )
        _stage_adr(
            tmp_path, "0043-bar",
            "## Context\n\nA completely different paragraph that has "
            "more than twenty words just to make sure the min token "
            "floor is cleared and the test stays valid.\n",
        )
        assert CHU028.check(tmp_path) == []


class TestCrossAdrDuplication:
    def test_two_adrs_sharing_paragraph_flagged(
        self, tmp_path: Path,
    ) -> None:
        _stage_adr(
            tmp_path, "0042-foo",
            "## Context\n\n" + _LONG_PARAGRAPH + "\n",
        )
        _stage_adr(
            tmp_path, "0043-bar",
            "## Decision\n\n" + _LONG_PARAGRAPH + "\n",
        )
        findings = CHU028.check(tmp_path)
        assert len(findings) == 2
        assert "duplicated across 2 ADRs" in findings[0].message

    def test_readme_excluded(self, tmp_path: Path) -> None:
        _stage_adr(
            tmp_path, "0042-foo",
            "## Context\n\n" + _LONG_PARAGRAPH + "\n",
        )
        readme = tmp_path / "plans" / "decisions" / "README.md"
        readme.write_text(_LONG_PARAGRAPH + "\n", encoding="utf-8")
        # README is excluded; only one ADR contains the paragraph.
        assert CHU028.check(tmp_path) == []


class TestScaffoldingNotFlagged:
    """Section headers and ADR metadata are scaffolding boundaries."""

    def test_section_header_shared_not_flagged(self, tmp_path: Path) -> None:
        _stage_adr(
            tmp_path, "0042-foo",
            "## Context\n\nUnique content for foo.\n",
        )
        _stage_adr(
            tmp_path, "0043-bar",
            "## Context\n\nUnique content for bar.\n",
        )
        assert CHU028.check(tmp_path) == []

    def test_metadata_fields_not_flagged(self, tmp_path: Path) -> None:
        # Status / Date / Related lines repeat across every ADR by
        # design.  They split paragraphs, never contribute content.
        for slug in ("0042-foo", "0043-bar"):
            _stage_adr(
                tmp_path, slug,
                f"# Decision {slug}\n\n"
                "Status: `accepted`\n"
                "Date: `2026-05-19`\n"
                "Related: none\n\n"
                f"## Context\n\nUnique content for {slug}.\n",
            )
        assert CHU028.check(tmp_path) == []


class TestMinTokenFloor:
    def test_short_paragraph_below_floor_not_flagged(
        self, tmp_path: Path,
    ) -> None:
        short = "Short shared sentence here.\n"
        _stage_adr(tmp_path, "0042-foo", "## Context\n\n" + short)
        _stage_adr(tmp_path, "0043-bar", "## Decision\n\n" + short)
        assert CHU028.check(tmp_path) == []


class TestSuppression:
    def test_noqa_on_paragraph_suppresses(self, tmp_path: Path) -> None:
        # The convention: the *why* AGENTS.md requires lives in
        # surrounding prose (separated by a blank line so it forms
        # its own paragraph, below the floor). The noqa marker sits
        # on its own line at the top of the suppressed paragraph.
        suppressed_body = (
            "## Context\n\n"
            "Intentional cross-link to Decision 0078.\n\n"  # noqa: CHU006  fixture: ADR-body data
            "<!-- noqa: CHU028 -->\n"
            + _LONG_PARAGRAPH + "\n"
        )
        unsuppressed_body = "## Decision\n\n" + _LONG_PARAGRAPH + "\n"
        _stage_adr(tmp_path, "0042-foo", suppressed_body)
        _stage_adr(tmp_path, "0043-bar", unsuppressed_body)
        findings = CHU028.check(tmp_path)
        # Only bar's finding remains.
        assert len(findings) == 1
        assert "0043-bar" in str(findings[0].path)


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU028.code == "CHU028"

    def test_description_present(self) -> None:
        assert "ADR" in CHU028.description
