"""Tests for CHU012 — dated narration / workstream-phase pointers."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu012 import CHU012


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    """Stage *content* at ``repo_root/relative`` and return the path."""
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    """Repos without any scan roots emit no findings."""

    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU012.check(tmp_path) == []

    def test_only_unrelated_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.py").write_text("# Captured 2026-05-09 incident\n")
        # The rule scans `libraries/`, `workbench/`, `support/`, `scripts/`.
        # Files outside those roots aren't checked — silent no-op.
        assert CHU012.check(tmp_path) == []


class TestPatternHits:
    """Every documented pattern fires at least once."""

    def test_dated_incident_surfaced(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# Surfaced 2026-05-09\n")
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU012"
        assert "dated incident" in findings[0].message

    def test_dated_verified_live(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# verified live 2026-05-09\n")
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1
        assert "dated verification" in findings[0].message

    def test_workstream_phase_pointer(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# Phase 7 of the auth workstream\n")
        findings = CHU012.check(tmp_path)
        assert any("workstream-phase" in finding.message for finding in findings)

    def test_phase_n_without_colon(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# Phase 4 follow-up\n")
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1

    def test_phase_n_with_colon_passes(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# Step 1: do this thing\n")
        assert CHU012.check(tmp_path) == []

    def test_item_n_pointer(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# Item 4 caveat applies here\n")
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1

    def test_removed_code_framing(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# Previously this used a global\n")
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1
        assert "removed-code framing" in findings[0].message

    def test_workstream_named_audit(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# in the deploy-audit pass\n")
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1

    def test_retained_until_lands(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "# retained only until the clean-slate default lands\n",
        )
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1
        assert "landed-history" in findings[0].message

    def test_before_landed(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# before the sentinel landed\n")
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1
        assert "landed-history" in findings[0].message

    def test_deferred_until(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "# deferred until a hardware-cheap probe is ready\n",
        )
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1
        assert "deferred-work" in findings[0].message

    def test_until_we_have_a(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "# until we have a hardware-cheap probe primitive\n",
        )
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1
        assert "deferred-work" in findings[0].message

    def test_lands_in_docstring_caught(self, tmp_path: Path) -> None:
        # The line-by-line scan covers docstrings too, no AST needed.
        _stage(
            tmp_path,
            "support/notes.py",
            '"""\nThis helper is retained only until the new path lands.\n"""\n',
        )
        findings = CHU012.check(tmp_path)
        assert len(findings) == 1


class TestSuppression:
    """``# noqa: CHU012`` mutes the rule on that line."""

    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# Surfaced 2026-05-09  # noqa: CHU012\n")
        assert CHU012.check(tmp_path) == []

    def test_html_noqa_suppresses_in_markdown(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "support/notes.md",
            "Surfaced 2026-05-09 <!-- noqa: CHU012 -->\n",
        )
        assert CHU012.check(tmp_path) == []

    def test_unrelated_noqa_does_not_suppress(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "# Surfaced 2026-05-09  # noqa: CHU001\n")
        assert len(CHU012.check(tmp_path)) == 1


class TestSelfExempt:
    """The rule's own source / tests are exempt."""

    def test_new_rule_source_is_exempt(self, tmp_path: Path) -> None:
        # Even with a forbidden pattern in the file, self-exempt keeps it
        # off the findings list.
        _stage(
            tmp_path,
            "workbench/checks/src/chumicro_checks/rules/chu012.py",
            "# Previously this had a different shape\n",
        )
        assert CHU012.check(tmp_path) == []

    def test_new_rule_tests_are_exempt(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/checks/tests/test_chu012.py",
            "# Surfaced 2026-05-09\n",
        )
        assert CHU012.check(tmp_path) == []


class TestScannedSuffixes:
    """Only ``.py`` and ``.md`` files are walked."""

    def test_yaml_not_scanned(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.yml", "# Surfaced 2026-05-09\n")
        assert CHU012.check(tmp_path) == []

    def test_markdown_scanned(self, tmp_path: Path) -> None:
        _stage(tmp_path, "support/notes.md", "Surfaced 2026-05-09\n")
        assert len(CHU012.check(tmp_path)) == 1


class TestTemplateShapeScopes:
    """Template / workspace top-level trees are walked too."""

    def test_packages_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "packages/foo/bar.py", "# Surfaced 2026-05-09\n")
        assert len(CHU012.check(tmp_path)) == 1

    def test_projects_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "projects/wifi/app.py", "# Phase 4 follow-up\n")
        assert len(CHU012.check(tmp_path)) == 1

    def test_shared_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "shared/util.py", "# Item 4 caveat\n")
        assert len(CHU012.check(tmp_path)) == 1

    def test_examples_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "examples/blink.md", "Surfaced 2026-05-09\n")
        assert len(CHU012.check(tmp_path)) == 1

    def test_root_tests_walked(self, tmp_path: Path) -> None:
        _stage(tmp_path, "tests/test_foo.py", "# Surfaced 2026-05-09\n")
        assert len(CHU012.check(tmp_path)) == 1


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU012.code == "CHU012"

    def test_description_present(self) -> None:
        assert "dated" in CHU012.description.lower()
