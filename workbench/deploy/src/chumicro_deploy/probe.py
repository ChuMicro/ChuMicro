"""probe_device — one-shot runtime-identity probe over a transport.

Thin wrapper over :meth:`TransportProtocol.probe_implementation` that
owns the transport lifecycle (connect / probe / disconnect) and
returns a :class:`DeviceInfo` callers can surface to users.

CPU UID is populated from the probe script itself —
:data:`~chumicro_deploy.protocol.PROBE_IMPLEMENTATION_SCRIPT` reads
``microcontroller.cpu.uid`` on CircuitPython and
``machine.unique_id()`` on MicroPython and emits it as the fourth
field of the ``__CHU_IMPL__:`` marker line.  Board ID discovery is
still planned but not yet wired up — the field is reserved on
:class:`DeviceInfo` and populated with the empty string for now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .host_platform import check_supported_platform
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
        uid: Hex-uppercase CPU UID probed from
            ``microcontroller.cpu.uid`` (CP) or ``machine.unique_id()``
            (MP) via :data:`PROBE_IMPLEMENTATION_SCRIPT`.  Empty when
            the probe couldn't read the ID (older firmware, ROM
            without the hardware ID, or the module raised).
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
        when the board returned the probe marker.  ``uid`` mirrors
        ``implementation.uid`` when the probe could read it;
        ``board_id`` stays empty until the board-ID probe ships in a
        later slice.
    """
    check_supported_platform()
    transport = device.create_transport()
    transport.connect()
    try:
        implementation = transport.probe_implementation()
    finally:
        transport.disconnect()
    uid = implementation.uid if implementation is not None else ""
    return DeviceInfo(implementation=implementation, uid=uid)
