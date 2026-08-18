"""CHU037: em-dash ban in user-facing prose."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu037 import CHU037

_DASHED = "A sentence — with an em-dash.\n"
_CLEAN = "A sentence, with a comma.\n"


def _write(root: Path, relative: str, text: str) -> Path:
    filepath = root / relative
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(text, encoding="utf-8")
    return filepath


class TestScope:
    def test_root_readme_flagged(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _DASHED)
        findings = CHU037.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU037"
        assert findings[0].line == 1

    def test_docs_and_library_pages_flagged(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/troubleshooting/page.md", _DASHED)
        _write(tmp_path, "libraries/timing/docs/index.md", _DASHED)
        _write(tmp_path, "workbench/deploy/docs/guide.md", _DASHED)
        _write(tmp_path, "demos/thing/README.md", _DASHED)
        assert len(CHU037.check(tmp_path)) == 4

    def test_pr_template_flagged_but_skills_tree_ignored(self, tmp_path: Path) -> None:
        _write(tmp_path, ".github/PULL_REQUEST_TEMPLATE.md", _DASHED)
        _write(tmp_path, ".github/skills/some-skill/SKILL.md", _DASHED)
        findings = CHU037.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].path.name == "PULL_REQUEST_TEMPLATE.md"

    def test_md_template_scaffolds_flagged(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "workbench/workspace/src/chumicro_workspace/_payloads/"
            "library_template/readme.md.template",
            _DASHED,
        )
        _write(tmp_path, "scripts/templates/bundle_readme.md.template", _DASHED)
        assert len(CHU037.check(tmp_path)) == 2

    def test_non_md_templates_ignored(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "workbench/workspace/src/chumicro_workspace/_payloads/"
            "secrets.toml.template",
            _DASHED,
        )
        assert CHU037.check(tmp_path) == []

    def test_plans_out_of_scope(self, tmp_path: Path) -> None:
        _write(tmp_path, "plans/next-up.md", _DASHED)
        _write(tmp_path, "plans/decisions/0001-something.md", _DASHED)
        assert CHU037.check(tmp_path) == []

    def test_test_trees_out_of_scope(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "workbench/deploy/tests/fixtures/third_party_template/README.md",
            _DASHED,
        )
        _write(tmp_path, "libraries/timing/functional_tests/notes.md", _DASHED)
        assert CHU037.check(tmp_path) == []

    def test_missing_directories_are_silent(self, tmp_path: Path) -> None:
        assert CHU037.check(tmp_path) == []


class TestDetection:
    def test_clean_file_passes(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _CLEAN)
        assert CHU037.check(tmp_path) == []

    def test_every_dashed_line_reported(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _DASHED + _CLEAN + _DASHED)
        lines = [finding.line for finding in CHU037.check(tmp_path)]
        assert lines == [1, 3]

    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "README.md",
            'Before: "declarative — you list devices" <!-- noqa: CHU037 -->\n',
        )
        assert CHU037.check(tmp_path) == []

    def test_bare_noqa_suppresses(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", "quoted — output <!-- noqa -->\n")
        assert CHU037.check(tmp_path) == []
