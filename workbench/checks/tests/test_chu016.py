"""Tests for CHU016 — example imports resolve per declared runtime."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu016 import CHU016

_EX = "libraries/foo/examples/demo.py"

_CROSS = '__chumicro_runtimes__ = ("circuitpython", "micropython")\n'
_CP_ONLY = '__chumicro_runtimes__ = ("circuitpython",)\n'


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU016.check(tmp_path) == []

    def test_example_without_runtime_marker(self, tmp_path: Path) -> None:
        # No marker → verify_examples already resolves all imports;
        # CHU016 stays out of it.
        _stage(tmp_path, _EX, "import board\n")
        assert CHU016.check(tmp_path) == []

    def test_non_example_path_ignored(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/x.py",
            _CROSS + "import board\n",
        )
        assert CHU016.check(tmp_path) == []


class TestFlags:
    def test_cp_only_import_in_cross_runtime_example(
        self, tmp_path: Path,
    ) -> None:
        _stage(tmp_path, _EX, _CROSS + "import board\n")
        findings = CHU016.check(tmp_path)
        assert len(findings) == 1
        assert "board" in findings[0].message
        assert "micropython" in findings[0].message

    def test_mp_only_importfrom_in_cross_runtime_example(
        self, tmp_path: Path,
    ) -> None:
        _stage(tmp_path, _EX, _CROSS + "from machine import Pin\n")
        findings = CHU016.check(tmp_path)
        assert len(findings) == 1
        assert "machine" in findings[0].message
        assert "circuitpython" in findings[0].message

    def test_finding_line_is_the_import(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _EX,
            _CROSS + "import os\nimport sys\nimport network\n",
        )
        findings = CHU016.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].line == 4  # marker(1) os(2) sys(3) network(4)


class TestCorrectPatternsNotFlagged:
    def test_single_runtime_example_top_level_import_ok(
        self, tmp_path: Path,
    ) -> None:
        # CircuitPython-only example may import board at top level.
        _stage(tmp_path, _EX, _CP_ONLY + "import board\n")
        assert CHU016.check(tmp_path) == []

    def test_guarded_under_implementation_branch_ok(
        self, tmp_path: Path,
    ) -> None:
        source = (
            _CROSS
            + "import sys\n"
            + 'if sys.implementation.name == "circuitpython":\n'
            + "    import board\n"
            + "else:\n"
            + "    from machine import Pin\n"
        )
        _stage(tmp_path, _EX, source)
        assert CHU016.check(tmp_path) == []

    def test_function_local_import_ok(self, tmp_path: Path) -> None:
        source = (
            _CROSS
            + "def wifi_up():\n"
            + "    import network\n"
            + "    return network\n"
        )
        _stage(tmp_path, _EX, source)
        assert CHU016.check(tmp_path) == []

    def test_try_guarded_import_ok(self, tmp_path: Path) -> None:
        source = (
            _CROSS
            + "try:\n"
            + "    import supervisor\n"
            + "except ImportError:\n"
            + "    supervisor = None\n"
        )
        _stage(tmp_path, _EX, source)
        assert CHU016.check(tmp_path) == []

    def test_universal_imports_never_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _EX,
            _CROSS + "import os\nimport sys\nimport struct\nimport time\n",
        )
        assert CHU016.check(tmp_path) == []


class TestSuppression:
    def test_noqa_on_import_line(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _EX,
            _CROSS + "import board  # noqa: CHU016 — CP demo, MP path below\n",
        )
        assert CHU016.check(tmp_path) == []


class TestAgainstRealRepo:
    """Cross-runtime examples must keep runtime-exclusive imports guarded.

    A re-introduced unguarded top-level `import board` / `import
    machine` in a dual-runtime example fails this test, not just
    review.
    """

    def test_repo_examples_are_clean(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        assert (repo_root / "libraries").is_dir()
        assert CHU016.check(repo_root) == []
