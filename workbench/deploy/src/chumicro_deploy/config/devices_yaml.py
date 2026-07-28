"""Three-zone ``devices.yml`` reader/writer.

Every field in a ``devices.yml`` device entry falls in one of three
zones:

* **user-owned**: workspace-identity stuff the user wrote by hand
  (``id``, ``description``, ``deploy_mode`` preference,
  ``serial_baudrate``).  Never overwritten without ``--force``.
* **hardware-once**: written on first probe, then frozen in place
  to avoid clobbering on every routine probe (``hardware.uid``,
  ``hardware.machine``, ``hardware.board_id``,
  ``hardware.firmware_source``).  Reprobing a different value raises
  :class:`HardwareOverwriteError` unless the caller passes
  ``force=True`` (``add-device --force``).
* **probed-always**: fully tool-owned, refreshed every probe
  (``address``, ``firmware_version``).  Silent overwrites, because
  these *should* drift across deploys.

The writer preserves user comments and field ordering on round-trip
via :mod:`ruamel.yaml`.  PyYAML can't do this, because it discards
comments and sorts keys alphabetically by default, so the runtime
cost of the extra dep buys a no-clobber-of-user-edits property.

The empty-registry text for a fresh workspace ships in
``_payloads/devices.yml.template`` next to this module, available via
:func:`read_devices_yml_template`.  Schema and default content live
together so changes stay co-located.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

#: Path to the ``devices.yml`` template inside the ``chumicro_deploy``
#: package.  Resolved at import time so reads stay simple, and the
#: wheel ships the same path.
_DEVICES_YML_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "_payloads"
    / "devices.yml.template"
)


def read_devices_yml_template() -> str:
    """Return the empty-registry ``devices.yml`` text.

    Three-zone-headed shape with ``defaults.{micropython,
    circuitpython}: null`` (filled when devices are registered),
    ``deploy_mode: flash``, ``ide_runtime: micropython``, and
    ``devices: []``.  Single source of truth for the file's empty
    shape.
    """
    return _DEVICES_YML_TEMPLATE_PATH.read_text(encoding="utf-8")

#: Field classification; see module docstring.  Top-level entry keys
#: only.  The nested ``hardware:`` block is classified separately by
#: :data:`HARDWARE_BLOCK_ZONES` since each leaf has its own zone.
USER_OWNED_FIELDS: frozenset[str] = frozenset({
    "id",
    "description",
    "deploy_mode",
    "serial_baudrate",
})

#: Fields that are tool-owned and refreshed silently on each probe.
PROBED_ALWAYS_FIELDS: frozenset[str] = frozenset({
    "address",
    "firmware_version",
})

#: Fields that are tool-owned but only written once, so overwriting
#: requires explicit ``force=True``.  ``runtime`` is included because
#: the runtime a board boots into doesn't change without a reflash.
HARDWARE_ONCE_FIELDS: frozenset[str] = frozenset({
    "runtime",
})

#: Per-leaf zone classification for the nested ``hardware:`` block.
#: Every key here is hardware-once.  No probed-always or user-owned
#: keys live under ``hardware:``.
HARDWARE_BLOCK_ZONES: dict[str, str] = {
    "uid": "hardware-once",
    "machine": "hardware-once",
    "board_id": "hardware-once",
    "firmware_source": "hardware-once",
}

#: Every top-level entry key the writer knows about.  Reader and
#: writer share this set so adding a field in one place keeps both
#: in sync.  ``"hardware"`` is the nested block; its leaves are
#: classified by :data:`HARDWARE_BLOCK_ZONES`.
ALL_TOP_LEVEL_ENTRY_FIELDS: frozenset[str] = (
    USER_OWNED_FIELDS
    | PROBED_ALWAYS_FIELDS
    | HARDWARE_ONCE_FIELDS
    | frozenset({"hardware"})
)


class DevicesYamlError(ValueError):
    """Raised on malformed devices.yml structure."""


class DeviceNotFoundError(KeyError):
    """Raised when a referenced device id isn't in the file."""


class DeviceAlreadyExistsError(ValueError):
    """Raised when adding a device with an id that already exists."""


