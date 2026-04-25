"""Tests for probe_device and DeviceInfo."""

from __future__ import annotations

import pytest
from chumicro_deploy import (
    Device,
    DeviceImplementation,
    DeviceInfo,
    FakeTransport,
    WindowsNotSupportedError,
    host_platform,
    probe_device,
)


def _device_returning(fake: FakeTransport) -> Device:
    class DeviceForTest(Device):
        def create_transport(self):  # type: ignore[override]
            return fake

    return DeviceForTest(transport="micropython", address="/dev/fake")


class TestProbeDevice:
    def test_returns_implementation_when_transport_probes_ok(self):
        expected = DeviceImplementation(
            name="micropython", version="1.26.0", machine="rp2040"
        )
        fake = FakeTransport(probe_result=expected)
        device = _device_returning(fake)

        info = probe_device(device)
        assert isinstance(info, DeviceInfo)
        assert info.implementation == expected

    def test_board_id_and_uid_reserved_empty(self):
        implementation = DeviceImplementation(
            name="circuitpython", version="10.2", machine="pico_w"
        )
        fake = FakeTransport(probe_result=implementation)
        device = _device_returning(fake)
        info = probe_device(device)
        assert info.board_id == ""
        assert info.uid == ""

    def test_transport_none_probe_yields_none_implementation(self):
        fake = FakeTransport(probe_result=None)
        device = _device_returning(fake)
        info = probe_device(device)
        assert info.implementation is None

    def test_connect_and_disconnect_lifecycle(self):
        fake = FakeTransport(
            probe_result=DeviceImplementation(name="micropython", version="1.26", machine="x")
        )
        device = _device_returning(fake)
        probe_device(device)
        method_order = [call[0] for call in fake.calls]
        assert method_order == ["connect", "probe_implementation", "disconnect"]

    def test_disconnect_called_on_probe_error(self):
        class BoomTransport(FakeTransport):
            def probe_implementation(self):  # type: ignore[override]
                self.calls.append(("probe_implementation", ()))
                raise RuntimeError("boom")

        fake = BoomTransport()
        device = _device_returning(fake)
        with pytest.raises(RuntimeError, match="boom"):
            probe_device(device)
        assert ("disconnect", ()) in fake.calls


class TestProbeWindowsGuard:
    """probe_device refuses to run on native Windows."""

    def test_raises_on_windows_before_touching_transport(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeTransport(
            probe_result=DeviceImplementation(
                name="micropython", version="1.26", machine="x",
            ),
        )
        device = _device_returning(fake)
        monkeypatch.setattr(host_platform.sys, "platform", "win32")
        with pytest.raises(WindowsNotSupportedError, match="WSL2"):
            probe_device(device)
        # Transport must not have been opened.
        assert fake.calls == []


class TestDeviceInfo:
    def test_default_board_id_and_uid_are_empty(self):
        info = DeviceInfo(implementation=None)
        assert info.board_id == ""
        assert info.uid == ""

    def test_frozen(self):
        from dataclasses import FrozenInstanceError

        info = DeviceInfo(implementation=None)
        with pytest.raises(FrozenInstanceError):
            info.board_id = "x"  # type: ignore[misc]
