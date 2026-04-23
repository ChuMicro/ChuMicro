"""Tests for flash_firmware and its helpers."""

from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from chumicro_deploy import Device, FlashFirmwareError, flash_firmware
from chumicro_deploy.firmware import (
    _copy_uf2_to_drive,
    _download_firmware,
    _enter_esp32_rom_bootloader,
    _enter_uf2_bootloader_programmatic,
    _flash_firmware_esptool,
    _flash_firmware_uf2,
    _prompt_manual_bootloader_entry,
    _scan_for_uf2_drive,
    _uf2_mount_candidates,
    _wait_for_drive_gone,
    _wait_for_uf2_drive,
)


class _FakeUrlResponse:
    """Minimal urlopen return fake — supports read(chunk), getheader, close."""

    def __init__(self, payload: bytes, *, content_length: bool = True) -> None:
        self._stream = io.BytesIO(payload)
        self._content_length = str(len(payload)) if content_length else None
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def getheader(self, name: str, default: str | None = None) -> str | None:
        if name.lower() == "content-length":
            return self._content_length
        return default

    def close(self) -> None:
        self.closed = True


@dataclass
class _FakeClock:
    """Monotonic that advances on demand; sleep advances it."""

    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TestDownloadFirmware:
    def test_writes_payload_to_destination(self, tmp_path: Path) -> None:
        destination = tmp_path / "fw.uf2"

        def fake_urlopen(url: str) -> _FakeUrlResponse:
            assert url == "https://example/fw.uf2"
            return _FakeUrlResponse(b"ABC" * 100)

        _download_firmware(
            "https://example/fw.uf2", destination, urlopen=fake_urlopen
        )
        assert destination.read_bytes() == b"ABC" * 100

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        destination = tmp_path / "nested" / "dir" / "fw.uf2"

        def fake_urlopen(_url: str) -> _FakeUrlResponse:
            return _FakeUrlResponse(b"payload")

        _download_firmware(
            "url", destination, urlopen=fake_urlopen
        )
        assert destination.read_bytes() == b"payload"

    def test_progress_reported_with_content_length(self, tmp_path: Path) -> None:
        # Payload larger than the 64 KiB chunk size so multiple progress
        # events fire.
        payload = b"x" * (64 * 1024 * 3)
        destination = tmp_path / "fw.uf2"

        def fake_urlopen(_url: str) -> _FakeUrlResponse:
            return _FakeUrlResponse(payload)

        events: list[tuple[float, str]] = []

        def record(fraction: float, message: str) -> None:
            events.append((fraction, message))

        _download_firmware(
            "url", destination, on_progress=record, urlopen=fake_urlopen,
        )
        assert events[0] == (0.0, "downloading url")
        assert events[-1] == (1.0, "download complete")
        mid_events = events[1:-1]
        assert mid_events, "expected incremental progress events"
        assert 0.0 < mid_events[-1][0] <= 1.0

    def test_url_error_wraps_with_recovery_hint(self, tmp_path: Path) -> None:
        from urllib.error import URLError

        def fake_urlopen(_url: str) -> _FakeUrlResponse:
            raise URLError("dns fail")

        with pytest.raises(FlashFirmwareError, match="Check the URL"):
            _download_firmware(
                "url", tmp_path / "fw.uf2", urlopen=fake_urlopen,
            )


