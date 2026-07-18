"""MicroPython ``network.WLAN`` adapter for the ESP-IDF and CYW43 wifi stacks.

One class covers both stacks (their substrate API is identical); two
stack-specific knobs, the ESP-IDF firmware-reconnect disable and the CYW43
power-save disable, are applied conditionally. Stack detection lives in
:meth:`MpWifiAdapter._detect_stack`; tests inject ``stack=`` to exercise
both branches on CPython.
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

#: Magic value that disables CYW43 idle power-save mode. Applied when
#: ``WifiConfig.power_save`` is ``False`` (the default). ``const(...)`` lets
#: MicroPython inline the literal at compile time.
CYW43_PM_DISABLE = const(0xA11140)

#: Known CYW43-based MicroPython board identifiers. Add new entries matching
#: the exact string a board reports via ``sys.implementation._machine``.
CYW43_MACHINES = (
    "Raspberry Pi Pico W with RP2040",
    "Raspberry Pi Pico 2 W with RP2350",
)


def _get_machine_name():
    machine = getattr(sys.implementation, "_machine", None)
    if machine is not None:
        return machine
    if hasattr(os, "uname"):
        return os.uname().machine
    return ""  # pragma: no cover - no host runtime hits this


class MpWifiAdapter(WifiAdapter):
    """MicroPython ``network.WLAN`` adapter for the ESP-IDF and CYW43 stacks.

    Args:
        wlan: Optional WLAN substrate. When ``None`` (default), builds
            ``network.WLAN(network.STA_IF)`` (MicroPython only). Tests inject
            a fake matching the surface the adapter touches: ``active``,
            ``connect``, ``isconnected``, ``ifconfig``, ``config``.
        stack: ``"espidf"``, ``"cyw43"``, or ``None`` to auto-detect via
            :meth:`_detect_stack`. Tests pass it explicitly to exercise
            either branch on CPython.
    """

    # MP's wlan.connect() is non-blocking: it dispatches the join and returns
    # before is_linked() reports success, so connect() == False is not a failure.
    connect_blocks = False

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
        # Default to espidf on an unknown board: the ESP-only config knob
        # no-ops on chips that don't expose it, so misclassifying is safe.
        if _get_machine_name() in CYW43_MACHINES:
            return "cyw43"
        return "espidf"

    @staticmethod
    def _acquire_runtime_wlan():
        try:
            import network  # pragma: no cover - MP runtime path
        except ImportError as error:
            raise RuntimeError(
                "MpWifiAdapter requires MicroPython with a network module. "
                "On a host, pass `wlan=<fake>` to test the wire format."
            ) from error
        return network.WLAN(network.STA_IF)  # pragma: no cover - MP runtime path

    def configure(self, config):
        """Activate the radio and apply hostname, TX power, and power-save.

        ESP-IDF's ``reconnects`` knob can't be set until after the first
        successful connect, so that call lives in :meth:`connect`. TX power
        is applied here right after activation (the station must be up for
        it) and before any connect; the CYW43 ``pm`` power-save knob too.
        """
        if config.hostname is not None:
            self._apply_hostname(config.hostname)
        self._wlan.active(True)
        if config.tx_power_dbm is not None:
            self._apply_tx_power(config.tx_power_dbm)
        if self._stack == "cyw43" and not config.power_save:
            try:
                self._wlan.config(pm=CYW43_PM_DISABLE)
            except (OSError, ValueError):
                # Older MP firmware may not expose the pm knob; proceed without
                # it. Power-save stays at default (possible idle latency spikes).
                pass

    def _apply_hostname(self, hostname):
        # Try the portable network.hostname() first: the ESP-only
        # dhcp_hostname kwarg below raises ValueError on CYW43 (Pi Pico W).
        try:
            import network  # pragma: no cover - MP runtime path
            network_hostname = getattr(network, "hostname", None)
        except ImportError:
            network_hostname = None
        if network_hostname is not None:
            try:
                network_hostname(hostname)
                return
            except (OSError, ValueError):
                pass
        try:
            self._wlan.config(dhcp_hostname=hostname)
        except (OSError, ValueError):
            # No hostname knob on this build; tolerate rather than block deploy.
            pass

    def _apply_tx_power(self, tx_power_dbm):
        # A build without a txpower knob raises ValueError (OSError on some
        # ports); tolerate it and stay at default power.
        try:
            self._wlan.config(txpower=tx_power_dbm)
        except (OSError, ValueError):
            pass

    def connect(self, config):
        """Dispatch the association via ``wlan.connect`` (non-blocking).

        ``wlan.connect`` returns immediately after dispatching; the service
        polls :meth:`is_linked` over the timeout window. On ESP-IDF, after
        the first link-up, drops the firmware auto-reconnect supervisor so
        the library is the sole retry driver; CYW43 has no such supervisor.
        """
        # Already linked: don't re-issue wlan.connect(), which aborts and
        # restarts the association on ESP-IDF and drops progress on CYW43.
        if self._wlan.isconnected():
            self._disable_supervisor_once()
            return True
        self._wlan.connect(config.ssid, config.password)
        if not self._wlan.isconnected():
            return False
        self._disable_supervisor_once()
        return True

    def _disable_supervisor_once(self):
        # ESP-IDF only: drop the firmware auto-reconnect supervisor after the
        # first link-up so the library is the sole retry driver. No-op on CYW43.
        if self._stack == "espidf" and not self._supervisor_disabled:
            try:
                self._wlan.config(reconnects=0)
                self._supervisor_disabled = True
            except (OSError, ValueError):
                # Some builds don't expose the reconnects knob; proceed anyway,
                # the library's own reconnect supervisor still works.
                pass

    def is_linked(self):
        """``True`` while ``isconnected()`` reports an active link.

        Link-loss detection is laggy, not instant, on both stacks:
        ``isconnected()`` flips only on the driver's beacon-miss / TX-fail
        event (seconds after an AP disappears), so a dropped link can read
        ``True`` for a while. ``WifiService`` polls this every ``check()``.
        """
        return bool(self._wlan.isconnected())

    def ip(self):
        """Return the IPv4 string from ``ifconfig()``, or ``None``.

        Returns ``None`` when not linked, or when the address is still the
        unset sentinel ``"0.0.0.0"`` (associated but pre-DHCP).
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
