"""Tests for CHU025 — Superseded-by pointer integrity."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu025 import CHU025


def _stage_adr(repo_root: Path, slug: str, body: str) -> Path:
    decisions = repo_root / "plans" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    target = decisions / f"{slug}.md"
    target.write_text(body, encoding="utf-8")
    return target


def _stage_target(repo_root: Path, number: str, name: str = "foo") -> Path:
    """Stage a stub ADR file so existence-check passes."""
    decisions = repo_root / "plans" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    target = decisions / f"{number}-{name}.md"
    target.write_text(f"# Decision {number}\n\nStatus: `accepted`\n")
    return target


class TestSilentNoOp:
    def test_no_decisions_dir(self, tmp_path: Path) -> None:
        assert CHU025.check(tmp_path) == []

    def test_clean_adr_passes(self, tmp_path: Path) -> None:
        _stage_adr(
            tmp_path,
            "0042-foo",
            "# Decision 0042\n\nStatus: `accepted`\n\n## Context\n",  # noqa: CHU006  fixture: ADR-body data
        )
        assert CHU025.check(tmp_path) == []

    def test_superseded_with_valid_target_passes(self, tmp_path: Path) -> None:
        _stage_target(tmp_path, "0050")
        _stage_adr(
            tmp_path,
            "0042-SUPERSEDED-BY-0050-foo",
            "# Decision 0042\n\n"  # noqa: CHU006  fixture: ADR-body data
            "Status: `superseded`\n"
            "Superseded by: [Decision 0050](0050-foo.md)\n",  # noqa: CHU006  fixture: ADR-body data
        )
        assert CHU025.check(tmp_path) == []


class TestDanglingCite:
    def test_superseded_by_missing_target_flagged(
        self, tmp_path: Path,
    ) -> None:
        _stage_adr(
            tmp_path,
            "0042-foo",
            "# Decision 0042\n\n"  # noqa: CHU006  fixture: ADR-body data
            "Status: `superseded`\n"
            "Superseded by: [Decision 0099](0099-foo.md)\n",  # noqa: CHU006  fixture: ADR-body data
        )
        findings = CHU025.check(tmp_path)
        assert any("0099" in finding.message for finding in findings)
        assert any("no `0099-*.md`" in finding.message for finding in findings)

    def test_filename_marker_missing_target_flagged(
        self, tmp_path: Path,
    ) -> None:
        # filename marker cites 0099 but no 0099-*.md exists.
        _stage_adr(
            tmp_path,
            "0042-SUPERSEDED-BY-0099-foo",
            "# Decision 0042\n\n"  # noqa: CHU006  fixture: ADR-body data
            "Status: `superseded`\n"
            "Superseded by: [Decision 0099](0099-foo.md)\n",  # noqa: CHU006  fixture: ADR-body data
        )
        findings = CHU025.check(tmp_path)
        # Two findings: one for the cite, one for the filename marker.
        assert len(findings) == 2
        assert any("filename marks" in finding.message for finding in findings)


class TestHalfFinishedSupersession:
    def test_accepted_with_superseded_by_flagged(
        self, tmp_path: Path,
    ) -> None:
        _stage_target(tmp_path, "0050")
        _stage_adr(
            tmp_path,
            "0042-foo",
            "# Decision 0042\n\n"  # noqa: CHU006  fixture: ADR-body data
            "Status: `accepted`\n"
            "Superseded by: [Decision 0050](0050-foo.md)\n",  # noqa: CHU006  fixture: ADR-body data
        )
        findings = CHU025.check(tmp_path)
        assert any("accepted" in finding.message for finding in findings)


class TestSuppression:
    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        _stage_adr(
            tmp_path,
            "0042-foo",
            "# Decision 0042\n\n"  # noqa: CHU006  fixture: ADR-body data
            "Status: `accepted`\n"
            "Superseded by: [Decision 0099](0099-foo.md)\n"  # noqa: CHU006  fixture: ADR-body data
            "<!-- noqa: CHU025 -->\n",
        )
        assert CHU025.check(tmp_path) == []


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU025.code == "CHU025"

    def test_description_present(self) -> None:
        assert "Superseded" in CHU025.description
