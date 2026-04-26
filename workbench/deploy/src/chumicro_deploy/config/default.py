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


def load_raw_entries(
    path: Path | str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a ``devices.yml`` into raw entries + defaults dict.

    The schema-shape primitive that ``chumicro-deploy`` owns: read
    the YAML, return the ``devices:`` list and the ``defaults:``
    mapping verbatim — no field validation, no Device construction,
    no normalisation.  Consumers with richer schemas (the chumicro
    mono-repo's IDE-test orchestration, future project-workspace
    template loaders) call this and layer their own validation on
    top, so the YAML shape lives in one place.

    Args:
        path: Filesystem path to the YAML file.

    Returns:
        Tuple of ``(entries, defaults)``.  *entries* is the
        ``devices:`` list verbatim (empty list when the key is
        missing).  *defaults* is the ``defaults:`` mapping verbatim
        (empty dict when missing).

    Raises:
        FileNotFoundError: The YAML file does not exist.
        ValueError: The YAML root is not a mapping, or
            ``defaults:`` / ``devices:`` are present but the wrong
            type.
    """
    import yaml

    yaml_path = Path(path)
    if not yaml_path.is_file():
        raise FileNotFoundError(f"devices.yml not found: {yaml_path!s}")

    with yaml_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}

    if not isinstance(document, dict):
        raise ValueError(
            f"Expected a YAML mapping in {yaml_path!s}, "
            f"got {type(document).__name__}"
        )

    raw_defaults = document.get("defaults") or {}
    if not isinstance(raw_defaults, dict):
        raise ValueError(
            f"defaults: section in {yaml_path!s} must be a mapping, "
            f"got {type(raw_defaults).__name__}"
        )

    raw_devices = document.get("devices")
    if raw_devices is None:
        entries: list[dict[str, Any]] = []
    elif isinstance(raw_devices, list):
        entries = raw_devices
    else:
        raise ValueError(
            f"devices: section in {yaml_path!s} must be a list, "
            f"got {type(raw_devices).__name__}"
        )

    return entries, raw_defaults


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
    runtime: str | None = None,
) -> Device:
    """Load one device from a ``devices.yml`` file.

    Resolution precedence:

    1. *device_id* — wins outright.
    2. *runtime* — picks ``defaults.<runtime>`` when *device_id* is
       ``None``.  Lets a caller that owns one runtime (e.g.
       ``chumicro-repl`` opening one session) disambiguate a
       ``defaults:`` block that has both runtimes set without
       requiring the user to memorize the device id.
    3. Single-default fallback — when both *device_id* and *runtime*
       are ``None``, exactly one runtime default in the file picks
       itself; otherwise raises.

    *device_id* and *runtime* are mutually exclusive: passing both
    raises so the caller cannot accidentally override a specific id
    with a runtime hint.

    Args:
        path: Filesystem path to the YAML file.
        device_id: Which entry to return.
        runtime: One of ``"circuitpython"`` or ``"micropython"``.

    Returns:
        A :class:`Device` corresponding to the selected entry.

    Raises:
        FileNotFoundError: The YAML file does not exist.
        ValueError: The file has no matching device, the
            ``device_id`` is not among the entries, or
            ``runtime`` is not one of the supported names.
    """
    if device_id is not None and runtime is not None:
        raise ValueError(
            "load_devices_yml: device_id and runtime are mutually "
            "exclusive — pass one or neither, not both."
        )

    yaml_path = Path(path)
    entries, defaults = load_raw_entries(yaml_path)
    default_deploy_mode = defaults.get("deploy_mode")
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
    elif runtime is not None:
        if runtime not in ("circuitpython", "micropython"):
            raise ValueError(
                f"Unsupported runtime {runtime!r} — expected "
                f"'circuitpython' or 'micropython'."
            )
        runtime_default = defaults.get(runtime)
        if not runtime_default:
            raise ValueError(
                f"No defaults.{runtime} entry in {yaml_path!s}.  "
                f"Pass device_id explicitly or set defaults.{runtime}."
            )
        if runtime_default not in entries_by_id:
            raise ValueError(
                f"defaults.{runtime}={runtime_default!r} not in devices "
                f"list of {yaml_path!s}."
            )
        chosen = entries_by_id[runtime_default]
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
                f"Pass device_id or runtime explicitly."
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
