"""Tests for run.py — CLI filter parsing and dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest
import run
from run import _parse_library_filters


def _make_fake_command(return_value: int = 0):
    """Return a fake command function plus its recorded calls."""
    calls: list[tuple[tuple, dict]] = []

    def fake_command(*args, **kwargs):
        calls.append((args, kwargs))
        return return_value

    return calls, fake_command


class TestParseLibraryFilters:
    """Tests for _parse_library_filters."""

    def test_simple_library_test(self):
        """Parse 'library/test' format."""
        result = _parse_library_filters("timing/test_heartbeat")
        assert result == {"timing": [(None, "test_heartbeat")]}

    def test_library_file_test(self):
        """Parse 'library/file/test' format."""
        result = _parse_library_filters("timing/test_ticks/ticks_add")
        assert result == {"timing": [("test_ticks", "ticks_add")]}

    def test_comma_separated(self):
        """Parse comma-separated multi-library filters."""
        result = _parse_library_filters("timing/ticks_diff,runner/task_handle")
        assert "timing" in result
        assert "runner" in result
        assert result["timing"] == [(None, "ticks_diff")]
        assert result["runner"] == [(None, "task_handle")]

    def test_multiple_filters_same_library(self):
        """Multiple filters for the same library are grouped."""
        result = _parse_library_filters("timing/test_a,timing/test_b")
        assert result == {"timing": [(None, "test_a"), (None, "test_b")]}

    def test_mixed_scoped_and_file(self):
        """Mix of library/test and library/file/test in one expression."""
        result = _parse_library_filters("timing/ticks_add,timing/test_ticks/ticks_diff")
        assert result == {
            "timing": [(None, "ticks_add"), ("test_ticks", "ticks_diff")],
        }

    def test_no_library_prefix_fails(self):
        """Entry without a slash causes SystemExit."""
        with pytest.raises(SystemExit):
            _parse_library_filters("just_a_test_name")

    def test_too_many_slashes_fails(self):
        """Entry with more than 3 parts causes SystemExit."""
        with pytest.raises(SystemExit):
            _parse_library_filters("a/b/c/d")

    def test_whitespace_handling(self):
        """Whitespace around entries is stripped."""
        result = _parse_library_filters(" timing/test_a , runner/test_b ")
        assert "timing" in result
        assert "runner" in result

    def test_empty_entries_ignored(self):
        """Empty entries from extra commas are ignored."""
        result = _parse_library_filters("timing/test_a,,runner/test_b,")
        assert len(result) == 2


class TestMainDispatch:
    """Tests for CLI command dispatch in run.main."""

    def test_no_task_prints_help_and_returns_1(self, capsys) -> None:
        """Invoking main without a task should print help and return 1."""
        result = run.main(["run.py"])

        captured = capsys.readouterr()
        assert result == 1
        assert "usage:" in captured.out
        assert "test-device" in captured.out

    @pytest.mark.parametrize(
        ("task_name", "function_name"),
        [
            ("setup", "setup"),
            ("sync-ide", "sync_ide"),
            ("lint", "lint"),
            ("build", "build"),
            ("prepare-micropython", "prepare_micropython"),
            ("prepare-circuitpython", "prepare_circuitpython"),
            ("prepare-mpy-cross", "prepare_mpy_cross"),
            ("check-version", "check_version"),
            ("check-api", "check_api"),
        ],
    )
    def test_no_argument_tasks_dispatch(
        self, monkeypatch, task_name: str, function_name: str,
    ) -> None:
        """No-argument tasks should dispatch to their backing functions."""
        calls, fake_command = _make_fake_command(return_value=23)
        monkeypatch.setattr(run, function_name, fake_command)

        result = run.main(["run.py", task_name])

        assert result == 23
        assert calls == [((), {})]

    def test_test_command_without_filter_uses_resolved_scope(
        self, monkeypatch,
    ) -> None:
        """Unfiltered test runs should resolve package scope first."""
        resolved_packages = [Path("/tmp/timing")]
        resolve_calls: list[tuple[bool, str | None]] = []

        def fake_resolve_scope(*, all_packages, libraries):
            resolve_calls.append((all_packages, libraries))
            return resolved_packages

        command_calls, fake_test_cpython = _make_fake_command(return_value=17)
        monkeypatch.setattr(run, "resolve_scope", fake_resolve_scope)
        monkeypatch.setattr(run, "test_cpython", fake_test_cpython)

        result = run.main(["run.py", "test", "--libraries", "timing", "--no-cov"])

        assert result == 17
        assert resolve_calls == [(False, "timing")]
        assert command_calls == [
            ((resolved_packages,), {
                "filter_expression": None,
                "exit_first": False,
                "verbose": False,
                "no_cov": True,
                "coverage_threshold": None,
            }),
        ]

    def test_test_command_with_filter_skips_scope_resolution(
        self, monkeypatch,
    ) -> None:
        """Filtered test runs should skip resolve_scope and let -k define scope."""
        command_calls, fake_test_cpython = _make_fake_command(return_value=19)

        def fail_resolve_scope(*, all_packages, libraries):
            raise AssertionError("resolve_scope should not run when -k is set")

        monkeypatch.setattr(run, "resolve_scope", fail_resolve_scope)
        monkeypatch.setattr(run, "test_cpython", fake_test_cpython)

        result = run.main(["run.py", "test", "-k", "timing/test_heartbeat"])

        assert result == 19
        assert command_calls == [
            (([],), {
                "filter_expression": "timing/test_heartbeat",
                "exit_first": False,
                "verbose": False,
                "no_cov": False,
                "coverage_threshold": None,
            }),
        ]

    def test_verify_examples_dispatches_resolved_scope(self, monkeypatch) -> None:
        """verify-examples should receive the resolved package list."""
        resolved_packages = [Path("/tmp/timing")]
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: resolved_packages,
        )
        command_calls, fake_verify_examples = _make_fake_command(return_value=5)
        monkeypatch.setattr(run, "verify_examples", fake_verify_examples)

        result = run.main(["run.py", "verify-examples", "--all"])

        assert result == 5
        assert command_calls == [((resolved_packages,), {})]

    def test_docs_dispatches_serve_flag(self, monkeypatch) -> None:
        """docs should forward both scope and the serve flag."""
        resolved_packages = [Path("/tmp/timing")]
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: resolved_packages,
        )
        command_calls, fake_docs = _make_fake_command(return_value=7)
        monkeypatch.setattr(run, "docs", fake_docs)

        result = run.main(["run.py", "docs", "--libraries", "timing", "--serve"])

        assert result == 7
        assert command_calls == [((resolved_packages,), {"serve": True})]

    def test_docs_preview_dispatches_resolved_scope(self, monkeypatch) -> None:
        """docs-preview should receive the resolved package list."""
        resolved_packages = [Path("/tmp/timing")]
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: resolved_packages,
        )
        command_calls, fake_docs_preview = _make_fake_command(return_value=11)
        monkeypatch.setattr(run, "docs_preview", fake_docs_preview)

        result = run.main(["run.py", "docs-preview", "--libraries", "timing"])

        assert result == 11
        assert command_calls == [((resolved_packages,), {})]

    def test_new_library_dispatches_name(self, monkeypatch) -> None:
        """new-library should pass through the requested library name."""
        command_calls, fake_new_library = _make_fake_command(return_value=13)
        monkeypatch.setattr(run, "new_library", fake_new_library)

        result = run.main(["run.py", "new-library", "settings"])

        assert result == 13
        assert command_calls == [(("settings",), {})]

    def test_test_scripts_dispatches_flags(self, monkeypatch) -> None:
        """test-scripts should pass through CLI flags to the task."""
        command_calls, fake_test_scripts = _make_fake_command(return_value=29)
        monkeypatch.setattr(run, "test_scripts", fake_test_scripts)

        result = run.main(["run.py", "test-scripts", "-x", "-v"])

        assert result == 29
        assert command_calls == [
            ((), {"exit_first": True, "verbose": True}),
        ]

    def test_docs_deploy_dispatches_optional_library_filter(self, monkeypatch) -> None:
        """docs-deploy should split the library filter before dispatch."""
        command_calls, fake_docs_deploy = _make_fake_command(return_value=31)
        monkeypatch.setattr(run, "docs_deploy", fake_docs_deploy)

        result = run.main([
            "run.py", "docs-deploy", "--channel", "experimental",
            "--libraries", "timing,runner",
        ])

        assert result == 31
        assert command_calls == [
            (("experimental",), {"libraries": ["timing", "runner"]}),
        ]

    def test_validate_mip_dispatches_arguments(self, monkeypatch) -> None:
        """validate-mip should forward its CLI arguments unchanged."""
        command_calls, fake_validate_mip = _make_fake_command(return_value=37)
        monkeypatch.setattr(run, "validate_mip", fake_validate_mip)

        result = run.main([
            "run.py", "validate-mip", "--bundle-repo", "Bundle",
            "--libraries", "timing", "--micropython-binary", "/tmp/mpy",
        ])

        assert result == 37
        assert command_calls == [
            ((), {
                "bundle_repo": "Bundle",
                "libraries": "timing",
                "micropython_binary": "/tmp/mpy",
                "staging_dir": None,
            }),
        ]

    def test_preflight_dispatches_binary_and_coverage_arguments(
        self, monkeypatch,
    ) -> None:
        """preflight should receive runtime-binary overrides and coverage threshold."""
        command_calls, fake_preflight = _make_fake_command(return_value=41)
        monkeypatch.setattr(run, "preflight", fake_preflight)

        result = run.main([
            "run.py", "preflight",
            "--micropython-binary", "/tmp/mpy",
            "--circuitpython-binary", "/tmp/cpy",
            "--coverage-threshold", "94",
        ])

        assert result == 41
        assert command_calls == [
            (("/tmp/mpy", "/tmp/cpy"), {"coverage_threshold": 94}),
        ]

    def test_runtime_compatibility_commands_dispatch(self, monkeypatch) -> None:
        """Runtime-specific compatibility tasks should forward their binary paths."""
        micropython_calls, fake_micropython = _make_fake_command(return_value=43)
        circuitpython_calls, fake_circuitpython = _make_fake_command(return_value=47)
        monkeypatch.setattr(
            run, "test_micropython_compatibility", fake_micropython,
        )
        monkeypatch.setattr(
            run, "test_circuitpython_compatibility", fake_circuitpython,
        )

        micropython_result = run.main([
            "run.py", "test-micropython-compatibility",
            "--micropython-binary", "/tmp/mpy",
        ])
        circuitpython_result = run.main([
            "run.py", "test-circuitpython-compatibility",
            "--circuitpython-binary", "/tmp/cpy",
        ])

        assert micropython_result == 43
        assert circuitpython_result == 47
        assert micropython_calls == [(("/tmp/mpy", None), {})]
        assert circuitpython_calls == [(("/tmp/cpy", None), {})]

    def test_runtime_compatibility_commands_dispatch_scoped_packages(
        self, monkeypatch,
    ) -> None:
        """Scoped runtime-compat commands should resolve package scope first."""
        resolved_packages = [Path("/tmp/timing")]
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: resolved_packages,
        )
        command_calls, fake_micropython = _make_fake_command(return_value=49)
        monkeypatch.setattr(
            run, "test_micropython_compatibility", fake_micropython,
        )

        result = run.main([
            "run.py", "test-micropython-compatibility",
            "--libraries", "timing",
        ])

        assert result == 49
        assert command_calls == [((None, resolved_packages), {})]

    def test_test_runtime_matrix_dispatches_binary_paths(self, monkeypatch) -> None:
        """test-runtime-matrix should receive both optional binary overrides."""
        command_calls, fake_test_runtime_matrix = _make_fake_command(return_value=53)
        monkeypatch.setattr(run, "test_runtime_matrix", fake_test_runtime_matrix)

        result = run.main([
            "run.py", "test-runtime-matrix",
            "--micropython-binary", "/tmp/mpy",
            "--circuitpython-binary", "/tmp/cpy",
        ])

        assert result == 53
        assert command_calls == [(("/tmp/mpy", "/tmp/cpy", None), {})]

    def test_test_runtime_matrix_dispatches_scoped_packages(self, monkeypatch) -> None:
        """test-runtime-matrix should forward an explicit package scope."""
        resolved_packages = [Path("/tmp/timing")]
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: resolved_packages,
        )
        command_calls, fake_test_runtime_matrix = _make_fake_command(return_value=57)
        monkeypatch.setattr(run, "test_runtime_matrix", fake_test_runtime_matrix)

        result = run.main([
            "run.py", "test-runtime-matrix", "--libraries", "timing",
        ])

        assert result == 57
        assert command_calls == [((None, None, resolved_packages), {})]

    def test_test_everything_uses_all_packages_by_default(self, monkeypatch) -> None:
        """test-everything should default to its own all-packages behavior."""
        command_calls, fake_test_everything = _make_fake_command(return_value=63)

        def fail_resolve_scope(*, all_packages, libraries):
            raise AssertionError("resolve_scope should not run without scope flags")

        monkeypatch.setattr(run, "resolve_scope", fail_resolve_scope)
        monkeypatch.setattr(run, "test_everything", fake_test_everything)

        result = run.main(["run.py", "test-everything", "--no-cov"])

        assert result == 63
        assert command_calls == [
            ((None,), {
                "micropython_binary": None,
                "circuitpython_binary": None,
                "exit_first": False,
                "verbose": False,
                "no_cov": True,
                "coverage_threshold": None,
                "with_device": False,
                "runtime": None,
                "micropython_device": None,
                "circuitpython_device": None,
                "library": None,
                "file_filter": None,
                "function_filter": None,
                "deploy_mode": None,
            }),
        ]

    def test_test_everything_dispatches_scope_and_device_arguments(
        self, monkeypatch,
    ) -> None:
        """test-everything should forward both scope and optional device flags."""
        resolved_packages = [Path("/tmp/timing")]
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: resolved_packages,
        )
        command_calls, fake_test_everything = _make_fake_command(return_value=65)
        monkeypatch.setattr(run, "test_everything", fake_test_everything)

        result = run.main([
            "run.py", "test-everything",
            "--libraries", "timing",
            "--with-device",
            "--runtime", "both",
            "--library", "timing",
            "--test", "heartbeat",
            "--deploy-mode", "flash",
            "--micropython-binary", "/tmp/mpy",
            "--circuitpython-binary", "/tmp/cpy",
            "--coverage-threshold", "94",
            "-x",
            "-v",
        ])

        assert result == 65
        assert command_calls == [
            ((resolved_packages,), {
                "micropython_binary": "/tmp/mpy",
                "circuitpython_binary": "/tmp/cpy",
                "exit_first": True,
                "verbose": True,
                "no_cov": False,
                "coverage_threshold": 94,
                "with_device": True,
                "runtime": "both",
                "micropython_device": None,
                "circuitpython_device": None,
                "library": "timing",
                "file_filter": None,
                "function_filter": "heartbeat",
                "deploy_mode": "flash",
            }),
        ]

    def test_test_device_without_filters_passes_none_values(
        self, monkeypatch,
    ) -> None:
        """Bare test-device should defer device selection to lower-level defaults."""
        command_calls, fake_test_device = _make_fake_command(return_value=59)
        monkeypatch.setattr(run, "test_device", fake_test_device)

        result = run.main(["run.py", "test-device"])

        assert result == 59
        assert command_calls == [
            ((), {
                "runtime": None,
                "micropython_device": None,
                "circuitpython_device": None,
                "library": None,
                "file_filter": None,
                "function_filter": None,
                "deploy_mode": None,
            }),
        ]

    def test_test_device_forwards_explicit_cli_filters(self, monkeypatch) -> None:
        """test-device should forward explicit runtime and filter flags."""
        command_calls, fake_test_device = _make_fake_command(return_value=61)
        monkeypatch.setattr(run, "test_device", fake_test_device)

        result = run.main([
            "run.py", "test-device",
            "--runtime", "circuitpython",
            "--library", "timing",
            "--file", "test_heartbeat",
            "--test", "heartbeat_fires",
            "--deploy-mode", "flash",
        ])

        assert result == 61
        assert command_calls == [
            ((), {
                "runtime": "circuitpython",
                "micropython_device": None,
                "circuitpython_device": None,
                "library": "timing",
                "file_filter": "test_heartbeat",
                "function_filter": "heartbeat_fires",
                "deploy_mode": "flash",
            }),
        ]

    def test_test_device_accepts_explicit_both_runtime(self, monkeypatch) -> None:
        """test-device should allow `--runtime both` as an explicit defaults alias."""
        command_calls, fake_test_device = _make_fake_command(return_value=67)
        monkeypatch.setattr(run, "test_device", fake_test_device)

        result = run.main(["run.py", "test-device", "--runtime", "both"])

        assert result == 67
        assert command_calls == [
            ((), {
                "runtime": "both",
                "micropython_device": None,
                "circuitpython_device": None,
                "library": None,
                "file_filter": None,
                "function_filter": None,
                "deploy_mode": None,
            }),
        ]

    def test_test_device_forwards_per_runtime_device_overrides(
        self, monkeypatch,
    ) -> None:
        """test-device should forward explicit per-runtime device overrides."""
        command_calls, fake_test_device = _make_fake_command(return_value=71)
        monkeypatch.setattr(run, "test_device", fake_test_device)

        result = run.main([
            "run.py", "test-device",
            "--runtime", "both",
            "--micropython-device", "mp-alt",
            "--circuitpython-device", "cp-alt",
        ])

        assert result == 71
        assert command_calls == [
            ((), {
                "runtime": "both",
                "micropython_device": "mp-alt",
                "circuitpython_device": "cp-alt",
                "library": None,
                "file_filter": None,
                "function_filter": None,
                "deploy_mode": None,
            }),
        ]

    def test_test_device_rejects_removed_legacy_device_flag(self) -> None:
        """The removed --device flag should fail with an argparse error."""
        with pytest.raises(SystemExit, match="2"):
            run.main([
                "run.py", "test-device",
                "--device", "board-1",
            ])


class TestCompositeTestCommands:
    """Tests for aggregated developer test commands."""

    def test_test_runtime_matrix_forwards_package_scope(self, monkeypatch) -> None:
        """test-runtime-matrix should pass scoped packages to every phase."""
        package_dirs = [Path("/tmp/timing")]
        cpython_calls, fake_cpython = _make_fake_command(return_value=0)
        micropython_calls, fake_micropython = _make_fake_command(return_value=0)
        circuitpython_calls, fake_circuitpython = _make_fake_command(return_value=0)
        monkeypatch.setattr(run, "test_cpython", fake_cpython)
        monkeypatch.setattr(run, "test_micropython_compatibility", fake_micropython)
        monkeypatch.setattr(run, "test_circuitpython_compatibility", fake_circuitpython)

        result = run.test_runtime_matrix(
            "/tmp/mpy", "/tmp/cpy", package_dirs,
        )

        assert result == 0
        assert cpython_calls == [((package_dirs,), {})]
        assert micropython_calls == [(("/tmp/mpy", package_dirs), {})]
        assert circuitpython_calls == [(("/tmp/cpy", package_dirs), {})]

    def test_test_everything_runs_all_non_device_phases(self, monkeypatch) -> None:
        """test-everything should aggregate CPython, scripts, and unix-port tests."""
        package_dirs = [Path("/tmp/timing")]
        cpython_calls, fake_cpython = _make_fake_command(return_value=0)
        scripts_calls, fake_scripts = _make_fake_command(return_value=0)
        micropython_calls, fake_micropython = _make_fake_command(return_value=0)
        circuitpython_calls, fake_circuitpython = _make_fake_command(return_value=0)
        monkeypatch.setattr(run, "test_cpython", fake_cpython)
        monkeypatch.setattr(run, "test_scripts", fake_scripts)
        monkeypatch.setattr(run, "test_micropython_compatibility", fake_micropython)
        monkeypatch.setattr(run, "test_circuitpython_compatibility", fake_circuitpython)

        result = run.test_everything(
            package_dirs,
            micropython_binary="/tmp/mpy",
            circuitpython_binary="/tmp/cpy",
            exit_first=True,
            verbose=True,
            no_cov=True,
            coverage_threshold=94,
        )

        assert result == 0
        assert cpython_calls == [((package_dirs,), {
            "exit_first": True,
            "verbose": True,
            "no_cov": True,
            "coverage_threshold": 94,
        })]
        assert scripts_calls == [((), {"exit_first": True, "verbose": True})]
        assert micropython_calls == [(("/tmp/mpy", package_dirs), {})]
        assert circuitpython_calls == [(("/tmp/cpy", package_dirs), {})]

    def test_test_everything_scopes_device_phase_by_selected_libraries(
        self, monkeypatch,
    ) -> None:
        """Scoped test-everything runs should execute device tests per selected library."""
        package_dirs = [
            run.ROOT / "libraries" / "timing",
            run.ROOT / "libraries" / "runner",
        ]
        monkeypatch.setattr(run, "test_cpython", lambda *args, **kwargs: 0)
        monkeypatch.setattr(run, "test_scripts", lambda *args, **kwargs: 0)
        monkeypatch.setattr(
            run, "test_micropython_compatibility", lambda *args, **kwargs: 0,
        )
        monkeypatch.setattr(
            run, "test_circuitpython_compatibility", lambda *args, **kwargs: 0,
        )
        device_calls, fake_test_device = _make_fake_command(return_value=0)
        monkeypatch.setattr(run, "test_device", fake_test_device)

        result = run.test_everything(package_dirs, with_device=True, runtime="both")

        assert result == 0
        assert device_calls == [
            ((), {
                "runtime": "both",
                "micropython_device": None,
                "circuitpython_device": None,
                "library": "timing",
                "file_filter": None,
                "function_filter": None,
                "deploy_mode": None,
            }),
            ((), {
                "runtime": "both",
                "micropython_device": None,
                "circuitpython_device": None,
                "library": "runner",
                "file_filter": None,
                "function_filter": None,
                "deploy_mode": None,
            }),
        ]


# ---------------------------------------------------------------------------
# Direct tests for run.test_cpython
# ---------------------------------------------------------------------------


def _make_test_package(tmp_path: Path, name: str) -> Path:
    """Create a fake library directory with a tests/ subdir."""
    package_dir = tmp_path / name
    (package_dir / "tests").mkdir(parents=True)
    (package_dir / "src" / f"chumicro_{name}").mkdir(parents=True)
    return package_dir


@pytest.fixture
def fake_root(monkeypatch, tmp_path):
    """Repoint run.ROOT at a tmp_path so relative_to() works for fake packages."""
    monkeypatch.setattr(run, "ROOT", tmp_path)
    return tmp_path


class TestTestCpython:
    """Direct tests for the test_cpython orchestration function."""

    def test_no_testable_packages_returns_zero(self, monkeypatch, fake_root):
        """A package with no tests/ directory short-circuits to success."""
        package_dir = fake_root / "empty"
        package_dir.mkdir()
        # No tests/ subdirectory.

        called: list[tuple] = []

        def fake_run_command(command, **kwargs):
            called.append(command)
            return 0

        monkeypatch.setattr(run, "run_command", fake_run_command)
        result = run.test_cpython([package_dir])
        assert result == 0
        assert called == []

    def test_runs_pytest_for_each_package(self, monkeypatch, fake_root):
        """Each package with tests/ produces a pytest invocation."""
        package_a = _make_test_package(fake_root, "alpha")
        package_b = _make_test_package(fake_root, "beta")

        commands: list[list[str]] = []

        def fake_run_command(command, **kwargs):
            commands.append(command)
            return 0

        monkeypatch.setattr(run, "run_command", fake_run_command)
        result = run.test_cpython([package_a, package_b], no_cov=True)
        assert result == 0
        # Two pytest runs (one per package).
        pytest_runs = [command for command in commands if "pytest" in command[0] or "-m" in command]
        assert len(pytest_runs) == 2

    def test_unknown_filter_library_returns_one(self, monkeypatch, fake_root):
        """A -k filter referencing an unknown library returns 1 with a clear message."""
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(run, "discover_package_dirs", lambda: [package_dir])

        result = run.test_cpython(
            [package_dir], filter_expression="ghost/test_thing",
        )
        assert result == 1

    def test_filter_with_missing_test_file_returns_one(self, monkeypatch, fake_root):
        """A file-scoped filter for a nonexistent test file returns 1."""
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(run, "discover_package_dirs", lambda: [package_dir])

        commands: list[list[str]] = []
        monkeypatch.setattr(
            run, "run_command",
            lambda command, **kwargs: (commands.append(command), 0)[1],
        )

        result = run.test_cpython(
            [package_dir], filter_expression="timing/no_such_file/test_thing",
        )
        assert result == 1
        # No pytest run before the file-existence check failed.
        assert commands == []

    def test_filter_swallows_exit_code_5(self, monkeypatch, fake_root):
        """pytest exit code 5 (no tests collected) does not propagate as a failure."""
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(run, "discover_package_dirs", lambda: [package_dir])

        def fake_run_command(command, **kwargs):
            # Pytest invocations have "pytest" as the third element
            # (PYTHON, "-m", "pytest", ...); coverage runs use "coverage".
            if len(command) > 2 and command[2] == "pytest":
                return 5
            return 0

        monkeypatch.setattr(run, "run_command", fake_run_command)
        result = run.test_cpython(
            [package_dir],
            filter_expression="timing/test_nothing_matches",
            no_cov=True,
        )
        assert result == 0

    def test_real_failure_propagates(self, monkeypatch, fake_root):
        """Non-zero non-5 exit codes from pytest propagate as the function's return."""
        package_dir = _make_test_package(fake_root, "timing")

        monkeypatch.setattr(run, "run_command", lambda command, **kwargs: 17)
        result = run.test_cpython([package_dir], no_cov=True)
        assert result == 17

    def test_coverage_threshold_passes_through(self, monkeypatch, fake_root):
        """coverage_threshold appears as --cov-fail-under in the pytest command."""
        package_dir = _make_test_package(fake_root, "timing")

        recorded: list[list[str]] = []

        def fake_run_command(command, **kwargs):
            recorded.append(command)
            return 0

        monkeypatch.setattr(run, "run_command", fake_run_command)
        run.test_cpython([package_dir], coverage_threshold=94)

        pytest_calls = [command for command in recorded if "-m" in command and "pytest" in command]
        assert any("--cov-fail-under=94" in command for command in pytest_calls)

    def test_elevated_packages_only_apply_threshold_to_listed_packages(
        self, monkeypatch, fake_root,
    ):
        """elevated_packages constrains which packages get the elevated threshold."""
        package_a = _make_test_package(fake_root, "alpha")
        package_b = _make_test_package(fake_root, "beta")

        recorded: list[list[str]] = []

        def fake_run_command(command, **kwargs):
            recorded.append(command)
            return 0

        monkeypatch.setattr(run, "run_command", fake_run_command)
        run.test_cpython(
            [package_a, package_b],
            coverage_threshold=94,
            elevated_packages={"alpha"},
        )

        # Only the alpha pytest run should carry --cov-fail-under=94.
        pytest_calls = [command for command in recorded if "-m" in command and "pytest" in command]
        alpha_calls = [
            command for command in pytest_calls
            if any("alpha" in str(arg) for arg in command)
        ]
        beta_calls = [
            command for command in pytest_calls
            if any("beta" in str(arg) for arg in command) and not any(
                "alpha" in str(arg) for arg in command
            )
        ]
        assert any("--cov-fail-under=94" in command for command in alpha_calls)
        assert not any("--cov-fail-under=94" in command for command in beta_calls)

    def test_no_cov_skips_coverage_collection(self, monkeypatch, fake_root):
        """no_cov=True omits --cov= collection flags (--cov-fail-under=0 still set)."""
        package_dir = _make_test_package(fake_root, "timing")

        recorded: list[list[str]] = []
        monkeypatch.setattr(
            run, "run_command",
            lambda command, **kwargs: (recorded.append(command), 0)[1],
        )

        run.test_cpython([package_dir], no_cov=True)
        pytest_calls = [command for command in recorded if "-m" in command and "pytest" in command]
        for command in pytest_calls:
            # No --cov= collection target.
            assert not any(arg.startswith("--cov=") for arg in command)
            # Implementation passes --cov-fail-under=0 to skip the gate when
            # no_cov is set; just ensure no real threshold is enforced.
            for arg in command:
                if arg.startswith("--cov-fail-under="):
                    assert arg == "--cov-fail-under=0"

    def test_filter_skips_coverage_gate(self, monkeypatch, fake_root):
        """filter_expression sets cov-fail-under=0 since filters reduce coverage."""
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(run, "discover_package_dirs", lambda: [package_dir])

        recorded: list[list[str]] = []
        monkeypatch.setattr(
            run, "run_command",
            lambda command, **kwargs: (recorded.append(command), 0)[1],
        )

        run.test_cpython(
            [package_dir], filter_expression="timing/test_thing",
        )
        pytest_calls = [command for command in recorded if "-m" in command and "pytest" in command]
        assert any("--cov-fail-under=0" in command for command in pytest_calls)

    def test_exit_first_passes_x_flag(self, monkeypatch, fake_root):
        """exit_first=True adds -x to the pytest command."""
        package_dir = _make_test_package(fake_root, "timing")
        recorded: list[list[str]] = []
        monkeypatch.setattr(
            run, "run_command",
            lambda command, **kwargs: (recorded.append(command), 0)[1],
        )
        run.test_cpython([package_dir], exit_first=True, no_cov=True)
        pytest_calls = [command for command in recorded if "-m" in command and "pytest" in command]
        assert any("-x" in command for command in pytest_calls)

    def test_verbose_passes_v_flag(self, monkeypatch, fake_root):
        """verbose=True adds -v to the pytest command."""
        package_dir = _make_test_package(fake_root, "timing")
        recorded: list[list[str]] = []
        monkeypatch.setattr(
            run, "run_command",
            lambda command, **kwargs: (recorded.append(command), 0)[1],
        )
        run.test_cpython([package_dir], verbose=True, no_cov=True)
        pytest_calls = [command for command in recorded if "-m" in command and "pytest" in command]
        assert any("-v" in command for command in pytest_calls)