class HardwareOverwriteError(RuntimeError):
    """Raised when a hardware-once field would be overwritten without ``force``.

    Carries the offending field name + old/new values so the caller
    can show the user a precise message ("uid was A1B2 but probe
    returned C3D4; did you swap boards?").
    """

    def __init__(self, field_name: str, old_value: Any, new_value: Any) -> None:
        super().__init__(
            f"hardware-once field {field_name!r} would change from "
            f"{old_value!r} to {new_value!r}; pass force=True to overwrite",
        )
        self.field_name = field_name
        self.old_value = old_value
        self.new_value = new_value


def _yaml() -> YAML:
    """Return a YAML instance configured for round-trip preservation.

    A fresh instance per call keeps the writer thread-friendly and
    avoids any cross-call state (ruamel.yaml's YAML object carries
    parser config between dumps).
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    # Match the indentation style the template ships with: 2 spaces
    # for mappings, 2 spaces for sequence items aligned with the key.
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def load_devices(path: Path) -> CommentedMap:
    """Load *path* with comments + key order preserved.

    Returns an empty :class:`CommentedMap` when *path* doesn't exist,
    the "fresh workspace, no add-device run yet" case.  Empty file
    behaves the same way.

    Raises:
        DevicesYamlError: When the top-level structure isn't a
            mapping (e.g., the user accidentally wrote a list at the
            top level).
    """
    if not path.is_file():
        return CommentedMap()
    with path.open("r", encoding="utf-8") as handle:
        loaded = _yaml().load(handle)
    if loaded is None:
        return CommentedMap()
    if not isinstance(loaded, Mapping):
        raise DevicesYamlError(
            f"{path}: top-level must be a mapping, got {type(loaded).__name__}",
        )
    return loaded  # type: ignore[return-value]


def dump_devices(data: CommentedMap, path: Path) -> None:
    """Write *data* atomically to *path*, preserving comments + order.

    Atomicity matters: a half-written devices.yml after a power loss
    or interrupted edit would force the user to recover their entries
    by hand.  Write to a sibling temp file + rename, because POSIX
    rename is atomic within a filesystem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = _yaml()
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed manually below
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        yaml.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(temp_path, path)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def _devices_list(data: CommentedMap) -> CommentedSeq:
    """Return the ``devices:`` list, creating an empty one if absent."""
    devices = data.setdefault("devices", CommentedSeq())
    if not isinstance(devices, CommentedSeq):
        # User wrote `devices: foo` instead of a list.  Surface as a
        # malformed-file error rather than silently coercing.
        raise DevicesYamlError(
            f"'devices' key must be a list, got {type(devices).__name__}",
        )
    return devices


def _defaults_block(data: CommentedMap) -> CommentedMap:
    """Return the ``defaults:`` block, creating an empty one if absent."""
    defaults = data.setdefault("defaults", CommentedMap())
    if not isinstance(defaults, Mapping):
        raise DevicesYamlError(
            f"'defaults' key must be a mapping, "
            f"got {type(defaults).__name__}",
        )
    return defaults  # type: ignore[return-value]


def find_device(data: CommentedMap, device_id: str) -> CommentedMap | None:
    """Return the entry whose ``id`` matches *device_id*, or ``None``."""
    for entry in data.get("devices") or []:
        if isinstance(entry, Mapping) and entry.get("id") == device_id:
            return entry  # type: ignore[return-value]
    return None


