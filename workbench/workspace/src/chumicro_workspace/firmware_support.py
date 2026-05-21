"""Firmware-version floor check for the workspace tool.

A board that's reachable over serial REPL can still be running
firmware *below* the workspace tool's tested matrix.  This module
owns the floor constants, parses the dotted version string the
probe returns, and classifies a
:class:`chumicro_deploy.DeviceImplementation` against the floor.

The ``add-device`` command prints a warning at registration when
the floor isn't met; other commands needing the same check route
through :func:`check_firmware_supported` + :func:`explain` so the
policy lives in one place.

Checks are warn-only; callers proceed regardless.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_deploy import DeviceImplementation


MIN_MICROPYTHON_VERSION: tuple[int, ...] = (1, 27, 0)
"""Minimum MicroPython version the workspace tool tests against."""

MIN_CIRCUITPYTHON_VERSION: tuple[int, ...] = (10, 1, 0)
"""Minimum CircuitPython version the workspace tool tests against."""


_RUNTIME_FLOORS: dict[str, tuple[int, ...]] = {
    "micropython": MIN_MICROPYTHON_VERSION,
    "circuitpython": MIN_CIRCUITPYTHON_VERSION,
}


class FirmwareSupportStatus(StrEnum):
    """Result of checking a probed runtime + version against the floor."""

    SUPPORTED = "supported"
    """Probed runtime + version meet the floor."""

    OLD = "old"
    """Probed runtime matches CP/MP, version below the floor."""

    UNKNOWN = "unknown"
    """Probed runtime name isn't ``circuitpython`` / ``micropython``."""

    UNPARSEABLE = "unparseable"
    """Probed ``version`` string doesn't parse as dotted ints."""


@dataclass(frozen=True)
class FirmwareSupportResult:
    """Classification result returned by :func:`check_firmware_supported`.

    Carries the status plus the parsed running version and floor so
    callers can format their own messages without re-doing the parse.

    Attributes:
        status: The classification.
        running_version: Parsed dotted version of the firmware on
            the board, or ``None`` if the probe ``version`` string
            didn't parse.
        floor: The floor for this runtime (matched lookup), or
            ``None`` when the runtime name isn't recognized.
        runtime_name: The probed implementation name, lowered.
    """

    status: FirmwareSupportStatus
    running_version: tuple[int, ...] | None
    floor: tuple[int, ...] | None
    runtime_name: str


def parse_version_tuple(version: str) -> tuple[int, ...] | None:
    """Parse a dotted version string into an int tuple.

    Takes the leading run of int-parseable dotted components and
    returns them as a tuple:

    * ``"10.1.4"`` → ``(10, 1, 4)``
    * ``"1.26.0"`` → ``(1, 26, 0)``
    * ``"10.2.0."`` → ``(10, 2, 0)`` — trailing dot from CP's
      ``(10, 2, 0, '')`` 4-tuple shape on RC builds
    * ``"10.2.0.rc.0"`` → ``(10, 2, 0)`` — non-int suffix stops parsing
    * ``"10.1.0-rc1"`` / ``"1.27.0-dev"`` → ``(10, 1, 0)`` / ``(1, 27, 0)``
      — release-suffix stripped before splitting
    * ``""`` / ``"abc"`` / no leading ints → ``None``

    Returns ``None`` for empty input, no leading int component, or
    any other parse failure — callers treat ``None`` as
    :attr:`FirmwareSupportStatus.UNPARSEABLE`.

    Args:
        version: Dotted version string from
            ``DeviceImplementation.version``.
    """
    if not version:
        return None
    head = version.split("-", 1)[0].split("+", 1)[0]
    result: list[int] = []
    for part in head.split("."):
        try:
            result.append(int(part))
        except ValueError:
            break
    # Require major.minor minimum so single-int parses don't silently
    # sort below the floor.
    if len(result) < 2:
        return None
    return tuple(result)


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
            f"an unrecognized version string).  "
            "Libraries may still work but the floor check could not run.",
        ]

    # UNKNOWN
    return [
        f"Runtime {result.runtime_name!r} is outside the workspace tool's "
        "tested matrix (currently MicroPython + CircuitPython).  "
        "Libraries may not be compatible.",
    ]