# ---------------------------------------------------------------------------
# Tests for _run_phases_in_parallel (parallel test_runtime_matrix)
# ---------------------------------------------------------------------------


class TestRunPhasesInParallel:
    """Tests for _run_phases_in_parallel buffered-output behavior."""

    def test_runs_all_phases_concurrently(self, capsys):
        """All phases run; their outputs appear in submission order."""
        log: list[str] = []

        def phase_one() -> int:
            print("from phase one")
            log.append("one")
            return 0

        def phase_two() -> int:
            print("from phase two")
            log.append("two")
            return 0

        result = run._run_phases_in_parallel((
            ("first", phase_one),
            ("second", phase_two),
        ))
        assert result == 0
        # Both phases ran.
        assert sorted(log) == ["one", "two"]
        # Output order matches submission order regardless of scheduling.
        out = capsys.readouterr().out
        first_index = out.index("from phase one")
        second_index = out.index("from phase two")
        assert first_index < second_index
        assert "== first ==" in out
        assert "== second ==" in out

    def test_first_failure_short_circuits_return_value(self):
        """A failing phase's exit code (in submission order) becomes the return."""

        def phase_failing() -> int:
            return 7

        def phase_succeeding() -> int:
            return 0

        result = run._run_phases_in_parallel((
            ("succeeded", phase_succeeding),
            ("failed", phase_failing),
        ))
        assert result == 7

    def test_first_failure_in_submission_order(self):
        """When two phases fail, the first one in submission order wins."""

        def phase_a() -> int:
            return 11

        def phase_b() -> int:
            return 13

        result = run._run_phases_in_parallel((
            ("a", phase_a),
            ("b", phase_b),
        ))
        assert result == 11

    def test_phase_crash_treated_as_failure(self, capsys):
        """An exception in a phase is captured and treated as exit code 1."""

        def phase_crashes() -> int:
            raise RuntimeError("oh no")

        result = run._run_phases_in_parallel((
            ("crashy", phase_crashes),
        ))
        assert result == 1
        out = capsys.readouterr().out
        assert "crashed" in out
