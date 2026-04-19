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
        assert micropython_calls == [(("/tmp/mpy",), {})]
        assert circuitpython_calls == [(("/tmp/cpy",), {})]

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
        assert command_calls == [(("/tmp/mpy", "/tmp/cpy"), {})]

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
                "device": None,
                "library": None,
                "test_filter": None,
                "deploy_mode": None,
            }),
        ]

    def test_test_device_forwards_explicit_cli_filters(self, monkeypatch) -> None:
        """test-device should forward explicit runtime, device, and filter flags."""
        command_calls, fake_test_device = _make_fake_command(return_value=61)
        monkeypatch.setattr(run, "test_device", fake_test_device)

        result = run.main([
            "run.py", "test-device",
            "--runtime", "circuitpython",
            "--device", "cp-board",
            "--library", "timing",
            "--test", "heartbeat",
            "--deploy-mode", "flash",
        ])

        assert result == 61
        assert command_calls == [
            ((), {
                "runtime": "circuitpython",
                "device": "cp-board",
                "library": "timing",
                "test_filter": "heartbeat",
                "deploy_mode": "flash",
            }),
        ]
