"""Opt-in loader for chumicro's ``devices.yml`` shape.

chumicro's mono repo already ships a rich ``devices.yml`` schema
(see ``scripts/device_config.py`` — Decision 0027).  This module
reads the same shape into :class:`~chumicro_deploy.Device`
instances so scripts / CLIs can reuse that config file without
depending on the chumicro mono repo's ``scripts/`` package.

The file shape (stable subset that matters for deploy):

.. code-block:: yaml

    defaults:
      micropython: <id of default MP device>
      circuitpython: <id of default CP device>
      deploy_mode: ram
    devices:
      - id: my-pico-w-mp
        runtime: micropython          # → Device.transport
        address: /dev/cu.usbmodem213101
        serial_baudrate: 115200
        deploy_mode: ram              # optional; falls back to defaults.deploy_mode
        circuitpy_drive_path: /Volumes/CIRCUITPY  # optional; CP flash only
        # description, setup_command, and other keys are tolerated
        # but ignored by this loader.

Importing this module pulls in PyYAML (already a dependency of
:mod:`chumicro-deploy` via the workbench / device testing tooling),
so the import cost is paid only when devices.yml is actually used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..device import Device


def _normalise_device_entry(
    entry: dict[str, Any],
    *,
    default_deploy_mode: str | None,
) -> dict[str, Any]:
    """Translate chumicro's device-entry shape into :meth:`Device.from_dict` keys.

    Differences between the two shapes:

    - chumicro's entry uses ``runtime`` (``"micropython"`` /
      ``"circuitpython"``); ``Device`` uses ``transport``.
    - chumicro's entry uses ``serial_baudrate``; ``Device`` uses
      ``baudrate``.
    - ``deploy_mode`` falls back to ``defaults.deploy_mode`` in
      chumicro's config; the fallback is applied here so the
      ``Device`` is complete.
    """
    normalised: dict[str, Any] = {
        "transport": entry["runtime"],
        "address": entry["address"],
    }
    if "serial_baudrate" in entry:
        normalised["baudrate"] = entry["serial_baudrate"]
    entry_deploy_mode = entry.get("deploy_mode")
    if entry_deploy_mode:
        normalised["deploy_mode"] = entry_deploy_mode
    elif default_deploy_mode:
        normalised["deploy_mode"] = default_deploy_mode
    if entry.get("circuitpy_drive_path"):
        normalised["circuitpy_drive_path"] = entry["circuitpy_drive_path"]
    return normalised


def load_devices_yml(
    path: Path | str,
    *,
    device_id: str | None = None,
) -> Device:
    """Load one device from a chumicro-shape ``devices.yml`` file.

    Args:
        path: Filesystem path to the YAML file.
        device_id: Which entry to return.  When ``None``, uses the
            ``defaults.micropython`` or ``defaults.circuitpython``
            pick — if exactly one runtime has a default configured,
            that one wins; otherwise raises so the caller picks
            explicitly.

    Returns:
        A :class:`Device` corresponding to the selected entry.

    Raises:
        FileNotFoundError: The YAML file does not exist.
        ValueError: The file has no matching device, or the
            ``device_id`` is not among the entries.
    """
    import yaml

    yaml_path = Path(path)
    if not yaml_path.is_file():
        raise FileNotFoundError(f"devices.yml not found: {yaml_path!s}")

    with yaml_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}

    defaults = document.get("defaults") or {}
    default_deploy_mode = defaults.get("deploy_mode")
    entries = document.get("devices") or []
    if not entries:
        raise ValueError(f"No devices configured in {yaml_path!s}")

    entries_by_id: dict[str, dict[str, Any]] = {}
    for raw_entry in entries:
        entry_id = raw_entry.get("id")
        if not entry_id:
            continue
        entries_by_id[entry_id] = raw_entry

    if device_id is not None:
        if device_id not in entries_by_id:
            available = sorted(entries_by_id.keys())
            raise ValueError(
                f"Device {device_id!r} not found in {yaml_path!s}.  "
                f"Available: {available!r}"
            )
        chosen = entries_by_id[device_id]
    else:
        candidates = [
            defaults.get("micropython"),
            defaults.get("circuitpython"),
        ]
        picks = [candidate for candidate in candidates if candidate]
        if len(picks) != 1:
            raise ValueError(
                f"Multiple or no default devices in {yaml_path!s} "
                f"(micropython={defaults.get('micropython')!r}, "
                f"circuitpython={defaults.get('circuitpython')!r}).  "
                f"Pass device_id explicitly."
            )
        fallback_id = picks[0]
        if fallback_id not in entries_by_id:
            raise ValueError(
                f"Default device {fallback_id!r} not in devices list of "
                f"{yaml_path!s}."
            )
        chosen = entries_by_id[fallback_id]

    normalised = _normalise_device_entry(
        chosen, default_deploy_mode=default_deploy_mode,
    )
    return Device.from_dict(normalised)
