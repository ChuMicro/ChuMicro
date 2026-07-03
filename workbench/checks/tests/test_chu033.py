"""Tests for CHU033: no async / await / asyncio in first-party package code."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu033 import CHU033

_SRC = "libraries/foo/src/chumicro_foo/core.py"


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU033.check(tmp_path) == []

    def test_scoped_dir_without_async(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "def handle(self, now_ms):\n    return 1\n")
        assert CHU033.check(tmp_path) == []


class TestFlags:
    def test_async_def(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "async def run():\n    return 1\n")
        findings = CHU033.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU033"
        assert "async def" in findings[0].message

    def test_await(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "async def run():\n    await other()\n")
        codes = [
            (finding.code, "await" in finding.message)
            for finding in CHU033.check(tmp_path)
        ]
        # The async def and the await both flag.
        assert ("CHU033", True) in codes

    def test_async_with_and_for(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _SRC,
            "async def run():\n"
            "    async with ctx() as handle:\n"
            "        async for item in stream():\n"
            "            use(item, handle)\n",
        )
        messages = " ".join(
            finding.message for finding in CHU033.check(tmp_path)
        )
        assert "async with" in messages
        assert "async for" in messages

    def test_import_asyncio(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "import asyncio\n")
        findings = CHU033.check(tmp_path)
        assert len(findings) == 1
        assert "import asyncio" in findings[0].message

    def test_import_uasyncio_and_private(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "import uasyncio\nimport _asyncio\n")
        assert len(CHU033.check(tmp_path)) == 2

    def test_from_asyncio_import(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "from asyncio import sleep\n")
        findings = CHU033.check(tmp_path)
        assert len(findings) == 1
        assert "from asyncio import" in findings[0].message

    def test_dotted_asyncio_submodule(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "import asyncio.tasks\n")
        assert len(CHU033.check(tmp_path)) == 1

    def test_flags_in_tests_support_and_workbench(self, tmp_path: Path) -> None:
        for relative in (
            "libraries/foo/tests/test_core.py",
            "support/bar/src/chumicro_bar/core.py",
            "workbench/baz/src/chumicro_baz/cli.py",
        ):
            _stage(tmp_path, relative, "async def run():\n    return 1\n")
        assert len(CHU033.check(tmp_path)) == 3


class TestSkips:
    def test_functional_tests_excluded(self, tmp_path: Path) -> None:
        # Host-only hardware-driving servers may be asyncio-based.
        _stage(
            tmp_path,
            "libraries/websockets/functional_tests/_host_echo_server.py",
            "import asyncio\nasync def serve():\n    await asyncio.sleep(1)\n",
        )
        assert CHU033.check(tmp_path) == []

    def test_async_in_string_literal_not_flagged(self, tmp_path: Path) -> None:
        # A boot shim that rejects async def stores the keyword as text.
        _stage(
            tmp_path, _SRC,
            'MESSAGE = "async def run() is not a usable entrypoint"\n'
            'SNIPPET = "async def run():\\n    pass\\n"\n',
        )
        assert CHU033.check(tmp_path) == []

    def test_demos_not_in_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "demos/x/app.py", "async def run():\n    return 1\n")
        assert CHU033.check(tmp_path) == []

    def test_non_python_file_skipped(self, tmp_path: Path) -> None:
        _stage(tmp_path, "libraries/foo/src/notes.txt", "async def run(): pass\n")
        assert CHU033.check(tmp_path) == []

    def test_non_asyncio_import_not_flagged(self, tmp_path: Path) -> None:
        # asynchat / a name merely starting with "async" is not asyncio.
        _stage(tmp_path, _SRC, "import asynchat\nfrom asyncfoo import bar\n")
        assert CHU033.check(tmp_path) == []

    def test_syntax_error_reported(self, tmp_path: Path) -> None:
        # A ``--select CHU033`` run over an unparseable file must not be
        # silently green: the file surfaces as a finding.
        _stage(tmp_path, _SRC, "def broken(:\n")
        findings = CHU033.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU033"
        assert "syntax error" in findings[0].message


class TestSuppression:
    def test_noqa_mutes_finding(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "import asyncio  # noqa: CHU033\n")
        assert CHU033.check(tmp_path) == []
