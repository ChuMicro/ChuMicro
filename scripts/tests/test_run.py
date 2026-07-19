"""Tests for run.py — CLI filter parsing and dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest
import run
from run_tasks import _dispatch, functional, testing_cpython, testing_crossruntime
from run_tasks import preflight as preflight_tasks
from run_tasks.testing_cpython import _parse_library_filters


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
        assert "test-libraries-functional" in captured.out

    @pytest.mark.parametrize(
        ("task_name", "function_name"),
        [
            ("setup", "setup"),
            ("sync-ide", "sync_ide"),
            ("lint", "lint"),
            ("prepare-micropython", "prepare_micropython"),
            ("prepare-circuitpython", "prepare_circuitpython"),
            ("prepare-mpy-cross", "prepare_mpy_cross"),
            ("check-dep-graph", "check_dep_graph"),
            ("check-size", "check_size"),
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

    def test_check_version_dispatches_base(self, monkeypatch) -> None:
        """``check-version`` forwards ``--base`` to ``check_version()``."""
        calls, fake_check_version = _make_fake_command(return_value=23)
        monkeypatch.setattr(run, "check_version", fake_check_version)

        result = run.main(["run.py", "check-version", "--base", "origin/dev"])

        assert result == 23
        assert calls == [((), {"base": "origin/dev"})]

    def test_check_version_defaults_base_to_origin_main(self, monkeypatch) -> None:
        """``check-version`` defaults ``--base`` to ``origin/main``."""
        calls, fake_check_version = _make_fake_command(return_value=23)
        monkeypatch.setattr(run, "check_version", fake_check_version)

        result = run.main(["run.py", "check-version"])

        assert result == 23
        assert calls == [((), {"base": "origin/main"})]

    def test_build_dispatches_package_workers(self, monkeypatch) -> None:
        """``build`` forwards ``--package-workers`` to ``build()``."""
        calls, fake_build = _make_fake_command(return_value=24)
        monkeypatch.setattr(run, "build", fake_build)

        result = run.main(["run.py", "build", "--package-workers", "8"])

        assert result == 24
        assert calls == [((), {"package_workers": 8, "quiet": False})]

    def test_check_api_dispatches_max_workers(self, monkeypatch) -> None:
        """``check-api`` forwards ``--max-workers`` and ``--base`` to ``check_api()``."""
        calls, fake_check_api = _make_fake_command(return_value=25)
        monkeypatch.setattr(run, "check_api", fake_check_api)

        result = run.main(["run.py", "check-api", "--max-workers", "6"])

        assert result == 25
        assert calls == [((), {"max_workers": 6, "base": "origin/main"})]

    def test_check_api_dispatches_base(self, monkeypatch) -> None:
        """``check-api`` forwards ``--base`` to ``check_api()``."""
        calls, fake_check_api = _make_fake_command(return_value=25)
        monkeypatch.setattr(run, "check_api", fake_check_api)

        result = run.main(
            ["run.py", "check-api", "--base", "origin/dev", "--max-workers", "2"],
        )

        assert result == 25
        assert calls == [((), {"max_workers": 2, "base": "origin/dev"})]

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
                "elevated_packages": None,
                "package_workers": _dispatch._DEFAULT_PACKAGE_PARALLEL_WORKERS,
                "quiet": False,
                "slow_test_threshold_s": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
                "allow_no_tests": False,
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
                "elevated_packages": None,
                "package_workers": _dispatch._DEFAULT_PACKAGE_PARALLEL_WORKERS,
                "quiet": False,
                "slow_test_threshold_s": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
                "allow_no_tests": False,
            }),
        ]

    def test_test_command_parses_elevated_packages_csv(self, monkeypatch) -> None:
        """`--elevated-packages a,b,c` becomes a {a, b, c} set on test_cpython."""
        resolved_packages = [Path("/tmp/timing"), Path("/tmp/runner")]
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: resolved_packages,
        )
        command_calls, fake_test_cpython = _make_fake_command(return_value=23)
        monkeypatch.setattr(run, "test_cpython", fake_test_cpython)

        result = run.main([
            "run.py", "test", "--all",
            "--coverage-threshold", "94",
            "--elevated-packages", "timing,runner, websockets ",
        ])

        assert result == 23
        # Whitespace tolerated, empty entries dropped.
        assert command_calls[0][1]["elevated_packages"] == {
            "timing", "runner", "websockets",
        }
        assert command_calls[0][1]["coverage_threshold"] == 94

    def test_test_command_empty_elevated_packages_resolves_to_none(
        self, monkeypatch,
    ) -> None:
        """`--elevated-packages ,, ` collapses to None (no opt-in libraries)."""
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: [Path("/tmp/timing")],
        )
        command_calls, fake_test_cpython = _make_fake_command(return_value=29)
        monkeypatch.setattr(run, "test_cpython", fake_test_cpython)

        result = run.main([
            "run.py", "test", "--all", "--elevated-packages", " , , ",
        ])

        assert result == 29
        assert command_calls[0][1]["elevated_packages"] is None

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
        assert command_calls == [
            ((resolved_packages,), {
                "serve": True,
                "package_workers": _dispatch._DEFAULT_PACKAGE_PARALLEL_WORKERS,
                "quiet": False,
            }),
        ]

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
        """new-library should pass through the name; library kind by default."""
        command_calls, fake_new_library = _make_fake_command(return_value=13)
        monkeypatch.setattr(run, "new_library", fake_new_library)

        result = run.main(["run.py", "new-library", "settings"])

        assert result == 13
        assert command_calls == [(("settings",), {"workbench": False})]

    def test_new_library_dispatches_workbench_flag(self, monkeypatch) -> None:
        """--workbench should reach new_library as workbench=True."""
        command_calls, fake_new_library = _make_fake_command(return_value=0)
        monkeypatch.setattr(run, "new_library", fake_new_library)

        result = run.main(["run.py", "new-library", "--workbench", "mytool"])

        assert result == 0
        assert command_calls == [(("mytool",), {"workbench": True})]

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
            (
                ("/tmp/mpy", "/tmp/cpy"),
                {
                    "coverage_threshold": 94,
                    "with_functional": False,
                    "with_device_unit": False,
                    "phase_workers": None,
                    "package_workers": _dispatch._DEFAULT_PACKAGE_PARALLEL_WORKERS,
                    "quiet": False,
                    "slow_test_threshold_cpython": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
                    "slow_test_threshold_unix_port": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
                },
            ),
        ]

    def test_runtime_compatibility_commands_dispatch(self, monkeypatch) -> None:
        """Runtime-specific compatibility tasks should forward their binary paths."""
        micropython_calls, fake_micropython = _make_fake_command(return_value=43)
        circuitpython_calls, fake_circuitpython = _make_fake_command(return_value=47)
        monkeypatch.setattr(
            run, "test_micropython", fake_micropython,
        )
        monkeypatch.setattr(
            run, "test_circuitpython", fake_circuitpython,
        )

        micropython_result = run.main([
            "run.py", "test-micropython",
            "--micropython-binary", "/tmp/mpy",
        ])
        circuitpython_result = run.main([
            "run.py", "test-circuitpython",
            "--circuitpython-binary", "/tmp/cpy",
        ])

        unix_port_kwargs = {
            "slow_test_threshold_s": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
        }
        assert micropython_result == 43
        assert circuitpython_result == 47
        assert micropython_calls == [(("/tmp/mpy", None), unix_port_kwargs)]
        assert circuitpython_calls == [(("/tmp/cpy", None), unix_port_kwargs)]

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
            run, "test_micropython", fake_micropython,
        )

        result = run.main([
            "run.py", "test-micropython",
            "--libraries", "timing",
        ])

        assert result == 49
        assert command_calls == [
            ((None, resolved_packages), {
                "slow_test_threshold_s": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
            }),
        ]

    def test_test_all_runtimes_dispatches_binary_paths(self, monkeypatch) -> None:
        """test-all-runtimes should receive both optional binary overrides."""
        command_calls, fake_test_all_runtimes = _make_fake_command(return_value=53)
        monkeypatch.setattr(run, "test_all_runtimes", fake_test_all_runtimes)

        result = run.main([
            "run.py", "test-all-runtimes",
            "--micropython-binary", "/tmp/mpy",
            "--circuitpython-binary", "/tmp/cpy",
        ])

        assert result == 53
        assert command_calls == [
            (("/tmp/mpy", "/tmp/cpy", None), {
                "slow_test_threshold_s": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
            }),
        ]

    def test_test_all_runtimes_dispatches_scoped_packages(self, monkeypatch) -> None:
        """test-all-runtimes should forward an explicit package scope."""
        resolved_packages = [Path("/tmp/timing")]
        monkeypatch.setattr(
            run, "resolve_scope", lambda **kwargs: resolved_packages,
        )
        command_calls, fake_test_all_runtimes = _make_fake_command(return_value=57)
        monkeypatch.setattr(run, "test_all_runtimes", fake_test_all_runtimes)

        result = run.main([
            "run.py", "test-all-runtimes", "--libraries", "timing",
        ])

        assert result == 57
        assert command_calls == [
            ((None, None, resolved_packages), {
                "slow_test_threshold_s": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
            }),
        ]

    def test_preflight_with_functional_flag_dispatches_through(
        self, monkeypatch,
    ) -> None:
        """preflight --with-functional should propagate the flag to preflight()."""
        command_calls, fake_preflight = _make_fake_command(return_value=42)
        monkeypatch.setattr(run, "preflight", fake_preflight)

        result = run.main(["run.py", "preflight", "--with-functional"])

        assert result == 42
        assert command_calls == [
            (
                (None, None),
                {
                    "coverage_threshold": None,
                    "with_functional": True,
                    "with_device_unit": False,
                    "phase_workers": None,
                    "package_workers": _dispatch._DEFAULT_PACKAGE_PARALLEL_WORKERS,
                    "quiet": False,
                    "slow_test_threshold_cpython": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
                    "slow_test_threshold_unix_port": _dispatch._DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
                },
            ),
        ]

    def test_test_functional_dispatches_flags(self, monkeypatch) -> None:
        """test-functional should forward -v and -x to test_functional()."""
        command_calls, fake_test_functional = _make_fake_command(return_value=63)
        monkeypatch.setattr(run, "test_functional", fake_test_functional)

        result = run.main(["run.py", "test-functional", "-v", "-x"])

        assert result == 63
        assert command_calls == [
            ((), {"verbose": True, "exit_first": True}),
        ]

    def test_test_libraries_functional_without_filters_passes_none_values(
        self, monkeypatch,
    ) -> None:
        """Bare test-libraries-functional should defer device selection to lower-level defaults."""
        command_calls, fake_test_libraries_functional = _make_fake_command(return_value=59)
        monkeypatch.setattr(run, "test_libraries_functional", fake_test_libraries_functional)

        result = run.main(["run.py", "test-libraries-functional"])

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

    def test_test_libraries_functional_forwards_explicit_cli_filters(self, monkeypatch) -> None:
        """test-libraries-functional should forward explicit runtime and filter flags."""
        command_calls, fake_test_libraries_functional = _make_fake_command(return_value=61)
        monkeypatch.setattr(run, "test_libraries_functional", fake_test_libraries_functional)

        result = run.main([
            "run.py", "test-libraries-functional",
            "--runtime", "circuitpython",
            "--library", "timing",
            "--file", "test_heartbeat",
            "--function", "heartbeat_fires",
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

    def test_test_libraries_functional_accepts_explicit_both_runtime(self, monkeypatch) -> None:
        """test-libraries-functional should allow `--runtime both` as an explicit defaults alias."""
        command_calls, fake_test_libraries_functional = _make_fake_command(return_value=67)
        monkeypatch.setattr(run, "test_libraries_functional", fake_test_libraries_functional)

        result = run.main(["run.py", "test-libraries-functional", "--runtime", "both"])

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

    def test_test_libraries_functional_forwards_per_runtime_device_overrides(
        self, monkeypatch,
    ) -> None:
        """test-libraries-functional should forward explicit per-runtime device overrides."""
        command_calls, fake_test_libraries_functional = _make_fake_command(return_value=71)
        monkeypatch.setattr(run, "test_libraries_functional", fake_test_libraries_functional)

        result = run.main([
            "run.py", "test-libraries-functional",
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

    def test_test_libraries_functional_rejects_removed_legacy_device_flag(self) -> None:
        """The removed --device flag should fail with an argparse error."""
        with pytest.raises(SystemExit, match="2"):
            run.main([
                "run.py", "test-libraries-functional",
                "--device", "board-1",
            ])

    def test_test_unit_on_device_without_flags_passes_none_values(
        self, monkeypatch,
    ) -> None:
        command_calls, fake = _make_fake_command(return_value=53)
        monkeypatch.setattr(run, "test_unit_on_device", fake)

        result = run.main(["run.py", "test-unit-on-device"])

        assert result == 53
        assert command_calls == [
            ((), {
                "runtime": None,
                "micropython_device": None,
                "circuitpython_device": None,
                "deploy_mode": None,
                "library": None,
                "per_file": False,
            }),
        ]

    def test_test_unit_on_device_forwards_explicit_flags(
        self, monkeypatch,
    ) -> None:
        command_calls, fake = _make_fake_command(return_value=57)
        monkeypatch.setattr(run, "test_unit_on_device", fake)

        result = run.main([
            "run.py", "test-unit-on-device",
            "--runtime", "circuitpython",
            "--circuitpython-device", "cp-alt",
            "--deploy-mode", "flash",
            "--library", "ntp",
        ])

        assert result == 57
        assert command_calls == [
            ((), {
                "runtime": "circuitpython",
                "micropython_device": None,
                "circuitpython_device": "cp-alt",
                "deploy_mode": "flash",
                "library": "ntp",
                "per_file": False,
            }),
        ]

    def test_test_unit_on_device_forwards_per_file(
        self, monkeypatch,
    ) -> None:
        command_calls, fake = _make_fake_command(return_value=58)
        monkeypatch.setattr(run, "test_unit_on_device", fake)

        result = run.main([
            "run.py", "test-unit-on-device", "--per-file",
        ])

        assert result == 58
        assert command_calls[0][1]["per_file"] is True

    def test_test_workbench_functional_without_filters_passes_none_values(
        self, monkeypatch,
    ) -> None:
        """Bare test-workbench-functional forwards no filters and uses devices.yml defaults."""
        command_calls, fake_test_workbench_functional = _make_fake_command(return_value=79)
        monkeypatch.setattr(run, "test_workbench_functional", fake_test_workbench_functional)

        result = run.main(["run.py", "test-workbench-functional"])

        assert result == 79
        assert command_calls == [
            ((), {
                "workbench": None,
                "file_filter": None,
                "function_filter": None,
                "verbose": False,
                "exit_first": False,
            }),
        ]

    def test_test_workbench_functional_forwards_explicit_cli_filters(self, monkeypatch) -> None:
        """test-workbench-functional should forward --workbench / --file / --function / -v / -x."""
        command_calls, fake_test_workbench_functional = _make_fake_command(return_value=83)
        monkeypatch.setattr(run, "test_workbench_functional", fake_test_workbench_functional)

        result = run.main([
            "run.py", "test-workbench-functional",
            "--workbench", "deploy",
            "--file", "test_deploy_files_hardware",
            "--function", "circuitpython_ram",
            "-v",
            "-x",
        ])

        assert result == 83
        assert command_calls == [
            ((), {
                "workbench": "deploy",
                "file_filter": "test_deploy_files_hardware",
                "function_filter": "circuitpython_ram",
                "verbose": True,
                "exit_first": True,
            }),
        ]


class TestPassThroughShims:
    """``add-device`` and ``deploy-example`` peel off before argparse
    and forward verbatim to ``python -m chumicro_workspace <cmd>``.
    The shim's contract: any args after the subcommand name flow
    through unchanged, and the workspace process's exit code is
    returned to the caller."""

    @pytest.mark.parametrize(
        ("subcommand", "extra_args"),
        [
            ("add-device", ["my-pico", "--address", "/dev/cu.fake"]),
            ("deploy-example", ["timing", "circuitpython_blink", "--non-interactive"]),
            ("deploy-example", ["--list"]),
            ("deploy-example", ["--list", "timing"]),
        ],
    )
    def test_subcommand_forwards_to_workspace(
        self, monkeypatch, subcommand: str, extra_args: list[str],
    ) -> None:
        """The shim spawns the workspace CLI with verbatim args
        and returns its exit code."""
        seen: list[list[str]] = []

        class _FakeCompletedProcess:
            def __init__(self, returncode: int) -> None:
                self.returncode = returncode

        def fake_subprocess_run(command, **_kwargs):
            seen.append(list(command))
            return _FakeCompletedProcess(returncode=42)

        monkeypatch.setattr(run.subprocess, "run", fake_subprocess_run)

        result = run.main(["run.py", subcommand, *extra_args])

        assert result == 42
        assert len(seen) == 1
        forwarded = seen[0]
        # Forwarded shape:  <python> -m chumicro_workspace <subcommand> <extra...>
        assert forwarded[1:3] == ["-m", "chumicro_workspace"]
        assert forwarded[3] == subcommand
        assert forwarded[4:] == extra_args


class TestTestWorkbenchFunctional:
    """Tests for functional.test_workbench_functional — workbench functional-test orchestration."""

    def _stub_discovery(self, monkeypatch, tmp_path: Path) -> list[Path]:
        """Build two fake workbench packages and return their paths.

        Only ``alpha`` has a ``functional_tests/`` directory so tests
        can exercise the "skip-suites-without-fn-dir" path cleanly.
        """
        alpha = tmp_path / "alpha"
        (alpha / "functional_tests").mkdir(parents=True)
        beta = tmp_path / "beta"
        beta.mkdir()
        monkeypatch.setattr(functional, "discover_workbench_dirs", lambda: [alpha, beta])
        return [alpha, beta]

    def _record_invocations(self, monkeypatch) -> list[list[str]]:
        """Replace ``functional.run_command`` with a recorder that returns 0."""
        invocations: list[list[str]] = []

        def fake_run_command(command, **_kwargs):
            invocations.append(command)
            return 0

        monkeypatch.setattr(functional, "run_command", fake_run_command)
        return invocations

    def test_runs_pytest_for_every_workbench_with_functional_tests(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        """Every workbench that ships functional_tests/ contributes one pytest call."""
        alpha, _beta = self._stub_discovery(monkeypatch, tmp_path)
        invocations = self._record_invocations(monkeypatch)

        result = functional.test_workbench_functional()

        assert result == 0
        assert len(invocations) == 1
        assert str(alpha / "functional_tests") in invocations[0]

    def test_workbench_functional_filter_limits_to_named_package(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        """--workbench alpha keeps only the alpha suite."""
        alpha, _beta = self._stub_discovery(monkeypatch, tmp_path)
        invocations = self._record_invocations(monkeypatch)

        result = functional.test_workbench_functional(workbench="alpha")

        assert result == 0
        assert len(invocations) == 1
        assert str(alpha / "functional_tests") in invocations[0]

    def test_unknown_workbench_returns_nonzero(
        self, monkeypatch, tmp_path: Path, capsys,
    ) -> None:
        """--workbench with no matching package errors out."""
        self._stub_discovery(monkeypatch, tmp_path)
        monkeypatch.setattr(functional, "run_command", lambda *_args, **_kwargs: 0)

        result = functional.test_workbench_functional(workbench="ghost")

        assert result == 1
        captured = capsys.readouterr()
        assert "ghost" in captured.out

    def test_file_and_function_filters_compose_via_and(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        """Both filters combine into a single pytest ``-k A and B`` expression."""
        self._stub_discovery(monkeypatch, tmp_path)
        invocations = self._record_invocations(monkeypatch)

        result = functional.test_workbench_functional(
            file_filter="test_deploy_files_hardware",
            function_filter="circuitpython_ram",
        )

        assert result == 0
        keyword_index = invocations[0].index("-k")
        assert invocations[0][keyword_index + 1] == (
            "test_deploy_files_hardware and circuitpython_ram"
        )

    def test_first_failing_suite_exit_code_wins(
        self, monkeypatch, tmp_path: Path,
    ) -> None:
        """When two suites run and the first fails, its exit code is returned."""
        alpha = tmp_path / "alpha"
        (alpha / "functional_tests").mkdir(parents=True)
        gamma = tmp_path / "gamma"
        (gamma / "functional_tests").mkdir(parents=True)
        monkeypatch.setattr(
            functional, "discover_workbench_dirs", lambda: [alpha, gamma],
        )
        return_values = iter([5, 0])
        monkeypatch.setattr(functional, "run_command", lambda *_args, **_kwargs: next(return_values))

        result = functional.test_workbench_functional()

        assert result == 5

    def test_empty_workbench_space_returns_zero(
        self, monkeypatch, capsys,
    ) -> None:
        """No workbench package with fn-tests prints a note and returns 0."""
        monkeypatch.setattr(functional, "discover_workbench_dirs", lambda: [])
        monkeypatch.setattr(functional, "run_command", lambda *_args, **_kwargs: 0)

        result = functional.test_workbench_functional()

        assert result == 0
        assert "No functional_tests/" in capsys.readouterr().out


class TestCompositeTestCommands:
    """Tests for aggregated developer test commands."""

    def test_test_all_runtimes_forwards_package_scope(self, monkeypatch) -> None:
        """test-all-runtimes should pass scoped packages to every phase."""
        package_dirs = [Path("/tmp/timing")]
        cpython_calls, fake_cpython = _make_fake_command(return_value=0)
        micropython_calls, fake_micropython = _make_fake_command(return_value=0)
        circuitpython_calls, fake_circuitpython = _make_fake_command(return_value=0)
        monkeypatch.setattr(testing_crossruntime, "test_cpython", fake_cpython)
        monkeypatch.setattr(testing_crossruntime, "test_micropython", fake_micropython)
        monkeypatch.setattr(testing_crossruntime, "test_circuitpython", fake_circuitpython)

        result = run.test_all_runtimes(
            "/tmp/mpy", "/tmp/cpy", package_dirs,
        )

        assert result == 0
        # cpython runs first in-process; mp + cp each receive a sink
        # injected by the parallel-phase runner.
        assert cpython_calls == [((package_dirs,), {})]
        assert len(micropython_calls) == 1
        mpy_args, mpy_kwargs = micropython_calls[0]
        assert mpy_args == ("/tmp/mpy", package_dirs)
        assert isinstance(mpy_kwargs.get("sink"), _dispatch._Sink)
        assert len(circuitpython_calls) == 1
        cpy_args, cpy_kwargs = circuitpython_calls[0]
        assert cpy_args == ("/tmp/cpy", package_dirs)
        assert isinstance(cpy_kwargs.get("sink"), _dispatch._Sink)

    def test_test_functional_runs_libraries_then_workbench(
        self, monkeypatch,
    ) -> None:
        """test_functional() should run libraries-functional then workbench-functional."""
        order: list[str] = []

        def fake_libraries() -> int:
            order.append("libraries")
            return 0

        workbench_calls: list[dict] = []

        def fake_workbench(**kwargs) -> int:
            order.append("workbench")
            workbench_calls.append(kwargs)
            return 0

        monkeypatch.setattr(functional, "test_libraries_functional", fake_libraries)
        monkeypatch.setattr(functional, "test_workbench_functional", fake_workbench)

        result = run.test_functional(verbose=True, exit_first=True)

        assert result == 0
        assert order == ["libraries", "workbench"]
        assert workbench_calls == [{"verbose": True, "exit_first": True}]

    def test_test_functional_first_failure_short_circuits(
        self, monkeypatch,
    ) -> None:
        """A failing libraries phase should prevent the workbench phase from running."""
        monkeypatch.setattr(
            functional, "test_libraries_functional", lambda: 7,
        )

        def fail_workbench(**_kwargs) -> int:
            raise AssertionError("workbench phase should not run after libraries fail")

        monkeypatch.setattr(functional, "test_workbench_functional", fail_workbench)

        result = run.test_functional()

        assert result == 7

    def test_preflight_with_functional_appends_functional_phases(
        self, monkeypatch,
    ) -> None:
        """preflight(with_functional=True) should append both functional phases.

        After Decision 0048 the unit-test phases are subprocess
        re-invocations of ``python scripts/run.py <subcommand>``,
        fanned out via ``_preflight_run_parallel_phases``.  We
        monkeypatch that single seam to bypass the subprocess block
        and verify the post-block functional tail still runs both
        phases serially in submission order.
        """
        monkeypatch.setattr(
            preflight_tasks, "_preflight_run_parallel_phases",
            lambda phases, **_kwargs: (0, None, []),
        )
        monkeypatch.setattr(preflight_tasks, "is_ref_reachable", lambda *_args, **_kwargs: True)

        functional_calls: list[str] = []
        monkeypatch.setattr(
            preflight_tasks, "test_libraries_functional",
            lambda: functional_calls.append("libraries") or 0,
        )
        monkeypatch.setattr(
            preflight_tasks, "test_workbench_functional",
            lambda **_kwargs: functional_calls.append("workbench") or 0,
        )

        result = run.preflight(with_functional=True)

        assert result == 0
        assert functional_calls == ["libraries", "workbench"]


# ---------------------------------------------------------------------------
# Direct tests for run.test_cpython
# ---------------------------------------------------------------------------


def _make_test_package(tmp_path: Path, name: str) -> Path:
    """Create a fake library directory with a tests/ subdir.

    The ``src/chumicro_<name>/__init__.py`` makes the package an
    importable, coverage-resolvable directory — without it
    ``coverage_args_for`` returns no ``--cov`` source and test_cpython
    now refuses the run rather than ship an inert gate.
    """
    package_dir = tmp_path / name
    (package_dir / "tests").mkdir(parents=True)
    source_dir = package_dir / "src" / f"chumicro_{name}"
    source_dir.mkdir(parents=True)
    (source_dir / "__init__.py").write_text("")
    return package_dir


@pytest.fixture
def fake_root(monkeypatch, tmp_path):
    """Repoint ROOT at a tmp_path so relative_to() works for fake packages.

    Patches both ``testing_cpython.ROOT`` and ``repo_layout.ROOT`` — ``test_cpython``
    builds labels off the former while ``coverage_args_for`` resolves
    ``--cov`` paths against the latter.
    """
    import repo_layout

    monkeypatch.setattr(testing_cpython, "ROOT", tmp_path)
    monkeypatch.setattr(repo_layout, "ROOT", tmp_path)
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

        monkeypatch.setattr(testing_cpython, "run_command", fake_run_command)
        result = testing_cpython.test_cpython([package_dir])
        assert result == 0
        assert called == []

    def test_runs_pytest_for_each_package(self, monkeypatch, fake_root):
        """Each package with tests/ produces a pytest invocation."""
        package_a = _make_test_package(fake_root, "alpha")
        package_b = _make_test_package(fake_root, "beta")

        commands: list[list[str]] = []

        def fake_run_pytest(command, environment, sink):
            commands.append(command)
            return 0

        monkeypatch.setattr(testing_cpython, "_run_pytest_capturing", fake_run_pytest)
        result = testing_cpython.test_cpython([package_a, package_b], no_cov=True)
        assert result == 0
        # Two pytest runs (one per package).
        pytest_runs = [
            command for command in commands
            if "pytest" in command[0] or "-m" in command
        ]
        assert len(pytest_runs) == 2

    def test_unknown_filter_library_returns_one(self, monkeypatch, fake_root):
        """A -k filter referencing an unknown library returns 1 with a clear message."""
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(testing_cpython, "discover_package_dirs", lambda: [package_dir])

        result = testing_cpython.test_cpython(
            [package_dir], filter_expression="ghost/test_thing",
        )
        assert result == 1

    def test_filter_with_missing_test_file_returns_one(self, monkeypatch, fake_root):
        """A file-scoped filter for a nonexistent test file returns 1."""
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(testing_cpython, "discover_package_dirs", lambda: [package_dir])

        commands: list[list[str]] = []
        monkeypatch.setattr(
            testing_cpython, "run_command",
            lambda command, **kwargs: (commands.append(command), 0)[1],
        )

        result = testing_cpython.test_cpython(
            [package_dir], filter_expression="timing/no_such_file/test_thing",
        )
        assert result == 1
        # No pytest run before the file-existence check failed.
        assert commands == []

    def test_filter_swallows_exit_code_5(self, monkeypatch, fake_root):
        """pytest exit code 5 (no tests collected) does not propagate as a failure.

        ``--allow-no-tests`` opts out of the zero-collected floor so this
        exercises the exit-5 normalization in isolation.
        """
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(testing_cpython, "discover_package_dirs", lambda: [package_dir])

        # _run_pytest_capturing normalizes pytest exit code 5 ("no tests
        # collected") to 0, mimicking what stream_subprocess + the
        # downstream remap would do for a real pytest run.
        def fake_stream(command, **_kwargs):
            return 5, ""

        monkeypatch.setattr(testing_cpython, "stream_subprocess", fake_stream)
        # Coverage post-processing also shells out via run_command;
        # short-circuit it so the test focuses on the exit-code remap.
        monkeypatch.setattr(testing_cpython, "run_command", lambda *_a, **_kw: 0)
        result = testing_cpython.test_cpython(
            [package_dir],
            filter_expression="timing/test_nothing_matches",
            no_cov=True,
            allow_no_tests=True,
        )
        assert result == 0

    def test_filter_matching_nothing_fails_by_default(self, monkeypatch, fake_root):
        """A -k filter that selects zero tests fails (the S6 zero-collected floor)."""
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(testing_cpython, "discover_package_dirs", lambda: [package_dir])
        monkeypatch.setattr(testing_cpython, "stream_subprocess", lambda command, **_kw: (5, ""))
        monkeypatch.setattr(testing_cpython, "run_command", lambda *_a, **_kw: 0)

        result = testing_cpython.test_cpython(
            [package_dir],
            filter_expression="timing/test_nothing_matches",
            no_cov=True,
        )
        assert result == 1

    def test_allow_no_tests_opts_out_of_floor(self, monkeypatch, fake_root, capsys):
        """--allow-no-tests turns the zero-collected failure back into a pass."""
        package_dir = _make_test_package(fake_root, "timing")
        monkeypatch.setattr(testing_cpython, "discover_package_dirs", lambda: [package_dir])
        monkeypatch.setattr(testing_cpython, "stream_subprocess", lambda command, **_kw: (5, ""))
        monkeypatch.setattr(testing_cpython, "run_command", lambda *_a, **_kw: 0)

        result = testing_cpython.test_cpython(
            [package_dir],
            filter_expression="timing/test_nothing_matches",
            no_cov=True,
            allow_no_tests=True,
        )
        assert result == 0
        assert "selected 0 tests" not in capsys.readouterr().out

    def test_real_failure_propagates(self, monkeypatch, fake_root):
        """Non-zero non-5 exit codes from pytest propagate as the function's return."""
        package_dir = _make_test_package(fake_root, "timing")

        monkeypatch.setattr(
            testing_cpython, "_run_pytest_capturing",
            lambda command, environment, sink: 17,
        )
        result = testing_cpython.test_cpython([package_dir], no_cov=True)
        assert result == 17

    def test_coverage_threshold_passes_through(self, monkeypatch, fake_root):
        """coverage_threshold appears as --cov-fail-under in the pytest command."""
        package_dir = _make_test_package(fake_root, "timing")

        recorded: list[list[str]] = []

        def fake_run_pytest(command, environment, sink):
            recorded.append(command)
            return 0

        monkeypatch.setattr(testing_cpython, "_run_pytest_capturing", fake_run_pytest)
        testing_cpython.test_cpython([package_dir], coverage_threshold=94)

        pytest_calls = [
            command for command in recorded if "-m" in command and "pytest" in command
        ]
        assert any("--cov-fail-under=94" in command for command in pytest_calls)

    def test_elevated_packages_only_apply_threshold_to_listed_packages(
        self, monkeypatch, fake_root,
    ):
        """elevated_packages constrains which packages get the elevated threshold."""
        package_a = _make_test_package(fake_root, "alpha")
        package_b = _make_test_package(fake_root, "beta")

        recorded: list[list[str]] = []

        def fake_run_pytest(command, environment, sink):
            recorded.append(command)
            return 0

        monkeypatch.setattr(testing_cpython, "_run_pytest_capturing", fake_run_pytest)
        testing_cpython.test_cpython(
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
            testing_cpython, "_run_pytest_capturing",
            lambda command, environment, sink: (recorded.append(command), 0)[1],
        )
        monkeypatch.setattr(testing_cpython, "run_command", lambda *_a, **_kw: 0)

        testing_cpython.test_cpython([package_dir], no_cov=True)
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
        monkeypatch.setattr(testing_cpython, "discover_package_dirs", lambda: [package_dir])

        recorded: list[list[str]] = []
        monkeypatch.setattr(
            testing_cpython, "_run_pytest_capturing",
            lambda command, environment, sink: (recorded.append(command), 0)[1],
        )

        testing_cpython.test_cpython(
            [package_dir], filter_expression="timing/test_thing",
        )
        pytest_calls = [
            command for command in recorded if "-m" in command and "pytest" in command
        ]
        assert any("--cov-fail-under=0" in command for command in pytest_calls)

    def test_exit_first_passes_x_flag(self, monkeypatch, fake_root):
        """exit_first=True adds -x to the pytest command."""
        package_dir = _make_test_package(fake_root, "timing")
        recorded: list[list[str]] = []
        monkeypatch.setattr(
            testing_cpython, "_run_pytest_capturing",
            lambda command, environment, sink: (recorded.append(command), 0)[1],
        )
        testing_cpython.test_cpython([package_dir], exit_first=True, no_cov=True)
        pytest_calls = [
            command for command in recorded if "-m" in command and "pytest" in command
        ]
        assert any("-x" in command for command in pytest_calls)

    def test_verbose_passes_v_flag(self, monkeypatch, fake_root):
        """verbose=True adds -v to the pytest command."""
        package_dir = _make_test_package(fake_root, "timing")
        recorded: list[list[str]] = []
        monkeypatch.setattr(
            testing_cpython, "_run_pytest_capturing",
            lambda command, environment, sink: (recorded.append(command), 0)[1],
        )
        testing_cpython.test_cpython([package_dir], verbose=True, no_cov=True)
        pytest_calls = [
            command for command in recorded if "-m" in command and "pytest" in command
        ]
        assert any("-v" in command for command in pytest_calls)


