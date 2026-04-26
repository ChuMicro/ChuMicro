"""MicroPython ESP32 ``network.WLAN`` adapter.

Wraps ``network.WLAN(network.STA_IF)``.  The library is the sole
reconnect supervisor: after the first successful connect, the
adapter calls ``wlan.config(reconnects=0)`` to disable ESP-IDF's
firmware-level auto-reconnect (``reconnects=0`` = one attempt then
stop; the library drives retries itself with uniform backoff via
``WifiService``).

``wlan`` defaults to a fresh ``network.WLAN(network.STA_IF)``; tests
inject a fake to exercise the adapter contract without hardware.
"""

__chumicro_runtimes__ = ("micropython",)

from chumicro_wifi._adapters.base import WifiAdapter


class MpEsp32WifiAdapter(WifiAdapter):
    """MP ESP32 ``network.WLAN`` adapter.

    Args:
        wlan: Optional WLAN substrate.  When ``None`` (default),
            constructs ``network.WLAN(network.STA_IF)`` — only
            available under MicroPython on an ESP32 build.  Tests
            inject a fake whose shape matches the subset of
            ``network.WLAN`` we touch: ``active(state=None)``
            (getter / setter), ``connect(ssid, password)``,
            ``disconnect()``, ``isconnected()``, ``ifconfig()``
            (returns ``(ip, netmask, gateway, dns)``),
            ``config(**kwargs)`` (the substrate's tuning knob).
    """

    NAMESPACE = "esp32"

    name = "mp_esp32"

    def __init__(self, wlan=None):
        if wlan is None:
            wlan = self._acquire_runtime_wlan()
        self._wlan = wlan
        self._supervisor_disabled = False

    @staticmethod
    def _acquire_runtime_wlan():
        """Build ``network.WLAN(network.STA_IF)`` or raise a clear error."""
        try:
            import network  # pragma: no cover - MP-ESP32 runtime path
        except ImportError as error:
            raise RuntimeError(
                "MpEsp32WifiAdapter requires MicroPython with a network module. "
                "On a host, pass `wlan=<fake>` to test the wire format."
            ) from error
        return network.WLAN(network.STA_IF)  # pragma: no cover - MP-ESP32 runtime path

    def configure(self, config):
        """Activate the radio + apply hostname; supervisor is disabled post-connect.

        ESP-IDF's auto-reconnect can't be disabled before the first
        successful connect (the config knob is read at the next
        re-association attempt, not at activation time), so the
        supervisor-off call moves into ``connect`` after the first
        success.
        """
        self._wlan.active(True)
        if config.hostname is not None:
            try:
                self._wlan.config(dhcp_hostname=config.hostname)
            except (OSError, ValueError):
                # Some MP-ESP32 builds reject hostname config when the
                # interface is up; tolerate the failure rather than
                # blocking deploy.  The supervisor-off call below is
                # the load-bearing one.
                pass

    def connect(self, config):
        """Begin / drive the association via ``wlan.connect``.

        MP's ``connect`` is non-blocking — it returns immediately
        after dispatching the association request; ``isconnected()``
        flips to ``True`` once the AP responds.  The substrate's
        timeout behavior is governed by ESP-IDF below the Python
        binding; we don't budget here, leaving the timing to
        ``WifiService``'s reconnect supervisor.

        After the first link-up, drops the firmware-level
        auto-reconnect supervisor so the library is the sole driver
        of retry behavior.
        """
        self._wlan.connect(config.ssid, config.password)
        if not self._wlan.isconnected():
            return False
        if not self._supervisor_disabled:
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
