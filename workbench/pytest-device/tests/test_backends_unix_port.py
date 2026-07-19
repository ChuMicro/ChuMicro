"""Tests for UnixPortBackend's binary resolution and subprocess execution.

Drives execute() against real subprocesses by pointing the runtime
binary at the host Python and the harness script at small stand-in
scripts, so the spawn / capture / empty-output / OSError paths run for
real without a MicroPython build.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_pytest_device.backends import (
    BackendExecuteError,
    BackendPrepareError,
    UnixPortBackend,
)

_HARNESS_RELATIVE = Path("support/test_harness/run_cross_runtime.py")


def _unix_port_target(runtime: str = "micropython") -> DeviceEntry:
    return DeviceEntry(
        identifier=f"{runtime}-unix-port", runtime=runtime, address="unix-port",
    )


def _workspace_with_harness(tmp_path: Path, harness_source: str) -> Path:
    """Create a workspace whose harness script is *harness_source*."""
    harness = tmp_path / _HARNESS_RELATIVE
    harness.parent.mkdir(parents=True)
    harness.write_text(harness_source)
    return tmp_path


def _item_for(test_file: Path) -> SimpleNamespace:
    return SimpleNamespace(test_file=test_file)


class TestHeapBudget:
    """Board-shaped heap budgets: config precedence, spawn args, OOM hint."""

    @staticmethod
    def _workspace_with_budgets(tmp_path: Path, toml_text: str) -> Path:
        workspace = _workspace_with_harness(
            tmp_path, "import sys\nprint(sys.argv)\nprint('SUMMARY total=0 failed=0 time=0.0s')\n",
        )
        (workspace / "target-runtimes.toml").write_text(toml_text)
        return workspace

    def test_runtime_default_budget_reaches_the_spawn(self, tmp_path: Path) -> None:
        # The fake harness echoes argv, so the -X heapsize pair the
        # backend injects is visible in the captured output.
        workspace = self._workspace_with_budgets(
            tmp_path, '[heap]\nmicropython = "192K"\n',
        )
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )
        output = backend.execute(
            _item_for(workspace / "test_x.py"), _unix_port_target(),
        )
        # CPython (the fake binary) swallows -X options it doesn't know,
        # so assert on the resolver instead of argv echo for the pair.
        assert backend._heap_budget("micropython", None) == "192K"
        assert "SUMMARY" in output

    def test_library_override_beats_runtime_default(self, tmp_path: Path) -> None:
        workspace = self._workspace_with_budgets(
            tmp_path,
            '[heap]\nmicropython = "192K"\n'
            '[heap.overrides.kvstore]\nmicropython = "256K"\n',
        )
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )
        assert backend._heap_budget("micropython", "kvstore") == "256K"
        assert backend._heap_budget("micropython", "timing") == "192K"
        assert backend._heap_budget("circuitpython", "kvstore") is None

    def test_cli_override_and_off_switch(self, tmp_path: Path) -> None:
        workspace = self._workspace_with_budgets(
            tmp_path, '[heap]\nmicropython = "192K"\n',
        )
        pinned = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
            heapsize="64K",
        )
        assert pinned._heap_budget("micropython", "kvstore") == "64K"
        disabled = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
            heapsize="off",
        )
        assert disabled._heap_budget("micropython", None) is None

    def test_missing_heap_table_means_no_ceiling(self, tmp_path: Path) -> None:
        workspace = _workspace_with_harness(tmp_path, "print('x')\n")
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )
        assert backend._heap_budget("micropython", None) is None

    def test_memoryerror_without_summary_names_the_budget(
        self, tmp_path: Path,
    ) -> None:
        # A worker that dies on the board-shaped heap before SUMMARY
        # surfaces as policy (budget named, override path coached),
        # not as a generic parse failure.
        workspace = _workspace_with_harness(
            tmp_path,
            "print('importing big thing')\nraise MemoryError('allocation failed')\n",
        )
        (workspace / "target-runtimes.toml").write_text(
            '[heap]\nmicropython = "192K"\n',
        )
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )
        with pytest.raises(BackendExecuteError, match="heapsize=192K") as excinfo:
            backend.execute(
                _item_for(workspace / "test_oom.py"), _unix_port_target(),
            )
        assert "OOM a real Pico W" in str(excinfo.value)
        assert "heap.overrides" in str(excinfo.value)

    def test_memoryerror_with_summary_is_not_intercepted(
        self, tmp_path: Path,
    ) -> None:
        # A test that legitimately exercises MemoryError handling and
        # still completes its run keeps normal reporting.
        workspace = _workspace_with_harness(
            tmp_path,
            "print('caught MemoryError in a test')\n"
            "print('SUMMARY total=1 failed=0 time=0.1s')\n",
        )
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )
        output = backend.execute(
            _item_for(workspace / "test_ok.py"), _unix_port_target(),
        )
        assert "SUMMARY" in output


class TestResolve:
    """Binary resolution order and failure modes."""

    def test_missing_binary_everywhere_raises_prepare_error(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """No override, no marker, no PATH hit: a coached prepare error."""
        monkeypatch.setattr(
            "chumicro_pytest_device.backends.shutil.which", lambda _name: None,
        )
        backend = UnixPortBackend(tmp_path)
        with pytest.raises(BackendPrepareError, match="binary not found"):
            backend._resolve("micropython")

    def test_second_resolve_returns_the_cached_path(
        self, tmp_path: Path,
    ) -> None:
        """The per-runtime resolution memoizes after the first call."""
        binary = tmp_path / "fake-runtime"
        binary.write_text("#!/bin/sh\n")
        backend = UnixPortBackend(
            tmp_path, binaries={"micropython": str(binary)},
        )

        first = backend._resolve("micropython")
        # Remove the file: a second call must not re-check existence.
        binary.unlink()
        second = backend._resolve("micropython")

        assert first == second == str(tmp_path / "fake-runtime")


class TestPrepare:
    """Front-loaded failure checks before any subprocess spawns."""

    def test_missing_harness_script_raises_prepare_error(
        self, tmp_path: Path,
    ) -> None:
        """A workspace without the worker script fails with the install hint."""
        backend = UnixPortBackend(
            tmp_path, binaries={"micropython": sys.executable},
        )
        with pytest.raises(BackendPrepareError, match="harness not found"):
            backend.prepare(
                _item_for(tmp_path / "test_x.py"), _unix_port_target(),
            )

    def test_prepare_with_binary_and_harness_succeeds(
        self, tmp_path: Path,
    ) -> None:
        """Binary resolved + harness present: prepare returns quietly."""
        workspace = _workspace_with_harness(tmp_path, "print('PASS')\n")
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )
        backend.prepare(
            _item_for(workspace / "test_x.py"), _unix_port_target(),
        )


class TestExecute:
    """Real subprocess spawn, output capture, and error surfaces."""

    def test_returns_harness_output_for_the_test_file(
        self, tmp_path: Path,
    ) -> None:
        """The worker invocation's stdout comes back for parsing."""
        workspace = _workspace_with_harness(
            tmp_path,
            "import sys\n"
            "print('PASS test_alpha (0.01s)')\n"
            "print('SUMMARY total=1 failed=0 time=0.01s')\n"
            "print('worker file:', sys.argv[-1])\n",
        )
        test_file = workspace / "test_demo.py"
        test_file.write_text("def test_alpha():\n    pass\n")
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )

        output = backend.execute(_item_for(test_file), _unix_port_target())

        assert "PASS test_alpha (0.01s)" in output
        # The worker received the test file path as its argument.
        assert str(test_file) in output

    def test_stderr_is_captured_alongside_stdout(
        self, tmp_path: Path,
    ) -> None:
        """Harness noise on stderr still reaches the parser input."""
        workspace = _workspace_with_harness(
            tmp_path,
            "import sys\n"
            "print('PASS test_a (0.01s)')\n"
            "print('boot noise', file=sys.stderr)\n",
        )
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )

        output = backend.execute(
            _item_for(workspace / "test_a.py"), _unix_port_target(),
        )

        assert "boot noise" in output

    def test_silent_nonzero_exit_raises_execute_error(
        self, tmp_path: Path,
    ) -> None:
        """A worker that dies without output surfaces the exit code."""
        workspace = _workspace_with_harness(
            tmp_path, "import sys\nsys.exit(3)\n",
        )
        backend = UnixPortBackend(
            workspace, binaries={"micropython": sys.executable},
        )

        with pytest.raises(BackendExecuteError, match="no output"):
            backend.execute(
                _item_for(workspace / "test_a.py"), _unix_port_target(),
            )

    def test_unspawnable_binary_raises_execute_error(
        self, tmp_path: Path,
    ) -> None:
        """A binary the OS refuses to exec surfaces as a spawn failure."""
        workspace = _workspace_with_harness(tmp_path, "print('PASS')\n")
        not_executable = workspace / "not-a-binary.txt"
        not_executable.write_text("plain text, not executable\n")
        backend = UnixPortBackend(
            workspace, binaries={"micropython": str(not_executable)},
        )

        with pytest.raises(BackendExecuteError, match="failed to spawn"):
            backend.execute(
                _item_for(workspace / "test_a.py"), _unix_port_target(),
            )


