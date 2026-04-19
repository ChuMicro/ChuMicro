"""Tests for device_config — device registry and environment config loading."""

from __future__ import annotations

from pathlib import Path

import pytest
from device_config import (
    DeviceConfigError,
    DeviceEntry,
    filter_devices,
    find_default_device,
    load_device_config,
    load_devices,
)


def _write_yaml(path: Path, content: str) -> Path:
    """Write YAML content to a file and return the path."""
    path.write_text(content)
    return path


class TestLoadDevices:
    """Tests for load_devices."""

    def test_loads_valid_devices(self, tmp_path) -> None:
        """A well-formed devices.yml should return DeviceEntry objects."""
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: board-one
    runtime: micropython
    address: /dev/ttyUSB0
    description: Test board
    board_type: esp32s3
""")
        devices = load_devices(devices_file)
        assert len(devices) == 1
        assert devices[0].identifier == "board-one"
        assert devices[0].runtime == "micropython"
        assert devices[0].address == "/dev/ttyUSB0"
        assert devices[0].description == "Test board"
        assert devices[0].board_type == "esp32s3"
        assert devices[0].deploy_mode == "ram"

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
        """A missing devices.yml should raise DeviceConfigError."""
        with pytest.raises(DeviceConfigError, match="not found"):
            load_devices(tmp_path / "nonexistent.yml")

    def test_missing_required_field_raises(self, tmp_path) -> None:
        """A device entry missing 'address' should raise DeviceConfigError."""
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: incomplete
    runtime: micropython
""")
        with pytest.raises(DeviceConfigError, match="missing required fields.*address"):
            load_devices(devices_file)

    def test_invalid_runtime_raises(self, tmp_path) -> None:
        """An unrecognized runtime value should raise DeviceConfigError."""
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: bad-runtime
    runtime: arduino
    address: /dev/ttyUSB0
""")
        with pytest.raises(DeviceConfigError, match="invalid runtime"):
            load_devices(devices_file)

    def test_missing_devices_key_raises(self, tmp_path) -> None:
        """A YAML file without a 'devices' list should raise DeviceConfigError."""
        devices_file = _write_yaml(tmp_path / "devices.yml", "something_else: true\n")
        with pytest.raises(DeviceConfigError, match="'devices' list"):
            load_devices(devices_file)

    def test_non_dict_yaml_raises(self, tmp_path) -> None:
        """A YAML file with a list at the root should raise DeviceConfigError."""
        devices_file = _write_yaml(tmp_path / "devices.yml", "- item\n")
        with pytest.raises(DeviceConfigError, match="YAML mapping"):
            load_devices(devices_file)

    def test_extra_fields_preserved(self, tmp_path) -> None:
        """Unknown fields should be preserved in the extra dict."""
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
        """Optional fields should have sensible defaults."""
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: minimal
    runtime: circuitpython
    address: /dev/cu.usbmodem1
""")
        device = load_devices(devices_file)[0]
        assert device.connection_type == "serial"
        assert device.serial_baudrate == 115200
        assert device.deploy_mode == "ram"
        assert device.setup_command is None
        assert device.description == ""

    def test_environment_variable_override(self, tmp_path, monkeypatch) -> None:
        """CHUMICRO_DEVICES should override the default path."""
        devices_file = _write_yaml(tmp_path / "custom.yml", """
devices:
  - id: env-board
    runtime: micropython
    address: /dev/ttyUSB9
""")
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        devices = load_devices()
        assert devices[0].identifier == "env-board"

    def test_generated_devices_content_parses(self, tmp_path) -> None:
        """The generated devices.yml content should parse without errors."""
        from shared import TEMPLATES_DIR

        template_content = (TEMPLATES_DIR / "devices.yml.template").read_text()
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(template_content)
        devices = load_devices(devices_file)
        assert len(devices) >= 1


