"""Tests for CHU024: banned ADR-authoring section markers."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu024 import CHU024


def _stage_decision(repo_root: Path, slug: str, body: str) -> Path:
    """Stage an ADR file under ``plans/decisions/`` and return its path."""
    decisions = repo_root / "plans" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    target = decisions / f"{slug}.md"
    target.write_text(body, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_no_decisions_dir(self, tmp_path: Path) -> None:
        assert CHU024.check(tmp_path) == []

    def test_clean_adr(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "# Decision 0042 — Foo\n\n## Context\n\nBaseline shape.\n",  # noqa: CHU006  fixture: ADR-body data
        )
        assert CHU024.check(tmp_path) == []


class TestSectionHeadingBanners:
    def test_update_heading_flagged(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\nBaseline.\n\n## Update (2026-05-19)\n\nLater.\n",
        )
        findings = CHU024.check(tmp_path)
        assert len(findings) == 1
        assert "Update" in findings[0].message

    def test_amendments_heading_flagged(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\nBaseline.\n\n## Amendments\n\nLater.\n",
        )
        findings = CHU024.check(tmp_path)
        assert any("Amendments" in finding.message for finding in findings)

    def test_changelog_heading_flagged(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\n## Changelog\n\nv2 changed X.\n",
        )
        findings = CHU024.check(tmp_path)
        assert any("Changelog" in finding.message for finding in findings)

    def test_progress_notes_heading_flagged(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\n## Progress notes\n\nLanded phase 1.\n",
        )
        findings = CHU024.check(tmp_path)
        assert any("Progress notes" in finding.message for finding in findings)


class TestBlockquoteBanner:
    def test_amended_by_blockquote_flagged(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\n> **Note:** Amended by Decision 0050.\n\nText.\n",  # noqa: CHU006  fixture: ADR-body data
        )
        findings = CHU024.check(tmp_path)
        assert any("Amended by" in finding.message for finding in findings)


class TestNarrativeRevisions:
    def test_this_was_revised_flagged(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\nEarlier draft did X.  This was revised: now Y.\n",
        )
        findings = CHU024.check(tmp_path)
        assert any("revision narrative" in finding.message for finding in findings)

    def test_decision_has_been_revised_flagged(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\nNote: this decision has been revised twice.\n",
        )
        findings = CHU024.check(tmp_path)
        assert any("revision preamble" in finding.message for finding in findings)


class TestDatedRevisionBanner:
    def test_revised_dated_line_flagged(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "# Decision 0042\n\nRevised: 2026-05-19 — vocabulary update.\n\n## Context\n",  # noqa: CHU006  fixture: ADR-body data
        )
        findings = CHU024.check(tmp_path)
        assert any("dated revision banner" in finding.message for finding in findings)


class TestExemptScopes:
    def test_other_docs_not_walked(self, tmp_path: Path) -> None:
        # Out-of-scope: docs/, plans/workstreams/, README outside decisions.
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "x.md").write_text("## Update (2026-05-19)\n")
        assert CHU024.check(tmp_path) == []

    def test_anchored_pattern_skips_inline_naming(self, tmp_path: Path) -> None:
        # A line that names the banned heading inside backticks (as the
        # README does when *describing* the rule) doesn't start with
        # ``## ``. The anchored pattern skips it.
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\nDo not add `## Update (YYYY-MM-DD)` sections.\n",
        )
        assert CHU024.check(tmp_path) == []


class TestSuppression:
    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        _stage_decision(
            tmp_path,
            "0042-foo",
            "## Context\n\nThis was revised twice.  <!-- noqa: CHU024 -->\n",
        )
        assert CHU024.check(tmp_path) == []


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU024.code == "CHU024"

    def test_description_present(self) -> None:
        assert "ADR" in CHU024.description or "banner" in CHU024.description