class TestPytestOutputFilter:
    """Tests for the per-library summary collapse + slow-test capture."""

    def test_summary_line_is_absorbed(self):
        """The ``=== N passed in Xs ===`` line is consumed, not forwarded."""
        filter_state = testing_cpython._PytestOutputFilter()
        assert filter_state.consume("==== 12 passed in 0.05s ====")
        assert filter_state.passed == 12
        assert filter_state.duration_s == 0.05

    def test_summary_line_with_skips(self):
        """Skips parse into the dedicated counter."""
        filter_state = testing_cpython._PytestOutputFilter()
        assert filter_state.consume(
            "==== 654 passed, 2 skipped in 5.42s ====",
        )
        assert filter_state.passed == 654
        assert filter_state.skipped == 2

    def test_no_tests_ran_is_absorbed(self):
        """The ``no tests ran in Xs`` line is consumed without bumping counters."""
        filter_state = testing_cpython._PytestOutputFilter()
        assert filter_state.consume("==== no tests ran in 0.01s ====")
        assert filter_state.passed == 0
        assert filter_state.skipped == 0

    def test_ansi_colored_summary_is_parsed(self):
        """A summary wrapped in ANSI SGR codes (FORCE_COLOR / tty) still parses.

        Without the sanitizer the coloured line no longer starts with ``=``,
        so the regex misses it and every count stays 0 (the S2 bug).
        """
        colored = (
            "\x1b[32m===== \x1b[1m\x1b[32m5 passed\x1b[0m\x1b[32m, "
            "2 deselected in 0.03s\x1b[0m\x1b[32m =====\x1b[0m"
        )
        filter_state = testing_cpython._PytestOutputFilter()
        assert filter_state.consume(colored)
        assert filter_state.passed == 5
        assert filter_state.deselected == 2
        assert filter_state.duration_s == 0.03

    def test_ansi_colored_durations_header_is_parsed(self):
        """A coloured ``slowest durations`` header still opens the block."""
        filter_state = testing_cpython._PytestOutputFilter()
        assert filter_state.consume(
            "\x1b[1m\x1b[33m===== slowest durations =====\x1b[0m",
        )
        assert filter_state.consume(
            "1.20s call     libraries/mqtt/tests/test_x.py::test_y",
        )
        assert filter_state.slow_tests == [
            (1.20, "libraries/mqtt/tests/test_x.py::test_y"),
        ]

    def test_durations_block_captures_call_phase_only(self):
        """``call`` rows feed slow_tests; setup/teardown rows are absorbed but ignored."""
        filter_state = testing_cpython._PytestOutputFilter()
        assert filter_state.consume(
            "============ slowest durations ============",
        )
        assert filter_state.consume(
            "1.43s call     libraries/mqtt/tests/test_x.py::test_y",
        )
        assert filter_state.consume(
            "0.98s teardown libraries/mqtt/tests/test_x.py::test_y",
        )
        assert filter_state.consume("(3 durations < 0.5s hidden.)")
        assert filter_state.slow_tests == [
            (1.43, "libraries/mqtt/tests/test_x.py::test_y"),
        ]

    def test_progress_lines_pass_through(self):
        """Non-summary lines (test progress, tracebacks) are not absorbed."""
        filter_state = testing_cpython._PytestOutputFilter()
        assert not filter_state.consume(
            "libraries/timing/tests/test_x.py ......  [100%]",
        )
        assert not filter_state.consume("E   AssertionError: oops")


