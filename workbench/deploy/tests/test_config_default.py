"""Tests for the built-in devices.yml loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy.config.default import load_devices_yml, load_raw_entries

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

    def test_runtime_picks_circuitpython_default(self, tmp_path: Path) -> None:
        """`runtime="circuitpython"` resolves to defaults.circuitpython."""
        yaml_path = _write(tmp_path, _BOTH_DEFAULTS_YAML)
        device = load_devices_yml(yaml_path, runtime="circuitpython")
        assert device.transport == "circuitpython"
        assert device.address == "/dev/b"

    def test_runtime_picks_micropython_default(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, _BOTH_DEFAULTS_YAML)
        device = load_devices_yml(yaml_path, runtime="micropython")
        assert device.transport == "micropython"
        assert device.address == "/dev/a"

    def test_runtime_with_unknown_name_raises(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, _BOTH_DEFAULTS_YAML)
        with pytest.raises(ValueError, match="Unsupported runtime"):
            load_devices_yml(yaml_path, runtime="cpython")

    def test_runtime_default_missing_in_file_raises(
        self, tmp_path: Path,
    ) -> None:
        # _MP_ONLY_YAML has no defaults.circuitpython.
        yaml_path = _write(tmp_path, _MP_ONLY_YAML)
        with pytest.raises(ValueError, match="No defaults.circuitpython"):
            load_devices_yml(yaml_path, runtime="circuitpython")

    def test_runtime_default_points_at_missing_id_raises(
        self, tmp_path: Path,
    ) -> None:
        content = """\
defaults:
  circuitpython: dangling-id
devices:
  - id: present
    runtime: circuitpython
    address: /dev/x
"""
        yaml_path = _write(tmp_path, content)
        with pytest.raises(ValueError, match="not in devices list"):
            load_devices_yml(yaml_path, runtime="circuitpython")

    def test_runtime_and_device_id_together_raise(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, _BOTH_DEFAULTS_YAML)
        with pytest.raises(ValueError, match="mutually exclusive"):
            load_devices_yml(
                yaml_path, device_id="mp-one", runtime="circuitpython",
            )

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


class TestLoadRawEntries:
    def test_returns_devices_and_defaults_separately(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, _MINIMAL_YAML)
        entries, defaults = load_raw_entries(yaml_path)
        assert isinstance(entries, list)
        assert len(entries) == 2
        assert entries[0]["id"] == "mp-board"
        assert defaults["micropython"] == "mp-board"
        assert defaults["deploy_mode"] == "ram"

    def test_returns_raw_dicts_unchanged(self, tmp_path: Path) -> None:
        """No normalisation: keys are exactly as written."""
        yaml_path = _write(tmp_path, _MINIMAL_YAML)
        entries, _defaults = load_raw_entries(yaml_path)
        assert entries[0].get("runtime") == "micropython"
        assert "transport" not in entries[0]
        assert entries[0].get("serial_baudrate") == 115200
        assert "baudrate" not in entries[0]

    def test_missing_devices_key_returns_empty_list(self, tmp_path: Path) -> None:
        """Permissive primitive: missing key = empty list, not an error.

        Strictness lives at the consumer (e.g. ``load_devices_yml`` raises
        on no entries; the workspace dispatcher likewise enforces a
        non-empty registry before deploying)."""
        yaml_path = _write(tmp_path, "defaults:\n  micropython: nope\n")
        entries, defaults = load_raw_entries(yaml_path)
        assert entries == []
        assert defaults == {"micropython": "nope"}

    def test_missing_defaults_returns_empty_dict(self, tmp_path: Path) -> None:
        yaml_path = _write(
            tmp_path,
            "devices:\n  - id: a\n    runtime: micropython\n    address: /dev/a\n",
        )
        entries, defaults = load_raw_entries(yaml_path)
        assert len(entries) == 1
        assert defaults == {}

    def test_missing_file_raises_filenotfound(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_raw_entries(tmp_path / "does-not-exist.yml")

    def test_root_not_mapping_raises_valueerror(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, "- just\n- a\n- list\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_raw_entries(yaml_path)

    def test_defaults_wrong_type_raises_valueerror(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, "defaults: not-a-mapping\ndevices: []\n")
        with pytest.raises(ValueError, match="defaults: section"):
            load_raw_entries(yaml_path)

    def test_devices_wrong_type_raises_valueerror(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, "devices: not-a-list\n")
        with pytest.raises(ValueError, match="devices: section"):
            load_raw_entries(yaml_path)

    def test_empty_yaml_returns_empty_pair(self, tmp_path: Path) -> None:
        yaml_path = _write(tmp_path, "")
        entries, defaults = load_raw_entries(yaml_path)
        assert entries == []
        assert defaults == {}
