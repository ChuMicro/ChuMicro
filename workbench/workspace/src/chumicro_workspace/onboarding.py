"""Board-state detection + onboarding diagnostics.

Boards arrive in one of four states from the workspace's point of view:

* :attr:`BoardState.REPL_REACHABLE`: serial port opens, probe returns
  a runtime and version.  This is the "I can run code on it" state.
  ``add-device`` registers cleanly without flashing first.
* :attr:`BoardState.UF2_BOOTLOADER`: a UF2 drive (a directory with
  ``INFO_UF2.TXT`` at its root) is mounted.  Pi Pico / Pi Pico W /
  most SAMD51 / nRF52840 boards land here on a fresh power-up with
  the BOOTSEL button held.  The right next step is
  ``install-firmware --method uf2``.
* :attr:`BoardState.NO_PROBE_RESPONSE`: serial opens but the probe
  doesn't return.  Most often an ESP32 family chip in ROM bootloader
  with no Python firmware installed yet.  The right next step is
  ``install-firmware --method esptool``, with ``--erase`` for a
  fresh chip.
* :attr:`BoardState.SERIAL_UNREACHABLE`: the serial port can't be
  opened.  Cable not plugged, wrong port path, permissions issue.
  The right next step is ``discover`` or replug.

Diagnosis uses ``chumicro_deploy``'s probe and a UF2 mount scan.
Neither writes to the board.  The returned ``next_steps`` are
English strings the caller prints; nothing in this module shells
out, flashes firmware, or reboots a device.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type-only
    from chumicro_deploy import Device, DeviceInfo


#: Default order for runtime inference probes.  MicroPython's raw
#: REPL is the most universal serial control sequence.  CircuitPython
#: also speaks raw REPL (Ctrl-A) so an MP transport on a CP board
#: typically still completes the probe.  Ordering exists in case
#: timing differs on edge-case ports; both candidates are tried.
DEFAULT_RUNTIME_INFERENCE_ORDER: tuple[str, ...] = (
    "micropython",
    "circuitpython",
)


class BoardState(StrEnum):
    """States distinguished by :func:`detect_board_state`."""

    REPL_REACHABLE = "repl_reachable"
    UF2_BOOTLOADER = "uf2_bootloader"
    NO_PROBE_RESPONSE = "no_probe_response"
    SERIAL_UNREACHABLE = "serial_unreachable"


#: Where a UF2 bootloader drive typically mounts per platform.
_UF2_MOUNT_SEARCH_PATHS: dict[str, list[Path]] = {
    "darwin": [Path("/Volumes")],
    "linux": [
        Path("/media") / Path.home().name,
        Path("/run/media") / Path.home().name,
        Path("/mnt"),
    ],
    "win32": [Path(f"{drive_letter}:/") for drive_letter in "DEFGHIJKLMNOPQRSTUVWXYZ"],
}


@dataclass(frozen=True)
class OnboardingDiagnosis:
    """Result of :func:`detect_board_state`: the diagnosis and next steps.

    Attributes:
        state: Which :class:`BoardState` the board is in.
        uf2_drive: When :attr:`state` is
            :attr:`~BoardState.UF2_BOOTLOADER`, the path of the
            mounted drive.  ``None`` otherwise.
        probe_implementation_name: When :attr:`state` is
            :attr:`~BoardState.REPL_REACHABLE`, the firmware identity
            from the probe (``"circuitpython"`` / ``"micropython"``).
            ``None`` otherwise.
        probe_error: When the probe failed, the str form of the
            exception that ended it.  Useful for showing the user
            why their board isn't responsive (port-busy, timeout,
            permission-denied).  Empty string when the probe wasn't
            attempted (e.g. UF2 drive found before probing).
        next_steps: Human-readable suggestions the CLI prints to
            stderr.  Free-form English, not machine-parseable.
    """

    state: BoardState
    uf2_drive: Path | None = None
    probe_implementation_name: str | None = None
    probe_error: str = ""
    next_steps: list[str] = field(default_factory=list)


def find_uf2_drive(search_paths: list[Path] | None = None) -> Path | None:
    """Scan platform-default mount paths for a directory with ``INFO_UF2.TXT``.

    INFO_UF2.TXT is the marker the UF2 bootloader writes to its
    mass-storage drive on every mount, regardless of board family or
    drive label (RPI-RP2, RPI-RP3, SAMD51, CIRCUITPYUF2, etc.).
    Scanning for it is the only board-agnostic detection method.

    Args:
        search_paths: Override platform-default mount roots.  Tests
            inject a temp-dir containing a fixture UF2 drive layout.

    Returns:
        The first matching drive directory, or ``None`` when no UF2
        drive is currently mounted.
    """
    candidates = (
        list(search_paths)
        if search_paths is not None
        else list(_UF2_MOUNT_SEARCH_PATHS.get(sys.platform, []))
    )
    for search_root in candidates:
        if not search_root.is_dir():
            continue
        for child in sorted(search_root.iterdir()):
            if not child.is_dir():
                continue
            if (child / "INFO_UF2.TXT").is_file():
                return child
    return None


def _next_steps_for(state: BoardState, *, uf2_drive: Path | None = None) -> list[str]:
    """Return the recommendation block for *state*."""
    if state is BoardState.REPL_REACHABLE:
        return [
            "Board is in REPL; register it with:",
            "  `python3 run.py add-device <id> --address <port> --runtime <runtime>`",
        ]
    if state is BoardState.UF2_BOOTLOADER:
        drive_hint = (
            f"  UF2 drive mounted at {uf2_drive}." if uf2_drive is not None else ""
        )
        return [
            "Board is in UF2 bootloader; install firmware first." + drive_hint,
            "  `python3 run.py install-firmware --method uf2 "
            "--url <firmware-url> --device <id>`",
            "  Then re-run `add-device` once the board reboots into the new firmware.",
        ]
    if state is BoardState.NO_PROBE_RESPONSE:
        return [
            "Serial opens but no probe response, "
            "likely a blank ESP32 chip in ROM bootloader.",
            "  `python3 run.py install-firmware --method esptool --erase "
            "--url <firmware-url> --device <id>`",
            "  Then re-run `add-device`.",
        ]
    # SERIAL_UNREACHABLE
    return [
        "Serial port could not be opened.",
        "  `python3 run.py discover` lists every visible port; "
        "pick the one that appears when you plug the board.",
        "  Check cable + USB port + permissions "
        "(Linux: confirm membership in `dialout` / `uucp`).",
    ]


def detect_board_state(
    device: Device,
    *,
    uf2_search_paths: list[Path] | None = None,
    probe_function: Callable[[Device], DeviceInfo] | None = None,
    drive_scanner: Callable[[list[Path] | None], Path | None] | None = None,
) -> OnboardingDiagnosis:
    """Diagnose what state *device*'s board is in right now.

    Order of operations:

    1. Try the probe.  If it returns an implementation marker, the
       board is in :attr:`~BoardState.REPL_REACHABLE`.  No UF2 scan
       is needed.  A running firmware can't also be the bootloader for
       the same board, and a stray UF2 drive from a different board
       would be a false positive.
    2. On probe failure, scan for a UF2 drive.  If found, the board
       is in :attr:`~BoardState.UF2_BOOTLOADER` (or one of the user's
       *other* boards is, but the user-facing recommendation is the
       same: flash firmware before retrying).
    3. Otherwise, the probe error string disambiguates.  A "could not
       open port" type failure maps to
       :attr:`~BoardState.SERIAL_UNREACHABLE`.  Anything else maps to
       :attr:`~BoardState.NO_PROBE_RESPONSE` (port opens but the
       board doesn't speak Python, typically an ESP32 in ROM
       bootloader).

    Args:
        device: Constructed :class:`chumicro_deploy.Device`.  The
            transport / address / runtime fields drive the probe;
            the deploy-mode fields are ignored.
        uf2_search_paths: Override the platform-default UF2 mount
            roots.  Forwarded to :func:`find_uf2_drive`; tests
            inject a tmp_path-rooted layout.
        probe_function: Inject a probe replacement.  Defaults to
            :func:`chumicro_deploy.probe_device`.
        drive_scanner: Inject a UF2 scanner replacement.  Defaults
            to :func:`find_uf2_drive`.
    """
    if probe_function is None:
        from chumicro_deploy import probe_device  # noqa: PLC0415

        probe_function = probe_device
    if drive_scanner is None:
        drive_scanner = find_uf2_drive

    probe_error_text = ""
    probe_implementation_name: str | None = None
    try:
        info = probe_function(device)
    except Exception as exception:  # noqa: BLE001 (diagnostic catches everything)
        probe_error_text = str(exception) or type(exception).__name__
    else:
        if info.implementation is not None:
            probe_implementation_name = info.implementation.name
            return OnboardingDiagnosis(
                state=BoardState.REPL_REACHABLE,
                probe_implementation_name=probe_implementation_name,
                next_steps=_next_steps_for(BoardState.REPL_REACHABLE),
            )

    drive = drive_scanner(uf2_search_paths)
    if drive is not None:
        return OnboardingDiagnosis(
            state=BoardState.UF2_BOOTLOADER,
            uf2_drive=drive,
            probe_error=probe_error_text,
            next_steps=_next_steps_for(BoardState.UF2_BOOTLOADER, uf2_drive=drive),
        )

    if _looks_like_serial_unreachable(probe_error_text):
        state = BoardState.SERIAL_UNREACHABLE
    else:
        state = BoardState.NO_PROBE_RESPONSE
    return OnboardingDiagnosis(
        state=state,
        probe_error=probe_error_text,
        next_steps=_next_steps_for(state),
    )


@dataclass(frozen=True)
class RuntimeInferenceResult:
    """Outcome of :func:`probe_with_runtime_inference`.

    Attributes:
        info: :class:`chumicro_deploy.DeviceInfo` from the first
            probe whose ``implementation`` field came back populated,
            or ``None`` when every candidate transport failed.
        runtime: The runtime name reported by the probe, i.e.
            ``info.implementation.name``.  ``None`` when no probe
            returned a marker.  This is the *truthful* runtime name
            from ``sys.implementation``, not necessarily the same
            as the candidate transport that succeeded (an MP
            transport on a CP board still returns
            ``implementation.name == "circuitpython"``).
        last_exception: The last exception encountered during the
            search, when no candidate succeeded.  ``None`` on
            success or when no exceptions were raised (every
            candidate returned cleanly with no marker).
    """

    info: DeviceInfo | None
    runtime: str | None
    last_exception: BaseException | None = None


def probe_with_runtime_inference(
    address: str,
    *,
    candidates: Sequence[str] = DEFAULT_RUNTIME_INFERENCE_ORDER,
    probe_function: Callable[[Device], DeviceInfo] | None = None,
    device_factory: Callable[[str, str], Device] | None = None,
) -> RuntimeInferenceResult:
    """Probe *address* without knowing the runtime up-front.

    Tries each candidate transport in :data:`DEFAULT_RUNTIME_INFERENCE_ORDER`
    until one returns an implementation marker.  Returns the
    :class:`RuntimeInferenceResult` so the caller can
    record the probed runtime and version once a candidate succeeds.

    Both runtimes speak the same probe script (reads
    ``sys.implementation``), so the returned implementation name is
    truthful regardless of which transport delivered it.  See
    :data:`DEFAULT_RUNTIME_INFERENCE_ORDER` for why both candidates
    are tried.

    Args:
        address: Serial port path of the board.
        candidates: Runtime names to try, in order.  Override for
            tests or to skip a runtime entirely.  Defaults to
            ``DEFAULT_RUNTIME_INFERENCE_ORDER``.
        probe_function: Inject a :func:`chumicro_deploy.probe_device`
            replacement.  Tests pass a fake to avoid hardware.
        device_factory: Inject a constructor for
            :class:`chumicro_deploy.Device`.  Receives ``(transport,
            address)`` and returns a Device.  Tests pass a fake.

    Returns:
        :class:`RuntimeInferenceResult` with ``info`` and ``runtime``
        populated on success; on failure both are ``None`` and
        ``last_exception`` carries the most recent exception (or
        ``None`` when every candidate completed cleanly without a
        marker).
    """
    if probe_function is None:
        from chumicro_deploy import probe_device  # noqa: PLC0415

        probe_function = probe_device
    if device_factory is None:
        from chumicro_deploy import Device as _DefaultDevice  # noqa: PLC0415

        def device_factory(transport: str, address_: str) -> Device:
            return _DefaultDevice(transport=transport, address=address_)

    last_exception: BaseException | None = None
    for candidate in candidates:
        device = device_factory(candidate, address)
        try:
            info = probe_function(device)
        except Exception as exception:  # noqa: BLE001 (fall through to next candidate)
            last_exception = exception
            continue
        if info.implementation is not None:
            return RuntimeInferenceResult(
                info=info,
                runtime=info.implementation.name,
            )
    return RuntimeInferenceResult(
        info=None,
        runtime=None,
        last_exception=last_exception,
    )


def _looks_like_serial_unreachable(error_text: str) -> bool:
    """Heuristic: does *error_text* read like 'I couldn't open the port'?

    Pulls from the common idioms pyserial / mpremote / OS-level
    failures emit when the serial port itself is unreachable.  Not
    a complete classifier.  When in doubt, the result falls through
    to :attr:`~BoardState.NO_PROBE_RESPONSE`, which suggests
    flashing rather than replugging.
    """
    if not error_text:
        return False
    lowered = error_text.lower()
    return any(
        marker in lowered
        for marker in (
            "could not open port",
            "no such file or directory",
            "permission denied",
            "device not configured",
            "port not found",
            "could not exclusively lock",
            "errno 2",     # ENOENT
            "errno 13",    # EACCES
            "errno 16",    # EBUSY
        )
    )