class TestFormatPytestPhaseSummary:
    """Tests for the rolled-up phase-summary formatter."""

    def test_single_invocation_omits_library_count_clause(self):
        """A single pytest result skips the ``across N libraries`` clause."""
        result = testing_cpython._PytestRunResult(
            label="test-micropython", exit_code=0, passed=654, duration_s=5.01,
        )
        lines = testing_cpython._format_pytest_phase_summary(
            "test-micropython", [result], slow_threshold_s=2.0,
        )
        assert lines == [
            "test-micropython: 654 passed in 5.01s",
        ]

    def test_multi_library_includes_skips(self):
        """Aggregated skip counts reach the rolled-up summary."""
        results = [
            testing_cpython._PytestRunResult(
                label="a", exit_code=0, passed=10, skipped=1, duration_s=0.1,
            ),
            testing_cpython._PytestRunResult(
                label="b", exit_code=0, passed=20, skipped=1, duration_s=0.2,
            ),
        ]
        lines = testing_cpython._format_pytest_phase_summary(
            "test", results, slow_threshold_s=1.0,
        )
        assert lines == [
            "test: 30 passed, 2 skipped across 2 libraries in 0.30s",
        ]

    def test_slow_notice_lists_only_tests_above_threshold(self):
        """Tests at or above *slow_threshold_s* appear in the SLOW notice."""
        results = [
            testing_cpython._PytestRunResult(
                label="a", exit_code=0, passed=3, duration_s=2.5,
                slow_tests=[(2.10, "a::slow"), (0.50, "a::fast")],
            ),
        ]
        lines = testing_cpython._format_pytest_phase_summary(
            "test-micropython", results, slow_threshold_s=2.0,
        )
        assert len(lines) == 2
        assert "SLOW (>2.0s)" in lines[1]
        assert "a::slow (2.10s)" in lines[1]
        assert "a::fast" not in lines[1]

    def test_no_slow_notice_when_all_under_threshold(self):
        """Only the summary line is emitted when no test crosses the threshold."""
        results = [
            testing_cpython._PytestRunResult(
                label="a", exit_code=0, passed=3, duration_s=0.5,
                slow_tests=[(0.6, "a::moderate")],
            ),
        ]
        lines = testing_cpython._format_pytest_phase_summary(
            "test", results, slow_threshold_s=1.0,
        )
        assert len(lines) == 1


