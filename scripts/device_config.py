"""Load and validate device configuration for device testing.

Two user-local config files (both gitignored):

- ``devices.yml`` — device registry (board connections, serial addresses,
  runtime type).  Template: ``devices.example.yml``.
- ``device-config.yml`` — shared test environment (WiFi, MQTT, etc.).
  Template: ``device-config.example.yml``.

Environment variable overrides: ``CHUMICRO_DEVICES`` and
``CHUMICRO_DEVICE_CONFIG``.

See Decision 0027 for the full schema.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from workspace import ROOT

#: Default path to the device registry file.
DEFAULT_DEVICES_PATH = ROOT / "devices.yml"
#: Default path to the shared test environment config file.
DEFAULT_DEVICE_CONFIG_PATH = ROOT / "device-config.yml"

#: Required fields for each device entry in devices.yml.
_REQUIRED_DEVICE_FIELDS = ("id", "runtime", "address")
#: Allowed runtime values.
_VALID_RUNTIMES = ("micropython", "circuitpython")


@dataclass
class DeviceEntry:
    """A single device from the device registry."""

    identifier: str
    runtime: str
    address: str
    description: str = ""
    connection_type: str = "serial"
    board_type: str = ""
    serial_baudrate: int = 115200
    transport_mode: str = "mount"
    setup_command: str | None = None
    extra: dict = field(default_factory=dict)


class DeviceConfigError(Exception):
    """Raised when device configuration is missing or invalid."""


def _resolve_path(
    environment_variable: str,
    default_path: Path,
) -> Path:
    """Resolve a config file path from an environment variable or default.

    Args:
        environment_variable: Name of the environment variable to check.
        default_path: Fallback path when the variable is not set.
    """
    override = os.environ.get(environment_variable)
    if override:
        return Path(override)
    return default_path


def _load_yaml(path: Path) -> dict:
    """Load and return a YAML file as a dict.

    Args:
        path: Path to the YAML file.

    Raises:
        DeviceConfigError: If the file is missing or not valid YAML.
    """
    if not path.exists():
        raise DeviceConfigError(
            f"Config file not found: {path}\n"
            f"Copy the example template and fill in your values."
        )
    with path.open() as config_file:
        data = yaml.safe_load(config_file)
    if not isinstance(data, dict):
        raise DeviceConfigError(
            f"Expected a YAML mapping in {path}, got {type(data).__name__}"
        )
    return data


def _validate_device(raw: dict, index: int) -> DeviceEntry:
    """Validate a single device entry and return a DeviceEntry.

    Args:
        raw: Raw dict from the YAML devices list.
        index: Position in the list (for error messages).

    Raises:
        DeviceConfigError: If required fields are missing or values are invalid.
    """
    missing = [
        field_name for field_name in _REQUIRED_DEVICE_FIELDS
        if field_name not in raw
    ]
    if missing:
        raise DeviceConfigError(
            f"Device entry {index}: missing required fields: {', '.join(missing)}"
        )

    runtime = raw["runtime"]
    if runtime not in _VALID_RUNTIMES:
        raise DeviceConfigError(
            f"Device entry {index} ({raw['id']}): "
            f"invalid runtime '{runtime}', must be one of {_VALID_RUNTIMES}"
        )

    # Extract known fields, put everything else in extra.
    known_keys = {
        "id", "runtime", "address", "description", "connection_type",
        "board_type", "serial_baudrate", "transport_mode", "setup_command",
    }
    extra = {key: value for key, value in raw.items() if key not in known_keys}

    return DeviceEntry(
        identifier=raw["id"],
        runtime=runtime,
        address=raw["address"],
        description=raw.get("description", ""),
        connection_type=raw.get("connection_type", "serial"),
        board_type=raw.get("board_type", ""),
        serial_baudrate=raw.get("serial_baudrate", 115200),
        transport_mode=raw.get("transport_mode", "mount"),
        setup_command=raw.get("setup_command"),
        extra=extra,
    )


def load_devices(path: Path | None = None) -> list[DeviceEntry]:
    """Load and validate the device registry.

    Args:
        path: Explicit path to devices.yml.  When ``None``, checks
            ``CHUMICRO_DEVICES`` then falls back to the workspace default.

    Returns:
        List of validated DeviceEntry objects.

    Raises:
        DeviceConfigError: If the file is missing, invalid, or contains
            entries with missing required fields.
    """
    resolved = path or _resolve_path("CHUMICRO_DEVICES", DEFAULT_DEVICES_PATH)
    data = _load_yaml(resolved)

    devices_list = data.get("devices")
    if not isinstance(devices_list, list):
        raise DeviceConfigError(
            f"Expected a 'devices' list in {resolved}"
        )

    return [
        _validate_device(entry, index)
        for index, entry in enumerate(devices_list)
    ]


def load_device_config(path: Path | None = None) -> dict:
    """Load the shared test environment configuration.

    Args:
        path: Explicit path to device-config.yml.  When ``None``, checks
            ``CHUMICRO_DEVICE_CONFIG`` then falls back to the workspace
            default.

    Returns:
        Dict of environment configuration (WiFi, MQTT, NTP, etc.).

    Raises:
        DeviceConfigError: If the file is missing or not valid YAML.
    """
    resolved = path or _resolve_path("CHUMICRO_DEVICE_CONFIG", DEFAULT_DEVICE_CONFIG_PATH)
    return _load_yaml(resolved)


def filter_devices(
    devices: list[DeviceEntry],
    *,
    runtime: str | None = None,
    device_id: str | None = None,
) -> list[DeviceEntry]:
    """Filter a device list by runtime and/or device ID.

    Args:
        devices: Full list of devices.
        runtime: Filter to devices matching this runtime.
        device_id: Filter to the device with this ID.

    Returns:
        Filtered list of DeviceEntry objects.
    """
    result = devices
    if runtime:
        result = [device for device in result if device.runtime == runtime]
    if device_id:
        result = [device for device in result if device.identifier == device_id]
    return result

