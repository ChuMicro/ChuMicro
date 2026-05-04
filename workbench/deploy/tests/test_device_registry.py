"""Tests for the device-registry schema in ``chumicro_deploy.config.default``.

Migrated from ``scripts/tests/test_device_config.py`` when the schema
moved out of the mono-repo's ``scripts/`` and into the publishable
workbench package (Decision 0032 §Rule 8).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import (
    DeviceConfigError,
    DeviceDefaults,
    DeviceEntry,
    load_device_registry,
    load_devices,
    resolve_ide_devices,
)
from chumicro_deploy.config.default import _parse_defaults


def _write_yaml(path: Path, content: str) -> Path:
    """Write YAML content to a file and return the path."""
    path.write_text(content)
    return path


class TestLoadDevices:
    """Tests for ``load_devices``."""

    def test_loads_valid_devices(self, tmp_path) -> None:
        """A well-formed ``devices.yml`` should return ``DeviceEntry`` objects."""
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: board-one
    runtime: micropython
    address: /dev/ttyUSB0
    description: Test board
""")
        devices = load_devices(devices_file)
        assert len(devices) == 1
        assert devices[0].identifier == "board-one"
        assert devices[0].runtime == "micropython"
        assert devices[0].address == "/dev/ttyUSB0"
        assert devices[0].description == "Test board"
        # Decision 0047 — flash is the default when no deploy_mode is set.
        assert devices[0].deploy_mode == "flash"

    def test_loads_multiple_devices(self, tmp_path) -> None:
        """Multiple device entries should all be returned."""
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: mp-board
    runtime: micropython
    address: /dev/ttyUSB0
  - id: cp-board
    runtime: circuitpython
    address: /dev/cu.usbmodem1234
