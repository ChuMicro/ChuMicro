"""Tests for CHU019: archived-decision marker consistency."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu019 import CHU019


def _adr(repo_root: Path, name: str, body: str) -> Path:
    target = repo_root / "plans" / "decisions" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def _codes(repo_root: Path) -> list[str]:
    return [finding.code for finding in CHU019.check(repo_root)]


_LIVE = "# 0042: A live one\n\nStatus: `accepted`\nDate: `2026-01-01`\n"
_SUPERSEDED = (
    "# 0035: Old shape\n\nStatus: `superseded`\n"
    "Date: `2026-01-01`\nSuperseded by: [0036](0036-x.md)\n"
)
_INERT = (
    "# 0004: Bootstrap\n\nStatus: `accepted`\nDate: `2026-01-01`\n"
    "Archived: inert — every seam it deferred has shipped.\n"
)


class TestSilentNoOp:
    def test_no_decisions_dir(self, tmp_path: Path) -> None:
        assert CHU019.check(tmp_path) == []

    def test_readme_is_skipped(self, tmp_path: Path) -> None:
        _adr(tmp_path, "README.md", "# Decisions\n\nStatus: `accepted`\n")
        assert CHU019.check(tmp_path) == []

    def test_file_without_status_skipped(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0099-notes.md", "# Just notes\n\nNo status here.\n")
        assert CHU019.check(tmp_path) == []


class TestClean:
    def test_live_adr(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0042-a-live-one.md", _LIVE)
        assert CHU019.check(tmp_path) == []

    def test_correctly_superseded(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0035-SUPERSEDED-BY-0036-old-shape.md", _SUPERSEDED)
        assert CHU019.check(tmp_path) == []

    def test_correctly_inert(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0004-INERT-bootstrap.md", _INERT)
        assert CHU019.check(tmp_path) == []


class TestSupersededContract:
    def test_status_superseded_without_marker(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0035-old-shape.md", _SUPERSEDED)
        assert _codes(tmp_path) == ["CHU019"]

    def test_marker_without_superseded_status(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0035-SUPERSEDED-BY-0036-old-shape.md", _LIVE)
        # accepted-status with the marker disagrees on status.
        assert "CHU019" in _codes(tmp_path)

    def test_superseded_without_pointer_line(self, tmp_path: Path) -> None:
        body = "# 0035: X\n\nStatus: `superseded`\nDate: `x`\n"
        _adr(tmp_path, "0035-SUPERSEDED-BY-0036-x.md", body)
        assert _codes(tmp_path) == ["CHU019"]

    def test_successor_mismatch(self, tmp_path: Path) -> None:
        body = (
            "# 0035: X\n\nStatus: `superseded`\nDate: `x`\n"
            "Superseded by: [0099](0099-y.md)\n"
        )
        _adr(tmp_path, "0035-SUPERSEDED-BY-0036-x.md", body)
        assert _codes(tmp_path) == ["CHU019"]


class TestInertContract:
    def test_inert_marker_without_archived_field(
        self, tmp_path: Path
    ) -> None:
        body = "# 0004: X\n\nStatus: `accepted`\nDate: `x`\n"
        _adr(tmp_path, "0004-INERT-x.md", body)
        assert _codes(tmp_path) == ["CHU019"]

    def test_inert_must_stay_accepted(self, tmp_path: Path) -> None:
        body = (
            "# 0004: X\n\nStatus: `superseded`\nDate: `x`\n"
            "Superseded by: [0009](0009-y.md)\n"
            "Archived: inert — spent.\n"
        )
        _adr(tmp_path, "0004-INERT-x.md", body)
        # superseded status + INERT marker disagree.
        assert "CHU019" in _codes(tmp_path)

    def test_archived_field_without_marker(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0004-bootstrap.md", _INERT)
        assert _codes(tmp_path) == ["CHU019"]


class TestStructural:
    def test_non_numbered_file_is_checked_but_not_prefix_tracked(
        self, tmp_path: Path
    ) -> None:
        # A decision-dir file without an NNNN- prefix: still content-
        # checked (has Status), but excluded from number-collision
        # tracking. A clean live one yields nothing.
        _adr(tmp_path, "draft-idea.md", _LIVE)
        assert CHU019.check(tmp_path) == []

    def test_duplicate_number_prefix(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0009-first.md", _LIVE)
        _adr(tmp_path, "0009-second.md", _LIVE)
        findings = CHU019.check(tmp_path)
        assert len(findings) == 2
        assert all(finding.code == "CHU019" for finding in findings)
        assert all(
            "number 0009" in finding.message for finding in findings
        )

    def test_intentional_number_gap_is_fine(self, tmp_path: Path) -> None:
        _adr(tmp_path, "0049-a.md", _LIVE)
        _adr(tmp_path, "0051-b.md", _LIVE)  # 0050 deliberately absent
        assert CHU019.check(tmp_path) == []


class TestSuppression:
    def test_noqa_suppresses_file(self, tmp_path: Path) -> None:
        body = _SUPERSEDED + "\n<!-- noqa: CHU019 -->\n"
        _adr(tmp_path, "0035-old-shape.md", body)  # missing marker, but noqa
        assert CHU019.check(tmp_path) == []