class TestUnixPortPytestCommand:
    """Tests for the single-pytest unix-port command builder."""

    def test_durations_threshold_flows_in(self):
        """``--durations=0 --durations-min=<threshold>`` lands on every command."""
        command = testing_crossruntime._pytest_unix_port_command(
            "micropython", "/tmp/mpy", None,
            slow_test_threshold_s=1.5,
        )
        assert "--durations=0" in command
        assert "--durations-min=1.5" in command

    def test_runtime_binary_forwarded(self):
        """``--{runtime}-binary <path>`` is appended when *binary* is set."""
        command = testing_crossruntime._pytest_unix_port_command(
            "circuitpython", "/tmp/cpy", None,
            slow_test_threshold_s=2.0,
        )
        assert "--circuitpython-binary" in command
        assert "/tmp/cpy" in command


# ---------------------------------------------------------------------------
# Tests for _run_parallel_phases (the unified runner) and the dispatchers
# ---------------------------------------------------------------------------


class TestRunParallelPhases:
    """Tests for _run_parallel_phases shape + dispatcher contract."""

    def test_runs_all_phases_concurrently(self):
        """Every submitted phase callable is invoked with a sink."""
        log: list[str] = []

        def phase_one(sink) -> int:
            sink.line("from phase one")
            log.append("one")
            return 0

        def phase_two(sink) -> int:
            sink.line("from phase two")
            log.append("two")
            return 0

        exit_code, failing_label, _phase_results = _dispatch._run_parallel_phases(
            (("first", phase_one), ("second", phase_two)),
            dispatcher=_dispatch._QuietDispatcher(),
        )
        assert exit_code == 0
        assert failing_label is None
        assert sorted(log) == ["one", "two"]

    def test_quiet_dispatcher_replays_in_submission_order(self, capsys):
        """The quiet dispatcher prints headers + captured output in order."""

        def phase_one(sink) -> int:
            sink.line("from phase one")
            return 0

        def phase_two(sink) -> int:
            sink.line("from phase two")
            return 0

        _dispatch._run_parallel_phases(
            (("first", phase_one), ("second", phase_two)),
            dispatcher=_dispatch._QuietDispatcher(),
        )
        out = capsys.readouterr().out
        # Output order matches submission order regardless of scheduling.
        first_index = out.index("from phase one")
        second_index = out.index("from phase two")
        assert first_index < second_index
        assert "== first ==" in out
        assert "== second ==" in out

    def test_first_failure_short_circuits_return_value(self):
        """A failing phase's exit code becomes the run's return value."""
        exit_code, failing_label, _phase_results = _dispatch._run_parallel_phases(
            (
                ("succeeded", lambda sink: 0),
                ("failed", lambda sink: 7),
            ),
            dispatcher=_dispatch._QuietDispatcher(),
        )
        assert exit_code == 7
        assert failing_label == "failed"

    def test_first_failure_in_submission_order(self):
        """When two phases fail, the first one in submission order wins."""
        exit_code, failing_label, _phase_results = _dispatch._run_parallel_phases(
            (
                ("a", lambda sink: 11),
                ("b", lambda sink: 13),
            ),
            dispatcher=_dispatch._QuietDispatcher(),
        )
        assert exit_code == 11
        assert failing_label == "a"

    def test_phase_crash_treated_as_failure(self):
        """An exception in a phase is captured and treated as exit code 1."""
        def phase_crashes(sink) -> int:
            raise RuntimeError("oh no")

        exit_code, failing_label, _phase_results = _dispatch._run_parallel_phases(
            (("crashy", phase_crashes),),
            dispatcher=_dispatch._QuietDispatcher(),
        )
        assert exit_code == 1
        assert failing_label == "crashy"

    def test_quiet_dispatcher_collapses_passing_phases_on_failure(self, capsys):
        """When any phase fails, passing phases collapse to header-only.

        Otherwise the user has to scroll past N successful phase transcripts
        to find the actual error.  Each passing phase becomes a single
        ``== <label> (passed) ==`` line; only failing phases get the full
        transcript dump.
        """
        def passing(sink) -> int:
            sink.line("noise from a passing phase that nobody wants to read")
            return 0

        def failing(sink) -> int:
            sink.line("actual error: the thing the user needs to see")
            return 1

        _dispatch._run_parallel_phases(
            (
                ("phase_a", passing),
                ("phase_b", failing),
                ("phase_c", passing),
            ),
            dispatcher=_dispatch._QuietDispatcher(),
        )
        out = capsys.readouterr().out
        # Failing phase shows full output + (failed) marker.
        assert "== phase_b (failed) ==" in out
        assert "actual error: the thing the user needs to see" in out
        # Passing phases show only the header — their captured output is
        # suppressed so the failing-phase transcript stays visible.
        assert "== phase_a (passed) ==" in out
        assert "== phase_c (passed) ==" in out
        assert "noise from a passing phase" not in out

    def test_quiet_dispatcher_keeps_full_output_when_all_pass(self, capsys):
        """No suppression when every phase passes — the transcripts remain."""
        def chatty(sink) -> int:
            sink.line("useful log line")
            return 0

        _dispatch._run_parallel_phases(
            (
                ("phase_a", chatty),
                ("phase_b", chatty),
            ),
            dispatcher=_dispatch._QuietDispatcher(),
        )
        out = capsys.readouterr().out
        assert "== phase_a ==" in out
        assert "== phase_b ==" in out
        assert out.count("useful log line") == 2


