__chumicro_runtimes__ = ("micropython",)

import os
import sys

from chumicro_wifi._adapters.base import WifiAdapter

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

# Magic value that disables CYW43 idle power-save mode.
CYW43_PM_DISABLE = const(0xA11140)

# ESP-IDF WIFI_PS_NONE: disables modem power-save on the esp32 stack.
ESP32_PM_NONE = const(0)

# Exact strings a board reports via sys.implementation._machine.
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
    # Refined per-stack in __init__ ("mp_esp32" / "mp_rp2").
    name = "mp"

    # MP's wlan.connect() returns before is_linked() reports success, so a False result is not a failure.
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
        # Default to espidf on unknown boards: the ESP-only knob no-ops elsewhere, so misclassifying is safe.
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
        if config.hostname is not None:
            self._apply_hostname(config.hostname)
        self._wlan.active(True)
        # TX power needs the station active, so apply it after active(True).
        if config.tx_power_dbm is not None:
            self._apply_tx_power(config.tx_power_dbm)
        if not config.power_save:
            pm_value = (
                CYW43_PM_DISABLE if self._stack == "cyw43" else ESP32_PM_NONE
            )
            try:
                self._wlan.config(pm=pm_value)
            except (OSError, ValueError):
                # Older MP firmware may not expose the pm knob; proceed at default power-save.
                pass

    def _apply_hostname(self, hostname):
        # Try portable network.hostname() first: the dhcp_hostname kwarg below raises ValueError on CYW43.
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
            # No hostname knob on this build; tolerate it.
            pass

    def _apply_tx_power(self, tx_power_dbm):
        # A build without the txpower knob raises ValueError (OSError on some ports).
        try:
            self._wlan.config(txpower=tx_power_dbm)
        except (OSError, ValueError):
            pass

    def connect(self, config, timeout_ms=None):
        # timeout_ms is unused: wlan.connect() dispatches a non-blocking
        # join, so the caller bounds the attempt by polling is_linked().
        # Already linked: re-issuing wlan.connect() aborts and restarts the association on ESP-IDF.
        if self._wlan.isconnected():
            self._disable_supervisor_once()
            return True
        self._wlan.connect(config.ssid, config.password)
        if not self._wlan.isconnected():
            return False
        self._disable_supervisor_once()
        return True

    def _disable_supervisor_once(self):
        # ESP-IDF only: drop the firmware auto-reconnect supervisor so the library is the sole retry driver.
        if self._stack == "espidf" and not self._supervisor_disabled:
            try:
                self._wlan.config(reconnects=0)
                self._supervisor_disabled = True
            except (OSError, ValueError):
                # Some builds don't expose the reconnects knob; the library's own supervisor still works.
                pass

    def is_linked(self):
        # Link-loss is laggy: isconnected() flips only on the driver's beacon-miss/TX-fail event.
        return bool(self._wlan.isconnected())

    def ip(self):
        if not self._wlan.isconnected():
            return None
        ifconfig = self._wlan.ifconfig()
        if not ifconfig:
            return None
        address = ifconfig[0]
        # "0.0.0.0" is the pre-DHCP sentinel: associated but no address yet.
        if not address or address == "0.0.0.0":
            return None
        return address
