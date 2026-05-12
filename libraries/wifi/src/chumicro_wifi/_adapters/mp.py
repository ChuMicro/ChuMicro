"""MicroPython ``network.WLAN`` adapter — covers both ESP-IDF and CYW43 stacks.

Wraps ``network.WLAN(network.STA_IF)`` on either MicroPython wifi
stack.  The substrate API itself is identical between the two; the
two stack-specific knobs the adapter applies are:

* **ESP-IDF stack** (ESP32, S2, S3, C3, C6, …): after the first
  successful association, calls ``wlan.config(reconnects=0)`` to
  disable the firmware-level auto-reconnect supervisor, leaving
  ``WifiService`` as the sole reconnect driver.
* **CYW43 stack** (Pi Pico W, …): when ``WifiConfig.power_save``
  is ``False`` (default), calls ``wlan.config(pm=0xa11140)`` at
  configure time to disable CYW43 idle power-save (eliminates
  ~30-100 ms tick spikes on chip wake-up).  CYW43 has no firmware
  reconnect supervisor, so no ``reconnects`` knob is issued.

Stack detection at construction time matches the runtime's machine
identifier against :data:`CYW43_MACHINES` — a positive whitelist of
known-CYW43 board identifiers.  The identifier comes from
``sys.implementation._machine`` (present on MicroPython and
CircuitPython, including unix-port host builds), falling back to
``os.uname().machine`` on CPython where ``_machine`` is absent.
Anything outside the whitelist (today's ESP boards + future
unknowns) falls through to ``"espidf"``, where the ESP-side knob
has its own try/except guard so it no-ops cleanly on chips that
don't expose it.  This shape avoids the prior "if not ESP, assume
CYW43" inference — new CYW43-bearing boards extend
:data:`CYW43_MACHINES` rather than relying on an exception path to
do the right thing.

Tests inject the stack explicitly via ``stack="espidf"`` /
``stack="cyw43"`` to exercise both branches on CPython.

``wlan`` defaults to a fresh ``network.WLAN(network.STA_IF)``;
tests inject a fake to exercise the adapter contract without
hardware.  ``name`` is ``"mp_esp32"`` for ESP-IDF or ``"mp_rp2"``
for CYW43 — the strings users read via ``wifi.adapter.name``.
"""

__chumicro_runtimes__ = ("micropython",)

import os
import sys

from chumicro_wifi._adapters.base import WifiAdapter

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

#: Magic value disabling CYW43 idle power-save mode.  From CYW43
#: vendor docs + community measurements; the adapter applies it
#: when ``WifiConfig.power_save`` is ``False`` (the default).
#: Wrapped in ``const(...)`` so MicroPython inlines the literal at
#: the use site at compile time.  Public name (no leading underscore)
#: so cross-runtime tests + on-device tests can keep importing it.
CYW43_PM_DISABLE = const(0xA11140)

#: Known CYW43-based MicroPython board identifiers.
#: Add new entries as CYW43-bearing boards land in upstream MP — match the
#: exact string the board reports (visible via
#: ``import sys; print(sys.implementation._machine)`` at the REPL).
CYW43_MACHINES = (
    "Raspberry Pi Pico W with RP2040",
)


def _get_machine_name():
    """Return the runtime's machine identifier, or ``""`` when unavailable.

    Prefers ``sys.implementation._machine`` — present on MicroPython and
    CircuitPython on both real boards and unix-port hosts.  On a Pi Pico W
    MP firmware this matches what ``os.uname().machine`` returns; on
    unix-port hosts it's the host build string (which won't match any
    entry in :data:`CYW43_MACHINES`).  Falls back to ``os.uname().machine``
    on CPython hosts where ``sys.implementation._machine`` is absent.
    Returns ``""`` when neither source works, which falls through to
    ``"espidf"`` in :meth:`MpWifiAdapter._detect_stack` (the safe default).
    """
    machine = getattr(sys.implementation, "_machine", None)
    if machine is not None:
        return machine
    if hasattr(os, "uname"):
        return os.uname().machine
    return ""  # pragma: no cover - no host runtime hits this


