"""Tests for CHU006 — no mono-repo-internal references in publishable trees."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu006 import (
    CHU006,
    _outside_chumicro_checks,
    _outside_chumicro_workspace,
    _publishable_package_dirs,
)


def _stage_publishable(
    repo_root: Path,
    parent: str,
    package: str,
    relative: str,
    body: str,
) -> Path:
    """Create ``<repo_root>/<parent>/<package>/<relative>`` with *body* + a marker pyproject."""
    package_dir = repo_root / parent / package
    (package_dir / "pyproject.toml").parent.mkdir(parents=True, exist_ok=True)
    (package_dir / "pyproject.toml").write_text("[project]\nname='fake'\n")
    target = package_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_no_libraries_or_workbench(self, tmp_path: Path) -> None:
        # A bare directory yields no scan roots.
        assert CHU006.check(tmp_path) == []


class TestDecisionPattern:
    def test_decision_ref_flagged(self, tmp_path: Path) -> None:
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", "# See Decision 0042\n")  # noqa: CHU006  fixture string for the rule under test
        findings = CHU006.check(tmp_path)
        assert any("Decision NNNN" in finding.message for finding in findings)

    def test_three_digit_decision_not_matched(self, tmp_path: Path) -> None:
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", "Decision 99 historic\n")
        assert CHU006.check(tmp_path) == []


class TestPlansPattern:
    def test_plans_md_path_flagged(self, tmp_path: Path) -> None:
        _stage_publishable(
            tmp_path,
            "libraries",
            "wifi",
            "src/x.py",
            "# see plans/decisions/0042-foo.md\n",
        )
        findings = CHU006.check(tmp_path)
        assert any("plans/...md" in finding.message for finding in findings)


class TestRunPyPatterns:
    def test_scripts_run_py_flagged(self, tmp_path: Path) -> None:
        body = "# python scripts/" + "run.py setup\n"  # noqa: CHU006  fixture string built so CHU006 doesn't self-flag this test source
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert any("scripts/run.py" in finding.message for finding in findings)

    def test_bare_run_py_flagged_in_normal_package(self, tmp_path: Path) -> None:
        body = "# call " + "run.py for help\n"  # noqa: CHU006  fixture string built so CHU006 doesn't self-flag this test source
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert any("bare " + "run.py" in finding.message for finding in findings)  # noqa: CHU006  assertion text matches the rule's own message

    def test_workspace_package_exempt_from_bare_run_py(self, tmp_path: Path) -> None:
        # Workspace owns the workspace-shim — its tree is exempt.
        body = "# call " + "run.py to start\n"  # noqa: CHU006  fixture string built so CHU006 doesn't self-flag this test source
        _stage_publishable(tmp_path, "workbench", "workspace", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert all("bare " + "run.py" not in finding.message for finding in findings)  # noqa: CHU006  assertion text matches the rule's own message


class TestMonoRepoFraming:
    def test_chumicro_mono_repo_flagged(self, tmp_path: Path) -> None:
        _stage_publishable(
            tmp_path, "libraries", "wifi", "src/x.py", "# from the chumicro mono-repo\n"
        )
        findings = CHU006.check(tmp_path)
        assert any("'chumicro mono-repo'" in finding.message for finding in findings)

    def test_case_insensitive(self, tmp_path: Path) -> None:
        _stage_publishable(
            tmp_path, "libraries", "wifi", "src/x.py", "# the Chumicro Mono-Repo\n"
        )
        assert len(CHU006.check(tmp_path)) >= 1


class TestChuCodeInProse:
    def test_chu_code_in_prose_flagged(self, tmp_path: Path) -> None:
        _stage_publishable(
            tmp_path, "libraries", "wifi", "src/x.py", "# enforced by CHU009\n"
        )
        findings = CHU006.check(tmp_path)
        assert any("CHU lint code" in finding.message for finding in findings)

    def test_noqa_chu_code_not_flagged(self, tmp_path: Path) -> None:
        # The literal `# noqa: CHU009` would self-trip the CHU codes
        # pattern without strip_noqa.  Suppression machinery handles it.
        _stage_publishable(
            tmp_path, "libraries", "wifi", "src/x.py", "x = 1  # noqa: CHU009\n"
        )
        assert CHU006.check(tmp_path) == []


class TestSuppression:
    def test_noqa_chu006_suppresses(self, tmp_path: Path) -> None:
        _stage_publishable(
            tmp_path,
            "libraries",
            "wifi",
            "src/x.py",
            "# Decision 0042  # noqa: CHU006\n",
        )
        assert CHU006.check(tmp_path) == []


class TestScanRoots:
    def test_publishable_dirs_includes_libraries_and_workbench(self, tmp_path: Path) -> None:
        (tmp_path / "libraries" / "wifi").mkdir(parents=True)
        (tmp_path / "workbench" / "deploy").mkdir(parents=True)
        roots = _publishable_package_dirs(tmp_path)
        names = sorted(root.name for root in roots)
        assert names == ["deploy", "wifi"]

    def test_publishable_dirs_includes_test_harness(self, tmp_path: Path) -> None:
        (tmp_path / "support" / "test_harness").mkdir(parents=True)
        roots = _publishable_package_dirs(tmp_path)
        assert any(root.name == "test_harness" for root in roots)


class TestScopePredicates:
    def test_outside_chumicro_workspace(self) -> None:
        assert _outside_chumicro_workspace(Path("workbench/workspace/src/x.py")) is False
        assert _outside_chumicro_workspace(Path("workbench/deploy/src/x.py")) is True

    def test_outside_chumicro_checks(self) -> None:
        assert _outside_chumicro_checks(Path("workbench/checks/src/x.py")) is False
        assert _outside_chumicro_checks(Path("workbench/deploy/src/x.py")) is True


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU006.code == "CHU006"

    def test_description(self) -> None:
        assert "publishable" in CHU006.description.lower()
