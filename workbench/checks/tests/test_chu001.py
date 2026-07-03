"""Tests for CHU001: descriptive names."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu001 import CHU001


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU001.check(tmp_path) == []

    def test_no_top_level_dirs(self, tmp_path: Path) -> None:
        # File outside the scan scope. The rule emits no findings.
        _stage(tmp_path, "src/foo.py", "x = 1\n")
        assert CHU001.check(tmp_path) == []


class TestSingleLetter:
    def test_assignment_target_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].message == "single-letter name 'x'"

    def test_underscore_allowed(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "_ = unused()\n")
        assert CHU001.check(tmp_path) == []

    def test_for_loop_target_exempt(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "for i in range(3):\n    pass\n")
        assert CHU001.check(tmp_path) == []

    def test_for_loop_tuple_target_exempt(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "for i, j in pairs:\n    pass\n")
        assert CHU001.check(tmp_path) == []

    def test_comprehension_target_exempt(self, tmp_path: Path) -> None:
        # ``sum(x for x in values)`` — the comprehension target is a
        # loop binding, exempt like ``for i in range(n)``.
        _stage(tmp_path, "scripts/foo.py", "total = sum(x for x in values)\n")
        assert CHU001.check(tmp_path) == []

    def test_list_comprehension_target_exempt(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "squares = [n * n for n in items]\n")
        assert CHU001.check(tmp_path) == []

    def test_async_for_target_exempt(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "async def drain():\n    async for i in stream():\n        handle(i)\n",
        )
        assert CHU001.check(tmp_path) == []

    def test_nested_tuple_loop_target_exempt(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "for a, (b, c) in rows:\n    pass\n",
        )
        assert CHU001.check(tmp_path) == []

    def test_starred_loop_target_exempt(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "for a, *rest in rows:\n    pass\n")
        assert CHU001.check(tmp_path) == []

    def test_single_letter_import_alias_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "import struct as s\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].message == "single-letter name 's'"

    def test_single_letter_from_import_alias_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "from os import path as p\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert "'p'" in findings[0].message

    def test_single_letter_class_name_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "class T:\n    pass\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].message == "single-letter name 'T'"

    def test_function_param_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "def func(x):\n    return x\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1

    def test_except_alias_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "try:\n    pass\nexcept ValueError as e:\n    raise\n",
        )
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert "'e'" in findings[0].message


class TestBannedAbbreviations:
    def test_bare_env_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "env = 'production'\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert "banned abbreviation" in findings[0].message

    def test_suffix_buf_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "data_buf = []\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert "banned abbreviation suffix '_buf'" in findings[0].message

    def test_function_name_with_suffix_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "scripts/foo.py",
            "def make_src():\n    return None\n",
        )
        findings = CHU001.check(tmp_path)
        assert any("'_src'" in finding.message for finding in findings)

    def test_banned_abbreviation_import_alias_flagged(self, tmp_path: Path) -> None:
        # Aliasing to a banned abbreviation dodges the check unless
        # ``import ... as`` bindings are inspected.
        _stage(tmp_path, "scripts/foo.py", "import subprocess as cmd\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert "banned abbreviation" in findings[0].message
        assert "'cmd'" in findings[0].message

    def test_descriptive_name_clean(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "environment = 'production'\n")
        assert CHU001.check(tmp_path) == []


class TestSuppression:
    def test_noqa_on_single_letter(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1  # noqa: CHU001\n")
        assert CHU001.check(tmp_path) == []

    def test_unrelated_noqa_does_not_suppress(self, tmp_path: Path) -> None:
        _stage(tmp_path, "scripts/foo.py", "x = 1  # noqa: CHU012\n")
        assert len(CHU001.check(tmp_path)) == 1


class TestEdgeCases:
    def test_syntax_error_reported_not_silently_skipped(
        self, tmp_path: Path,
    ) -> None:
        # An unparseable file must surface as a finding, not pass as
        # clean — it named nothing the rule could check.
        _stage(tmp_path, "scripts/foo.py", "def broken(\n")
        findings = CHU001.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU001"
        assert "syntax error" in findings[0].message

    def test_walks_libraries(self, tmp_path: Path) -> None:
        _stage(tmp_path, "libraries/wifi/src/wifi/x.py", "x = 1\n")
        assert len(CHU001.check(tmp_path)) == 1

    def test_walks_workbench(self, tmp_path: Path) -> None:
        _stage(tmp_path, "workbench/repl/src/repl/x.py", "x = 1\n")
        assert len(CHU001.check(tmp_path)) == 1

    def test_walks_template_packages(self, tmp_path: Path) -> None:
        _stage(tmp_path, "packages/foo/x.py", "x = 1\n")
        assert len(CHU001.check(tmp_path)) == 1

    def test_walks_template_projects(self, tmp_path: Path) -> None:
        _stage(tmp_path, "projects/wifi_only/app.py", "x = 1\n")
        assert len(CHU001.check(tmp_path)) == 1

    def test_walks_template_shared(self, tmp_path: Path) -> None:
        _stage(tmp_path, "shared/util.py", "x = 1\n")
        assert len(CHU001.check(tmp_path)) == 1

    def test_walks_template_root_tests(self, tmp_path: Path) -> None:
        _stage(tmp_path, "tests/test_foo.py", "x = 1\n")
        assert len(CHU001.check(tmp_path)) == 1

    def test_walks_template_examples(self, tmp_path: Path) -> None:
        _stage(tmp_path, "examples/blink.py", "x = 1\n")
        assert len(CHU001.check(tmp_path)) == 1


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU001.code == "CHU001"

    def test_description(self) -> None:
        assert "single-letter" in CHU001.description.lower()