class MpWifiAdapter(WifiAdapter):
    """MP ``network.WLAN`` adapter for both ESP-IDF and CYW43 stacks.

    Args:
        wlan: Optional WLAN substrate.  When ``None`` (default),
            constructs ``network.WLAN(network.STA_IF)`` — only
            available under MicroPython on a board with a wifi
            chip.  Tests inject a fake matching the WLAN surface
            the adapter touches: ``active(state=None)``,
            ``connect(ssid, password)``, ``disconnect()``,
            ``isconnected()``, ``ifconfig()``,
            ``config(**kwargs)``.
        stack: Optional stack identifier — ``"espidf"``,
            ``"cyw43"``, or ``None`` (auto-detect via
            ``import esp32``).  Tests pass this explicitly to
            exercise either branch on CPython.
    """

    def __init__(self, wlan=None, *, stack=None):
        if stack is None:
            stack = self._detect_stack()
        if stack not in ("espidf", "cyw43"):
            raise ValueError(
                f"stack must be 'espidf' or 'cyw43', got {stack!r}"
            )
        self._stack = stack
        self.name = "mp_esp32" if stack == "espidf" else "mp_rp2"
        if wlan is None:
            wlan = self._acquire_runtime_wlan()
        self._wlan = wlan
        self._supervisor_disabled = False

    @staticmethod
    def _detect_stack():
        """Return ``"cyw43"`` if the runtime reports a known CYW43 board.

        Reads the machine identifier via :func:`_get_machine_name` and
        falls through to ``"espidf"`` for everything outside
        :data:`CYW43_MACHINES` — ESP-side handling has its own
        try/except guards so a misclassified non-ESP board still
        operates safely (the ESP-specific knob no-ops cleanly on
        chips that don't expose it).  Extend :data:`CYW43_MACHINES`
        when a new CYW43-bearing board appears.
        """
        if _get_machine_name() in CYW43_MACHINES:
            return "cyw43"
        return "espidf"

    @staticmethod
    def _acquire_runtime_wlan():
        """Build ``network.WLAN(network.STA_IF)`` or raise a clear error."""
        try:
            import network  # pragma: no cover - MP runtime path
        except ImportError as error:
            raise RuntimeError(
                "MpWifiAdapter requires MicroPython with a network module. "
                "On a host, pass `wlan=<fake>` to test the wire format."
            ) from error
        return network.WLAN(network.STA_IF)  # pragma: no cover - MP runtime path

    def configure(self, config):
        """Activate the radio + apply hostname + apply CYW43 power-save knob.

        ESP-IDF's ``reconnects`` knob can't be set before the first
        successful connect (it's read at re-association time, not
        activation), so the supervisor-off call moves into
        :meth:`connect` after the first link-up.  The CYW43 ``pm``
        knob is stateless from the substrate's perspective —
        applied here at configure time so the first link is
        already in the user's preferred mode.
        """
        self._wlan.active(True)
        if config.hostname is not None:
            try:
                self._wlan.config(dhcp_hostname=config.hostname)
            except (OSError, ValueError):
                # Some MP builds reject hostname config when the
                # interface is up; tolerate the failure rather than
                # blocking deploy.
                pass
        if self._stack == "cyw43" and not config.power_save:
            try:
                self._wlan.config(pm=CYW43_PM_DISABLE)
            except (OSError, ValueError):
                # Older MP firmware may not expose the pm knob; we
                # proceed without it.  Power-save stays at the
                # firmware default — user code may notice idle
                # latency spikes but the connection still works.
                pass

    def connect(self, config):
        """Begin / drive the association via ``wlan.connect``.

        MP's ``connect`` is non-blocking — returns immediately
        after dispatching the request; ``isconnected()`` flips to
        ``True`` once the AP responds.  The substrate's timeout
        behavior is governed by ESP-IDF (or CYW43) below the
        Python binding; we don't budget here, leaving the timing
        to ``WifiService``'s reconnect supervisor.

        On the ESP-IDF stack, after the first link-up, drops the
        firmware-level auto-reconnect supervisor so the library is
        the sole driver of retry behavior.  CYW43 has no firmware
        supervisor, so no supervisor-off call fires.
        """
        self._wlan.connect(config.ssid, config.password)
        if not self._wlan.isconnected():
            return False
        if self._stack == "espidf" and not self._supervisor_disabled:
            try:
                self._wlan.config(reconnects=0)
                self._supervisor_disabled = True
            except (OSError, ValueError):
                # Some MP builds (older firmware, non-ESP-IDF stacks)
                # don't expose the reconnects knob; we proceed anyway
                # — the library's reconnect supervisor still works,
                # we just don't get the firmware-side guarantee.
                pass
        return True

    def disconnect(self):
        """Drop the active association.  Idempotent on the substrate."""
        self._wlan.disconnect()

    def is_linked(self):
        """``True`` while ``isconnected()`` reports an active association."""
        return bool(self._wlan.isconnected())

    def ip(self):
        """Return the IPv4 string from ``ifconfig()``, or ``None``.

        ``ifconfig`` returns a 4-tuple ``(ip, netmask, gateway, dns)``;
        the first element is the address as a string.  Returns
        ``None`` when not linked, or when the substrate's IP is the
        unset sentinel ``"0.0.0.0"`` (post-association but pre-DHCP).
        """
        if not self._wlan.isconnected():
            return None
        ifconfig = self._wlan.ifconfig()
        if not ifconfig:
            return None
        address = ifconfig[0]
        if not address or address == "0.0.0.0":
            return None
        return address