class TestPickDispatcher:
    """Tests for the TTY + env-var-based dispatcher selection."""

    def _clear_dispatcher_environment(self, monkeypatch):
        monkeypatch.delenv(_dispatch._RAW_OUTPUT_ENV_VAR, raising=False)
        monkeypatch.delenv(_dispatch._OUTPUT_MODE_ENV_VAR, raising=False)
        monkeypatch.delenv("PYCHARM_HOSTED", raising=False)

    def test_quiet_flag_picks_quiet_dispatcher(self, monkeypatch):
        self._clear_dispatcher_environment(monkeypatch)
        dispatcher = _dispatch._pick_dispatcher(quiet=True)
        assert isinstance(dispatcher, _dispatch._QuietDispatcher)

    def test_raw_env_var_overrides_quiet_flag(self, monkeypatch):
        self._clear_dispatcher_environment(monkeypatch)
        monkeypatch.setenv(_dispatch._RAW_OUTPUT_ENV_VAR, "1")
        dispatcher = _dispatch._pick_dispatcher(quiet=True)
        assert isinstance(dispatcher, _dispatch._RawDispatcher)

    def test_non_tty_picks_interleave_dispatcher(self, monkeypatch):
        self._clear_dispatcher_environment(monkeypatch)
        monkeypatch.setattr(_dispatch.sys.stdout, "isatty", lambda: False)
        dispatcher = _dispatch._pick_dispatcher(quiet=False)
        assert isinstance(dispatcher, _dispatch._InterleaveDispatcher)

    def test_tty_picks_status_dispatcher(self, monkeypatch):
        self._clear_dispatcher_environment(monkeypatch)
        monkeypatch.setattr(_dispatch.sys.stdout, "isatty", lambda: True)
        dispatcher = _dispatch._pick_dispatcher(quiet=False)
        assert isinstance(dispatcher, _dispatch._StatusDispatcher)

    def test_pycharm_env_var_picks_status_even_without_tty(self, monkeypatch):
        """PyCharm Run-config console isn't a TTY but should get status mode."""
        self._clear_dispatcher_environment(monkeypatch)
        monkeypatch.setattr(_dispatch.sys.stdout, "isatty", lambda: False)
        monkeypatch.setenv("PYCHARM_HOSTED", "1")
        dispatcher = _dispatch._pick_dispatcher(quiet=False)
        assert isinstance(dispatcher, _dispatch._StatusDispatcher)

    def test_output_mode_env_var_overrides_tty(self, monkeypatch):
        """CHUMICRO_OUTPUT_MODE=interleave forces interleave even in a TTY."""
        self._clear_dispatcher_environment(monkeypatch)
        monkeypatch.setattr(_dispatch.sys.stdout, "isatty", lambda: True)
        monkeypatch.setenv(_dispatch._OUTPUT_MODE_ENV_VAR, "interleave")
        dispatcher = _dispatch._pick_dispatcher(quiet=False)
        assert isinstance(dispatcher, _dispatch._InterleaveDispatcher)

    def test_output_mode_env_var_picks_status_in_pipe(self, monkeypatch):
        """CHUMICRO_OUTPUT_MODE=status forces status even when piped."""
        self._clear_dispatcher_environment(monkeypatch)
        monkeypatch.setattr(_dispatch.sys.stdout, "isatty", lambda: False)
        monkeypatch.setenv(_dispatch._OUTPUT_MODE_ENV_VAR, "status")
        dispatcher = _dispatch._pick_dispatcher(quiet=False)
        assert isinstance(dispatcher, _dispatch._StatusDispatcher)

    def test_output_mode_env_var_unknown_value_falls_through(self, monkeypatch):
        """An unrecognized CHUMICRO_OUTPUT_MODE silently falls through to TTY logic."""
        self._clear_dispatcher_environment(monkeypatch)
        monkeypatch.setattr(_dispatch.sys.stdout, "isatty", lambda: True)
        monkeypatch.setenv(_dispatch._OUTPUT_MODE_ENV_VAR, "nonsense")
        dispatcher = _dispatch._pick_dispatcher(quiet=False)
        assert isinstance(dispatcher, _dispatch._StatusDispatcher)

    def test_quiet_flag_beats_output_mode_env_var(self, monkeypatch):
        """--quiet wins over CHUMICRO_OUTPUT_MODE=status (explicit user intent)."""
        self._clear_dispatcher_environment(monkeypatch)
        monkeypatch.setenv(_dispatch._OUTPUT_MODE_ENV_VAR, "status")
        dispatcher = _dispatch._pick_dispatcher(quiet=True)
        assert isinstance(dispatcher, _dispatch._QuietDispatcher)


# ---------------------------------------------------------------------------
# Tests for the Decision 0048 / 0054 preflight phase-level parallel block
# ---------------------------------------------------------------------------


class TestSubcommandPhaseFactory:
    """Tests for the subprocess-runner closure built per preflight phase."""

    def test_streams_subprocess_output_through_sink(self, monkeypatch):
        """Each line of child output is delivered to the sink as it arrives."""
        captured: dict[str, object] = {}

        def fake_stream(command, *, cwd, environment, on_line):
            captured["command"] = list(command)
            captured["cwd"] = cwd
            captured["environment"] = environment
            on_line("hello stdout")
            on_line("hello stderr")
            return 0, "hello stdout\nhello stderr\n"

        monkeypatch.setattr(_dispatch, "stream_subprocess", fake_stream)

        factory = _dispatch._subcommand_phase_factory("lint", ["lint"])
        sink = _dispatch._Sink(_dispatch._QuietDispatcher(), "lint")
        exit_code = factory(sink)

        assert exit_code == 0
        assert captured["command"][1:] == ["scripts/run.py", "lint"]
        assert captured["cwd"] == _dispatch.ROOT
        # Child runs with CHUMICRO_RAW_OUTPUT=1 so its dispatcher is raw.
        assert captured["environment"][_dispatch._RAW_OUTPUT_ENV_VAR] == "1"
        # Banner + every line flow through the sink.
        lines = sink.captured.splitlines()
        assert lines[0].startswith("+ ")
        assert "scripts/run.py lint" in lines[0]
        assert "hello stdout" in lines
        assert "hello stderr" in lines

    def test_appends_failure_banner_on_nonzero_exit(self, monkeypatch):
        """A non-zero exit code produces a ``Phase failed: <label>`` line."""
        monkeypatch.setattr(
            _dispatch, "stream_subprocess",
            lambda *_a, **_kw: (7, ""),
        )
        factory = _dispatch._subcommand_phase_factory(
            "test (python 3.13)", ["test", "--all"],
        )
        sink = _dispatch._Sink(_dispatch._QuietDispatcher(), "test (python 3.13)")
        exit_code = factory(sink)

        assert exit_code == 7
        assert "Phase failed: test (python 3.13)" in sink.captured

    def test_forwards_extra_subcommand_args(self, monkeypatch):
        """Extra args land after ``scripts/run.py <subcommand>`` verbatim."""
        seen_command: list[str] = []

        def fake_stream(command, **_kwargs):
            seen_command.extend(command)
            return 0, ""

        monkeypatch.setattr(_dispatch, "stream_subprocess", fake_stream)
        factory = _dispatch._subcommand_phase_factory(
            "test", ["test", "--all", "--coverage-threshold", "94"],
        )
        sink = _dispatch._Sink(_dispatch._QuietDispatcher(), "test")
        factory(sink)

        # The first element is the running interpreter; the rest is
        # exactly what we asked for.
        assert seen_command[1:] == [
            "scripts/run.py", "test", "--all", "--coverage-threshold", "94",
        ]


