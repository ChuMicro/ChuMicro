"""Tests for the built-in devices.yml loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy.config.default import load_devices_yml

_MINIMAL_YAML = """\
defaults:
  micropython: mp-board
  circuitpython: cp-board
  deploy_mode: ram
devices:
  - id: mp-board
    runtime: micropython
    address: /dev/cu.usbmodem213101
    serial_baudrate: 115200
  - id: cp-board
    runtime: circuitpython
    address: /dev/cu.usbmodem11401
    serial_baudrate: 115200
    circuitpy_drive_path: /Volumes/CIRCUITPY
"""

_MP_ONLY_YAML = """\
defaults:
  micropython: solo
  deploy_mode: flash
devices:
  - id: solo
    runtime: micropython
    address: /dev/ttyACM0
    serial_baudrate: 460800
"""

_BOTH_DEFAULTS_YAML = """\
defaults:
  micropython: mp-one
  circuitpython: cp-one
devices:
  - id: mp-one
    runtime: micropython
    address: /dev/a
  - id: cp-one
    runtime: circuitpython
    address: /dev/b
"""


def _write(tmp_path: Path, content: str) -> Path:
    yaml_path = tmp_path / "devices.yml"
    yaml_path.write_text(content)
    return yaml_path


class TestLoadDevicesYml:
    def test_explicit_device_id(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, _MINIMAL_YAML)
        device = load_devices_yml(yaml_path, device_id="mp-board")
        assert device.transport == "micropython"
        assert device.address == "/dev/cu.usbmodem213101"
        assert device.baudrate == 115200
        assert device.deploy_mode == "ram"

    def test_explicit_cp_with_drive(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, _MINIMAL_YAML)
        device = load_devices_yml(yaml_path, device_id="cp-board")
        assert device.circuitpy_drive_path == Path("/Volumes/CIRCUITPY")

    def test_unique_default_picks_runtime(self, tmp_path: Path) -> None:
        """When only one runtime has a default, that one is used."""
        yaml_path = _write(tmp_path, _MP_ONLY_YAML)
        device = load_devices_yml(yaml_path)
        assert device.transport == "micropython"
        assert device.address == "/dev/ttyACM0"
        # defaults.deploy_mode is applied when entry omits it.
        assert device.deploy_mode == "flash"
        # serial_baudrate → baudrate.
        assert device.baudrate == 460800

    def test_ambiguous_defaults_raise(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, _BOTH_DEFAULTS_YAML)
        with pytest.raises(ValueError, match="Multiple or no default"):
            load_devices_yml(yaml_path)

    def test_unknown_device_id_raises(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, _MINIMAL_YAML)
        with pytest.raises(ValueError, match="not found"):
            load_devices_yml(yaml_path, device_id="nonexistent")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_devices_yml(tmp_path / "missing.yml")

    def test_empty_devices_raises(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, "defaults:\n  micropython: x\ndevices: []\n")
        with pytest.raises(ValueError, match="No devices"):
            load_devices_yml(yaml_path)

    def test_entry_deploy_mode_overrides_default(self, tmp_path: Path) -> None:
        content = """\
defaults:
  micropython: x
  deploy_mode: ram
devices:
  - id: x
    runtime: micropython
    address: /dev/x
    deploy_mode: flash
"""
        yaml_path = _write(tmp_path, content)
        device = load_devices_yml(yaml_path)
        assert device.deploy_mode == "flash"

    def test_tolerates_extra_entry_keys(self, tmp_path: Path) -> None:
        content = """\
defaults:
  micropython: x
devices:
  - id: x
    runtime: micropython
    address: /dev/x
    description: my board
    connection_type: serial
    setup_command: null
"""
        yaml_path = _write(tmp_path, content)
        # extra fields are tolerated by Device.from_dict; should not raise.
        device = load_devices_yml(yaml_path)
        assert device.address == "/dev/x"
