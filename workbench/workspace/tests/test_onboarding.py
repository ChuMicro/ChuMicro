"""Tests for board-state detection + onboarding diagnostics."""

from pathlib import Path
from typing import Any

import pytest
from chumicro_deploy import Device, DeviceImplementation
from chumicro_workspace.onboarding import (
    BoardState,
    OnboardingDiagnosis,
    detect_board_state,
    find_uf2_drive,
    probe_with_runtime_inference,
)

# ---------------------------------------------------------------------------
# find_uf2_drive
# ---------------------------------------------------------------------------


def _make_uf2_layout(
    base: Path,
    *,
    label: str = "RPI-RP2",
    drive_label: str = "INFO_UF2.TXT",
) -> Path:
    """Create a fake UF2 mount root with one drive labeled *label*."""
    drive = base / label
    drive.mkdir()
    (drive / drive_label).write_text("UF2 Bootloader\n")
    return drive


class TestFindUf2Drive:
    def test_returns_drive_when_present(self, tmp_path: Path) -> None:
        drive = _make_uf2_layout(tmp_path)
        assert find_uf2_drive([tmp_path]) == drive

    def test_returns_none_when_no_drive(self, tmp_path: Path) -> None:
        assert find_uf2_drive([tmp_path]) is None

    def test_returns_none_when_search_path_missing(self, tmp_path: Path) -> None:
        assert find_uf2_drive([tmp_path / "absent"]) is None

    def test_skips_non_directory_children(self, tmp_path: Path) -> None:
        (tmp_path / "regular-file.txt").write_text("hi\n")
        assert find_uf2_drive([tmp_path]) is None

    def test_skips_directory_without_info_uf2_txt(self, tmp_path: Path) -> None:
        (tmp_path / "RegularDrive").mkdir()
        assert find_uf2_drive([tmp_path]) is None

    def test_first_match_wins_in_sorted_order(self, tmp_path: Path) -> None:
        """Sorted iteration gives a stable answer when two drives are mounted."""
        first = _make_uf2_layout(tmp_path, label="AAA-RP2")
        _make_uf2_layout(tmp_path, label="ZZZ-RP2")
        assert find_uf2_drive([tmp_path]) == first

    def test_default_search_paths_used_when_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Hitting the default-platform branch — no drive on the dev box, returns None."""
        # Force an empty default by monkeypatching the lookup table.
        from chumicro_workspace import onboarding

        monkeypatch.setattr(onboarding, "_UF2_MOUNT_SEARCH_PATHS", {})
        assert find_uf2_drive() is None


# ---------------------------------------------------------------------------
# detect_board_state — REPL_REACHABLE branch
# ---------------------------------------------------------------------------


def _device() -> Device:
    return Device(transport="micropython", address="/dev/cu.fake")


def _info_with_implementation(name: str = "micropython") -> Any:
    """Mimic the shape chumicro_deploy.probe_device returns."""

    class _Info:
        implementation = DeviceImplementation(
            name=name, version="1.26.0", machine="Pi Pico W", uid="ABCD",
        )
        board_id = "raspberry_pi_pico_w"
        uid = "ABCD"

    return _Info()


def _info_without_implementation() -> Any:
    class _Info:
        implementation = None
        board_id = ""
        uid = ""

    return _Info()


class TestReplReachable:
    def test_probe_returns_implementation(self) -> None:
        diagnosis = detect_board_state(
            _device(),
            probe_function=lambda _device: _info_with_implementation(),
            drive_scanner=lambda _paths: None,
        )
        assert diagnosis.state is BoardState.REPL_REACHABLE
        assert diagnosis.probe_implementation_name == "micropython"
        assert diagnosis.probe_error == ""
        assert diagnosis.uf2_drive is None
        assert any("REPL" in step for step in diagnosis.next_steps)

    def test_uf2_drive_not_scanned_when_probe_succeeds(
        self,
        tmp_path: Path,
    ) -> None:
        """Successful probe wins — no spurious UF2 lookup that could false-positive."""
        scanner_calls: list[Any] = []

        def fake_scanner(paths: list[Path] | None) -> Path | None:
            scanner_calls.append(paths)
            return _make_uf2_layout(tmp_path)

        diagnosis = detect_board_state(
            _device(),
            probe_function=lambda _device: _info_with_implementation(),
            drive_scanner=fake_scanner,
        )
        assert diagnosis.state is BoardState.REPL_REACHABLE
        assert scanner_calls == []  # scanner was not called


# ---------------------------------------------------------------------------
# detect_board_state — UF2_BOOTLOADER branch
# ---------------------------------------------------------------------------


class TestUf2Bootloader:
    def test_probe_no_marker_with_uf2_present(self, tmp_path: Path) -> None:
        drive = _make_uf2_layout(tmp_path)
        diagnosis = detect_board_state(
            _device(),
            probe_function=lambda _device: _info_without_implementation(),
            drive_scanner=lambda _paths: drive,
        )
        assert diagnosis.state is BoardState.UF2_BOOTLOADER
        assert diagnosis.uf2_drive == drive
        assert any("install firmware" in step.lower() for step in diagnosis.next_steps)

    def test_probe_raises_with_uf2_present(self, tmp_path: Path) -> None:
        drive = _make_uf2_layout(tmp_path)

        def fake_probe(_device: Device) -> Any:
            raise ConnectionError("could not open port /dev/cu.fake")

        diagnosis = detect_board_state(
            _device(),
            probe_function=fake_probe,
            drive_scanner=lambda _paths: drive,
        )
        assert diagnosis.state is BoardState.UF2_BOOTLOADER
        assert diagnosis.uf2_drive == drive
        # Probe error preserved for diagnostic display.
        assert "could not open port" in diagnosis.probe_error

    def test_uf2_hint_includes_drive_path(self, tmp_path: Path) -> None:
        drive = _make_uf2_layout(tmp_path)
        diagnosis = detect_board_state(
            _device(),
            probe_function=lambda _device: _info_without_implementation(),
            drive_scanner=lambda _paths: drive,
        )
        assert any(str(drive) in step for step in diagnosis.next_steps)


# ---------------------------------------------------------------------------
# detect_board_state — NO_PROBE_RESPONSE branch
# ---------------------------------------------------------------------------


class TestNoProbeResponse:
    def test_no_implementation_no_uf2(self) -> None:
        diagnosis = detect_board_state(
            _device(),
            probe_function=lambda _device: _info_without_implementation(),
            drive_scanner=lambda _paths: None,
        )
        assert diagnosis.state is BoardState.NO_PROBE_RESPONSE
        assert any("esptool" in step.lower() for step in diagnosis.next_steps)

    def test_probe_raises_non_serial_error(self) -> None:
        def fake_probe(_device: Device) -> Any:
            raise RuntimeError("execute returned no output after 5s")

        diagnosis = detect_board_state(
            _device(),
            probe_function=fake_probe,
            drive_scanner=lambda _paths: None,
        )
        assert diagnosis.state is BoardState.NO_PROBE_RESPONSE
        assert "no output after" in diagnosis.probe_error


# ---------------------------------------------------------------------------
# detect_board_state — SERIAL_UNREACHABLE branch
# ---------------------------------------------------------------------------


class TestSerialUnreachable:
    @pytest.mark.parametrize(
        "error_message",
        [
            "could not open port /dev/cu.absent",
            "[Errno 2] No such file or directory: '/dev/cu.x'",
            "[Errno 13] Permission denied: '/dev/ttyACM0'",
            "device not configured",
            "[Errno 16] Resource busy: '/dev/cu.usbmodem'",
            "could not exclusively lock port",
        ],
    )
    def test_serial_idioms_route_to_unreachable(self, error_message: str) -> None:
        def fake_probe(_device: Device) -> Any:
            raise OSError(error_message)

        diagnosis = detect_board_state(
            _device(),
            probe_function=fake_probe,
            drive_scanner=lambda _paths: None,
        )
        assert diagnosis.state is BoardState.SERIAL_UNREACHABLE
        assert any("discover" in step for step in diagnosis.next_steps)

    def test_empty_error_text_not_treated_as_unreachable(self) -> None:
        """A bare exception with no message falls through to NO_PROBE_RESPONSE."""

        def fake_probe(_device: Device) -> Any:
            raise RuntimeError

        diagnosis = detect_board_state(
            _device(),
            probe_function=fake_probe,
            drive_scanner=lambda _paths: None,
        )
        # Empty str(exception) → falls back to type name → "RuntimeError".
        # Not a serial idiom, so NO_PROBE_RESPONSE.
        assert diagnosis.state is BoardState.NO_PROBE_RESPONSE
        assert diagnosis.probe_error == "RuntimeError"


# ---------------------------------------------------------------------------
# Default-arg branches (production path)
# ---------------------------------------------------------------------------


class TestDefaultArgs:
    def test_default_probe_function_uses_chumicro_deploy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without injection, detect_board_state pulls probe_device from chumicro_deploy."""
        import chumicro_deploy

        called: list[Device] = []

        def fake_probe(device: Device) -> Any:
            called.append(device)
            return _info_with_implementation()

        monkeypatch.setattr(chumicro_deploy, "probe_device", fake_probe)
        diagnosis = detect_board_state(
            _device(),
            drive_scanner=lambda _paths: None,
        )
        assert diagnosis.state is BoardState.REPL_REACHABLE
        assert called == [_device()] or len(called) == 1

    def test_default_drive_scanner_uses_find_uf2_drive(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace import onboarding

        # No UF2 drives on dev box — point default search at empty tmp_path.
        monkeypatch.setattr(
            onboarding,
            "_UF2_MOUNT_SEARCH_PATHS",
            {"darwin": [tmp_path], "linux": [tmp_path], "win32": [tmp_path]},
        )
        diagnosis = detect_board_state(
            _device(),
            probe_function=lambda _device: _info_without_implementation(),
        )
        assert diagnosis.state is BoardState.NO_PROBE_RESPONSE


# ---------------------------------------------------------------------------
# OnboardingDiagnosis dataclass smoke test
# ---------------------------------------------------------------------------


class TestOnboardingDiagnosis:
    def test_default_construction(self) -> None:
        diagnosis = OnboardingDiagnosis(state=BoardState.REPL_REACHABLE)
        assert diagnosis.uf2_drive is None
        assert diagnosis.probe_implementation_name is None
        assert diagnosis.probe_error == ""
        assert diagnosis.next_steps == []


# ---------------------------------------------------------------------------
# probe_with_runtime_inference — Step 3 of beginner-onramp
# ---------------------------------------------------------------------------


class _FakeDevice:
    """Minimal stand-in for chumicro_deploy.Device for the inference tests."""

    def __init__(self, transport: str, address: str) -> None:
        self.transport = transport
        self.address = address


def _device_factory(transport: str, address: str) -> Any:
    return _FakeDevice(transport, address)


class TestProbeWithRuntimeInference:
    def test_first_candidate_succeeds(self) -> None:
        """MP transport works → MP runtime → no need to fall through to CP."""
        attempts: list[str] = []

        def fake_probe(device: _FakeDevice) -> Any:
            attempts.append(device.transport)
            return _info_with_implementation(name="micropython")

        result = probe_with_runtime_inference(
            "/dev/cu.x",
            probe_function=fake_probe,
            device_factory=_device_factory,
        )
        assert result.runtime == "micropython"
        assert result.transport_used == "micropython"
        assert result.info is not None
        assert attempts == ["micropython"]

    def test_falls_through_to_circuitpython(self) -> None:
        """First candidate raises → second candidate's success wins."""
        attempts: list[str] = []

        def fake_probe(device: _FakeDevice) -> Any:
            attempts.append(device.transport)
            if device.transport == "micropython":
                raise RuntimeError("MP transport said no")
            return _info_with_implementation(name="circuitpython")

        result = probe_with_runtime_inference(
            "/dev/cu.x",
            probe_function=fake_probe,
            device_factory=_device_factory,
        )
        assert result.runtime == "circuitpython"
        assert result.transport_used == "circuitpython"
        assert attempts == ["micropython", "circuitpython"]

    def test_implementation_name_takes_precedence_over_transport(self) -> None:
        """MP transport on a CP board → still register as CP.

        The probe script reads ``sys.implementation`` regardless of
        which transport delivered the bytes.  Our public answer is
        whatever the board reports, not the transport we used to
        reach it.
        """

        def fake_probe(device: _FakeDevice) -> Any:
            return _info_with_implementation(name="circuitpython")

        result = probe_with_runtime_inference(
            "/dev/cu.x",
            probe_function=fake_probe,
            device_factory=_device_factory,
        )
        assert result.runtime == "circuitpython"
        assert result.transport_used == "micropython"  # first candidate

    def test_all_candidates_fail_returns_empty_result(self) -> None:
        attempts: list[str] = []

        def fake_probe(device: _FakeDevice) -> Any:
            attempts.append(device.transport)
            raise RuntimeError("nothing's listening")

        result = probe_with_runtime_inference(
            "/dev/cu.x",
            probe_function=fake_probe,
            device_factory=_device_factory,
        )
        assert result.runtime is None
        assert result.transport_used is None
        assert result.info is None
        assert isinstance(result.last_exception, RuntimeError)
        assert attempts == ["micropython", "circuitpython"]

    def test_no_marker_falls_through(self) -> None:
        """Probe completes but returns no implementation marker → keep trying."""
        attempts: list[str] = []

        def fake_probe(device: _FakeDevice) -> Any:
            attempts.append(device.transport)
            return _info_without_implementation()

        result = probe_with_runtime_inference(
            "/dev/cu.x",
            probe_function=fake_probe,
            device_factory=_device_factory,
        )
        assert result.runtime is None
        # Both candidates were tried; neither raised, so last_exception
        # stays None — the caller can distinguish "transport refused"
        # from "transport opened but board didn't speak Python".
        assert result.last_exception is None
        assert attempts == ["micropython", "circuitpython"]

    def test_custom_candidate_order(self) -> None:
        """Caller can override the default order or skip a runtime."""
        attempts: list[str] = []

        def fake_probe(device: _FakeDevice) -> Any:
            attempts.append(device.transport)
            return _info_with_implementation(name="circuitpython")

        result = probe_with_runtime_inference(
            "/dev/cu.x",
            candidates=("circuitpython",),
            probe_function=fake_probe,
            device_factory=_device_factory,
        )
        assert result.runtime == "circuitpython"
        assert attempts == ["circuitpython"]

    def test_defaults_use_chumicro_deploy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without injection, the helper imports probe_device + Device.

        Exercises the default-factory branches so coverage doesn't
        rely on hardware-only paths to reach them.
        """
        import chumicro_deploy

        attempts: list[str] = []

        class _RecordingDevice:
            def __init__(self, transport: str, address: str) -> None:
                self.transport = transport
                self.address = address

        def fake_probe(device: _RecordingDevice) -> Any:
            attempts.append(device.transport)
            return _info_with_implementation(name="micropython")

        monkeypatch.setattr(chumicro_deploy, "probe_device", fake_probe)
        monkeypatch.setattr(chumicro_deploy, "Device", _RecordingDevice)

        result = probe_with_runtime_inference("/dev/cu.x")
        assert result.runtime == "micropython"
        assert attempts == ["micropython"]
