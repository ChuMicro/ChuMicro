"""Tests for CHU029: ADR Summary frontmatter field."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu029 import CHU029


def _stage_adr(repo_root: Path, slug: str, body: str) -> Path:
    decisions = repo_root / "plans" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    target = decisions / f"{slug}.md"
    target.write_text(body, encoding="utf-8")
    return target


_GOOD_HEADER = (
    "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
    "\n"
    "Status: `accepted`\n"
    "Date: `2026-05-24`\n"
    "Summary: A one-sentence summary that names what was decided.\n"
    "Related: none\n"
    "\n"
    "## Context\n"
)


class TestSilentNoOp:
    def test_no_decisions_dir(self, tmp_path: Path) -> None:
        assert CHU029.check(tmp_path) == []

    def test_clean_adr_passes(self, tmp_path: Path) -> None:
        _stage_adr(tmp_path, "0042-foo", _GOOD_HEADER)
        assert CHU029.check(tmp_path) == []

    def test_readme_skipped(self, tmp_path: Path) -> None:
        decisions = tmp_path / "plans" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "README.md").write_text("no summary needed here\n")
        assert CHU029.check(tmp_path) == []

    def test_non_numbered_file_skipped(self, tmp_path: Path) -> None:
        _stage_adr(tmp_path, "notes", "no summary needed here\n")
        assert CHU029.check(tmp_path) == []


class TestMissingSummary:
    def test_no_summary_field_flagged(self, tmp_path: Path) -> None:
        body = (
            "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
            "\n"
            "Status: `accepted`\n"
            "Date: `2026-05-24`\n"
            "Related: none\n"
            "\n"
            "## Context\n"
        )
        _stage_adr(tmp_path, "0042-foo", body)
        findings = CHU029.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU029"
        assert "missing" in findings[0].message

    def test_summary_after_frontmatter_window_flagged(
        self, tmp_path: Path,
    ) -> None:
        # Summary appears on line 12, past the 10-line frontmatter window.
        body = (
            "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
            "\n"
            "Status: `accepted`\n"
            "Date: `2026-05-24`\n"
            "Related: none\n"
            "\n"
            "## Context\n"
            "\n"
            "Some context paragraph.\n"
            "Another paragraph.\n"
            "Another paragraph.\n"
            "Summary: This is too late to count.\n"
        )
        _stage_adr(tmp_path, "0042-foo", body)
        findings = CHU029.check(tmp_path)
        assert len(findings) == 1
        assert "missing" in findings[0].message


class TestEmptySummary:
    def test_bare_summary_colon_flagged(self, tmp_path: Path) -> None:
        body = (
            "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
            "\n"
            "Status: `accepted`\n"
            "Date: `2026-05-24`\n"
            "Summary:\n"
            "Related: none\n"
            "\n"
            "## Context\n"
        )
        _stage_adr(tmp_path, "0042-foo", body)
        findings = CHU029.check(tmp_path)
        assert len(findings) == 1
        assert "empty" in findings[0].message

    def test_summary_with_only_whitespace_flagged(
        self, tmp_path: Path,
    ) -> None:
        body = (
            "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
            "\n"
            "Status: `accepted`\n"
            "Date: `2026-05-24`\n"
            "Summary:    \n"
            "Related: none\n"
            "\n"
            "## Context\n"
        )
        _stage_adr(tmp_path, "0042-foo", body)
        findings = CHU029.check(tmp_path)
        assert len(findings) == 1
        assert "empty" in findings[0].message


class TestOversizedSummary:
    def test_201_char_summary_flagged(self, tmp_path: Path) -> None:
        oversized = "x" * 201
        body = (
            "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
            "\n"
            "Status: `accepted`\n"
            "Date: `2026-05-24`\n"
            f"Summary: {oversized}\n"
            "Related: none\n"
            "\n"
            "## Context\n"
        )
        _stage_adr(tmp_path, "0042-foo", body)
        findings = CHU029.check(tmp_path)
        assert len(findings) == 1
        assert "201 chars" in findings[0].message
        assert "cap 200" in findings[0].message

    def test_exact_200_char_summary_passes(self, tmp_path: Path) -> None:
        at_cap = "x" * 200
        body = (
            "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
            "\n"
            "Status: `accepted`\n"
            "Date: `2026-05-24`\n"
            f"Summary: {at_cap}\n"
            "Related: none\n"
            "\n"
            "## Context\n"
        )
        _stage_adr(tmp_path, "0042-foo", body)
        assert CHU029.check(tmp_path) == []


class TestSuppression:
    def test_noqa_suppresses_missing(self, tmp_path: Path) -> None:
        body = (
            "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
            "\n"
            "Status: `accepted`\n"
            "Date: `2026-05-24`\n"
            "Related: none\n"
            "\n"
            "<!-- noqa: CHU029 -->\n"
        )
        _stage_adr(tmp_path, "0042-foo", body)
        assert CHU029.check(tmp_path) == []

    def test_noqa_suppresses_oversized(self, tmp_path: Path) -> None:
        oversized = "x" * 300
        body = (
            "# Decision 0042: Example\n"  # noqa: CHU006  fixture: ADR-body data
            "\n"
            "Status: `accepted`\n"
            "Date: `2026-05-24`\n"
            f"Summary: {oversized}\n"
            "Related: none\n"
            "\n"
            "<!-- noqa: CHU029 -->\n"
        )
        _stage_adr(tmp_path, "0042-foo", body)
        assert CHU029.check(tmp_path) == []


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU029.code == "CHU029"

    def test_description_present(self) -> None:
        assert "Summary" in CHU029.description