class TestUf2DriveDetection:
    def test_scan_finds_drive_with_info_marker(self, tmp_path: Path) -> None:
        drive = tmp_path / "RPI-RP2"
        drive.mkdir()
        (drive / "INFO_UF2.TXT").write_text("UF2 Bootloader\r\n")
        other = tmp_path / "Other"
        other.mkdir()
        found = _scan_for_uf2_drive([tmp_path])
        assert found == drive

    def test_scan_skips_non_uf2_directories(self, tmp_path: Path) -> None:
        (tmp_path / "A").mkdir()
        (tmp_path / "B").mkdir()
        assert _scan_for_uf2_drive([tmp_path]) is None

    def test_scan_ignores_files(self, tmp_path: Path) -> None:
        (tmp_path / "loose.txt").write_text("not a drive")
        assert _scan_for_uf2_drive([tmp_path]) is None

    def test_scan_tolerates_missing_search_root(self, tmp_path: Path) -> None:
        assert _scan_for_uf2_drive([tmp_path / "missing"]) is None

    def test_wait_for_drive_polls(self, tmp_path: Path) -> None:
        clock = _FakeClock()
        drive = tmp_path / "RPI-RP2"

        # Create the drive after two poll intervals so we exercise
        # the retry branch.
        def sleep_that_creates(_seconds: float) -> None:
            clock.now += _seconds
            if clock.now >= 1.0 and not drive.exists():
                drive.mkdir()
                (drive / "INFO_UF2.TXT").write_text("marker")

        found = _wait_for_uf2_drive(
            [tmp_path],
            sleep=sleep_that_creates,
            monotonic=clock.monotonic,
        )
        assert found == drive

    def test_wait_for_drive_times_out(self, tmp_path: Path) -> None:
        clock = _FakeClock()
        found = _wait_for_uf2_drive(
            [tmp_path],
            timeout=0.2,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        assert found is None

    def test_wait_for_drive_gone_detects_unmount(self, tmp_path: Path) -> None:
        clock = _FakeClock()
        drive = tmp_path / "RPI-RP2"
        drive.mkdir()
        (drive / "INFO_UF2.TXT").write_text("marker")

        def sleep_that_removes(_seconds: float) -> None:
            clock.now += _seconds
            if clock.now >= 1.0 and (drive / "INFO_UF2.TXT").exists():
                (drive / "INFO_UF2.TXT").unlink()

        assert _wait_for_drive_gone(
            drive,
            timeout=5.0,
            sleep=sleep_that_removes,
            monotonic=clock.monotonic,
        ) is True

    def test_wait_for_drive_gone_times_out(self, tmp_path: Path) -> None:
        clock = _FakeClock()
        drive = tmp_path / "RPI-RP2"
        drive.mkdir()
        (drive / "INFO_UF2.TXT").write_text("marker")
        assert _wait_for_drive_gone(
            drive, timeout=0.2, sleep=clock.sleep, monotonic=clock.monotonic,
        ) is False


class TestUf2MountCandidates:
    def test_uses_explicit_paths_when_provided(self, tmp_path: Path) -> None:
        assert _uf2_mount_candidates([tmp_path]) == [tmp_path]

    def test_platform_defaults_returns_a_list(self) -> None:
        result = _uf2_mount_candidates()
        assert isinstance(result, list)


class TestCopyUf2:
    def test_copies_and_reports_progress(self, tmp_path: Path) -> None:
        firmware = tmp_path / "firmware.uf2"
        firmware.write_bytes(b"UF2 bytes")
        drive = tmp_path / "RPI-RP2"
        drive.mkdir()

        events: list[tuple[float, str]] = []

        def record(fraction: float, message: str) -> None:
            events.append((fraction, message))

        _copy_uf2_to_drive(firmware, drive, on_progress=record)

        assert (drive / "firmware.uf2").read_bytes() == b"UF2 bytes"
        assert events[0][0] == 0.0
        assert events[-1][0] == 1.0

    def test_copy_failure_wraps_with_recovery_hint(self, tmp_path: Path) -> None:
        firmware = tmp_path / "firmware.uf2"
        firmware.write_bytes(b"x")
        # Drive target that exists as a file, so shutil.copy fails.
        fake_drive = tmp_path / "drive_file"
        fake_drive.write_text("not a dir")
        with pytest.raises(FlashFirmwareError, match="bootloader mode"):
            _copy_uf2_to_drive(firmware, fake_drive / "firmware.uf2")


class TestBootloaderEntry:
    def test_delegates_to_transport_reset_into_bootloader(self) -> None:
        from chumicro_deploy import FakeTransport as PublicFakeTransport

        fake = PublicFakeTransport(bootloader_reset_result=True)

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = DeviceForTest(transport="circuitpython", address="/dev/x")
        assert _enter_uf2_bootloader_programmatic(device) is True
        method_order = [call[0] for call in fake.calls]
        assert method_order == ["connect", "reset_into_bootloader", "disconnect"]

    def test_returns_false_when_transport_says_unsupported(self) -> None:
        from chumicro_deploy import FakeTransport as PublicFakeTransport

        fake = PublicFakeTransport(bootloader_reset_result=False)

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = DeviceForTest(transport="micropython", address="/dev/x")
        assert _enter_uf2_bootloader_programmatic(device) is False

    def test_connect_failure_returns_false(self) -> None:
        class FailingTransport:
            mode = "ram"

            def connect(self) -> None:
                raise RuntimeError("serial busy")

            def reset_into_bootloader(self) -> bool:
                raise AssertionError("should not be called if connect fails")

            def disconnect(self) -> None:
                pass

            def stage(self, *args: Any, **kwargs: Any) -> None:
                pass

            def execute(self, script: str) -> str:
                return ""

            def soft_reset(self) -> None:
                pass

            def reset(self) -> None:
                pass

            def recover(self) -> None:
                pass

            def probe_implementation(self) -> None:
                return None

            def deploy_files(self, *args: Any, **kwargs: Any) -> str:
                return ""

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                return FailingTransport()

        device = DeviceForTest(transport="circuitpython", address="/dev/x")
        assert _enter_uf2_bootloader_programmatic(device) is False


class TestManualBootloaderPrompt:
    def test_prompt_message_names_address(self) -> None:
        captured: list[str] = []

        def fake_prompt(message: str) -> str:
            captured.append(message)
            return ""

        device = Device(transport="circuitpython", address="/dev/my-fancy-port")
        _prompt_manual_bootloader_entry(device, prompt=fake_prompt)

        assert "my-fancy-port" in captured[0]
        assert "bootloader" in captured[0].lower()


class TestEsptoolPath:
    def test_missing_esptool_raises_with_install_hint(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: None)
        device = Device(transport="micropython", address="/dev/ttyUSB0")
        firmware = tmp_path / "fw.bin"
        firmware.write_bytes(b"x")
        with pytest.raises(FlashFirmwareError, match="Install it with"):
            _flash_firmware_esptool(firmware, device, on_progress=None)

    def test_successful_invocation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/fake/esptool" if name == "esptool" else None,
        )

        runner_calls: list[list[str]] = []

        def fake_runner(command, **_kwargs):  # noqa: ANN001
            runner_calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, "", "")

        device = Device(transport="micropython", address="/dev/ttyUSB0")
        firmware = tmp_path / "fw.bin"
        firmware.write_bytes(b"x")
        _flash_firmware_esptool(firmware, device, on_progress=None, runner=fake_runner)

        assert len(runner_calls) == 1
        assert runner_calls[0][0] == "/fake/esptool"
        assert "--port" in runner_calls[0]
        assert "/dev/ttyUSB0" in runner_calls[0]
        assert "write-flash" in runner_calls[0]
        # Default offset is 0x0; the offset slot is the argv
        # position immediately after ``write-flash``.
        assert runner_calls[0][runner_calls[0].index("write-flash") + 1] == "0x0"

    def test_custom_flash_offset_is_passed_to_esptool(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """MicroPython ESP32 .bin needs 0x1000 — custom offset must round-trip."""
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/fake/esptool" if name == "esptool" else None,
        )

        captured: list[list[str]] = []

        def fake_runner(command, **_kwargs):  # noqa: ANN001
            captured.append(list(command))
            return subprocess.CompletedProcess(command, 0, "", "")

        device = Device(transport="micropython", address="/dev/ttyUSB0")
        firmware = tmp_path / "fw.bin"
        firmware.write_bytes(b"x")
        _flash_firmware_esptool(
            firmware, device, on_progress=None,
            flash_offset="0x1000", runner=fake_runner,
        )

        assert len(captured) == 1
        assert captured[0][captured[0].index("write-flash") + 1] == "0x1000"

    def test_erase_flash_uses_two_invocations_with_no_reset_on_erase(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """Erase and write are separate esptool calls.

        esptool v5 dropped chained sub-commands; each sub-command
        is its own invocation.  The erase call must pass
        ``--after no_reset`` so the chip stays in ROM bootloader
        for the write call — otherwise esptool's default hard_reset
        strands the (now empty-flash) board until the user holds
        GPIO0 and re-plugs.
        """
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/fake/esptool" if name == "esptool" else None,
        )

        invocations: list[list[str]] = []

        def fake_runner(command, **_kwargs):  # noqa: ANN001
            invocations.append(list(command))
            return subprocess.CompletedProcess(command, 0, "", "")

        device = Device(transport="micropython", address="/dev/ttyUSB0")
        firmware = tmp_path / "fw.bin"
        firmware.write_bytes(b"x")
        _flash_firmware_esptool(
            firmware, device, on_progress=None,
            erase_flash=True, runner=fake_runner,
        )

        assert len(invocations) == 2
        erase_command, write_command = invocations
        assert "erase-flash" in erase_command
        assert "no_reset" in erase_command
        assert "write-flash" in write_command
        assert "no_reset" not in write_command

    def test_erase_flash_failure_surfaces_step_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/fake/esptool" if name == "esptool" else None,
        )

        def fake_runner(command, **_kwargs):  # noqa: ANN001
            return subprocess.CompletedProcess(command, 1, "", "erase boom")

        device = Device(transport="micropython", address="/dev/ttyUSB0")
        firmware = tmp_path / "fw.bin"
        firmware.write_bytes(b"x")
        with pytest.raises(FlashFirmwareError, match="erase-flash exited"):
            _flash_firmware_esptool(
                firmware, device, on_progress=None,
                erase_flash=True, runner=fake_runner,
            )

    def test_nonzero_exit_wraps_with_recovery_hint(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/fake/esptool" if name == "esptool" else None,
        )

        def fake_runner(command, **_kwargs):  # noqa: ANN001
            return subprocess.CompletedProcess(
                command, 1, "", "bootloader not found",
            )

        device = Device(transport="micropython", address="/dev/ttyUSB0")
        firmware = tmp_path / "fw.bin"
        firmware.write_bytes(b"x")
        with pytest.raises(FlashFirmwareError, match="write"):
            _flash_firmware_esptool(firmware, device, on_progress=None, runner=fake_runner)


