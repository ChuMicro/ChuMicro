"""Generate starter device configuration files during workspace setup.

When ``devices.yml`` or ``device-config.yml`` do not exist, this module
writes them with sensible placeholder content so the user can fill in
their board details immediately.  Existing files are never overwritten.

Called by ``python scripts/run.py setup``.
"""

from __future__ import annotations

from workspace import ROOT

_DEVICES_CONTENT = """\
# Device registry for local/CI device testing.
#
# Fill in your board details below.
# This file is gitignored — it will not be committed.
#
# See Decision 0027 for the full schema.

devices:
  - id: sample-circuitpython-board
    description: Example CircuitPython board entry for local device validation.
    runtime: circuitpython
    connection_type: serial
    address: /dev/cu.usbmodemEXAMPLE
    board_type: esp32s3
    serial_baudrate: 115200
    setup_command: null
    # Path to the CIRCUITPY USB drive mount point on the host.
    # Used for flash deploy mode (--deploy-mode flash).
    # Auto-detected if omitted; set explicitly with multiple boards.
    # circuitpy_drive_path: /Volumes/CIRCUITPY

  - id: sample-micropython-board
    description: Example MicroPython board entry for local device validation.
    runtime: micropython
    connection_type: serial
    address: /dev/cu.usbserial-EXAMPLE
    board_type: esp32s3
    serial_baudrate: 115200
    # Transport mode: "mount" (default, no flash wear) or "copy" (write to flash).
    transport_mode: mount
    setup_command: null
"""

_DEVICE_CONFIG_CONTENT = """\
# Shared test environment configuration.
#
# Fill in your values below.
# This file is gitignored — it will not be committed.
#
# Tests access these values via the injected `device_config` dict.
# See Decision 0027 for the full configuration schema.

wifi:
  ssid: "YourNetworkName"
  password: "YourNetworkPassword"

# Optional: MQTT broker for libraries that need messaging tests.
# mqtt:
#   broker: "192.168.1.100"
#   port: 1883
#   username: ""
#   password: ""

# Optional: NTP server for time-sync tests.
# ntp:
#   server: "pool.ntp.org"
"""

#: Files to generate: (relative path, content).
_CONFIGS: list[tuple[str, str]] = [
    ("devices.yml", _DEVICES_CONTENT),
    ("device-config.yml", _DEVICE_CONFIG_CONTENT),
]


def generate_config_files() -> int:
    """Write starter config files that do not yet exist.

    Returns 0 always (missing configs are not errors).
    """
    for relative_path, content in _CONFIGS:
        target = ROOT / relative_path
        if target.exists():
            print(f"  {relative_path} already exists — skipped")
        else:
            target.write_text(content)
            print(f"  Created {relative_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
