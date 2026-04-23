"""probe_device — one-shot runtime-identity probe over a transport.

Thin wrapper over :meth:`TransportProtocol.probe_implementation` that
owns the transport lifecycle (connect / probe / disconnect) and
returns a :class:`DeviceInfo` callers can surface to users.

Board ID and CPU UID discovery is planned but not yet wired up —
those fields are reserved on :class:`DeviceInfo` and populated with
empty strings for now.  When a future slice adds them, callers don't
need to change: the fields are already part of the return type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .protocol import DeviceImplementation

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .device import Device


@dataclass(frozen=True)
class DeviceInfo:
    """What :func:`probe_device` gathered from a connected board.

    Attributes:
        implementation: Parsed ``sys.implementation`` fields (runtime
            name, version, machine string).  ``None`` when the probe
            script ran but no marker came back — almost always a
            hardware or connection issue.
        board_id: Normalised board identifier (e.g.
            ``"raspberry_pi_pico_w"``).  Reserved — populated in a
            later slice via a board-specific probe.  Empty string
            today.
        uid: Hex-encoded CPU UID.  Reserved — populated in a later
            slice via ``microcontroller.cpu.uid`` (CP) or
            ``machine.unique_id()`` (MP).  Empty string today.
    """

    implementation: DeviceImplementation | None
    board_id: str = ""
    uid: str = ""


def probe_device(device: Device) -> DeviceInfo:
    """Connect, probe, disconnect — return what the board reports.

    Exceptions during the probe propagate; callers that want soft
    failure (onboarding flows where a hardware probe is best-effort)
    wrap the call themselves.  The transport is always disconnected,
    even on error.

    Args:
        device: Target :class:`Device`.

    Returns:
        :class:`DeviceInfo` with the implementation field populated
        when the board returned the probe marker; board_id and uid
        stay empty until the richer probe ships in a later slice.
    """
    transport = device.create_transport()
    transport.connect()
    try:
        implementation = transport.probe_implementation()
    finally:
        transport.disconnect()
    return DeviceInfo(implementation=implementation)
