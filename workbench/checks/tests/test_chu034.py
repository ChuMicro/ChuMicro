"""Tests for CHU034: device-staging primitives are chumicro_deploy-internal."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu034 import CHU034

_CONSUMER = "workbench/workspace/src/chumicro_workspace/cli/deploy.py"


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU034.check(tmp_path) == []

    def test_consumer_using_deploy_diff_is_clean(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _CONSUMER,
            "def run(runner, source):\n"
            "    return runner.deploy_diff(source, clean=True)\n",
        )
        assert CHU034.check(tmp_path) == []


class TestFlags:
    def test_deploy_files_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _CONSUMER,
            "def run(transport, files, entrypoint):\n"
            "    return transport.deploy_files(files, entrypoint)\n",
        )
        findings = CHU034.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU034"
        assert "deploy_files" in findings[0].message
        assert "deploy_diff" in findings[0].message

    def test_delete_files_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _CONSUMER,
            "def run(transport, stale):\n"
            "    transport.delete_files(stale)\n",
        )
        findings = CHU034.check(tmp_path)
        assert len(findings) == 1
        assert "delete_files" in findings[0].message

    def test_list_files_in_scope_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _CONSUMER,
            "def run(transport):\n"
            "    return transport.list_files_in_scope(clean_slate=True)\n",
        )
        findings = CHU034.check(tmp_path)
        assert len(findings) == 1
        assert "list_files_in_scope" in findings[0].message

    def test_reimplemented_diff_flags_each_primitive(self, tmp_path: Path) -> None:
        # A command re-implementing deploy_diff's reconcile-then-write
        # sequence trips one finding per reserved primitive.
        _stage(
            tmp_path, _CONSUMER,
            "def deploy(transport, files, entrypoint):\n"
            "    on_device = set(transport.list_files_in_scope())\n"
            "    transport.delete_files(sorted(on_device - set(files)))\n"
            "    return transport.deploy_files(files, entrypoint)\n",
        )
        assert len(CHU034.check(tmp_path)) == 3

    def test_flags_in_support_and_workbench_non_deploy(
        self, tmp_path: Path,
    ) -> None:
        for relative in (
            "libraries/foo/src/chumicro_foo/core.py",
            "support/bar/src/chumicro_bar/core.py",
            "workbench/repl/src/chumicro_repl/cli.py",
        ):
            _stage(
                tmp_path, relative,
                "def run(transport, files, entrypoint):\n"
                "    return transport.deploy_files(files, entrypoint)\n",
            )
        assert len(CHU034.check(tmp_path)) == 3


class TestSkips:
    def test_deploy_package_is_the_blessed_home(self, tmp_path: Path) -> None:
        # The chumicro_deploy package defines and orchestrates the
        # primitives; it is exempt.
        _stage(
            tmp_path,
            "workbench/deploy/src/chumicro_deploy/deployer.py",
            "def _run(transport, files, entrypoint):\n"
            "    return transport.deploy_files(files, entrypoint)\n",
        )
        assert CHU034.check(tmp_path) == []

    def test_deploy_package_tests_exempt(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/deploy/tests/test_transport.py",
            "def test_it(transport):\n"
            "    transport.delete_files(['/lib/x.py'])\n",
        )
        assert CHU034.check(tmp_path) == []

    def test_sanctioned_second_axis_primitives_not_reserved(
        self, tmp_path: Path,
    ) -> None:
        # The harness-over-REPL stage, the entrypoint clear, and the
        # standalone destructive erase are a separate legitimate axis.
        _stage(
            tmp_path, _CONSUMER,
            "def run(transport, dirs, tests, harness):\n"
            "    transport.stage(dirs, tests, harness)\n"
            "    transport.clear_entrypoints()\n"
            "    transport.wipe_filesystem()\n",
        )
        assert CHU034.check(tmp_path) == []

    def test_name_in_string_literal_not_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _CONSUMER,
            'DOC = "call deploy_files() only from chumicro_deploy"\n',
        )
        assert CHU034.check(tmp_path) == []

    def test_method_definition_not_flagged(self, tmp_path: Path) -> None:
        # Defining a method named deploy_files is not calling one; only
        # call sites are the drift signal.
        _stage(
            tmp_path,
            "workbench/repl/src/chumicro_repl/thing.py",
            "class Thing:\n"
            "    def deploy_files(self, files):\n"
            "        return files\n",
        )
        assert CHU034.check(tmp_path) == []

    def test_demos_not_in_scope(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, "demos/x/app.py",
            "def run(transport, files, entrypoint):\n"
            "    return transport.deploy_files(files, entrypoint)\n",
        )
        assert CHU034.check(tmp_path) == []

    def test_non_python_file_skipped(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, "workbench/repl/src/chumicro_repl/notes.txt",
            "transport.deploy_files(files, entrypoint)\n",
        )
        assert CHU034.check(tmp_path) == []

    def test_syntax_error_reported(self, tmp_path: Path) -> None:
        _stage(tmp_path, _CONSUMER, "def broken(:\n")
        findings = CHU034.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU034"
        assert "syntax error" in findings[0].message


class TestSuppression:
    def test_noqa_mutes_finding(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _CONSUMER,
            "def run(transport, files, entrypoint):\n"
            "    return transport.deploy_files(files, entrypoint)  # noqa: CHU034\n",
        )
        assert CHU034.check(tmp_path) == []