class TestPreflightParallelDispatch:
    """Tests for preflight()'s phase-list construction and dispatch."""

    def test_skips_diff_phases_when_origin_main_unreachable(
        self, monkeypatch, capsys,
    ):
        """check-version + check-api skip when origin/main is unreachable."""
        monkeypatch.setattr(preflight_tasks, "is_ref_reachable", lambda *_a, **_kw: False)

        captured_phases: list[list[str]] = []

        def fake_run(phases, **_kwargs):
            captured_phases.extend([label for label, _ in phases])
            return 0, None, []

        monkeypatch.setattr(preflight_tasks, "_preflight_run_parallel_phases", fake_run)

        result = run.preflight()
        assert result == 0
        out = capsys.readouterr().out
        # Both diff phases got their skip notice printed up-front.
        assert "== check-version ==" in out
        assert "== check-api ==" in out
        assert "SKIP" in out
        # And neither got handed to the parallel block.
        assert "check-version" not in captured_phases
        assert "check-api" not in captured_phases
        # The other 10 phases are all present.
        for expected in (
            "lint", "build", "docs", "test-scripts", "verify-examples",
            "verify-demos", "check-dep-graph", "check-size",
            "test-micropython", "test-circuitpython",
        ):
            assert expected in captured_phases

    def test_includes_diff_phases_when_origin_main_reachable(self, monkeypatch):
        """All 13 phases dispatch when origin/main is reachable."""
        monkeypatch.setattr(preflight_tasks, "is_ref_reachable", lambda *_a, **_kw: True)

        captured_labels: list[str] = []

        def fake_run(phases, **_kwargs):
            captured_labels.extend([label for label, _ in phases])
            return 0, None, []

        monkeypatch.setattr(preflight_tasks, "_preflight_run_parallel_phases", fake_run)

        result = run.preflight()
        assert result == 0
        # Submission order matches the documented log-replay order.
        python_version = (
            f"test (python "
            f"{run.sys.version_info.major}.{run.sys.version_info.minor})"
        )
        assert captured_labels == [
            "lint", "build", "docs", python_version, "test-scripts",
            "verify-examples", "verify-demos", "check-dep-graph", "check-size",
            "check-version", "check-api", "test-micropython", "test-circuitpython",
        ]

    def test_coverage_threshold_flows_to_test_phase_args(self, monkeypatch):
        """--coverage-threshold becomes a flag on the test subcommand args."""
        monkeypatch.setattr(preflight_tasks, "is_ref_reachable", lambda *_a, **_kw: True)

        seen: list[list[str]] = []

        def capturing_factory(label, args):
            seen.append([label, *args])
            return lambda sink: 0

        monkeypatch.setattr(
            preflight_tasks, "_subcommand_phase_factory", capturing_factory,
        )
        monkeypatch.setattr(
            preflight_tasks, "_preflight_run_parallel_phases",
            lambda phases, **_kwargs: (0, None, []),
        )

        run.preflight(coverage_threshold=94)

        # The "test (python ...)" phase carries --coverage-threshold 94.
        test_invocation = next(
            entry for entry in seen if entry[1] == "test"
        )
        assert "--coverage-threshold" in test_invocation
        assert "94" in test_invocation

    def test_binary_overrides_flow_to_runtime_phases(self, monkeypatch):
        """--micropython-binary / --circuitpython-binary flow to the right phases."""
        monkeypatch.setattr(preflight_tasks, "is_ref_reachable", lambda *_a, **_kw: True)

        seen: list[list[str]] = []

        def capturing_factory(label, args):
            seen.append([label, *args])
            return lambda sink: 0

        monkeypatch.setattr(
            preflight_tasks, "_subcommand_phase_factory", capturing_factory,
        )
        monkeypatch.setattr(
            preflight_tasks, "_preflight_run_parallel_phases",
            lambda phases, **_kwargs: (0, None, []),
        )

        run.preflight(
            micropython_binary="/tmp/mpy",
            circuitpython_binary="/tmp/cpy",
        )

        mpy_invocation = next(
            entry for entry in seen if entry[1] == "test-micropython"
        )
        cpy_invocation = next(
            entry for entry in seen if entry[1] == "test-circuitpython"
        )
        assert "--micropython-binary" in mpy_invocation
        assert "/tmp/mpy" in mpy_invocation
        assert "--circuitpython-binary" in cpy_invocation
        assert "/tmp/cpy" in cpy_invocation

    def test_parallel_block_failure_returns_exit_code(self, monkeypatch, capsys):
        """A failing parallel block short-circuits before the functional tail
        and surfaces the failing phase label in the tail message — survives
        interleaved-output schedulers where the [FAIL] line scrolls past."""
        monkeypatch.setattr(preflight_tasks, "is_ref_reachable", lambda *_a, **_kw: True)
        monkeypatch.setattr(
            preflight_tasks, "_preflight_run_parallel_phases",
            lambda phases, **_kwargs: (13, "test-micropython", []),
        )

        functional_calls: list[str] = []

        def fail_libraries():
            functional_calls.append("libraries")
            return 0

        monkeypatch.setattr(preflight_tasks, "test_libraries_functional", fail_libraries)

        result = run.preflight(with_functional=True)
        assert result == 13
        # The functional tail must NOT run when the parallel block failed.
        assert functional_calls == []
        out = capsys.readouterr().out
        assert "Preflight failed at: test-micropython" in out


class TestPreflightPhaseTable:
    """The per-phase status table rendered after the parallel block."""

    def test_table_rows_carry_status_and_wall_time_in_submission_order(self):
        """Each non-skipped spec gets a PASS/FAIL row with its wall seconds."""
        specs = [
            ("lint", ["lint"]),
            ("build", ["build"]),
            ("test-micropython", ["test-micropython"]),
        ]
        results = [
            _dispatch._PhaseResult("lint", 0, 1.2, "ok\n"),
            _dispatch._PhaseResult("build", 0, 3.4, "ok\n"),
            _dispatch._PhaseResult("test-micropython", 1, 5.6, "boom\n"),
        ]
        lines = preflight_tasks._format_preflight_phase_table(specs, results)
        text = "\n".join(lines)
        assert "lint" in text and "PASS" in text and "1.2s" in text
        assert "FAIL" in text and "5.6s" in text
        # Submission order: lint before build before test-micropython.
        assert text.index("lint") < text.index("build")
        assert text.index("build") < text.index("test-micropython")

    def test_skipped_spec_renders_skip_row(self):
        """A spec with None args (origin/main unreachable) shows SKIP."""
        specs = [("check-version", None), ("lint", ["lint"])]
        results = [_dispatch._PhaseResult("lint", 0, 0.1, "")]
        lines = preflight_tasks._format_preflight_phase_table(specs, results)
        text = "\n".join(lines)
        assert "check-version" in text
        assert "SKIP" in text


class TestPreflightFailureRecap:
    """The end-of-run recap that re-prints the failing phase's tail."""

    def test_recap_reprints_last_lines_of_failing_phase(self):
        """The recap pulls the failing phase's trailing lines to EOF."""
        captured = "\n".join(f"line {index}" for index in range(100)) + "\n"
        results = [
            _dispatch._PhaseResult("test", 1, 2.0, captured),
            _dispatch._PhaseResult("lint", 0, 0.5, "lint ok\n"),
        ]
        lines = preflight_tasks._format_preflight_failure_recap("test", results)
        text = "\n".join(lines)
        assert "test (failed)" in text
        # Last line present, an early line beyond the recap window absent.
        assert "line 99" in text
        assert "line 10" not in text
        # Only the failing phase's transcript, not the passing one.
        assert "lint ok" not in text

    def test_recap_empty_when_no_failing_label(self):
        """No failing label means no recap lines."""
        assert preflight_tasks._format_preflight_failure_recap(None, []) == []

    def test_preflight_prints_table_and_recap_on_failure(self, monkeypatch, capsys):
        """A failing preflight prints the phase table then the failing recap."""
        monkeypatch.setattr(preflight_tasks, "is_ref_reachable", lambda *_a, **_kw: True)
        failing = _dispatch._PhaseResult(
            "test (python 3.14)", 1, 2.0,
            "ERROR: support/test_harness coverage 87% < fail-under=94%\n",
        )

        def fake_run(phases, **_kwargs):
            return 1, "test (python 3.14)", [failing]

        monkeypatch.setattr(preflight_tasks, "_preflight_run_parallel_phases", fake_run)

        result = run.preflight(coverage_threshold=94)
        assert result == 1
        out = capsys.readouterr().out
        assert "Phase summary:" in out
        assert "(failed)" in out
        # The attributed coverage line surfaces in the recap tail.
        assert "support/test_harness coverage 87%" in out
        assert "Preflight failed at: test (python 3.14)" in out


class TestCoverageFailureAttribution:
    """A coverage-gate failure carries the package label out of the fan-out."""

    def test_filter_captures_coverage_failure_percentages(self):
        """pytest-cov's unlabeled gate line is parsed and suppressed."""
        filter_state = testing_cpython._PytestOutputFilter()
        absorbed = filter_state.consume(
            "ERROR: Coverage failure: total of 87 is less than fail-under=94",
        )
        assert absorbed is True
        assert filter_state.coverage_failure == (87, 94)

    def test_phase_summary_names_failing_run(self):
        """A non-zero run gets its own FAILED attribution line."""
        results = [
            testing_cpython._PytestRunResult("libraries/timing/tests", 0, passed=10),
            testing_cpython._PytestRunResult("support/test_harness/tests", 1, passed=5),
        ]
        lines = testing_cpython._format_pytest_phase_summary(
            "test", results, slow_threshold_s=1.0,
        )
        text = "\n".join(lines)
        assert "FAILED support/test_harness/tests (exit=1)" in text

    def test_phase_summary_reports_deselected_count(self):
        """A deselected count surfaces in the rolled-up summary."""
        results = [testing_cpython._PytestRunResult("lib/tests", 0, passed=3, deselected=7)]
        lines = testing_cpython._format_pytest_phase_summary(
            "test", results, slow_threshold_s=1.0,
        )
        assert "7 deselected" in lines[0]


class TestCoverageGateArgs:
    """The per-package --cov-fail-under gate selection."""

    def test_package_uses_threshold(self):
        """A package gets the elevated threshold as an explicit flag."""
        args = testing_cpython._coverage_gate_args(
            "timing",
            skip_coverage_gate=False,
            coverage_threshold=94,
            elevated_packages=None,
        )
        assert args == ["--cov-fail-under=94"]

    def test_skip_gate_forces_zero(self):
        """skip_coverage_gate overrides every threshold with --cov-fail-under=0."""
        args = testing_cpython._coverage_gate_args(
            "timing",
            skip_coverage_gate=True,
            coverage_threshold=94,
            elevated_packages=None,
        )
        assert args == ["--cov-fail-under=0"]

    def test_none_threshold_adds_no_flag(self):
        """With no threshold the package falls back to the pyproject default (no flag)."""
        args = testing_cpython._coverage_gate_args(
            "timing",
            skip_coverage_gate=False,
            coverage_threshold=None,
            elevated_packages=None,
        )
        assert args == []

    def test_unelevated_package_falls_back_to_default(self):
        """A package outside elevated_packages gets no explicit flag."""
        args = testing_cpython._coverage_gate_args(
            "timing",
            skip_coverage_gate=False,
            coverage_threshold=94,
            elevated_packages={"sockets"},
        )
        assert args == []

    def test_elevated_package_gets_threshold(self):
        """A package inside elevated_packages gets the threshold flag."""
        args = testing_cpython._coverage_gate_args(
            "sockets",
            skip_coverage_gate=False,
            coverage_threshold=94,
            elevated_packages={"sockets"},
        )
        assert args == ["--cov-fail-under=94"]


class TestInertCoverageGuard:
    """A testable package whose coverage source resolves empty fails loudly."""

    def test_no_coverage_source_fails_the_phase(
        self, monkeypatch, fake_root, capsys,
    ):
        """A package with tests but no resolvable __init__.py is a loud error."""
        package_dir = fake_root / "ghost"
        (package_dir / "tests").mkdir(parents=True)
        # src/ tree without an __init__.py: find_package_dir returns None.
        (package_dir / "src" / "chumicro_ghost").mkdir(parents=True)

        monkeypatch.setattr(
            testing_cpython, "_run_pytest_capturing",
            lambda *_a, **_kw: pytest.fail("pytest must not run"),
        )

        result = testing_cpython.test_cpython([package_dir], coverage_threshold=94)
        assert result == 1
        out = capsys.readouterr().out
        assert "no resolvable coverage source" in out

    def test_no_cov_bypasses_the_guard(self, monkeypatch, fake_root):
        """With no_cov the empty-source package still runs (gate intentionally off)."""
        package_dir = fake_root / "ghost"
        (package_dir / "tests").mkdir(parents=True)
        (package_dir / "src" / "chumicro_ghost").mkdir(parents=True)

        recorded: list[list[str]] = []
        monkeypatch.setattr(
            testing_cpython, "_run_pytest_capturing",
            lambda command, environment, sink: (recorded.append(command), 0)[1],
        )
        monkeypatch.setattr(testing_cpython, "run_command", lambda *_a, **_kw: 0)

        result = testing_cpython.test_cpython([package_dir], no_cov=True)
        assert result == 0
        assert recorded  # pytest ran


