"""Tests for check_no_silent_test_skip.py — CHU009 + CHU010."""

from __future__ import annotations

from pathlib import Path

from check_no_silent_test_skip import (
    _CHU009,
    _CHU010,
    _is_in_scope,
    _read_noqa_lines,
    check_file,
    check_paths,
)

# ---------------------------------------------------------------------------
# _is_in_scope
# ---------------------------------------------------------------------------


class TestIsInScope:
    """Only ``libraries/<name>/{tests,functional_tests}/test_*.py`` is in scope."""

    def test_library_unit_test(self) -> None:
        """Standard host-side unit tests are in scope."""
        assert _is_in_scope(
            Path("libraries/wifi/tests/test_wifi.py"),
        ) is True

    def test_library_functional_test(self) -> None:
        """Hardware-gated functional tests are in scope."""
        assert _is_in_scope(
            Path("libraries/wifi/functional_tests/test_acceptance.py"),
        ) is True

    def test_library_pytest_only_unit_test(self) -> None:
        """``test_*_pytest.py`` files are still in the unit-test scope."""
        assert _is_in_scope(
            Path("libraries/sockets/tests/test_factories_pytest.py"),
        ) is True

    def test_library_src_excluded(self) -> None:
        """Library source files are not in scope."""
        assert _is_in_scope(
            Path("libraries/wifi/src/chumicro_wifi/config.py"),
        ) is False

    def test_workbench_test_excluded(self) -> None:
        """Workbench tests are out of scope (the audit was library-focused)."""
        assert _is_in_scope(
            Path("workbench/deploy/tests/test_deploy.py"),
        ) is False

    def test_support_test_excluded(self) -> None:
        """``support/`` tests are out of scope."""
        assert _is_in_scope(
            Path("support/test_harness/tests/test_runner.py"),
        ) is False

    def test_non_test_filename_excluded(self) -> None:
        """A file under tests/ that isn't ``test_*.py`` is out of scope."""
        assert _is_in_scope(
            Path("libraries/wifi/tests/conftest.py"),
        ) is False

    def test_non_python_file_excluded(self) -> None:
        """Markdown / yaml / etc. files are out of scope."""
        assert _is_in_scope(
            Path("libraries/wifi/tests/test_data.yml"),
        ) is False


# ---------------------------------------------------------------------------
# _read_noqa_lines
# ---------------------------------------------------------------------------


class TestReadNoqaLines:
    """The noqa scanner returns 1-based line numbers per rule code."""

    def test_no_noqa(self) -> None:
        """A plain source has no suppressed lines."""
        assert _read_noqa_lines("def test_x(): pass\n", _CHU009) == set()

    def test_chu009_specific(self) -> None:
        """``# noqa: CHU009`` marks that line for CHU009 only."""
        assert _read_noqa_lines(
            "if x: return  # noqa: CHU009\n", _CHU009,
        ) == {1}
        assert _read_noqa_lines(
            "if x: return  # noqa: CHU009\n", _CHU010,
        ) == set()

    def test_bare_noqa(self) -> None:
        """Bare ``# noqa`` suppresses both rules."""
        assert _read_noqa_lines("if x: return  # noqa\n", _CHU009) == {1}
        assert _read_noqa_lines("if x: return  # noqa\n", _CHU010) == {1}

    def test_unrelated_rule_does_not_suppress(self) -> None:
        """A different CHU code doesn't silence CHU009."""
        assert _read_noqa_lines(
            "if x: return  # noqa: CHU001\n", _CHU009,
        ) == set()


# ---------------------------------------------------------------------------
# CHU009 — bare-return / pass in test body
# ---------------------------------------------------------------------------


class TestChu009BareReturn:
    """Catch ``if <cond>: return/pass`` patterns inside test functions."""

    def _write_lib_test(self, tmp_path: Path, source: str) -> Path:
        target = tmp_path / "libraries" / "fake" / "tests" / "test_thing.py"
        target.parent.mkdir(parents=True)
        target.write_text(source)
        return target

    def test_flags_if_return_at_top_of_test(self, tmp_path: Path) -> None:
        """Classic credential-guard shape — flagged."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():\n"
            "    if not _flag:\n"
            "        return\n"
            "    assert True\n",
        )
        errors = check_file(target)
        assert any(_CHU009 in error for error in errors)

    def test_flags_if_pass_in_test(self, tmp_path: Path) -> None:
        """``if <cond>: pass`` is even more obviously dead code — flagged."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():\n"
            "    if not _flag:\n"
            "        pass\n"
            "    assert True\n",
        )
        errors = check_file(target)
        assert any(_CHU009 in error for error in errors)

    def test_flags_late_return_inside_test(self, tmp_path: Path) -> None:
        """A bare-return guard later in the function is also a silent-PASS."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():\n"
            "    do_setup()\n"
            "    if late_check():\n"
            "        return\n"
            "    assert True\n",
        )
        errors = check_file(target)
        assert any(_CHU009 in error for error in errors)

    def test_does_not_flag_if_with_assert_body(self, tmp_path: Path) -> None:
        """``if <cond>: assert ...`` is a real assertion, not a silent skip."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():\n"
            "    if cond:\n"
            "        assert True\n",
        )
        errors = check_file(target)
        assert not any(_CHU009 in error for error in errors)

    def test_does_not_flag_if_with_skip_call(self, tmp_path: Path) -> None:
        """``if <cond>: skip(reason)`` is a visible skip, not silent."""
        target = self._write_lib_test(
            tmp_path,
            "from chumicro_test_harness import skip\n"
            "def test_foo():\n"
            "    if cond:\n"
            "        skip('reason')\n"
            "    assert True\n",
        )
        errors = check_file(target)
        assert not any(_CHU009 in error for error in errors)

    def test_noqa_suppresses_chu009(self, tmp_path: Path) -> None:
        """``# noqa: CHU009`` on the if-line silences the rule."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():\n"
            "    if cond:  # noqa: CHU009\n"
            "        return\n"
            "    assert True\n",
        )
        errors = check_file(target)
        assert not any(_CHU009 in error for error in errors)

    def test_does_not_apply_to_non_test_function(self, tmp_path: Path) -> None:
        """``if <cond>: return`` in a helper isn't a test body — not flagged."""
        target = self._write_lib_test(
            tmp_path,
            "def _helper():\n"
            "    if cond:\n"
            "        return\n"
            "def test_foo():\n"
            "    assert _helper() is None\n",
        )
        errors = check_file(target)
        assert not any(_CHU009 in error for error in errors)


