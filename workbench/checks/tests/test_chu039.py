"""Tests for CHU039: Python fences in the docs parse and import names that exist."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu039 import CHU039

_TIMING_SOURCE = "libraries/timing/src/chumicro_timing"

_TIMING_INIT = (
    "from chumicro_timing.deadline import Rate\n"
    "__all__ = ['Rate', 'LazyClock']\n"
    "\n"
    "def __getattr__(name):\n"
    "    if name == 'SlowClock':\n"
    "        from chumicro_timing.deadline import Deadline\n"
    "        return Deadline\n"
    "    raise AttributeError(f'module has no attribute {name!r}')\n"
)
_TIMING_DEADLINE = "class Rate:\n    pass\n\n\nclass Deadline:\n    pass\n"
_TIMING_TESTING = "class FakeTicks:\n    pass\n"

_BROKEN = "if ready\n    go()\n"


def _write(root: Path, relative: str, text: str) -> Path:
    filepath = root / relative
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(text, encoding="utf-8")
    return filepath


def _stage_timing(root: Path) -> None:
    _write(root, f"{_TIMING_SOURCE}/__init__.py", _TIMING_INIT)
    _write(root, f"{_TIMING_SOURCE}/deadline.py", _TIMING_DEADLINE)
    _write(root, f"{_TIMING_SOURCE}/testing.py", _TIMING_TESTING)


def _fence(body: str, above: str = "", language: str = "python") -> str:
    """Return a markdown page whose ``language`` fence opens on line 3, or 4 with *above*."""
    marker = f"{above}\n" if above else ""
    return f"Intro.\n\n{marker}```{language}\n{body}```\n"


def _messages(root: Path) -> list[str]:
    return [finding.message for finding in CHU039.check(root)]


class TestScope:
    def test_empty_repo_is_silent(self, tmp_path: Path) -> None:
        assert CHU039.check(tmp_path) == []

    def test_every_scoped_tree_is_read(self, tmp_path: Path) -> None:
        for relative in (
            "README.md",
            "docs/troubleshooting/page.md",
            "libraries/timing/README.md",
            "libraries/timing/docs/guide.md",
            "workbench/deploy/README.md",
            "workbench/deploy/docs/guide.md",
            "demos/README.md",
            "demos/mqtt_pub_sub/README.md",
        ):
            _write(tmp_path, relative, _fence(_BROKEN))
        assert len(CHU039.check(tmp_path)) == 8

    def test_out_of_scope_markdown_is_skipped(self, tmp_path: Path) -> None:
        for relative in (
            "AGENTS.md",
            "plans/next-up.md",
            "libraries/timing/CHANGELOG.md",
            "libraries/timing/examples/README.md",
            "libraries/timing/docs/reference/deep.md",
            ".github/skills/some-skill/SKILL.md",
            "demos/mqtt_pub_sub/NOTES.md",
        ):
            _write(tmp_path, relative, _fence(_BROKEN))
        assert CHU039.check(tmp_path) == []

    def test_other_languages_are_skipped(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "README.md",
            _fence(_BROKEN, language="bash") + _fence(_BROKEN, language="text"),
        )
        assert CHU039.check(tmp_path) == []

    def test_py_and_attributed_info_strings_count(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "README.md",
            _fence(_BROKEN, language="py")
            + _fence(_BROKEN, language='python title="code.py"'),
        )
        assert len(CHU039.check(tmp_path)) == 2


class TestSyntax:
    def test_passing_fence(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _fence("ready = True\nif ready:\n    print(ready)\n"))
        assert CHU039.check(tmp_path) == []

    def test_syntax_error_points_at_parser_line(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _fence("ready = True\n" + _BROKEN))
        findings = CHU039.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU039"
        assert findings[0].line == 5
        assert "fails to parse" in findings[0].message

    def test_fence_under_list_item_parses_dedented(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "README.md",
            "1. Save this:\n"
            "\n"
            "   ```python\n"
            "   ready = True\n"
            "   if ready:\n"
            "       print(ready)\n"
            "   ```\n",
        )
        assert CHU039.check(tmp_path) == []

    def test_tilde_fence_is_read(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", "~~~python\n" + _BROKEN + "~~~\n")
        assert len(CHU039.check(tmp_path)) == 1

    def test_unclosed_fence_runs_to_end_of_file(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", "```python\nready = True\n" + _BROKEN)
        findings = CHU039.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].line == 3

    def test_python_inside_longer_markdown_fence_is_skipped(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "README.md",
            "````markdown\n```python\n" + _BROKEN + "```\n````\n",
        )
        assert CHU039.check(tmp_path) == []

    def test_invalid_escape_parses_without_a_finding(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _fence('pattern = "\\d+"\n'))
        assert CHU039.check(tmp_path) == []


class TestFragment:
    def test_marked_fragment_passes(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "README.md",
            _fence(
                "led = Pin('LED', Pin.OUT)\n...\n        led.toggle()\n",
                above="<!-- fragment -->",
            ),
        )
        assert CHU039.check(tmp_path) == []

    def test_marker_above_a_blank_line_counts(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _fence(_BROKEN, above="<!-- fragment -->\n"))
        assert CHU039.check(tmp_path) == []

    def test_marker_at_end_of_prose_line_is_ignored(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "README.md",
            _fence(_BROKEN, above="Only the changed lines: <!-- fragment -->"),
        )
        assert len(CHU039.check(tmp_path)) == 1

    def test_marker_line_with_prose_between_comments_is_ignored(
        self, tmp_path: Path,
    ) -> None:
        _write(
            tmp_path, "README.md",
            _fence(_BROKEN, above="<!-- fragment --> Changed lines: <!-- end -->"),
        )
        assert len(CHU039.check(tmp_path)) == 1

    def test_marker_above_earlier_prose_is_ignored(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "README.md",
            _fence(_BROKEN, above="<!-- fragment -->\n\nOnly the changed lines:"),
        )
        assert len(CHU039.check(tmp_path)) == 1

    def test_parsing_fragment_still_has_imports_checked(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(
            tmp_path, "README.md",
            _fence("from chumicro_timing import Heartbeat\n", above="<!-- fragment -->"),
        )
        assert len(CHU039.check(tmp_path)) == 1


class TestImports:
    def test_exported_names_pass(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(
            tmp_path, "README.md",
            _fence(
                "from chumicro_timing import Rate, LazyClock, SlowClock, deadline\n"
                "from chumicro_timing.testing import FakeTicks\n"
                "import chumicro_timing.deadline\n"
                "from chumicro_timing import *\n"
            ),
        )
        assert CHU039.check(tmp_path) == []

    def test_missing_name_points_at_its_line(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(
            tmp_path, "README.md",
            _fence("from chumicro_timing import (\n    Rate,\n    Heartbeat,\n)\n"),
        )
        findings = CHU039.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].line == 6
        assert findings[0].message == "`Heartbeat` is absent from `chumicro_timing`"

    def test_submodule_import_resolves_against_the_submodule(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(
            tmp_path, "README.md",
            _fence(
                "from chumicro_timing.deadline import Deadline\n"
                "from chumicro_timing.deadline import FakeTicks\n"
            ),
        )
        assert _messages(tmp_path) == [
            "`FakeTicks` is absent from `chumicro_timing.deadline`. "
            "`chumicro_timing.testing` exports it",
        ]

    def test_close_match_is_suggested(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(tmp_path, "README.md", _fence("from chumicro_timing import Rat\n"))
        assert _messages(tmp_path) == [
            "`Rat` is absent from `chumicro_timing`. `Rate` is the closest name it exports",
        ]

    def test_missing_module_is_flagged(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(
            tmp_path, "README.md",
            _fence("from chumicro_timing.clock import Rate\nimport chumicro_timing.clock\n"),
        )
        findings = CHU039.check(tmp_path)
        assert [finding.line for finding in findings] == [4, 5]
        assert all("chumicro_timing.clock" in finding.message for finding in findings)

    def test_package_without_source_is_skipped(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(
            tmp_path, "README.md",
            _fence("from chumicro_my_sensor import Sensor\nimport chumicro_my_sensor\n"),
        )
        assert CHU039.check(tmp_path) == []

    def test_other_and_relative_imports_are_skipped(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(
            tmp_path, "README.md",
            _fence("import time\nfrom machine import Pin\nfrom . import chumicro_timing\n"),
        )
        assert CHU039.check(tmp_path) == []

    def test_imports_and_annotated_all_count_and_scoped_names_do_not(
        self, tmp_path: Path,
    ) -> None:
        _write(
            tmp_path, "libraries/compat/src/chumicro_compat/__init__.py",
            "import gc as collector\n"
            "import os.path\n"
            "SQUARES = [value * value for value in range(3)]\n"
            "DOUBLE = lambda number: number * 2\n"
            "__all__: list[str] = ['Exported']\n",
        )
        _write(
            tmp_path, "README.md",
            _fence(
                "from chumicro_compat import collector, os, SQUARES, DOUBLE, Exported\n"
                "from chumicro_compat import value, number\n"
            ),
        )
        assert [finding.line for finding in CHU039.check(tmp_path)] == [5, 5]

    def test_conditional_module_level_bindings_count(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "libraries/compat/src/chumicro_compat/__init__.py",
            "try:\n"
            "    from fast import fast_path\n"
            "except ImportError as missing:\n"
            "    fast_path = None\n"
            "if fast_path is None:\n"
            "    def slow_path():\n"
            "        hidden = 1\n"
            "        return hidden\n"
            "for SCALE in (1,):\n"
            "    pass\n",
        )
        _write(
            tmp_path, "README.md",
            _fence(
                "from chumicro_compat import fast_path, slow_path, missing, SCALE\n"
                "from chumicro_compat import hidden\n"
            ),
        )
        findings = CHU039.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].line == 5
        assert "`hidden`" in findings[0].message

    def test_source_is_parsed_and_never_imported(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "libraries/compat/src/chumicro_compat/__init__.py",
            "raise RuntimeError('importing this module fails')\nVALUE = 1\n",
        )
        _write(tmp_path, "README.md", _fence("from chumicro_compat import VALUE\n"))
        assert CHU039.check(tmp_path) == []

    def test_workbench_and_support_sources_are_indexed(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "workbench/deploy/src/chumicro_deploy/__init__.py",
            "class Deployer:\n    pass\n",
        )
        _write(
            tmp_path, "support/test_harness/src/chumicro_test_harness/skip.py",
            "def skip(reason):\n    pass\n",
        )
        _write(
            tmp_path, "README.md",
            _fence(
                "from chumicro_deploy import Deployer, Probe\n"
                "from chumicro_test_harness.skip import skip\n"
                "from chumicro_test_harness import skip\n"
            ),
        )
        assert _messages(tmp_path) == ["`Probe` is absent from `chumicro_deploy`"]

    def test_unparseable_source_resolves_every_name(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "libraries/compat/src/chumicro_compat/__init__.py",
            "def broken(:\n",
        )
        _write(tmp_path, "README.md", _fence("from chumicro_compat import anything\n"))
        assert CHU039.check(tmp_path) == []

    def test_init_file_directly_under_src_is_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "libraries/odd/src/__init__.py", "VALUE = 1\n")
        _stage_timing(tmp_path)
        _write(tmp_path, "README.md", _fence("from chumicro_timing import Rate\n"))
        assert CHU039.check(tmp_path) == []

    def test_undecodable_markdown_is_skipped(self, tmp_path: Path) -> None:
        target = tmp_path / "README.md"
        target.write_bytes(b"\xff\xfe```python\nif ready\n```\n")
        assert CHU039.check(tmp_path) == []


class TestSuppression:
    def test_noqa_inside_fence_mutes_that_line(self, tmp_path: Path) -> None:
        _stage_timing(tmp_path)
        _write(
            tmp_path, "README.md",
            _fence(
                "from chumicro_timing import Heartbeat  # noqa: CHU039 - shows the error\n"
                "from chumicro_timing import Pulse\n"
            ),
        )
        findings = CHU039.check(tmp_path)
        assert len(findings) == 1
        assert "`Pulse`" in findings[0].message

    def test_noqa_above_fence_mutes_the_fence(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _fence(_BROKEN, above="<!-- noqa: CHU039 -->"))
        assert CHU039.check(tmp_path) == []

    def test_noqa_for_another_code_does_not_mute(self, tmp_path: Path) -> None:
        _write(tmp_path, "README.md", _fence(_BROKEN, above="<!-- noqa: CHU037 -->"))
        assert len(CHU039.check(tmp_path)) == 1

    def test_noqa_at_end_of_prose_line_does_not_mute(self, tmp_path: Path) -> None:
        _write(
            tmp_path, "README.md",
            _fence(_BROKEN, above="A quoted sample. <!-- noqa: CHU039 -->"),
        )
        assert len(CHU039.check(tmp_path)) == 1
