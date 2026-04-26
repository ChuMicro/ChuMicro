"""Firmware-version floor check for the workspace tool.

A board that's reachable over serial REPL can still be running
firmware *below* the workspace tool's tested matrix — see
[Decision 0039](../../../plans/decisions/0039-firmware-version-floor.md)
for the rationale.  This module owns the floor constants, parses
the dotted version string the probe returns, and classifies a
:class:`chumicro_deploy.DeviceImplementation` against the floor.

The classification is consumed by ``_cmd_add_device`` to print a
warning at registration time when the floor isn't met.  It's also
consumed by future commands (the bootstrap wizard) — both go
through the same :func:`check_firmware_supported` + :func:`explain`
pair so the policy stays in one place.

Strictness is warn-not-block per Decision 0039.  ``add-device``
proceeds on every status; the warning is informational.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_deploy import DeviceImplementation


MIN_MICROPYTHON_VERSION: tuple[int, ...] = (1, 27, 0)
"""Minimum MicroPython version the workspace tool tests against.

Bumping this is a non-breaking workspace-tool change — the floor
moves forward as the test matrix moves forward (Decision 0039)."""

MIN_CIRCUITPYTHON_VERSION: tuple[int, ...] = (10, 1, 0)
"""Minimum CircuitPython version the workspace tool tests against."""


_RUNTIME_FLOORS: dict[str, tuple[int, ...]] = {
    "micropython": MIN_MICROPYTHON_VERSION,
    "circuitpython": MIN_CIRCUITPYTHON_VERSION,
}


class FirmwareSupportStatus(StrEnum):
    """Result of checking a probed runtime + version against the floor."""

    SUPPORTED = "supported"
    """Probed runtime + version meet the floor — silent."""

    OLD = "old"
    """Probed runtime matches CP/MP, version below the floor — warn."""

    UNKNOWN = "unknown"
    """Probed runtime name isn't ``circuitpython`` / ``micropython``."""

    UNPARSEABLE = "unparseable"
    """Probed ``version`` string doesn't parse as dotted ints."""


@dataclass(frozen=True)
class FirmwareSupportResult:
    """Status + the parsed floor + the parsed running version.

    Returned by :func:`check_firmware_supported` so callers can
    format their own messages without re-doing the parse.

    Attributes:
        status: The classification.
        running_version: Parsed dotted version of the firmware on
            the board, or ``None`` if the probe ``version`` string
            didn't parse.
        floor: The floor for this runtime (matched lookup), or
            ``None`` when the runtime name isn't recognised.
        runtime_name: The probed implementation name, lowered.
    """

    status: FirmwareSupportStatus
    running_version: tuple[int, ...] | None
    floor: tuple[int, ...] | None
    runtime_name: str


def parse_version_tuple(version: str) -> tuple[int, ...] | None:
    """Parse a dotted version string into an int tuple.

    ``"10.1.4"`` → ``(10, 1, 4)``.  ``"1.26.0"`` → ``(1, 26, 0)``.
    Returns ``None`` for empty input, non-numeric components, or
    any other parse failure — callers treat ``None`` as
    :attr:`FirmwareSupportStatus.UNPARSEABLE`.

    Trailing release suffixes (``"1.27.0-dev"``, ``"10.1.0-rc1"``)
    aren't expected from ``sys.implementation.version`` (which is
    always a dotted-int tuple) but are stripped defensively to keep
    the parse honest if a future runtime adds them.

    Args:
        version: Dotted version string from
            ``DeviceImplementation.version``.
    """
    if not version:
        return None
    head = version.split("-", 1)[0].split("+", 1)[0]
    parts = head.split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def check_firmware_supported(
    implementation: "DeviceImplementation",
) -> FirmwareSupportResult:
    """Classify a probed implementation against the floor.

    Args:
        implementation: The probe's :class:`DeviceImplementation`
            with ``name`` (lowercase runtime name) and ``version``
            (dotted string from ``sys.implementation.version``).

    Returns:
        A :class:`FirmwareSupportResult` capturing the status, the
        parsed running version, the per-runtime floor, and the
        probed runtime name.
    """
    runtime_name = implementation.name.strip().lower()
    parsed_version = parse_version_tuple(implementation.version)
    floor = _RUNTIME_FLOORS.get(runtime_name)

    if floor is None:
        return FirmwareSupportResult(
            status=FirmwareSupportStatus.UNKNOWN,
            running_version=parsed_version,
            floor=None,
            runtime_name=runtime_name,
        )
    if parsed_version is None:
        return FirmwareSupportResult(
            status=FirmwareSupportStatus.UNPARSEABLE,
            running_version=None,
            floor=floor,
            runtime_name=runtime_name,
        )
    if parsed_version < floor:
        return FirmwareSupportResult(
            status=FirmwareSupportStatus.OLD,
            running_version=parsed_version,
            floor=floor,
            runtime_name=runtime_name,
        )
    return FirmwareSupportResult(
        status=FirmwareSupportStatus.SUPPORTED,
        running_version=parsed_version,
        floor=floor,
        runtime_name=runtime_name,
    )


def _format_version(version_tuple: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version_tuple)


def explain(result: FirmwareSupportResult) -> list[str]:
    """Return human-readable lines describing the result.

    Empty list for :attr:`FirmwareSupportStatus.SUPPORTED` — silent
    on the happy path.  Non-empty for OLD / UNKNOWN / UNPARSEABLE,
    each ending with the install-firmware pointer when applicable.

    Args:
        result: The :func:`check_firmware_supported` output.
    """
    if result.status is FirmwareSupportStatus.SUPPORTED:
        return []

    if result.status is FirmwareSupportStatus.OLD:
        running = (
            _format_version(result.running_version)
            if result.running_version is not None
            else "unknown"
        )
        floor = (
            _format_version(result.floor)
            if result.floor is not None
            else "unknown"
        )
        return [
            f"Firmware below the supported floor: "
            f"{result.runtime_name} {running} (need >= {floor}).",
            "  Library compatibility on older firmware is not tested. "
            "To upgrade in place:",
            "  `python run.py install-firmware --device <id>`",
        ]

    if result.status is FirmwareSupportStatus.UNPARSEABLE:
        return [
            f"Could not parse the firmware version "
            f"({result.runtime_name} reported "
            f"an unrecognised version string).  "
            "Libraries may still work but the floor check could not run.",
        ]

    # UNKNOWN
    return [
        f"Runtime {result.runtime_name!r} is outside the workspace tool's "
        "tested matrix (currently MicroPython + CircuitPython).  "
        "Libraries may not be compatible.",
    ]