class TestEnterEsp32RomBootloader:
    """Tests for the automated-with-fallback ESP32 bootloader-entry helper."""

    def test_bootloader_address_short_circuits(self, tmp_path: Path) -> None:
        device = Device(
            transport="micropython", address="/dev/cu.usbmodem01",
        )
        # With a bootloader-style address, no transport calls should fire
        # and no polling is needed — the helper returns the address
        # unchanged.
        result = _enter_esp32_rom_bootloader(
            device, interactive=False,
        )
        assert result == "/dev/cu.usbmodem01"

    def test_programmatic_entry_detects_new_port(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_deploy import FakeTransport as PublicFakeTransport

        fake = PublicFakeTransport(bootloader_reset_result=True)

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = DeviceForTest(
            transport="circuitpython", address="/dev/cu.usbmodem12345",
        )

        port_sequence = [
            {"/dev/cu.usbmodem12345"},  # baseline snapshot
            {"/dev/cu.usbmodem12345"},  # still only running port
            {"/dev/cu.usbmodem12345", "/dev/cu.usbmodem01"},  # bootloader up
        ]

        def fake_list_ports(*_args, **_kwargs):
            return port_sequence.pop(0) if port_sequence else set()

        monkeypatch.setattr(
            "chumicro_deploy.firmware._list_candidate_serial_ports",
            fake_list_ports,
        )

        clock = _FakeClock()
        result = _enter_esp32_rom_bootloader(
            device,
            interactive=False,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        assert result == "/dev/cu.usbmodem01"
        assert ("reset_into_bootloader", ()) in fake.calls

    def test_non_interactive_failure_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_deploy import FakeTransport as PublicFakeTransport

        fake = PublicFakeTransport(bootloader_reset_result=False)

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = DeviceForTest(
            transport="micropython", address="/dev/cu.usbmodem211101",
        )

        # Port list never changes — programmatic entry never produces a
        # new port.
        monkeypatch.setattr(
            "chumicro_deploy.firmware._list_candidate_serial_ports",
            lambda *_args, **_kwargs: {"/dev/cu.usbmodem211101"},
        )
        clock = _FakeClock()
        with pytest.raises(FlashFirmwareError, match="ROM bootloader"):
            _enter_esp32_rom_bootloader(
                device,
                interactive=False,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            )

    def test_interactive_fallback_recovers(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_deploy import FakeTransport as PublicFakeTransport

        fake = PublicFakeTransport(bootloader_reset_result=False)

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = DeviceForTest(
            transport="micropython", address="/dev/cu.usbmodem211101",
        )

        prompt_fired = [False]

        def fake_list_ports(*_args, **_kwargs):
            if prompt_fired[0]:
                return {"/dev/cu.usbmodem211101", "/dev/cu.usbmodem01"}
            return {"/dev/cu.usbmodem211101"}

        monkeypatch.setattr(
            "chumicro_deploy.firmware._list_candidate_serial_ports",
            fake_list_ports,
        )

        prompt_inputs: list[str] = []

        def fake_prompt(message: str) -> str:
            prompt_inputs.append(message)
            prompt_fired[0] = True
            return ""

        clock = _FakeClock()
        result = _enter_esp32_rom_bootloader(
            device,
            interactive=True,
            prompt=fake_prompt,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        assert result == "/dev/cu.usbmodem01"
        assert len(prompt_inputs) == 1
        assert "BOOT" in prompt_inputs[0]


class TestFlashFirmware:
    def test_unknown_method_rejects(self) -> None:
        device = Device(transport="micropython", address="/dev/x")
        with pytest.raises(ValueError, match="Unsupported reflash_method"):
            flash_firmware("https://ex/fw.uf2", device, reflash_method="dfu")


class TestFlashFirmwareUf2End2End:
    def test_happy_path_with_explicit_drive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Integration-style: download → copy → reboot (all faked)."""
        firmware_path = tmp_path / "fw.uf2"
        firmware_path.write_bytes(b"UF2 MAGIC")

        drive = tmp_path / "RPI-RP2"
        drive.mkdir()
        (drive / "INFO_UF2.TXT").write_text("marker")

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                class NeverUsedTransport:
                    mode = "ram"

                    def connect(self):
                        return

                    def execute(self, script):
                        return ""

                    def disconnect(self):
                        return

                    def stage(self, *args, **kwargs):
                        return

                    def soft_reset(self):
                        return

                    def reset(self):
                        return

                    def recover(self):
                        return

                    def probe_implementation(self):
                        return None

                    def reset_into_bootloader(self) -> bool:
                        return True

                    def deploy_files(self, *args, **kwargs):
                        return ""

                return NeverUsedTransport()

        device = DeviceForTest(transport="circuitpython", address="/dev/x")

        clock = _FakeClock()

        def sleep_marking(_seconds: float) -> None:
            clock.sleep(_seconds)
            # Simulate the drive disappearing after reboot.
            info = drive / "INFO_UF2.TXT"
            if clock.now > 1.0 and info.exists():
                info.unlink()

        _flash_firmware_uf2(
            firmware_path,
            device,
            bootloader_drive_path=drive,
            interactive=False,
            on_progress=None,
            sleep=sleep_marking,
            monotonic=clock.monotonic,
        )

        assert (drive / "fw.uf2").read_bytes() == b"UF2 MAGIC"

    def test_drive_never_appears_raises_with_recovery_hint(
        self, tmp_path: Path,
    ) -> None:
        firmware_path = tmp_path / "fw.uf2"
        firmware_path.write_bytes(b"x")

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                class FailConnectTransport:
                    mode = "ram"

                    def connect(self):
                        raise RuntimeError("no serial")

                    def execute(self, script):
                        return ""

                    def disconnect(self):
                        return

                    def stage(self, *args, **kwargs):
                        return

                    def soft_reset(self):
                        return

                    def reset(self):
                        return

                    def recover(self):
                        return

                    def probe_implementation(self):
                        return None

                    def deploy_files(self, *args, **kwargs):
                        return ""

                return FailConnectTransport()

        device = DeviceForTest(transport="circuitpython", address="/dev/x")
        empty_parent = tmp_path / "empty"
        empty_parent.mkdir()
        clock = _FakeClock()
        with pytest.raises(FlashFirmwareError, match="INFO_UF2"):
            _flash_firmware_uf2(
                firmware_path,
                device,
                bootloader_drive_path=None,
                interactive=False,
                on_progress=None,
                search_paths=[empty_parent],
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            )
