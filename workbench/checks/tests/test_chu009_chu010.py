"""Tests for CHU009 + CHU010 — silent test skip rules."""

from __future__ import annotations

import textwrap
from pathlib import Path

from chumicro_checks.rules.chu009_chu010 import CHU009, CHU010


def _stage_test(repo_root: Path, library: str, scope: str, body: str) -> Path:
    """Stage ``libraries/<library>/<scope>/test_x.py`` with *body*."""
    target = repo_root / "libraries" / library / scope / "test_x.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_no_libraries_dir(self, tmp_path: Path) -> None:
        assert CHU009.check(tmp_path) == []
        assert CHU010.check(tmp_path) == []

    def test_empty_libraries(self, tmp_path: Path) -> None:
        (tmp_path / "libraries").mkdir()
        assert CHU009.check(tmp_path) == []
        assert CHU010.check(tmp_path) == []


class TestScope:
    def test_only_libraries_tests(self, tmp_path: Path) -> None:
        # File outside libraries/ — out of scope.
        target = tmp_path / "scripts" / "tests" / "test_x.py"
        target.parent.mkdir(parents=True)
        target.write_text("def test_thing():\n    pass\n")
        assert CHU009.check(tmp_path) == []
        assert CHU010.check(tmp_path) == []

    def test_workbench_tests_out_of_scope(self, tmp_path: Path) -> None:
        target = tmp_path / "workbench" / "deploy" / "tests" / "test_x.py"
        target.parent.mkdir(parents=True)
        target.write_text("def test_thing():\n    pass\n")
        assert CHU009.check(tmp_path) == []
        assert CHU010.check(tmp_path) == []

    def test_examples_tree_out_of_scope(self, tmp_path: Path) -> None:
        target = tmp_path / "libraries" / "foo" / "examples" / "test_x.py"
        target.parent.mkdir(parents=True)
        target.write_text("def test_thing():\n    pass\n")
        assert CHU009.check(tmp_path) == []
        assert CHU010.check(tmp_path) == []

    def test_non_test_prefix_skipped(self, tmp_path: Path) -> None:
        target = tmp_path / "libraries" / "foo" / "tests" / "helpers.py"
        target.parent.mkdir(parents=True)
        target.write_text("def helper():\n    return 1\n")
        assert CHU009.check(tmp_path) == []
        assert CHU010.check(tmp_path) == []

    def test_functional_tests_in_scope(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "functional_tests", """
            def test_thing() -> None:
                if True:
                    return
                assert False
        """)
        assert len(CHU009.check(tmp_path)) == 1


class TestCHU009:
    def test_silent_return_flagged(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                if True:
                    return
                assert False
        """)
        findings = CHU009.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU009"
        assert "silent" in findings[0].message

    def test_silent_pass_flagged(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                if True:
                    pass
                assert False
        """)
        findings = CHU009.check(tmp_path)
        assert len(findings) == 1

    def test_real_skip_call_clean(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            from chumicro_test_harness import skip
            def test_thing() -> None:
                if True:
                    skip("not applicable")
                assert False
        """)
        assert CHU009.check(tmp_path) == []

    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                if True:
                    return  # noqa: CHU009
                assert False
        """)
        assert CHU009.check(tmp_path) == []

    def test_noqa_on_if_line_also_suppresses(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                if True:  # noqa: CHU009
                    return
                assert False
        """)
        assert CHU009.check(tmp_path) == []

    def test_method_in_test_class(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            class TestThings:
                def test_method(self) -> None:
                    if True:
                        return
                    assert False
        """)
        assert len(CHU009.check(tmp_path)) == 1


class TestCHU010:
    def test_no_assertion_flagged(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                value = 1
                value = value + 1
        """)
        findings = CHU010.check(tmp_path)
        assert len(findings) == 1
        assert "no assertion" in findings[0].message

    def test_assert_satisfies(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                assert True
        """)
        assert CHU010.check(tmp_path) == []

    def test_raise_satisfies(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                raise AssertionError("x")
        """)
        assert CHU010.check(tmp_path) == []

    def test_pytest_raises_satisfies(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            import pytest
            def test_thing() -> None:
                with pytest.raises(ValueError):
                    int("nope")
        """)
        assert CHU010.check(tmp_path) == []

    def test_skip_satisfies(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            from chumicro_test_harness import skip
            def test_thing() -> None:
                skip("reason")
        """)
        assert CHU010.check(tmp_path) == []

    def test_dotted_call_satisfies(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            import pytest
            def test_thing() -> None:
                pytest.fail("nope")
        """)
        assert CHU010.check(tmp_path) == []

    def test_noqa_on_def_suppresses(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:  # noqa: CHU010
                value = 1
        """)
        assert CHU010.check(tmp_path) == []


class TestEdgeCases:
    def test_syntax_error_skipped(self, tmp_path: Path) -> None:
        _stage_test(tmp_path, "foo", "tests", "def broken(\n")
        assert CHU009.check(tmp_path) == []
        assert CHU010.check(tmp_path) == []


class TestRuleMetadata:
    def test_chu009_code(self) -> None:
        assert CHU009.code == "CHU009"

    def test_chu010_code(self) -> None:
        assert CHU010.code == "CHU010"

    def test_descriptions_distinct(self) -> None:
        assert CHU009.description != CHU010.description
