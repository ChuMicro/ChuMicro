"""Coverage-closing tests for the UnixPortBackend and the LAN IP helper.

Covers UnixPortBackend._resolve's cache-hit and missing-path branches
and the three execute() outcomes (success, spawn failure, empty output),
plus detect_lan_ip's OSError fallback — all with monkeypatched
subprocess / socket, no real binary or network.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_pytest_device import backends
from chumicro_pytest_device.fixtures import lan


def _target(runtime: str = "micropython") -> DeviceEntry:
    """Build a synthetic unix-port DeviceEntry for the given runtime."""
    return DeviceEntry(
        identifier=f"{runtime}-unix-port",
        runtime=runtime,
        address="unix-port",
    )


def _backend_with_binary(tmp_path: Path) -> tuple[backends.UnixPortBackend, Path]:
    """Build a backend pointed at a real stub binary; return (backend, binary)."""
    binary = tmp_path / "stub-micropython"
    binary.write_text("#!/bin/sh\n")
    backend = backends.UnixPortBackend(
        tmp_path, binaries={"micropython": str(binary)},
    )
    return backend, binary


def _write_harness(tmp_path: Path) -> None:
    """Create the run_cross_runtime.py harness script prepare/execute expect."""
    harness = tmp_path / "support" / "test_harness" / "run_cross_runtime.py"
    harness.parent.mkdir(parents=True)
    harness.write_text("# stub harness\n")


class TestUnixPortBackendResolve:
    """Tests for UnixPortBackend._resolve caching and existence guards."""

    def test_second_resolve_returns_memoized_path(self, tmp_path: Path) -> None:
        """The second _resolve for a runtime returns the cached path without re-resolving."""
        backend, binary = _backend_with_binary(tmp_path)
        first = backend._resolve("micropython")
        second = backend._resolve("micropython")
        assert first == second == str(binary)

    def test_resolve_raises_when_override_path_missing(self, tmp_path: Path) -> None:
        """An override pointing at a nonexistent file fails with a path-does-not-exist error."""
        backend = backends.UnixPortBackend(
            tmp_path, binaries={"micropython": str(tmp_path / "nope" / "mpy")},
        )
        with pytest.raises(backends.BackendPrepareError, match="does not exist"):
            backend._resolve("micropython")


class TestUnixPortBackendExecute:
    """Tests for UnixPortBackend.execute's subprocess outcomes."""

    def test_execute_returns_combined_output_on_success(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """A successful spawn returns stdout+stderr for the result parser to read."""
        backend, _binary = _backend_with_binary(tmp_path)
        _write_harness(tmp_path)
        monkeypatch.setattr(
            backends.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(
                stdout="PASS test_x (0.001s)\n", stderr="", returncode=0,
            ),
        )
        item = SimpleNamespace(test_file=tmp_path / "test_x.py")

        output = backend.execute(item, _target())  # type: ignore[arg-type]
        assert "PASS test_x" in output

    def test_execute_wraps_spawn_oserror(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """An OSError during spawn becomes a BackendExecuteError naming the failure."""
        backend, _binary = _backend_with_binary(tmp_path)
        _write_harness(tmp_path)

        def _raise(*args, **kwargs):
            raise OSError("exec format error")

        monkeypatch.setattr(backends.subprocess, "run", _raise)
        item = SimpleNamespace(test_file=tmp_path / "test_x.py")

        with pytest.raises(backends.BackendExecuteError, match="failed to spawn"):
            backend.execute(item, _target())  # type: ignore[arg-type]

    def test_execute_raises_on_empty_output(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """A run that emits only whitespace with a nonzero exit fails as no-output."""
        backend, _binary = _backend_with_binary(tmp_path)
        _write_harness(tmp_path)
        monkeypatch.setattr(
            backends.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(
                stdout="  \n", stderr="", returncode=1,
            ),
        )
        item = SimpleNamespace(test_file=tmp_path / "test_x.py")

        with pytest.raises(backends.BackendExecuteError, match="no output"):
            backend.execute(item, _target())  # type: ignore[arg-type]


class TestDetectLanIp:
    """Tests for the detect_lan_ip OSError fallback."""

    def test_returns_none_when_connect_raises_oserror(self, monkeypatch) -> None:
        """A socket whose connect raises OSError yields None and still closes the socket."""
        closed = {"value": False}

        class _FakeSocket:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def connect(self, _address) -> None:
                raise OSError("network unreachable")

            def getsockname(self):
                raise AssertionError("getsockname should not run after connect fails")

            def close(self) -> None:
                closed["value"] = True

        monkeypatch.setattr(lan.socket, "socket", _FakeSocket)

        assert lan.detect_lan_ip() is None
        assert closed["value"] is True