class TestDuplicatePhaseLabels:
    """Phase labels must stay unique across the fan-out."""

    def test_run_parallel_rejects_duplicate_labels(self):
        """Identical labels raise rather than silently clobber dispatcher state."""
        with pytest.raises(ValueError, match="Duplicate phase label"):
            _dispatch._run_parallel_phases(
                (("dup", lambda sink: 0), ("dup", lambda sink: 0)),
                dispatcher=_dispatch._QuietDispatcher(),
            )

    def test_same_file_scoped_filters_get_distinct_labels(
        self, monkeypatch, fake_root,
    ):
        """Two -k entries on the same test file produce distinct phase labels."""
        package_dir = _make_test_package(fake_root, "timing")
        (package_dir / "tests" / "test_ticks.py").write_text(
            "def test_a():\n    assert True\n"
            "def test_b():\n    assert True\n",
        )
        monkeypatch.setattr(testing_cpython, "discover_package_dirs", lambda: [package_dir])
        monkeypatch.setattr(
            testing_cpython, "_run_pytest_capturing",
            lambda command, environment, sink: 0,
        )

        captured_labels: list[str] = []

        def capture_phases(phases, **_kwargs):
            captured_labels.extend(label for label, _ in phases)
            return 0, None, []

        monkeypatch.setattr(testing_cpython, "_run_parallel_phases", capture_phases)
        # Two file-scoped entries naming the same file.
        testing_cpython.test_cpython(
            [package_dir],
            filter_expression="timing/test_ticks/test_a,timing/test_ticks/test_b",
        )
        assert len(captured_labels) == 2
        assert len(set(captured_labels)) == 2  # distinct, no collision


class TestInterruptCleanup:
    """KeyboardInterrupt mid-block cancels queued phases and reaps children."""

    def test_keyboard_interrupt_terminates_registered_processes(
        self, monkeypatch,
    ):
        """A KeyboardInterrupt propagates after terminate_all reaps the group."""
        terminated: list[str] = []

        class _FakeRegistry:
            def add(self, _process):
                pass

            def terminate_all(self):
                terminated.append("terminated")

        monkeypatch.setattr(_dispatch, "_ProcessRegistry", _FakeRegistry)

        def interrupting_phase(sink):
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            _dispatch._run_parallel_phases(
                (("phase", interrupting_phase),),
                dispatcher=_dispatch._QuietDispatcher(),
            )
        assert terminated == ["terminated"]

    def test_registry_signals_group_then_kills_on_timeout(self, monkeypatch):
        """terminate_all sends SIGTERM, then SIGKILL to a group that won't die."""
        import subprocess as subprocess_module

        signals: list[int] = []

        class _StubProcess:
            pid = 4242

            def poll(self):
                return None

            def wait(self, timeout=None):
                raise subprocess_module.TimeoutExpired(cmd="x", timeout=timeout)

        monkeypatch.setattr(_dispatch.os, "getpgid", lambda _pid: 4242)
        monkeypatch.setattr(
            _dispatch.os, "killpg", lambda _pgid, sig: signals.append(sig),
        )

        registry = _dispatch._ProcessRegistry()
        registry.add(_StubProcess())
        registry.terminate_all()
        assert _dispatch.signal.SIGTERM in signals
        assert _dispatch.signal.SIGKILL in signals


class TestRawDispatcherLocking:
    """The raw child dispatcher serializes its line emission."""

    def test_raw_dispatcher_holds_a_lock(self):
        """_RawDispatcher carries a lock so concurrent phase_line can't tear."""
        dispatcher = _dispatch._RawDispatcher()
        # The lock attribute exists and is a usable context manager.
        with dispatcher._lock:
            pass


