"""Tests for CHU009 + CHU010: silent test skip rules."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from chumicro_checks.rules.chu009_chu010 import (
    CHU009,
    CHU010,
    _callable_tail_name,
    _function_has_assertion,
    _is_in_scope,
    _iter_test_functions,
)


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
        # File outside libraries/. The rule is out of scope.
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


class TestIsInScopeHelper:
    """Direct tests for the scope-detection edge cases."""

    def test_non_py_file_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "libraries" / "wifi" / "tests" / "test_x.txt"
        assert _is_in_scope(target, tmp_path) is False

    def test_path_outside_repo_root_rejected(self, tmp_path: Path) -> None:
        # ``Path.relative_to`` raises ValueError when the file isn't
        # under repo_root. The helper should return False rather than
        # propagating the exception.
        outside = Path("/elsewhere/libraries/wifi/tests/test_x.py")
        assert _is_in_scope(outside, tmp_path) is False

    def test_too_few_path_parts_rejected(self, tmp_path: Path) -> None:
        # ``libraries/wifi/test_x.py`` has only 3 parts. The rule
        # needs ``libraries/<pkg>/<scope_dir>/test_*.py`` (4+ parts).
        target = tmp_path / "libraries" / "wifi" / "test_x.py"
        assert _is_in_scope(target, tmp_path) is False

    def test_non_libraries_root_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "workbench" / "deploy" / "tests" / "test_x.py"
        assert _is_in_scope(target, tmp_path) is False


class TestIterTestFunctionsHelper:
    """Direct tests for ``_iter_test_functions`` edge cases."""

    def test_test_class_with_non_test_methods(self) -> None:
        # ``Test*`` class with a mix of test_ and helper methods.
        # Only the test_ methods come back.
        tree = ast.parse(textwrap.dedent("""
            class TestStuff:
                def helper(self):
                    pass
                def test_one(self):
                    assert True
                attr = 1
        """).strip())
        names = [func.name for func in _iter_test_functions(tree)]
        assert names == ["test_one"]

    def test_module_level_non_test_def_ignored(self) -> None:
        tree = ast.parse(textwrap.dedent("""
            def helper():
                pass
            def test_real():
                assert True
        """).strip())
        names = [func.name for func in _iter_test_functions(tree)]
        assert names == ["test_real"]


class TestCallableTailName:
    """Direct tests for the AST-shape parser."""

    def test_name_callable(self) -> None:
        call = ast.parse("foo()").body[0].value
        assert _callable_tail_name(call.func) == "foo"

    def test_attribute_callable(self) -> None:
        call = ast.parse("module.foo()").body[0].value
        assert _callable_tail_name(call.func) == "foo"

    def test_subscript_callable_returns_none(self) -> None:
        # ``handlers[0]()`` is a subscript callable. The helper returns
        # None so the call is treated as not-an-assertion (conservative).
        call = ast.parse("handlers[0]()").body[0].value
        assert _callable_tail_name(call.func) is None


class TestFunctionHasAssertionEarlyExits:
    """Verify each early-success path triggers."""

    def test_assert_satisfies(self) -> None:
        func = ast.parse("def f():\n    assert True\n").body[0]
        assert _function_has_assertion(func) is True

    def test_raise_satisfies(self) -> None:
        func = ast.parse("def f():\n    raise ValueError\n").body[0]
        assert _function_has_assertion(func) is True

    def test_assertion_call_satisfies(self) -> None:
        func = ast.parse("def f():\n    skip('x')\n").body[0]
        assert _function_has_assertion(func) is True

    def test_no_assertion_returns_false(self) -> None:
        func = ast.parse("def f():\n    x = 1\n    y = x + 1\n").body[0]
        assert _function_has_assertion(func) is False


class TestSilentReturnEdgeCases:
    """Widened CHU009: any ``if``-body-final return/pass + bare early exit."""

    def test_multi_statement_if_body_last_return_flagged(self, tmp_path: Path) -> None:
        # ``if cond:\n    log(); return``. The guarded branch still
        # skips ``assert False`` below, so it is a silent skip.
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                if True:
                    print("logged")
                    return
                assert False
        """)
        findings = CHU009.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU009"

    def test_bare_early_return_flagged(self, tmp_path: Path) -> None:
        # An unconditional early return orphans the assertion below it.
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                setup()
                return
                assert result()
        """)
        findings = CHU009.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU009"

    def test_return_inside_nested_closure_not_flagged(self, tmp_path: Path) -> None:
        # A ``return`` inside a factory/callback is that callable's
        # logic, not the test silently passing.
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                calls = []
                def factory():
                    if not calls:
                        calls.append(True)
                        return object()
                    raise OSError("down")
                assert factory() is not None
        """)
        assert CHU009.check(tmp_path) == []

    def test_legit_final_return_not_flagged(self, tmp_path: Path) -> None:
        # A return as the function's last statement is normal Python.
        _stage_test(tmp_path, "foo", "tests", """
            def test_thing() -> None:
                assert compute() == 1
                return
        """)
        assert CHU009.check(tmp_path) == []