""")
        devices = load_devices(devices_file)
        assert len(devices) == 2
        assert devices[0].identifier == "mp-board"
        assert devices[1].identifier == "cp-board"

    def test_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(DeviceConfigError, match="not found"):
            load_devices(tmp_path / "nonexistent.yml")

    def test_missing_required_field_raises(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: incomplete
    runtime: micropython
""")
        with pytest.raises(DeviceConfigError, match="missing required fields.*address"):
            load_devices(devices_file)

    def test_invalid_runtime_raises(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: bad-runtime
    runtime: arduino
    address: /dev/ttyUSB0
""")
        with pytest.raises(DeviceConfigError, match="invalid runtime"):
            load_devices(devices_file)

    def test_missing_devices_key_raises(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", "something_else: true\n")
        with pytest.raises(DeviceConfigError, match="'devices' list"):
            load_devices(devices_file)

    def test_invalid_per_device_deploy_mode_raises(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: bad-mode
    runtime: micropython
    address: /dev/ttyUSB0
    deploy_mode: turbo
""")
        with pytest.raises(DeviceConfigError, match="invalid deploy_mode"):
            load_devices(devices_file)

    def test_non_dict_yaml_raises(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", "- item\n")
        with pytest.raises(DeviceConfigError, match="YAML mapping"):
            load_devices(devices_file)

    def test_extra_fields_preserved(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: extended
    runtime: micropython
    address: /dev/ttyUSB0
    custom_property:
      host: "192.168.1.42"
""")
        devices = load_devices(devices_file)
        assert "custom_property" in devices[0].extra
        assert devices[0].extra["custom_property"]["host"] == "192.168.1.42"

    def test_defaults_for_optional_fields(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: minimal
    runtime: circuitpython
    address: /dev/cu.usbmodem1
""")
        device = load_devices(devices_file)[0]
        assert device.connection_type == "serial"
        assert device.serial_baudrate == 115200
        # Decision 0047 — flash is the default when no deploy_mode is set.
        assert device.deploy_mode == "flash"
        assert device.setup_command is None
        assert device.description == ""

class TestLoadDeviceRegistry:
    """Tests for ``load_device_registry``."""

    def test_returns_devices_and_defaults(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", """
defaults:
  micropython: board-one
  deploy_mode: flash
  ide_runtime: both
devices:
  - id: board-one
    runtime: micropython
    address: /dev/ttyUSB0
""")
        devices, defaults = load_device_registry(devices_file)
        assert len(devices) == 1
        assert defaults.micropython == "board-one"
        assert defaults.deploy_mode == "flash"
        assert defaults.ide_runtime == "both"

    def test_applies_global_deploy_mode_to_devices(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", """
defaults:
  deploy_mode: flash
devices:
  - id: no-mode
    runtime: micropython
    address: /dev/ttyUSB0
  - id: has-mode
    runtime: circuitpython
    address: /dev/cu.usb1
    deploy_mode: ram
""")
        devices, _defaults = load_device_registry(devices_file)
        assert devices[0].deploy_mode == "flash"
        assert devices[1].deploy_mode == "ram"

    def test_missing_defaults_section_uses_fallbacks(self, tmp_path) -> None:
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: board1
    runtime: micropython
    address: /dev/ttyUSB0
""")
        devices, defaults = load_device_registry(devices_file)
        # Decision 0047 — flash is the default fall-through.
        assert defaults.deploy_mode == "flash"
        assert defaults.ide_runtime == "micropython"
        assert defaults.micropython is None
        assert defaults.circuitpython is None
        assert devices[0].deploy_mode == "flash"


class TestParseDefaults:
    """Tests for the private ``_parse_defaults`` helper."""

    def test_empty_dict_returns_defaults(self) -> None:
        result = _parse_defaults({})
        # Decision 0047 — flash is the default fall-through.
        assert result.deploy_mode == "flash"
        assert result.ide_runtime == "micropython"
        assert result.micropython is None
        assert result.circuitpython is None

    def test_all_fields_parsed(self) -> None:
        result = _parse_defaults({
            "micropython": "mp-board",
            "circuitpython": "cp-board",
            "deploy_mode": "flash",
            "ide_runtime": "both",
        })
        assert result.micropython == "mp-board"
        assert result.circuitpython == "cp-board"
        assert result.deploy_mode == "flash"
        assert result.ide_runtime == "both"

    def test_invalid_deploy_mode_raises(self) -> None:
        with pytest.raises(DeviceConfigError, match="deploy_mode"):
            _parse_defaults({"deploy_mode": "turbo"})

    def test_invalid_ide_runtime_raises(self) -> None:
        with pytest.raises(DeviceConfigError, match="ide_runtime"):
            _parse_defaults({"ide_runtime": "arduino"})


class TestResolveIdeDevices:
    """Tests for ``resolve_ide_devices``."""

    @pytest.fixture()
    def mixed_devices(self) -> list[DeviceEntry]:
        return [
            DeviceEntry(identifier="mp-1", runtime="micropython", address="/dev/0"),
            DeviceEntry(identifier="mp-2", runtime="micropython", address="/dev/1"),
            DeviceEntry(identifier="cp-1", runtime="circuitpython", address="/dev/2"),
            DeviceEntry(identifier="cp-2", runtime="circuitpython", address="/dev/3"),
        ]

    def test_micropython_only(self, mixed_devices) -> None:
        defaults = DeviceDefaults(
            micropython="mp-1", ide_runtime="micropython",
        )
        result = resolve_ide_devices(mixed_devices, defaults)
        assert len(result) == 1
        assert result[0].identifier == "mp-1"

    def test_circuitpython_only(self, mixed_devices) -> None:
        defaults = DeviceDefaults(
            circuitpython="cp-2", ide_runtime="circuitpython",
        )
        result = resolve_ide_devices(mixed_devices, defaults)
        assert len(result) == 1
        assert result[0].identifier == "cp-2"

    def test_both_runtimes(self, mixed_devices) -> None:
        defaults = DeviceDefaults(
            micropython="mp-2", circuitpython="cp-1", ide_runtime="both",
        )
        result = resolve_ide_devices(mixed_devices, defaults)
        assert len(result) == 2
        assert result[0].identifier == "mp-2"
        assert result[1].identifier == "cp-1"

    def test_falls_back_to_first_of_runtime(self, mixed_devices) -> None:
        defaults = DeviceDefaults(ide_runtime="both")
        result = resolve_ide_devices(mixed_devices, defaults)
        assert len(result) == 2
        assert result[0].identifier == "mp-1"
        assert result[1].identifier == "cp-1"

    def test_missing_device_id_skipped(self, mixed_devices) -> None:
        defaults = DeviceDefaults(
            micropython="nonexistent", ide_runtime="micropython",
        )
        result = resolve_ide_devices(mixed_devices, defaults)
        assert result == []

    def test_empty_device_list(self) -> None:
        defaults = DeviceDefaults(ide_runtime="both")
        result = resolve_ide_devices([], defaults)
        assert result == []

    def test_no_devices_of_runtime(self) -> None:
        devices = [
            DeviceEntry(identifier="mp-1", runtime="micropython", address="/dev/0"),
        ]
        defaults = DeviceDefaults(ide_runtime="both")
        result = resolve_ide_devices(devices, defaults)
        assert len(result) == 1
        assert result[0].runtime == "micropython"
