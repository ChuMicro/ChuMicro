"""Tests for CHU008 — no upstream-derivative framing in workspace-template trees."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu008 import (
    CHU008,
    _template_repo_scan_roots,
)

# Forbidden-pattern fixtures built at runtime so CHU006 (which scans
# this test file too) doesn't see literal violation patterns in the
# source.  CHU008 reading the staged content sees the assembled string
# and matches as expected.
_DECISION_REF = "Decision " + "0042"
_PLANS_PATH = "plans/" + "decisions/0001-foo.md"
_SCRIPTS_RUN_PY = "scripts/run" + ".py"
_MONO_REPO_FRAMING = "chumicro " + "mono-repo"


def _make_template_repo(repo_root: Path) -> None:
    """Stage the minimum directory shape that detects-as-template-repo.

    A `packages/` directory at the root is the detection signal.
    """
    (repo_root / "packages").mkdir()


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_mono_repo_shape_no_op(self, tmp_path: Path) -> None:
        # Mono-repo has libraries/ but not packages/ — CHU008 self-no-ops.
        (tmp_path / "libraries").mkdir()
        _stage(tmp_path, "README.md", f"{_DECISION_REF} — see {_PLANS_PATH}\n")
        assert CHU008.check(tmp_path) == []

    def test_empty_repo_no_op(self, tmp_path: Path) -> None:
        assert CHU008.check(tmp_path) == []


class TestTemplateRepoDetection:
    def test_packages_dir_triggers_scanning(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "README.md", f"see {_DECISION_REF}\n")
        findings = CHU008.check(tmp_path)
        assert len(findings) == 1

    def test_no_packages_dir_means_no_op(self, tmp_path: Path) -> None:
        _stage(tmp_path, "projects/foo/x.py", f"# {_DECISION_REF}\n")
        # Without `packages/`, the rule self-no-ops even though the
        # forbidden pattern is present.
        assert CHU008.check(tmp_path) == []


class TestPatterns:
    def test_decision_ref_in_project_config(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "projects/wifi/project_config.toml", f"# {_DECISION_REF}\n")
        findings = CHU008.check(tmp_path)
        assert any("Decision/ADR NNNN" in finding.message for finding in findings)

    def test_adr_reference_in_project_config(self, tmp_path: Path) -> None:
        # Symmetric with the Decision case: the ADR-NNNN shape is the same concept.
        adr_reference = "ADR " + "0042"
        _make_template_repo(tmp_path)
        _stage(tmp_path, "projects/wifi/project_config.toml", f"# {adr_reference}\n")
        findings = CHU008.check(tmp_path)
        assert any("Decision/ADR NNNN" in finding.message for finding in findings)

    def test_plans_md_ref_in_examples(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "examples/blink.py", f"# see {_PLANS_PATH}\n")
        findings = CHU008.check(tmp_path)
        assert any("plans/...md" in finding.message for finding in findings)

    def test_scripts_run_py_reference(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "shared/util.py", f"# python {_SCRIPTS_RUN_PY} setup\n")
        findings = CHU008.check(tmp_path)
        assert any("scripts/run.py" in finding.message for finding in findings)

    def test_chumicro_mono_repo_framing(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "AGENTS.md", f"from the {_MONO_REPO_FRAMING}\n")
        findings = CHU008.check(tmp_path)
        assert any("'chumicro mono-repo'" in finding.message for finding in findings)


class TestRootLevelFiles:
    def test_workspace_yml_scanned(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "workspace.yml", f"# {_DECISION_REF}\n")
        findings = CHU008.check(tmp_path)
        assert len(findings) == 1

    def test_devices_yml_scanned(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "devices.yml", f"# see {_PLANS_PATH}\n")
        findings = CHU008.check(tmp_path)
        assert len(findings) == 1

    def test_root_pyproject_scanned(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "pyproject.toml", f"# {_DECISION_REF}\n")
        findings = CHU008.check(tmp_path)
        assert len(findings) == 1


class TestSuppression:
    def test_noqa_suppresses_in_python(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(
            tmp_path,
            "shared/util.py",
            f"# {_DECISION_REF} here  # noqa: CHU008\n",
        )
        assert CHU008.check(tmp_path) == []

    def test_html_noqa_in_markdown(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        _stage(tmp_path, "README.md", f"{_DECISION_REF} <!-- noqa: CHU008 -->\n")
        assert CHU008.check(tmp_path) == []


class TestScanRoots:
    def test_returns_empty_without_packages_dir(self, tmp_path: Path) -> None:
        # Even with other template subdirs present, no `packages/` →
        # silent.
        (tmp_path / "projects").mkdir()
        (tmp_path / "examples").mkdir()
        assert _template_repo_scan_roots(tmp_path) == []

    def test_yields_present_subdirs_only(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        (tmp_path / "projects").mkdir()
        roots = _template_repo_scan_roots(tmp_path)
        names = sorted(root.name for root in roots)
        # `examples/`, `shared/`, `tests/` are absent — only present
        # subdirs come back.
        assert names == ["packages", "projects"]

    def test_yields_present_root_files(self, tmp_path: Path) -> None:
        _make_template_repo(tmp_path)
        (tmp_path / "README.md").write_text("hi\n")
        (tmp_path / "workspace.yml").write_text("---\n")
        roots = _template_repo_scan_roots(tmp_path)
        names = sorted(root.name for root in roots)
        assert "README.md" in names
        assert "workspace.yml" in names


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU008.code == "CHU008"

    def test_description(self) -> None:
        assert "template" in CHU008.description.lower()