class TestUnitOnDeviceSweep:
    """The on-device unit sweep resolves per-library mode (own-src
    scoping) and runs one single-mode session per (runtime, mode).
    """

    @staticmethod
    def _make_library(root: Path, name: str, *, ships_data_file: bool):
        library_dir = root / name
        source_dir = library_dir / "src" / f"chumicro_{name}"
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").write_text("X = 1\n")
        if ships_data_file:
            (source_dir / "_ca_bundle.der").write_bytes(b"\x30\x82")
        tests_dir = library_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_it.py").write_text("def test_it():\n    assert True\n")
        return library_dir

    def test_groups_libraries_into_one_session_per_mode(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        from types import SimpleNamespace

        import chumicro_deploy
        from chumicro_workspace import device_orchestration as _test_runner

        ntp = self._make_library(tmp_path, "ntp", ships_data_file=False)
        sockets = self._make_library(tmp_path, "sockets", ships_data_file=True)

        monkeypatch.setattr(
            functional, "discover_library_dirs", lambda: [ntp, sockets],
        )
        monkeypatch.setattr(
            chumicro_deploy, "load_device_registry",
            lambda **_kwargs: (
                [SimpleNamespace(
                    identifier="cp-1", supports_ram_mode=True,
                )],
                SimpleNamespace(circuitpython="cp-1", micropython=None),
            ),
        )
        # Own-src scoping: closure is each library's own src only, so
        # find_libraries_requiring_flash sees no flagged pyproject.
        monkeypatch.setattr(
            _test_runner, "resolve_library_source_dirs",
            lambda library_dir, **_kwargs: [library_dir / "src"],
        )
        commands: list[list[str]] = []

        def _fake_run_command(command, environment=None):  # noqa: ARG001
            commands.append(command)
            return 0

        monkeypatch.setattr(functional, "run_command", _fake_run_command)

        result = functional.test_unit_on_device(runtime="circuitpython")

        assert result == 0
        # ntp (clean own-src) → ram session; sockets (own-src ships
        # _ca_bundle.der) → flash session.  Flash runs first.
        assert len(commands) == 2
        flash_command, ram_command = commands
        assert "--deploy-mode" in flash_command
        assert flash_command[flash_command.index("--deploy-mode") + 1] == "flash"
        assert any("sockets/tests" in part for part in flash_command)
        assert ram_command[ram_command.index("--deploy-mode") + 1] == "ram"
        assert any("ntp/tests" in part for part in ram_command)
        for command in commands:
            assert command[command.index("--target") + 1] == "device-unit"
            assert command[command.index("--runtime") + 1] == "circuitpython"
            assert (
                command[command.index("--circuitpython-device") + 1] == "cp-1"
            )

    def test_skips_runtime_with_no_configured_device(
        self, tmp_path: Path, monkeypatch, capsys,
    ) -> None:
        from types import SimpleNamespace

        import chumicro_deploy

        ntp = self._make_library(tmp_path, "ntp", ships_data_file=False)
        monkeypatch.setattr(functional, "discover_library_dirs", lambda: [ntp])
        monkeypatch.setattr(
            chumicro_deploy, "load_device_registry",
            lambda **_kwargs: (
                [], SimpleNamespace(circuitpython=None, micropython=None),
            ),
        )
        monkeypatch.setattr(
            functional, "run_command",
            lambda *_a, **_k: pytest.fail("must not run pytest"),
        )

        result = functional.test_unit_on_device(runtime="circuitpython")

        assert result == 0
        assert "No circuitpython device configured" in capsys.readouterr().out


class TestSweepDevices:
    """The bench-board sweep iterates devices.yml serially: demo smoke
    layer per board, optional functional layer routed through the
    runtime-specific device override.
    """

    @staticmethod
    def _entry(identifier: str, runtime: str):
        from chumicro_deploy.config.default import DeviceEntry

        return DeviceEntry(
            identifier=identifier, runtime=runtime, address="/dev/fake",
        )

    def _patch_registry(self, monkeypatch, entries) -> None:
        import chumicro_deploy.config.default as device_config

        monkeypatch.setattr(
            device_config, "load_device_registry",
            lambda **_kwargs: (entries, None),
        )

    def test_dispatch_forwards_flags(self, monkeypatch) -> None:
        """sweep-devices should forward every CLI flag to sweep_devices()."""
        calls, fake_sweep = _make_fake_command(return_value=71)
        monkeypatch.setattr(run, "sweep_devices", fake_sweep)

        result = run.main([
            "run.py", "sweep-devices",
            "--device", "board-a", "--device", "board-b",
            "--demo", "mqtt_pub_sub",
            "--skip-demo", "--functional", "--skip-workbench",
            "--library", "sockets", "--deploy-mode", "ram",
        ])

        assert result == 71
        assert calls == [
            ((), {
                "device_ids": ["board-a", "board-b"],
                "demo": "mqtt_pub_sub",
                "skip_demo": True,
                "functional": True,
                "skip_workbench": True,
                "library": "sockets",
                "deploy_mode": "ram",
            }),
        ]

    def test_runs_demo_per_registered_device_in_order(
        self, monkeypatch, capsys,
    ) -> None:
        """Default sweep runs the demo driver once per device, registry order."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
            self._entry("cp-board", "circuitpython"),
        ])
        commands: list[list[str]] = []
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kwargs: (commands.append(command) or (0, "")),
        )
        monkeypatch.setattr(functional, "test_workbench_functional", lambda *args, **kwargs: 0)

        result = run.sweep_devices()

        assert result == 0
        assert [command[-1] for command in commands] == ["mp-board", "cp-board"]
        assert all(command[-2] == "--device" for command in commands)
        assert all("sockets_runner_connector" in command[1] for command in commands)
        output = capsys.readouterr().out
        assert "== sweep summary ==" in output
        # Two board demo rows plus the closing workbench-functional row.
        assert output.count("PASS") == 3

    def test_failing_demo_yields_exit_1_and_fail_row(
        self, monkeypatch, capsys,
    ) -> None:
        """One failing board fails the sweep but the rest still run."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
            self._entry("cp-board", "circuitpython"),
        ])
        # (1, "") — a non-cold-start failure (empty transcript carries no
        # WIFI_OK-timeout signature), so it fails without a retry.
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kwargs: (1, "") if "mp-board" in command else (0, ""),
        )
        monkeypatch.setattr(functional, "test_workbench_functional", lambda *args, **kwargs: 0)

        result = run.sweep_devices()

        assert result == 1
        output = capsys.readouterr().out
        assert "FAIL" in output
        # cp-board demo PASS plus the closing workbench-functional PASS.
        assert output.count("PASS") == 2

    def test_cold_start_marker_timeout_retries_once_and_passes(
        self, monkeypatch, capsys,
    ) -> None:
        """A WIFI_OK first-association timeout is retried once; a warm pass counts."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
            self._entry("cp-board", "circuitpython"),
        ])
        # cp-board times out on its first association (cold start), then
        # passes warm on the retry; mp-board passes first try.
        responses = {
            "mp-board": [(0, "")],
            "cp-board": [
                (3, "driver: Timed out after 45.000s waiting for marker 'WIFI_OK'\n"),
                (0, ""),
            ],
        }
        calls: list[list[str]] = []

        def fake_stream(command, **_kwargs):
            calls.append(command)
            sequence = responses[command[-1]]
            return sequence.pop(0) if len(sequence) > 1 else sequence[0]

        monkeypatch.setattr(functional, "stream_subprocess", fake_stream)
        monkeypatch.setattr(functional, "test_workbench_functional", lambda *args, **kwargs: 0)

        result = run.sweep_devices()

        assert result == 0
        # cp-board ran twice (cold start + one retry); mp-board once.
        assert [command[-1] for command in calls] == [
            "mp-board", "cp-board", "cp-board",
        ]
        output = capsys.readouterr().out
        assert "first-association grace" in output
        assert "PASS*" in output
        assert "cp-board: demo passed on retry (cold-start grace)" in output

    def test_cold_start_retry_still_failing_is_a_fail(
        self, monkeypatch, capsys,
    ) -> None:
        """When the warm retry also times out, the cell is a genuine FAIL."""
        self._patch_registry(monkeypatch, [
            self._entry("cp-board", "circuitpython"),
        ])
        timeout_line = (
            "driver: Timed out after 45.000s waiting for marker 'WIFI_OK'\n"
        )
        calls: list[list[str]] = []
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kwargs: (calls.append(command) or (3, timeout_line)),
        )
        monkeypatch.setattr(functional, "test_workbench_functional", lambda *args, **kwargs: 0)

        result = run.sweep_devices()

        assert result == 1
        # Exactly one retry granted (two attempts total), then it stays FAIL.
        assert len(calls) == 2
        output = capsys.readouterr().out
        assert "FAIL" in output
        assert "still FAIL" in output

    def test_non_first_association_timeout_is_not_retried(
        self, monkeypatch, capsys,
    ) -> None:
        """A later-marker timeout (not WIFI_OK) fails without a cold-start retry."""
        self._patch_registry(monkeypatch, [
            self._entry("cp-board", "circuitpython"),
        ])
        calls: list[list[str]] = []
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kwargs: (
                calls.append(command)
                or (3, "driver: Timed out after 30.000s waiting for marker "
                       "'DEMO_COMPLETE'\n")
            ),
        )
        monkeypatch.setattr(functional, "test_workbench_functional", lambda *args, **kwargs: 0)

        result = run.sweep_devices()

        assert result == 1
        # No grace for a non-first-association timeout: a single attempt only.
        assert len(calls) == 1
        output = capsys.readouterr().out
        assert "cold-start grace" not in output
        assert "passed on retry" not in output

    def test_functional_layer_routes_runtime_specific_device_kwarg(
        self, monkeypatch,
    ) -> None:
        """--functional runs the suite per board with the matching override."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
            self._entry("cp-board", "circuitpython"),
        ])
        calls, fake_functional = _make_fake_command(return_value=0)
        monkeypatch.setattr(functional, "test_libraries_functional", fake_functional)
        monkeypatch.setattr(functional, "test_workbench_functional", lambda *args, **kwargs: 0)

        result = run.sweep_devices(
            skip_demo=True, functional=True, library="sockets",
        )

        assert result == 0
        assert calls == [
            ((), {
                "runtime": "micropython",
                "library": "sockets",
                "deploy_mode": None,
                "micropython_device": "mp-board",
            }),
            ((), {
                "runtime": "circuitpython",
                "library": "sockets",
                "deploy_mode": None,
                "circuitpython_device": "cp-board",
            }),
        ]

    def test_workbench_phase_runs_after_all_boards(
        self, monkeypatch, capsys,
    ) -> None:
        """The workbench suites close the sweep after every board cell."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
            self._entry("cp-board", "circuitpython"),
        ])
        events: list[str] = []
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kwargs: (events.append(command[-1]) or (0, "")),
        )
        workbench_calls: list[tuple[tuple, dict]] = []

        def fake_workbench(*args, **kwargs):
            events.append("workbench")
            workbench_calls.append((args, kwargs))
            return 0

        monkeypatch.setattr(functional, "test_workbench_functional", fake_workbench)

        result = run.sweep_devices()

        assert result == 0
        # Strict serial discipline: both boards, then the workbench phase.
        assert events == ["mp-board", "cp-board", "workbench"]
        # Called with no args (its conftests read devices.yml defaults).
        assert workbench_calls == [((), {})]
        output = capsys.readouterr().out
        assert "== sweep workbench-functional (devices.yml defaults) ==" in output
        assert "workbench-functional" in output
        assert "defaults" in output

    def test_failing_workbench_yields_exit_1_and_fail_row(
        self, monkeypatch, capsys,
    ) -> None:
        """A workbench failure fails the sweep; board cells stay PASS."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
            self._entry("cp-board", "circuitpython"),
        ])
        monkeypatch.setattr(
            functional, "stream_subprocess", lambda command, **_kwargs: (0, ""),
        )
        monkeypatch.setattr(functional, "test_workbench_functional", lambda *args, **kwargs: 1)

        result = run.sweep_devices()

        assert result == 1
        output = capsys.readouterr().out
        # Only the workbench row fails; both board demo cells stay PASS.
        assert output.count("FAIL") == 1
        assert output.count("PASS") == 2

    def test_skip_workbench_skips_the_workbench_phase(
        self, monkeypatch, capsys,
    ) -> None:
        """--skip-workbench does not call or report the workbench phase."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
        ])
        monkeypatch.setattr(
            functional, "stream_subprocess", lambda command, **_kwargs: (0, ""),
        )
        calls, fake_workbench = _make_fake_command(return_value=0)
        monkeypatch.setattr(functional, "test_workbench_functional", fake_workbench)

        result = run.sweep_devices(skip_workbench=True)

        assert result == 0
        assert calls == []
        assert "workbench-functional" not in capsys.readouterr().out

    def test_device_filter_selects_and_orders_the_sweep(
        self, monkeypatch,
    ) -> None:
        """--device narrows the sweep and fixes its order."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
            self._entry("cp-board", "circuitpython"),
        ])
        commands: list[list[str]] = []
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kwargs: (commands.append(command) or (0, "")),
        )
        monkeypatch.setattr(functional, "test_workbench_functional", lambda *args, **kwargs: 0)

        result = run.sweep_devices(device_ids=["cp-board"])

        assert result == 0
        assert [command[-1] for command in commands] == ["cp-board"]

    def test_unknown_device_id_is_a_config_error(
        self, monkeypatch, capsys,
    ) -> None:
        """An unregistered --device id fails fast with the registry listed."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
        ])

        result = run.sweep_devices(device_ids=["nope"])

        assert result == 2
        output = capsys.readouterr().out
        assert "unknown device id" in output
        assert "mp-board" in output

    def test_skip_demo_skip_workbench_without_functional_is_a_config_error(
        self, capsys,
    ) -> None:
        """--skip-demo + --skip-workbench + no --functional runs nothing."""
        result = run.sweep_devices(skip_demo=True, skip_workbench=True)

        assert result == 2
        assert "leaves nothing to run" in capsys.readouterr().out

    def test_skip_demo_without_functional_runs_workbench_only(
        self, monkeypatch, capsys,
    ) -> None:
        """--skip-demo alone is legitimate: the workbench phase still runs."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
        ])
        demo_commands: list[list[str]] = []
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kwargs: (demo_commands.append(command) or (0, "")),
        )
        calls, fake_workbench = _make_fake_command(return_value=0)
        monkeypatch.setattr(functional, "test_workbench_functional", fake_workbench)

        result = run.sweep_devices(skip_demo=True)

        assert result == 0
        assert demo_commands == []
        assert calls == [((), {})]
        assert "workbench-functional" in capsys.readouterr().out

    def test_unknown_demo_is_a_config_error(self, monkeypatch, capsys) -> None:
        """A demo without a driver.py fails fast, listing the real demos."""
        self._patch_registry(monkeypatch, [
            self._entry("mp-board", "micropython"),
        ])

        result = run.sweep_devices(demo="not_a_demo")

        assert result == 2
        output = capsys.readouterr().out
        assert "no demo named 'not_a_demo'" in output
        assert "sockets_runner_connector" in output

    def test_registry_load_failure_is_a_config_error(
        self, monkeypatch, capsys,
    ) -> None:
        """A malformed devices.yml surfaces as exit 2, not a traceback."""
        import chumicro_deploy.config.default as device_config

        def raise_config_error(**_kwargs):
            raise device_config.DeviceConfigError("boom")

        monkeypatch.setattr(
            device_config, "load_device_registry", raise_config_error,
        )

        result = run.sweep_devices()

        assert result == 2
        assert "boom" in capsys.readouterr().out


class TestFirstAssociationGrace:
    """First-association (cold-start) retry helpers for the demo sweep.

    A freshly-erased ESP32-family board runs RF calibration on its very
    first wifi association, which can blow the demo's WIFI_OK budget
    once; the retry runs against the now-warm radio.  The signal is
    board-agnostic — a WIFI_OK marker timeout — not any board/vendor id.
    """

    def test_detector_matches_wifi_ok_timeout(self) -> None:
        text = "driver: Timed out after 45.000s waiting for marker 'WIFI_OK'\n"
        assert functional._demo_output_shows_first_association_timeout(text)

    def test_detector_ignores_other_marker_timeouts(self) -> None:
        text = "driver: Timed out after 30.000s waiting for marker 'DEMO_COMPLETE'\n"
        assert not functional._demo_output_shows_first_association_timeout(text)

    def test_detector_ignores_empty_output(self) -> None:
        assert not functional._demo_output_shows_first_association_timeout("")

    def test_cell_passes_first_try_without_retry(self, monkeypatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kw: (calls.append(command) or (0, "")),
        )
        cell, note = functional._run_demo_cell(Path("driver.py"), "cp-board")
        assert (cell, note) == ("PASS", None)
        assert len(calls) == 1

    def test_cell_non_cold_start_failure_is_not_retried(self, monkeypatch) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kw: (calls.append(command) or (2, "boom")),
        )
        cell, note = functional._run_demo_cell(Path("driver.py"), "cp-board")
        assert cell == "FAIL"
        assert note is None
        assert len(calls) == 1

    def test_cell_cold_start_retry_pass_is_noted(self, monkeypatch) -> None:
        sequence = [
            (3, "driver: Timed out after 45.000s waiting for marker 'WIFI_OK'\n"),
            (0, ""),
        ]
        monkeypatch.setattr(
            functional, "stream_subprocess",
            lambda command, **_kw: sequence.pop(0),
        )
        cell, note = functional._run_demo_cell(Path("driver.py"), "cp-board")
        assert cell == "PASS*"
        assert note == "cp-board: demo passed on retry (cold-start grace)"
