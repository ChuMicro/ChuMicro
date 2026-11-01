"""Tests for CHU038: library examples and demo apps never exit."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu038 import CHU038

_EXAMPLE = "libraries/foo/examples/blink.py"
_DEMO = "demos/foo_roundtrip/app.py"

_FOREVER = "while True:\n    tick()\n"


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _messages(repo_root: Path) -> list[str]:
    return [finding.message for finding in CHU038.check(repo_root)]


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU038.check(tmp_path) == []

    def test_example_ending_in_while_true(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "import foo\nsetup()\n" + _FOREVER)
        assert CHU038.check(tmp_path) == []

    def test_demo_ending_in_while_true(self, tmp_path: Path) -> None:
        _stage(tmp_path, _DEMO, "runner = make()\n" + _FOREVER)
        assert CHU038.check(tmp_path) == []

    def test_while_one_counts(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "while 1:\n    tick()\n")
        assert CHU038.check(tmp_path) == []

    def test_loop_inside_module_level_try(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "try:\n"
            "    while True:\n"
            "        tick()\n"
            "finally:\n"
            "    cleanup()\n",
        )
        assert CHU038.check(tmp_path) == []

    def test_loop_inside_module_level_match_case(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "match MODE:\n"
            "    case 'demo':\n"
            "        while True:\n"
            "            tick()\n",
        )
        assert CHU038.check(tmp_path) == []

    def test_break_inside_nested_for_stays_in_the_for(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "while True:\n"
            "    for reading in readings():\n"
            "        if reading is None:\n"
            "            break\n",
        )
        assert CHU038.check(tmp_path) == []

    def test_break_inside_nested_function_stays_in_the_function(
        self, tmp_path: Path,
    ) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "while True:\n"
            "    def drain():\n"
            "        while True:\n"
            "            break\n"
            "    drain()\n",
        )
        assert CHU038.check(tmp_path) == []


class TestExitCalls:
    def test_raise_system_exit_called(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "raise SystemExit(1)\n" + _FOREVER)
        findings = CHU038.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU038"
        assert findings[0].line == 1
        assert "raise SystemExit" in findings[0].message

    def test_bare_raise_system_exit(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, _FOREVER + "    raise SystemExit\n")
        findings = CHU038.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].line == 3

    def test_sys_exit_inside_a_function(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "import sys\n"
            "def give_up():\n"
            "    sys.exit(2)\n" + _FOREVER,
        )
        findings = CHU038.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].line == 3
        assert "sys.exit()" in findings[0].message

    def test_bare_exit_quit_and_os_exit(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "import os\n"
            "if failed:\n"
            "    exit(1)\n"
            "if done:\n"
            "    quit()\n"
            "if wedged:\n"
            "    os._exit(3)\n" + _FOREVER,
        )
        messages = " ".join(_messages(tmp_path))
        assert "exit()" in messages
        assert "quit()" in messages
        assert "os._exit()" in messages
        assert len(CHU038.check(tmp_path)) == 3

    def test_other_exceptions_not_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "raise ValueError('bad pin')\n" + _FOREVER)
        assert CHU038.check(tmp_path) == []

    def test_findings_sorted_by_line(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "import sys\nsetup()\nsys.exit(0)\n")
        lines = [finding.line for finding in CHU038.check(tmp_path)]
        assert lines == [1, 3]


class TestMissingLoop:
    def test_runs_off_the_end(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "import foo\nprint(foo.query())\n")
        findings = CHU038.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].line == 1
        assert "while True:" in findings[0].message

    def test_bounded_while_not_enough(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "while not handle.done:\n    tick()\n")
        assert len(CHU038.check(tmp_path)) == 1

    def test_break_out_of_while_true(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "while True:\n"
            "    tick()\n"
            "    if handle.done:\n"
            "        break\n",
        )
        assert len(CHU038.check(tmp_path)) == 1

    def test_break_in_nested_loop_else_leaves_the_outer_loop(
        self, tmp_path: Path,
    ) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "while True:\n"
            "    for attempt in range(3):\n"
            "        tick()\n"
            "    else:\n"
            "        break\n",
        )
        assert len(CHU038.check(tmp_path)) == 1

    def test_break_inside_try_handler_leaves_the_loop(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "while True:\n"
            "    try:\n"
            "        tick()\n"
            "    except OSError:\n"
            "        break\n",
        )
        assert len(CHU038.check(tmp_path)) == 1

    def test_loop_inside_main_function(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "def main():\n"
            "    while True:\n"
            "        tick()\n"
            "main()\n",
        )
        assert len(CHU038.check(tmp_path)) == 1

    def test_demo_without_loop(self, tmp_path: Path) -> None:
        _stage(tmp_path, _DEMO, "print('DEMO_COMPLETE')\n")
        findings = CHU038.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].path.name == "app.py"


class TestScope:
    def test_helpers_module_skipped(self, tmp_path: Path) -> None:
        _stage(tmp_path, "libraries/foo/examples/helpers.py", "def wifi_up():\n    pass\n")
        assert CHU038.check(tmp_path) == []

    def test_example_subdirectory_skipped(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, "libraries/foo/examples/_generated/config.py",
            "raise SystemExit\n",
        )
        assert CHU038.check(tmp_path) == []

    def test_demo_driver_skipped(self, tmp_path: Path) -> None:
        _stage(tmp_path, "demos/foo_roundtrip/driver.py", "raise SystemExit(main())\n")
        assert CHU038.check(tmp_path) == []

    def test_library_source_and_tests_skipped(self, tmp_path: Path) -> None:
        _stage(tmp_path, "libraries/foo/src/chumicro_foo/core.py", "raise SystemExit\n")
        _stage(tmp_path, "libraries/foo/tests/test_core.py", "raise SystemExit\n")
        assert CHU038.check(tmp_path) == []

    def test_non_python_file_skipped(self, tmp_path: Path) -> None:
        _stage(tmp_path, "libraries/foo/examples/README.md", "raise SystemExit\n")
        assert CHU038.check(tmp_path) == []

    def test_undecodable_file_skipped(self, tmp_path: Path) -> None:
        target = tmp_path / _EXAMPLE
        target.parent.mkdir(parents=True)
        target.write_bytes(b"\xff\xfe raise SystemExit\n")
        assert CHU038.check(tmp_path) == []

    def test_syntax_error_reported(self, tmp_path: Path) -> None:
        # A ``--select CHU038`` run over an unparseable file must not be
        # silently green: the file surfaces as a finding.
        _stage(tmp_path, _EXAMPLE, "while True\n")
        findings = CHU038.check(tmp_path)
        assert len(findings) == 1
        assert "syntax error" in findings[0].message


class TestSuppression:
    def test_noqa_on_exit_line_mutes_that_call(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            "raise SystemExit(1)  # noqa: CHU038 - test fixture\n" + _FOREVER,
        )
        assert CHU038.check(tmp_path) == []

    def test_noqa_on_exit_line_leaves_missing_loop(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "raise SystemExit(1)  # noqa: CHU038 - test fixture\n")
        findings = CHU038.check(tmp_path)
        assert len(findings) == 1
        assert "while True:" in findings[0].message

    def test_comment_only_line_exempts_the_file(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            '"""Benchmark."""\n'
            "# noqa: CHU038 - benchmark: runs each scenario once, then prints a summary\n"
            "import sys\n"
            "run_scenarios()\n"
            "sys.exit(0)\n",
        )
        assert CHU038.check(tmp_path) == []

    def test_bare_noqa_line_does_not_exempt(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "# noqa\nrun_once()\n")
        assert len(CHU038.check(tmp_path)) == 1

    def test_other_code_line_does_not_exempt(self, tmp_path: Path) -> None:
        _stage(tmp_path, _EXAMPLE, "# noqa: CHU033 - unrelated\nrun_once()\n")
        assert len(CHU038.check(tmp_path)) == 1

    def test_directive_quoted_in_docstring_does_not_exempt(
        self, tmp_path: Path,
    ) -> None:
        _stage(
            tmp_path, _EXAMPLE,
            '"""Shows the opt-out.\n'
            "\n"
            "    # noqa: CHU038 - runs once\n"
            '"""\n'
            "run_once()\n",
        )
        assert len(CHU038.check(tmp_path)) == 1
