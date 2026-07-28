"""Default YAML config loader that ships with ``chumicro-deploy``.

Loads the ``devices.yml`` schema that ``chumicro-deploy`` defines and
owns.  Any project (its own workspace, a project-workspace template,
or a third-party consumer) can write this shape to configure its
deploy targets without depending on any upstream tooling.

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
        # description and other keys are tolerated
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
``chumicro_deploy.config_loaders`` entry-point group; see
:func:`chumicro_deploy.config.discover_config_loaders`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..device import DEFAULT_DEPLOY_MODE, Device
from ..protocol import DeployMode
from .devices_yaml import ALL_TOP_LEVEL_ENTRY_FIELDS

DEFAULT_DEVICES_FILENAME = "devices.yml"

_REQUIRED_DEVICE_FIELDS = ("id", "runtime", "address")
_VALID_RUNTIMES = ("micropython", "circuitpython")
#: Recognized ``deploy_transport`` values.  Mirrors
#: :data:`chumicro_deploy.device._VALID_DEPLOY_TRANSPORTS`.
_VALID_DEPLOY_TRANSPORTS = ("auto", "serial", "drive")
#: Derived from the :class:`DeployMode` enum so the tuple can't drift
#: from the source of truth.
_VALID_DEPLOY_MODES = tuple(mode.value for mode in DeployMode)
_VALID_IDE_RUNTIMES = ("micropython", "circuitpython", "both")

#: Fields the reader exposes as typed properties on :class:`DeviceEntry`.
#: Derived from the zone-classified spec
#: (:data:`chumicro_deploy.config.devices_yaml.ALL_TOP_LEVEL_ENTRY_FIELDS`)
#: plus the small set of deploy-only fields the writer doesn't need
#: to manage zone-wise.
#: Anything outside this set falls into :attr:`DeviceEntry.extra`.
_DEPLOY_ONLY_FIELDS: frozenset[str] = frozenset(
    {"connection_type", "supports_ram_mode", "deploy_transport"},
)
_KNOWN_KEYS: frozenset[str] = ALL_TOP_LEVEL_ENTRY_FIELDS | _DEPLOY_ONLY_FIELDS


# ---------------------------------------------------------------------------
# Validated registry shape
#
# :class:`DeviceEntry` is the devices.yml record: a description and
# any extra metadata alongside the deploy-relevant fields.
# :class:`Device`, one level below, carries only what
# ``create_transport`` needs.
# ---------------------------------------------------------------------------


class DeviceConfigError(Exception):
    """Raised when a ``devices.yml`` is missing or fails validation."""


@dataclass
class DeviceEntry:
    """A single device from a validated ``devices.yml`` registry."""

    identifier: str
    runtime: str
    address: str
    description: str = ""
    connection_type: str = "serial"
    serial_baudrate: int = 115200
    deploy_mode: str = DEFAULT_DEPLOY_MODE
    #: Board *capability*, orthogonal to the ``deploy_mode``
    #: *preference*: ``False`` only for a board that cannot run RAM
    #: mode at all.  RAM being merely *tight* (e.g. Pi Pico W's 256 KB)
    #: is a per-library concern, not this.  Absent in ``devices.yml``
    #: defaults to ``True``.
    supports_ram_mode: bool = True
    #: CircuitPython deploy-path selector.  ``"auto"`` (default) lets
    #: :func:`build_transport_for_entry` pick drive-vs-serial from
    #: whether any CIRCUITPY volume is mounted; ``"serial"`` forces the
    #: drive-less raw-REPL transport (a classic ESP32 with no native USB
    #: exposes no CIRCUITPY drive); ``"drive"`` forces the CIRCUITPY-drive
    #: transport.  Ignored for MicroPython.
    deploy_transport: str = "auto"
    extra: dict = field(default_factory=dict)


@dataclass
class DeviceDefaults:
    """Top-level defaults from the ``defaults:`` section of ``devices.yml``.

    Controls which devices are targeted from IDE play buttons, the
    default deploy mode for all devices, and which runtimes the IDE
    targets.
    """

    micropython: str | None = None
    circuitpython: str | None = None
    deploy_mode: str = DEFAULT_DEPLOY_MODE
    ide_runtime: str = "micropython"


def _resolve_devices_path(workspace_root: Path | None = None) -> Path:
    """Resolve a ``devices.yml`` path under *workspace_root*.

    Args:
        workspace_root: Directory that contains ``devices.yml``.
            Defaults to :func:`Path.cwd`.
    """
    root = workspace_root if workspace_root is not None else Path.cwd()
    return root / DEFAULT_DEVICES_FILENAME


def _parse_defaults(raw: dict) -> DeviceDefaults:
    """Validate and parse the ``defaults:`` block of ``devices.yml``."""
    deploy_mode = raw.get("deploy_mode", DEFAULT_DEPLOY_MODE)
    if deploy_mode not in _VALID_DEPLOY_MODES:
        raise DeviceConfigError(
            f"Invalid deploy_mode '{deploy_mode}' in defaults, "
            f"must be one of {_VALID_DEPLOY_MODES}"
        )
    ide_runtime = raw.get("ide_runtime", "micropython")
    if ide_runtime not in _VALID_IDE_RUNTIMES:
        raise DeviceConfigError(
            f"Invalid ide_runtime '{ide_runtime}' in defaults, "
            f"must be one of {_VALID_IDE_RUNTIMES}"
        )
    return DeviceDefaults(
        micropython=raw.get("micropython"),
        circuitpython=raw.get("circuitpython"),
        deploy_mode=deploy_mode,
        ide_runtime=ide_runtime,
    )


def _validate_device(
    raw: dict, index: int, *, global_deploy_mode: str = DEFAULT_DEPLOY_MODE,
) -> DeviceEntry:
    """Validate a single raw entry and return a :class:`DeviceEntry`."""
    missing = [
        field_name for field_name in _REQUIRED_DEVICE_FIELDS
        if field_name not in raw
    ]
    if missing:
        raise DeviceConfigError(
            f"Device entry {index}: missing required fields: "
            f"{', '.join(missing)}"
        )

    runtime = raw["runtime"]
    if runtime not in _VALID_RUNTIMES:
        raise DeviceConfigError(
            f"Device entry {index} ({raw['id']}): "
            f"invalid runtime '{runtime}', must be one of {_VALID_RUNTIMES}"
        )

    if "deploy_mode" in raw and raw["deploy_mode"] not in _VALID_DEPLOY_MODES:
        raise DeviceConfigError(
            f"Device entry {index} ({raw['id']}): "
            f"invalid deploy_mode '{raw['deploy_mode']}', "
            f"must be one of {_VALID_DEPLOY_MODES}"
        )

    if "supports_ram_mode" in raw and not isinstance(
        raw["supports_ram_mode"], bool,
    ):
        raise DeviceConfigError(
            f"Device entry {index} ({raw['id']}): "
            f"invalid supports_ram_mode {raw['supports_ram_mode']!r}, "
            f"must be true or false"
        )

    if (
        "deploy_transport" in raw
        and raw["deploy_transport"] not in _VALID_DEPLOY_TRANSPORTS
    ):
        raise DeviceConfigError(
            f"Device entry {index} ({raw['id']}): "
            f"invalid deploy_transport {raw['deploy_transport']!r}, "
            f"must be one of {_VALID_DEPLOY_TRANSPORTS}"
        )

    extra = {key: value for key, value in raw.items() if key not in _KNOWN_KEYS}

    return DeviceEntry(
        identifier=raw["id"],
        runtime=runtime,
        address=raw["address"],
        description=raw.get("description", ""),
        connection_type=raw.get("connection_type", "serial"),
        serial_baudrate=raw.get("serial_baudrate", 115200),
        deploy_mode=raw.get("deploy_mode", global_deploy_mode),
        supports_ram_mode=raw.get("supports_ram_mode", True),
        deploy_transport=raw.get("deploy_transport", "auto"),
        extra=extra,
    )


def load_device_registry(
    path: Path | None = None,
    *,
    workspace_root: Path | None = None,
) -> tuple[list[DeviceEntry], DeviceDefaults]:
    """Load and validate ``devices.yml`` into ``(entries, defaults)``.

    Each entry is a :class:`DeviceEntry` carrying the description and
    any extra keys from the YAML alongside the deploy-relevant fields.

    Args:
        path: Explicit path to ``devices.yml``.  When ``None``,
            falls back to ``workspace_root / devices.yml``.
        workspace_root: Directory that contains ``devices.yml``.
            Defaults to :func:`Path.cwd`.

    Returns:
        Tuple of ``(devices, defaults)``.

    Raises:
        DeviceConfigError: File missing, malformed, or fails validation.
    """
    resolved = path or _resolve_devices_path(workspace_root)
    try:
        entries, raw_defaults = load_raw_entries(resolved)
    except FileNotFoundError as error:
        raise DeviceConfigError(
            f"Config file not found: {resolved}\n"
            "Run 'chumicro-workspace add-device <id> --address <port>' to "
            "register a board, or hand-write a devices.yml entry."
        ) from error
    except ValueError as error:
        # ``load_raw_entries`` already wraps ruamel.yaml's parse errors
        # in ``ValueError`` so the deploy public surface doesn't leak
        # the underlying parser type.
        raise DeviceConfigError(str(error)) from error

    defaults = _parse_defaults(raw_defaults)
    return (
        [
            _validate_device(
                entry, index, global_deploy_mode=defaults.deploy_mode,
            )
            for index, entry in enumerate(entries)
        ],
        defaults,
    )


def load_devices(
    path: Path | None = None,
    *,
    workspace_root: Path | None = None,
) -> list[DeviceEntry]:
    """Load just the validated device list from ``devices.yml``.

    Convenience wrapper around :func:`load_device_registry`.
    """
    devices, _defaults = load_device_registry(path, workspace_root=workspace_root)
    return devices


def resolve_ide_devices(
    devices: list[DeviceEntry],
    defaults: DeviceDefaults,
) -> list[DeviceEntry]:
    """Return the devices an IDE play button should target.

    For each runtime selected by ``defaults.ide_runtime``, picks the
    device whose ID matches ``defaults.<runtime>``, or the first
    device of that runtime when no default is set.
    """
    runtimes_to_target: list[str] = []
    if defaults.ide_runtime in ("micropython", "both"):
        runtimes_to_target.append("micropython")
    if defaults.ide_runtime in ("circuitpython", "both"):
        runtimes_to_target.append("circuitpython")

    result: list[DeviceEntry] = []
    for runtime in runtimes_to_target:
        target_id = getattr(defaults, runtime, None)
        if target_id:
            for device in devices:
                if device.identifier == target_id:
                    result.append(device)
                    break
        else:
            for device in devices:
                if device.runtime == runtime:
                    result.append(device)
                    break
    return result


def load_raw_entries(
    path: Path | str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a ``devices.yml`` into raw entries + defaults dict.

    Reads the YAML and returns the ``devices:`` list and the
    ``defaults:`` mapping verbatim: no field validation, no
    :class:`Device` construction, no normalization.  Richer schemas
    layer their own validation on top of this, so the on-disk shape
    is defined in one place.

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
    from ruamel.yaml import YAML, YAMLError  # noqa: PLC0415

    yaml_path = Path(path)
    if not yaml_path.is_file():
        raise FileNotFoundError(f"devices.yml not found: {yaml_path!s}")

    yaml_loader = YAML(typ="safe")
    try:
        with yaml_path.open("r", encoding="utf-8") as handle:
            document = yaml_loader.load(handle) or {}
    except YAMLError as error:
        raise ValueError(str(error)) from error

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


def _normalize_device_entry(
    entry: dict[str, Any],
    *,
    default_deploy_mode: str | None,
) -> dict[str, Any]:
    """Translate a raw YAML entry into :meth:`Device.from_dict` keys.

    Schema vs. :class:`Device` differences:

    - Schema uses ``runtime`` (``"micropython"`` / ``"circuitpython"``).
      :class:`Device` uses ``transport``.
    - Schema uses ``serial_baudrate``.  :class:`Device` uses
      ``baudrate``.
    - ``deploy_mode`` falls back to ``defaults.deploy_mode`` when
      absent from the entry.  The fallback is applied here so the
      :class:`Device` is complete.
    """
    normalized: dict[str, Any] = {
        "transport": entry["runtime"],
        "address": entry["address"],
    }
    if "serial_baudrate" in entry:
        normalized["baudrate"] = entry["serial_baudrate"]
    if entry.get("deploy_transport"):
        normalized["deploy_transport"] = entry["deploy_transport"]
    entry_deploy_mode = entry.get("deploy_mode")
    if entry_deploy_mode:
        normalized["deploy_mode"] = entry_deploy_mode
    elif default_deploy_mode:
        normalized["deploy_mode"] = default_deploy_mode
    return normalized


def _resolve_raw_entry(
    yaml_path: Path,
    *,
    device_id: str | None,
    runtime: str | None,
) -> tuple[dict[str, Any], str | None]:
    """Resolve one raw ``devices.yml`` entry by the precedence rules.

    Resolution order: ``device_id → defaults.<runtime> → single-default``.

    Returns ``(chosen_entry, default_deploy_mode)``.  Raises as
    documented on :func:`load_devices_yml`.
    """
    if device_id is not None and runtime is not None:
        raise ValueError(
            "load_devices_yml: device_id and runtime are mutually "
            "exclusive: pass one or neither, not both."
        )

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
                f"Unsupported runtime {runtime!r}: expected "
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

    return chosen, default_deploy_mode


def load_devices_yml(
    path: Path | str,
    *,
    device_id: str | None = None,
    runtime: str | None = None,
) -> Device:
    """Load one device from a ``devices.yml`` file.

    Resolution precedence:

    1. *device_id* wins outright.
    2. *runtime* picks ``defaults.<runtime>`` when *device_id* is
       ``None``, so a single-runtime caller disambiguates a
       two-runtime ``defaults:`` block without naming the device id.
    3. Single-default fallback: when both *device_id* and *runtime*
       are ``None``, exactly one runtime default in the file picks
       itself, otherwise raises.

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
    chosen, default_deploy_mode = _resolve_raw_entry(
        Path(path), device_id=device_id, runtime=runtime,
    )
    normalized = _normalize_device_entry(
        chosen, default_deploy_mode=default_deploy_mode,
    )
    return Device.from_dict(normalized)


def load_devices_yml_raw(
    path: Path | str,
    *,
    device_id: str | None = None,
    runtime: str | None = None,
) -> dict[str, Any]:
    """Resolve one device and return its raw ``devices.yml`` entry.

    Identical resolution to :func:`load_devices_yml` (same precedence,
    same errors) but returns the unmapped entry dict, including
    ``hardware`` and other keys the :class:`Device` dataclass drops.
    Use when fields off the schema are needed alongside the transport
    facade (firmware-URL derivation reads ``hardware.firmware_source``).
    """
    chosen, _ = _resolve_raw_entry(
        Path(path), device_id=device_id, runtime=runtime,
    )
    return chosen