# ---------------------------------------------------------------------------
# CHU010 — test must contain at least one assertion
# ---------------------------------------------------------------------------


class TestChu010NoAssertion:
    """Catch test functions with no way to fail other than crashing."""

    def _write_lib_test(self, tmp_path: Path, source: str) -> Path:
        target = tmp_path / "libraries" / "fake" / "tests" / "test_thing.py"
        target.parent.mkdir(parents=True)
        target.write_text(source)
        return target

    def test_flags_test_with_no_assertion(self, tmp_path: Path) -> None:
        """A test that just calls a function — no way to fail — flagged."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():\n"
            "    do_something()\n",
        )
        errors = check_file(target)
        assert any(_CHU010 in error for error in errors)

    def test_does_not_flag_assert(self, tmp_path: Path) -> None:
        """Plain ``assert`` is enough."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():\n"
            "    assert True\n",
        )
        errors = check_file(target)
        assert not any(_CHU010 in error for error in errors)

    def test_does_not_flag_pytest_raises(self, tmp_path: Path) -> None:
        """``with pytest.raises(...)`` counts as an assertion."""
        target = self._write_lib_test(
            tmp_path,
            "import pytest\n"
            "def test_foo():\n"
            "    with pytest.raises(ValueError):\n"
            "        do_thing()\n",
        )
        errors = check_file(target)
        assert not any(_CHU010 in error for error in errors)

    def test_does_not_flag_chumicro_raises(self, tmp_path: Path) -> None:
        """``with raises(...)`` from the test_harness counts."""
        target = self._write_lib_test(
            tmp_path,
            "from chumicro_test_harness import raises\n"
            "def test_foo():\n"
            "    with raises(ValueError):\n"
            "        do_thing()\n",
        )
        errors = check_file(target)
        assert not any(_CHU010 in error for error in errors)

    def test_does_not_flag_skip_call(self, tmp_path: Path) -> None:
        """A test that always skips counts (skip is visible)."""
        target = self._write_lib_test(
            tmp_path,
            "from chumicro_test_harness import skip\n"
            "def test_foo():\n"
            "    skip('not applicable')\n",
        )
        errors = check_file(target)
        assert not any(_CHU010 in error for error in errors)

    def test_does_not_flag_raise_statement(self, tmp_path: Path) -> None:
        """A bare ``raise AssertionError(...)`` is a real failure path."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():\n"
            "    raise AssertionError('explicit fail')\n",
        )
        errors = check_file(target)
        assert not any(_CHU010 in error for error in errors)

    def test_noqa_suppresses_chu010(self, tmp_path: Path) -> None:
        """``# noqa: CHU010`` on the def line silences the rule."""
        target = self._write_lib_test(
            tmp_path,
            "def test_foo():  # noqa: CHU010\n"
            "    do_something()\n",
        )
        errors = check_file(target)
        assert not any(_CHU010 in error for error in errors)

    def test_class_method_test_is_inspected(self, tmp_path: Path) -> None:
        """Methods on ``Test*`` classes follow the same rules."""
        target = self._write_lib_test(
            tmp_path,
            "class TestThing:\n"
            "    def test_foo(self):\n"
            "        do_something()\n",
        )
        errors = check_file(target)
        assert any(_CHU010 in error for error in errors)


class TestCheckPaths:
    """End-to-end: scanning a directory tree picks up violations."""

    def test_clean_tree_returns_zero(self, tmp_path: Path) -> None:
        """A library with a clean test passes."""
        target = tmp_path / "libraries" / "fake" / "tests" / "test_clean.py"
        target.parent.mkdir(parents=True)
        target.write_text("def test_one():\n    assert True\n")

        assert check_paths([str(tmp_path)]) == 0

    def test_dirty_tree_returns_one(
        self, tmp_path: Path, capsys,
    ) -> None:
        """A library with a silent-skip test fails."""
        target = tmp_path / "libraries" / "fake" / "tests" / "test_bad.py"
        target.parent.mkdir(parents=True)
        target.write_text(
            "def test_one():\n"
            "    if cond:\n"
            "        return\n"
            "    assert True\n",
        )

        assert check_paths([str(tmp_path)]) == 1
        captured = capsys.readouterr().out
        assert _CHU009 in captured

    def test_workbench_tree_ignored(self, tmp_path: Path) -> None:
        """Workbench tests are out of scope — same shape passes there."""
        target = tmp_path / "workbench" / "fake" / "tests" / "test_x.py"
        target.parent.mkdir(parents=True)
        target.write_text(
            "def test_one():\n"
            "    do_thing()\n",
        )

        assert check_paths([str(tmp_path)]) == 0