class TestLoadDeviceConfig:
    """Tests for load_device_config."""

    def test_loads_valid_config(self, tmp_path) -> None:
        """A well-formed device-config.yml should return a dict."""
        config_file = _write_yaml(tmp_path / "device-config.yml", """
wifi:
  ssid: "TestNet"
  password: "secret123"
""")
        config = load_device_config(config_file)
        assert config["wifi"]["ssid"] == "TestNet"

    def test_missing_file_raises(self, tmp_path) -> None:
        """A missing device-config.yml should raise DeviceConfigError."""
        with pytest.raises(DeviceConfigError, match="not found"):
            load_device_config(tmp_path / "nope.yml")

    def test_environment_variable_override(self, tmp_path, monkeypatch) -> None:
        """CHUMICRO_DEVICE_CONFIG should override the default path."""
        config_file = _write_yaml(tmp_path / "custom-config.yml", """
wifi:
  ssid: "EnvNet"
""")
        monkeypatch.setenv("CHUMICRO_DEVICE_CONFIG", str(config_file))
        config = load_device_config()
        assert config["wifi"]["ssid"] == "EnvNet"

    def test_generated_device_config_content_parses(self, tmp_path) -> None:
        """The generated device-config.yml content should parse."""
        from shared import TEMPLATES_DIR

        template_content = (TEMPLATES_DIR / "device-config.yml.template").read_text()
        config_file = tmp_path / "device-config.yml"
        config_file.write_text(template_content)
        config = load_device_config(config_file)
        assert isinstance(config, dict)


class TestFilterDevices:
    """Tests for filter_devices."""

    @pytest.fixture()
    def sample_devices(self) -> list[DeviceEntry]:
        """Return a mixed list of devices for filtering tests."""
        return [
            DeviceEntry(identifier="mp-1", runtime="micropython", address="/dev/ttyUSB0"),
            DeviceEntry(identifier="mp-2", runtime="micropython", address="/dev/ttyUSB1"),
            DeviceEntry(identifier="cp-1", runtime="circuitpython", address="/dev/cu.usbmodem1"),
        ]

    def test_filter_by_runtime(self, sample_devices) -> None:
        """Filtering by runtime should return only matching devices."""
        result = filter_devices(sample_devices, runtime="micropython")
        assert len(result) == 2
        assert all(device.runtime == "micropython" for device in result)

    def test_filter_by_device_id(self, sample_devices) -> None:
        """Filtering by device_id should return exactly one device."""
        result = filter_devices(sample_devices, device_id="cp-1")
        assert len(result) == 1
        assert result[0].identifier == "cp-1"

    def test_filter_by_both(self, sample_devices) -> None:
        """Filtering by both runtime and device_id should intersect."""
        result = filter_devices(sample_devices, runtime="micropython", device_id="mp-2")
        assert len(result) == 1
        assert result[0].identifier == "mp-2"

    def test_no_filter_returns_all(self, sample_devices) -> None:
        """No filter should return all devices."""
        result = filter_devices(sample_devices)
        assert len(result) == 3

    def test_no_match_returns_empty(self, sample_devices) -> None:
        """A filter that matches nothing should return an empty list."""
        result = filter_devices(sample_devices, device_id="nonexistent")
        assert result == []


class TestFindDefaultDevice:
    """Tests for find_default_device."""

    def test_returns_none_for_empty_list(self) -> None:
        """An empty device list should return None."""
        assert find_default_device([]) is None

    def test_returns_marked_default(self) -> None:
        """Should return the device marked default: true."""
        devices = [
            DeviceEntry(identifier="first", runtime="micropython", address="/dev/0"),
            DeviceEntry(
                identifier="second", runtime="circuitpython",
                address="/dev/1", default=True,
            ),
            DeviceEntry(identifier="third", runtime="micropython", address="/dev/2"),
        ]
        result = find_default_device(devices)
        assert result.identifier == "second"

    def test_returns_first_when_none_marked(self) -> None:
        """When no device is marked default, should return the first one."""
        devices = [
            DeviceEntry(identifier="alpha", runtime="micropython", address="/dev/0"),
            DeviceEntry(identifier="beta", runtime="circuitpython", address="/dev/1"),
        ]
        result = find_default_device(devices)
        assert result.identifier == "alpha"

    def test_returns_first_default_if_multiple(self) -> None:
        """If multiple devices are marked default, return the first one."""
        devices = [
            DeviceEntry(identifier="a", runtime="micropython", address="/dev/0", default=True),
            DeviceEntry(identifier="b", runtime="circuitpython", address="/dev/1", default=True),
        ]
        result = find_default_device(devices)
        assert result.identifier == "a"


class TestDefaultField:
    """Tests for the default field on DeviceEntry."""

    def test_default_false_by_default(self, tmp_path) -> None:
        """Devices without 'default' should have default=False."""
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: board1
    runtime: micropython
    address: /dev/ttyUSB0
""")
        device = load_devices(devices_file)[0]
        assert device.default is False

    def test_default_true_parsed(self, tmp_path) -> None:
        """The 'default: true' field should be parsed correctly."""
        devices_file = _write_yaml(tmp_path / "devices.yml", """
devices:
  - id: board1
    runtime: circuitpython
    address: /dev/cu.usb1
    default: true
""")
        device = load_devices(devices_file)[0]
        assert device.default is True