def list_device_ids(data: CommentedMap) -> list[str]:
    """Return every ``id`` present in *data*'s ``devices:`` list, in order."""
    result: list[str] = []
    for entry in data.get("devices") or []:
        if not isinstance(entry, Mapping):
            continue
        identifier = entry.get("id")
        if isinstance(identifier, str):
            result.append(identifier)
    return result


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def add_device(
    data: CommentedMap,
    *,
    device_id: str,
    runtime: str,
    address: str,
    hardware: Mapping[str, Any] | None = None,
    description: str | None = None,
    deploy_mode: str | None = None,
    serial_baudrate: int | None = None,
    firmware_version: str | None = None,
    set_default: bool = True,
) -> CommentedMap:
    """Append a new device entry.

    The entry is built with a deterministic key order so newly-added
    blocks read consistently in diffs: ``id`` first, then user-owned
    metadata, then probed-always (``address``), then hardware-once
    (``runtime``, ``hardware:`` block).  Every key is optional except
    *device_id*, *runtime*, and *address*.

    Args:
        data: The full ``devices.yml`` document (from :func:`load_devices`).
        device_id: User-friendly id (e.g. ``"back-porch"``).
        runtime: ``"circuitpython"`` or ``"micropython"``.
        address: Serial port path.  Treated as probed-always, so it gets
            silently refreshed by :func:`update_device_address`.
        hardware: Probed hardware info.  Each leaf is in the
            hardware-once zone, passed once at registration and
            should not change unless the board is physically swapped.
        description: Free-form user note.
        deploy_mode: ``"ram"`` or ``"flash"`` preference.
        serial_baudrate: CP-only baud override.
        firmware_version: Probed-always.  Dotted version string
            from ``sys.implementation.version``.  Captured at
            registration so future commands can read floor
            compliance without re-probing.
        set_default: When ``True`` (default) and ``defaults.<runtime>``
            is unset, also writes ``defaults.<runtime>: <device_id>``
            so the first registered board for a runtime becomes the
            implicit default.

    Returns:
        The newly-created entry (a :class:`CommentedMap`).

    Raises:
        DeviceAlreadyExistsError: An entry with that id already exists.
    """
    if find_device(data, device_id) is not None:
        raise DeviceAlreadyExistsError(
            f"device {device_id!r} already exists in devices.yml",
        )

    entry: CommentedMap = CommentedMap()
    entry["id"] = device_id
    if description is not None:
        entry["description"] = description
    if deploy_mode is not None:
        entry["deploy_mode"] = deploy_mode
    if serial_baudrate is not None:
        entry["serial_baudrate"] = serial_baudrate
    entry["address"] = address
    if firmware_version is not None:
        entry["firmware_version"] = firmware_version
    entry["runtime"] = runtime
    if hardware:
        hardware_block: CommentedMap = CommentedMap()
        for key, value in hardware.items():
            hardware_block[key] = value
        entry["hardware"] = hardware_block

    _devices_list(data).append(entry)

    if set_default:
        defaults = _defaults_block(data)
        # Treat both "absent key" and "key present with null value" as
        # "no default set yet".  The shipped template materializes
        # ``micropython:`` and ``circuitpython:`` as null values
        # (keys present), so ``runtime in defaults`` would be True
        # even before any default is set.  ``defaults.get(runtime)
        # is None`` covers both shapes.
        if defaults.get(runtime) is None:
            defaults[runtime] = device_id

    return entry


def update_device_address(
    data: CommentedMap,
    device_id: str,
    new_address: str,
) -> None:
    """Silently update a device's cached ``address`` (probed-always zone).

    Address is the "moves around" field, because macOS reassigns
    ``/dev/cu.usbmodem...`` numbers, and a board moved between ports
    on the same hub looks like a fresh device unless we cache.
    Identity follows ``hardware.uid``, not the port, and this updater
    is the silent-cache-refresh side of that contract.

    Raises:
        DeviceNotFoundError: No entry with that id.
    """
    entry = find_device(data, device_id)
    if entry is None:
        raise DeviceNotFoundError(device_id)
    entry["address"] = new_address


def update_device_firmware_version(
    data: CommentedMap,
    device_id: str,
    new_version: str,
) -> None:
    """Silently refresh a device's cached ``firmware_version`` (probed-always).

    The firmware on a board can be upgraded out of band (the user
    runs `install-firmware`, or flashes via a vendor tool), so a
    fresh probe just overwrites the cached value with no prompt.

    Raises:
        DeviceNotFoundError: No entry with that id.
    """
    entry = find_device(data, device_id)
    if entry is None:
        raise DeviceNotFoundError(device_id)
    entry["firmware_version"] = new_version


