"""Tests for the device_bootstrap_runner fixture body.

Drives the fixture generator directly (via its ``__wrapped__``
function) against a FakeTransport-primed session, so the stage /
bootstrap-build / runner-spawn setup and the join-then-shutdown
teardown run for real without a board.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_deploy.testing import FakeTransport
from chumicro_pytest_device.fixtures import host_driver
from chumicro_pytest_device.testing import (
    FakeSession,
    prime_transport_cache,
)
from chumicro_pytest_device.transport_cache import _TransportCache
from chumicro_workspace.device_runner import DeviceBootstrapRunner

_FIXTURE_BODY = host_driver.device_bootstrap_runner.__wrapped__


def _micropython_device() -> DeviceEntry:
    """An MP entry: keeps build_device_bootstrap off the CP-RAM chunk path."""
    return DeviceEntry(
        identifier="mp-1", runtime="micropython",
        address="/dev/ttyUSB-mp", deploy_mode="ram",
    )


def _build_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Create a demo library with a paired host + board functional test.

    Returns ``(host_file, board_file)``.
    """
    library_dir = tmp_path / "libraries" / "demo"
    source_dir = library_dir / "src" / "chumicro_demo"
    source_dir.mkdir(parents=True)
    (source_dir / "__init__.py").write_text("")
    (library_dir / "pyproject.toml").write_text(
        '[project]\nname = "chumicro-demo"\nversion = "0.0.1"\n'
        "dependencies = []\n",
    )
    functional_dir = library_dir / "functional_tests"
    functional_dir.mkdir()
    board_file = functional_dir / "test_real_demo.py"
    board_file.write_text('print("BOARD_SIDE_RAN")\n')
    host_file = functional_dir / "test_real_demo_host.py"
    host_file.write_text("def test_host_side():\n    pass\n")
    return host_file, board_file


def _session_with_transport(
    tmp_path: Path, device: DeviceEntry, transport: FakeTransport,
) -> FakeSession:
    cache = _TransportCache()
    cache.set_resolved_deploy_mode(device.identifier, "ram")
    prime_transport_cache(cache, device, transport)
    session = FakeSession(cache, rootpath=tmp_path)
    session._device_targets = [device]
    return session


def _request_stub(host_file: Path, session: FakeSession) -> SimpleNamespace:
    """FixtureRequest stand-in: fspath + markerless node + session."""
    node = SimpleNamespace(get_closest_marker=lambda _name: None)
    return SimpleNamespace(fspath=str(host_file), node=node, session=session)


class TestDeviceBootstrapRunnerFixture:
    """Setup stages the board file and teardown reaps the runner."""

    def test_yields_started_runner_after_staging_board_sources(
        self, tmp_path: Path,
    ) -> None:
        """The fixture stages library sources + board file, then yields a runner."""
        host_file, board_file = _build_workspace(tmp_path)
        device = _micropython_device()
        transport = FakeTransport(execute_output="BOARD_SIDE_RAN\n")
        session = _session_with_transport(tmp_path, device, transport)

        generator = _FIXTURE_BODY(_request_stub(host_file, session))
        runner = next(generator)
        try:
            assert isinstance(runner, DeviceBootstrapRunner)
            stage_calls = [
                call for call in transport.calls if call[0] == "stage"
            ]
            assert len(stage_calls) == 1
            source_dirs, test_files, _harness, _extra_modules, extra_files, \
                include_test_support = stage_calls[0][1]
            assert board_file.parent.parent / "src" in source_dirs
            assert test_files == [board_file]
            # No runtime-config payload registered and not a unit sweep.
            assert extra_files is None
            assert include_test_support is False
            # The runner was started: the bootstrap thread is live and
            # delivers the board output.
            assert "BOARD_SIDE_RAN" in runner.wait_for_completion(
                timeout_s=1.0,
            )
        finally:
            with pytest.raises(StopIteration):
                next(generator)

    def test_falls_back_to_registry_default_when_no_targets(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """An empty target list resolves the device via the registry fallback."""
        host_file, _board_file = _build_workspace(tmp_path)
        device = _micropython_device()
        transport = FakeTransport()
        session = _session_with_transport(tmp_path, device, transport)
        session._device_targets = []

        fallback_calls: list[object] = []

        def fake_fallback(fallback_session: object) -> DeviceEntry:
            fallback_calls.append(fallback_session)
            return device

        monkeypatch.setattr(
            host_driver, "_load_fallback_device", fake_fallback,
        )

        generator = _FIXTURE_BODY(_request_stub(host_file, session))
        runner = next(generator)
        try:
            assert isinstance(runner, DeviceBootstrapRunner)
            assert fallback_calls == [session]
        finally:
            with pytest.raises(StopIteration):
                next(generator)

    def test_teardown_survives_completion_timeout_and_still_shuts_down(
        self, tmp_path: Path,
    ) -> None:
        """A bootstrap that never finishes doesn't mask teardown shutdown."""
        host_file, _board_file = _build_workspace(tmp_path)
        device = _micropython_device()
        transport = FakeTransport()
        session = _session_with_transport(tmp_path, device, transport)

        generator = _FIXTURE_BODY(_request_stub(host_file, session))
        runner = next(generator)

        shutdown_calls: list[str] = []
        original_shutdown = runner.shutdown

        def recording_shutdown() -> None:
            shutdown_calls.append("shutdown")
            original_shutdown()

        def timing_out(timeout_s: float) -> str:
            raise TimeoutError("bootstrap never completed")

        runner.wait_for_completion = timing_out
        runner.shutdown = recording_shutdown

        with pytest.raises(StopIteration):
            next(generator)

        assert shutdown_calls == ["shutdown"]
