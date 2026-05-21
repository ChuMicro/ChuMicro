"""Tests for CHU026: orphan governance-doc files."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu026 import CHU026


def _write(repo_root: Path, relative: str, body: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_no_claude_md(self, tmp_path: Path) -> None:
        # Without CLAUDE.md the rule has nothing to walk.
        _write(tmp_path, "AGENTS.md", "Some rules.\n")
        assert CHU026.check(tmp_path) == []

    def test_clean_repo(self, tmp_path: Path) -> None:
        _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
        _write(tmp_path, "AGENTS.md", "Some rules with no governance refs.\n")
        assert CHU026.check(tmp_path) == []


class TestOrphanDetection:
    def test_orphan_agents_notes_flagged(self, tmp_path: Path) -> None:
        _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
        _write(
            tmp_path,
            "AGENTS.md",
            "See AGENTS.notes.md for rationale.\n",
        )
        _write(tmp_path, "AGENTS.notes.md", "Detail content.\n")
        findings = CHU026.check(tmp_path)
        assert len(findings) == 1
        assert "AGENTS.notes.md" in findings[0].message

    def test_orphan_rules_md_flagged(self, tmp_path: Path) -> None:
        _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
        _write(tmp_path, "AGENTS.md", "See RULES.md for the strict subset.\n")
        _write(tmp_path, "RULES.md", "Strict rules.\n")
        findings = CHU026.check(tmp_path)
        assert any("RULES.md" in finding.message for finding in findings)

    def test_orphan_guidelines_file_flagged(self, tmp_path: Path) -> None:
        _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
        _write(
            tmp_path,
            "AGENTS.md",
            "See STYLE_GUIDELINES.md for tone.\n",
        )
        _write(tmp_path, "STYLE_GUIDELINES.md", "Guidelines.\n")
        findings = CHU026.check(tmp_path)
        assert any("STYLE_GUIDELINES.md" in finding.message for finding in findings)


class TestNoFalsePositives:
    def test_reference_to_nonexistent_file_skipped(
        self, tmp_path: Path,
    ) -> None:
        # File doesn't exist on disk, so this is a CHU006-class leak instead of the orphan shape.
        _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
        _write(tmp_path, "AGENTS.md", "See RULES.md for ...\n")
        # No RULES.md written.
        assert CHU026.check(tmp_path) == []

    def test_reachable_governance_doc_not_flagged(
        self, tmp_path: Path,
    ) -> None:
        # AGENTS.notes.md is referenced AND reachable via @-include.
        _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n@AGENTS.notes.md\n")
        _write(tmp_path, "AGENTS.md", "See AGENTS.notes.md for detail.\n")
        _write(tmp_path, "AGENTS.notes.md", "Detail.\n")
        assert CHU026.check(tmp_path) == []

    def test_transitive_reachability_via_at_include(
        self, tmp_path: Path,
    ) -> None:
        # CLAUDE.md -> AGENTS.md -> @AGENTS.notes.md (transitive include).
        _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
        _write(
            tmp_path,
            "AGENTS.md",
            "@AGENTS.notes.md\n\nSee AGENTS.notes.md for detail.\n",
        )
        _write(tmp_path, "AGENTS.notes.md", "Detail.\n")
        assert CHU026.check(tmp_path) == []


class TestSuppression:
    def test_noqa_on_line_suppresses(self, tmp_path: Path) -> None:
        _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
        _write(
            tmp_path,
            "AGENTS.md",
            "See RULES.md for the strict rules.  <!-- noqa: CHU026 -->\n",
        )
        _write(tmp_path, "RULES.md", "Rules.\n")
        assert CHU026.check(tmp_path) == []


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU026.code == "CHU026"

    def test_description_present(self) -> None:
        assert "governance" in CHU026.description.lower()