def update_device_hardware(
    data: CommentedMap,
    device_id: str,
    hardware: Mapping[str, Any],
    *,
    force: bool = False,
) -> None:
    """Update fields in the nested ``hardware:`` block (hardware-once zone).

    Each leaf is checked individually: a leaf that's currently unset
    (or absent from the entry) is written without a prompt, but a
    leaf that already has a different value raises
    :class:`HardwareOverwriteError` unless *force* is ``True``.  This
    is the "did you swap boards?" guard.  The typical case is a
    re-probe of the same board returning identical values, which
    no-ops cleanly.

    Raises:
        DeviceNotFoundError: No entry with that id.
        HardwareOverwriteError: A hardware-once leaf would change
            and *force* is ``False``.
    """
    entry = find_device(data, device_id)
    if entry is None:
        raise DeviceNotFoundError(device_id)
    hardware_block = entry.setdefault("hardware", CommentedMap())
    if not isinstance(hardware_block, Mapping):
        raise DevicesYamlError(
            f"{device_id!r}: 'hardware' must be a mapping, "
            f"got {type(hardware_block).__name__}",
        )
    for key, new_value in hardware.items():
        existing = hardware_block.get(key)
        if existing is not None and existing != new_value and not force:
            raise HardwareOverwriteError(
                field_name=f"hardware.{key}",
                old_value=existing,
                new_value=new_value,
            )
        hardware_block[key] = new_value


def rename_device(
    data: CommentedMap,
    old_id: str,
    new_id: str,
) -> None:
    """Rename a device id + update every reference to it in ``defaults:``.

    The user-owned ``defaults.<runtime>`` references and any
    third-party ``defaults.<custom>`` references that happen to match
    ``old_id`` are all updated.  Comments + key order on the entry
    itself are preserved.  The rename is a single-key mutation, not a
    delete-and-re-add.

    Raises:
        DeviceNotFoundError: No entry with *old_id*.
        DeviceAlreadyExistsError: An entry with *new_id* already exists.
    """
    entry = find_device(data, old_id)
    if entry is None:
        raise DeviceNotFoundError(old_id)
    if find_device(data, new_id) is not None:
        raise DeviceAlreadyExistsError(
            f"cannot rename {old_id!r} to {new_id!r}: already exists",
        )
    entry["id"] = new_id
    defaults = data.get("defaults") or {}
    for default_key, default_value in list(defaults.items()):
        if default_value == old_id:
            defaults[default_key] = new_id


def remove_device(data: CommentedMap, device_id: str) -> CommentedMap:
    """Delete a device entry and null any ``defaults:`` ref to it.

    The destructive counterpart to :func:`add_device`.  Drops the
    matching entry from the ``devices:`` list.  Every ``defaults.<key>``
    whose value is *device_id* is set to ``None`` (the "unset"
    sentinel the template ships) rather than left dangling, since a
    stale default would surface as a hard error on next load.
    Nulling *every* matching default, not just the active runtime's,
    is deliberate: a board whose firmware was reflashed CP↔MP must
    not keep a default pointing at the now-wrong runtime.

    Returns the removed entry (a :class:`CommentedMap`) for symmetry
    with :func:`add_device` so the same id can be re-registered.

    Raises:
        DeviceNotFoundError: No entry with that id.
    """
    devices = _devices_list(data)
    for index, entry in enumerate(devices):
        if isinstance(entry, Mapping) and entry.get("id") == device_id:
            removed: CommentedMap = devices.pop(index)
            break
    else:
        raise DeviceNotFoundError(device_id)

    defaults = data.get("defaults")
    if isinstance(defaults, Mapping):
        for default_key, default_value in list(defaults.items()):
            if default_value == device_id:
                defaults[default_key] = None
    return removed


def set_runtime_default(
    data: CommentedMap,
    runtime: str,
    device_id: str,
) -> None:
    """Set ``defaults.<runtime>`` to *device_id*.

    Raises:
        DeviceNotFoundError: *device_id* isn't an entry in the file.
    """
    if find_device(data, device_id) is None:
        raise DeviceNotFoundError(device_id)
    _defaults_block(data)[runtime] = device_id
