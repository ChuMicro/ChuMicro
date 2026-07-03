"""Tests for CHU006: no mono-repo-internal references in publishable trees."""

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
        assert any("Decision/ADR NNNN" in finding.message for finding in findings)

    def test_adr_ref_flagged(self, tmp_path: Path) -> None:
        # The ADR-NNNN shape is the same concept as Decision-NNNN. Both
        # point a PyPI consumer at plans/decisions/ they don't have.
        body = "# See " + "ADR " + "0030 §1\n"  # noqa: CHU006  fixture string built so CHU006 doesn't self-flag this test source
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert any("Decision/ADR NNNN" in finding.message for finding in findings)

    def test_three_digit_decision_not_matched(self, tmp_path: Path) -> None:
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", "Decision 99 historic\n")
        assert CHU006.check(tmp_path) == []

    def test_three_digit_adr_not_matched(self, tmp_path: Path) -> None:
        # Bare "ADR 30" without leading zero is too lossy a match.
        # It would catch lots of unrelated three-digit prose.
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", "ADR 30 historic\n")
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
        # Workspace owns the workspace-shim. Its tree is exempt.
        body = "# call " + "run.py to start\n"  # noqa: CHU006  fixture string built so CHU006 doesn't self-flag this test source
        _stage_publishable(tmp_path, "workbench", "workspace", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert all("bare " + "run.py" not in finding.message for finding in findings)  # noqa: CHU006  assertion text matches the rule's own message

    def test_template_user_content_exempt_from_bare_run_py(self, tmp_path: Path) -> None:
        # In a workspace cloned from the template, run.py IS the
        # legitimate command runner. Bare mentions in user content
        # are correct.
        target = tmp_path / "packages" / "foo" / "x.py"
        target.parent.mkdir(parents=True)
        body = "# python " + "run.py setup\n"  # noqa: CHU006  fixture: rule-pattern data
        target.write_text(body, encoding="utf-8")
        findings = CHU006.check(tmp_path)
        assert all("bare " + "run.py" not in finding.message for finding in findings)  # noqa: CHU006  assertion text matches the rule's own message

    def test_bare_run_py_flagged_in_library_examples(self, tmp_path: Path) -> None:
        # A package's own examples/ subdirectory ships to bundle
        # consumers; a bare run.py ref there is a leak, not template
        # user content. The exemption keys on the first repo-relative
        # segment (``libraries``), not a coincidental ``examples`` part.
        body = "# run with " + "run.py deploy\n"  # noqa: CHU006  fixture: rule-pattern data
        _stage_publishable(tmp_path, "libraries", "wifi", "examples/demo.py", body)
        findings = CHU006.check(tmp_path)
        assert any("bare " + "run.py" in finding.message for finding in findings)  # noqa: CHU006  assertion text matches the rule's own message

    def test_bare_run_py_flagged_in_library_tests(self, tmp_path: Path) -> None:
        body = "# regenerate with " + "run.py fixtures\n"  # noqa: CHU006  fixture: rule-pattern data
        _stage_publishable(tmp_path, "libraries", "wifi", "tests/test_x.py", body)
        findings = CHU006.check(tmp_path)
        assert any("bare " + "run.py" in finding.message for finding in findings)  # noqa: CHU006  assertion text matches the rule's own message


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


class TestGovernanceFilePattern:
    def test_agents_md_ref_flagged(self, tmp_path: Path) -> None:
        body = "# see " + "AGENTS.md" + " for the rule\n"  # noqa: CHU006  fixture: rule-pattern data
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert any("governance file" in finding.message for finding in findings)

    def test_contributing_md_ref_flagged(self, tmp_path: Path) -> None:
        body = "# see " + "CONTRIBUTING.md" + " for setup\n"  # noqa: CHU006  fixture: rule-pattern data
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert any("governance file" in finding.message for finding in findings)

    def test_agents_notes_md_ref_flagged(self, tmp_path: Path) -> None:
        # The second-governance-file shape. Even if no current file
        # exists, a publishable-tree pointer to it is a leak.
        body = "# see " + "AGENTS.notes.md" + "\n"  # noqa: CHU006  fixture: rule-pattern data
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert any("governance file" in finding.message for finding in findings)

    def test_checks_package_exempt(self, tmp_path: Path) -> None:
        # The chu008 / chu017 rules legitimately enumerate AGENTS.md
        # as data. The existing chumicro_checks exemption covers them.
        body = "# rule scans " + "AGENTS.md" + "\n"  # noqa: CHU006  fixture: rule-pattern data
        _stage_publishable(tmp_path, "workbench", "checks", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert all("governance file" not in finding.message for finding in findings)


class TestScratchPathPattern:
    def test_scratch_path_flagged(self, tmp_path: Path) -> None:
        body = "# see " + ".scratch/run_perf.py" + " for bench\n"  # noqa: CHU006  fixture: rule-pattern data
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert any(".scratch/" in finding.message for finding in findings)

    def test_scratch_in_markdown_flagged(self, tmp_path: Path) -> None:
        body = "Run `" + ".scratch/perf.py" + "` for fragmentation testing.\n"  # noqa: CHU006  fixture: rule-pattern data
        _stage_publishable(tmp_path, "libraries", "wifi", "README.md", body)
        findings = CHU006.check(tmp_path)
        assert any(".scratch/" in finding.message for finding in findings)


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

    def test_hyphenated_noqa_prose_does_not_suppress(self, tmp_path: Path) -> None:
        # A hyphenated ``noqa`` token co-located with a leak is prose,
        # not a directive, so the leak on the same line still fires.
        # The ref is split in this source so the test file itself stays
        # clean under CHU006.
        body = (
            '"""' + "Decision" + " 0042 lives upstream.  "
            "# noqa-tracking follow-up\"\"\"\n"
        )
        _stage_publishable(tmp_path, "libraries", "wifi", "src/x.py", body)
        findings = CHU006.check(tmp_path)
        assert any("Decision/ADR NNNN" in finding.message for finding in findings)


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

    def test_publishable_dirs_includes_template_packages(self, tmp_path: Path) -> None:
        (tmp_path / "packages" / "foo").mkdir(parents=True)
        (tmp_path / "projects" / "wifi_only").mkdir(parents=True)
        roots = _publishable_package_dirs(tmp_path)
        names = sorted(root.name for root in roots)
        assert "foo" in names
        assert "wifi_only" in names

    def test_publishable_dirs_includes_template_flat_trees(self, tmp_path: Path) -> None:
        (tmp_path / "shared").mkdir()
        (tmp_path / "examples").mkdir()
        (tmp_path / "tests").mkdir()
        roots = _publishable_package_dirs(tmp_path)
        names = sorted(root.name for root in roots)
        assert "shared" in names
        assert "examples" in names
        assert "tests" in names


class TestTemplateShapeFires:
    """CHU006 fires on template-shape user content trees too."""

    def test_decision_ref_in_packages(self, tmp_path: Path) -> None:
        target = tmp_path / "packages" / "foo" / "x.py"
        target.parent.mkdir(parents=True)
        target.write_text("# See Decision 0042\n")  # noqa: CHU006  fixture string
        findings = CHU006.check(tmp_path)
        assert any("Decision/ADR NNNN" in finding.message for finding in findings)

    def test_plans_path_in_projects(self, tmp_path: Path) -> None:
        target = tmp_path / "projects" / "wifi" / "app.py"
        target.parent.mkdir(parents=True)
        target.write_text("# see plans/decisions/0001-foo.md\n")
        findings = CHU006.check(tmp_path)
        assert any("plans/...md" in finding.message for finding in findings)

    def test_mono_repo_framing_in_shared(self, tmp_path: Path) -> None:
        (tmp_path / "shared").mkdir()
        (tmp_path / "shared" / "util.py").write_text("# from chumicro mono-repo\n")
        findings = CHU006.check(tmp_path)
        assert any("'chumicro mono-repo'" in finding.message for finding in findings)


class TestNestedCheckoutPath:
    """Predicate exemptions key on the repo-relative path, not the absolute one."""

    def test_plans_path_fires_when_repo_nested_under_workbench_checks(
        self, tmp_path: Path,
    ) -> None:
        # Repo checked out under a path whose own segments include
        # ``workbench/checks`` (a CI workspace, or this repo's own
        # ``.scratch/``). The scope predicate must consult the
        # repo-relative path, or every _outside_chumicro_checks-scoped
        # pattern silently switches off repo-wide.
        repo_root = tmp_path / "workbench" / "checks" / "userrepo"
        target = repo_root / "libraries" / "pkg" / "src" / "mod.py"
        target.parent.mkdir(parents=True)
        target.write_text("# tracked in plans/next-up.md upstream\n")
        findings = CHU006.check(repo_root)
        assert any("plans/...md" in finding.message for finding in findings)

    def test_bare_run_py_fires_when_repo_nested_under_examples(
        self, tmp_path: Path,
    ) -> None:
        # A coincidental ``examples`` segment above the repo root must
        # not exempt the whole tree from the bare-run.py pattern.
        repo_root = tmp_path / "examples" / "userrepo"
        target = repo_root / "libraries" / "pkg" / "src" / "mod.py"
        target.parent.mkdir(parents=True)
        body = "# run " + "run.py deploy\n"  # noqa: CHU006  fixture: rule-pattern data
        target.write_text(body, encoding="utf-8")
        findings = CHU006.check(repo_root)
        assert any("bare " + "run.py" in finding.message for finding in findings)  # noqa: CHU006  assertion text matches the rule's own message


class TestScopePredicates:
    def test_outside_chumicro_workspace(self) -> None:
        assert _outside_chumicro_workspace(Path("workbench/workspace/src/x.py")) is False
        assert _outside_chumicro_workspace(Path("workbench/deploy/src/x.py")) is True

    def test_outside_chumicro_checks(self) -> None:
        assert _outside_chumicro_checks(Path("workbench/checks/src/x.py")) is False
        assert _outside_chumicro_checks(Path("workbench/deploy/src/x.py")) is True

    def test_workspace_predicate_uses_segment_match_not_substring(self) -> None:
        # A directory like ``my-workbench/workspace-staging/...`` must
        # not satisfy the predicate. The segments aren't the literal
        # ``workbench`` / ``workspace`` boundary.
        assert _outside_chumicro_workspace(
            Path("my-workbench/workspace-staging/src/x.py")
        ) is True
        # Single segment containing the substring ``workbench/workspace``
        # similarly must not satisfy it.
        assert _outside_chumicro_workspace(
            Path("foo-workbench-workspace-bar/src/x.py")
        ) is True

    def test_checks_predicate_uses_segment_match_not_substring(self) -> None:
        assert _outside_chumicro_checks(
            Path("my-workbench/checks-staging/src/x.py")
        ) is True
        assert _outside_chumicro_checks(
            Path("foo-workbench-checks-bar/src/x.py")
        ) is True

    def test_predicates_match_at_arbitrary_depth(self) -> None:
        # Absolute path of a real mono-repo checkout: parts begin with
        # the filesystem root, so the segment match has to walk the
        # whole tuple. Anchoring at parts[0] would miss this.
        deep = Path("/Users/dev/code/chumicro/workbench/workspace/src/x.py")
        assert _outside_chumicro_workspace(deep) is False
        deep_checks = Path("/Users/dev/code/chumicro/workbench/checks/src/x.py")
        assert _outside_chumicro_checks(deep_checks) is False


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU006.code == "CHU006"

    def test_description(self) -> None:
        assert "publishable" in CHU006.description.lower()
