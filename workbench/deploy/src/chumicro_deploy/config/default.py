"""Default YAML config loader that ships with ``chumicro-deploy``.

This is the built-in loader for the ``devices.yml`` schema that
``chumicro-deploy`` defines and owns.  Any project — the `chumicro`
mono repo, a project-workspace template, or a third-party consumer —
can write this shape to configure its deploy targets without
depending on any upstream tooling.

The schema (stable subset that the loader accepts):

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

Required fields per device: ``id``, ``runtime``, ``address``.
Everything else is optional.  Extra keys are silently ignored so
consumers that carry additional metadata (test-orchestration hints,
setup commands, descriptions) can share the same file.

Importing this module pulls in PyYAML (already a dependency of
:mod:`chumicro-deploy`), so the import cost is paid only when
``devices.yml`` is actually used.

Third parties that need a different shape (JSON, TOML, a custom
YAML layout) can register their own loader via the
``chumicro_deploy.config_loaders`` entry-point group — see
:func:`chumicro_deploy.config.discover_config_loaders`.
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
    """Translate a raw YAML entry into :meth:`Device.from_dict` keys.

    Schema vs. :class:`Device` differences:

    - Schema uses ``runtime`` (``"micropython"`` / ``"circuitpython"``);
      :class:`Device` uses ``transport``.
    - Schema uses ``serial_baudrate``; :class:`Device` uses
      ``baudrate``.
    - ``deploy_mode`` falls back to ``defaults.deploy_mode`` when
      absent from the entry; the fallback is applied here so the
      :class:`Device` is complete.
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
    """Load one device from a ``devices.yml`` file.

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