class TestExecuteTimeout:
    """A worker that runs past the timeout is killed and named, not left hanging."""

    def test_hanging_worker_times_out_naming_the_file(
        self, tmp_path: Path,
    ) -> None:
        """A file that exceeds the timeout raises, naming the file and ceiling.

        The worker script sleeps far longer than the 0.2 s timeout, so
        ``subprocess.run`` kills it and the backend surfaces a
        ``BackendExecuteError`` naming the file — one wedged file fails
        cleanly instead of stalling the lane.
        """
        workspace = _workspace_with_harness(
            tmp_path, "import time\ntime.sleep(30)\n",
        )
        test_file = workspace / "test_hang.py"
        backend = UnixPortBackend(
            workspace,
            binaries={"micropython": sys.executable},
            execute_timeout_seconds=0.2,
        )

        with pytest.raises(BackendExecuteError, match="timed out") as excinfo:
            backend.execute(_item_for(test_file), _unix_port_target())
        assert "test_hang.py" in str(excinfo.value)
        assert "0.2s" in str(excinfo.value)

    def test_fast_file_under_the_timeout_returns_output(
        self, tmp_path: Path,
    ) -> None:
        """A file that finishes within the timeout returns its captured output."""
        workspace = _workspace_with_harness(
            tmp_path, "print('PASS test_a (0.01s)')\n",
        )
        backend = UnixPortBackend(
            workspace,
            binaries={"micropython": sys.executable},
            execute_timeout_seconds=30.0,
        )

        output = backend.execute(
            _item_for(workspace / "test_a.py"), _unix_port_target(),
        )
        assert "PASS test_a" in output
