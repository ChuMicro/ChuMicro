"""CircuitPython ``wifi.radio`` adapter.

Wraps the native ``wifi.radio`` singleton and drives the connect path
itself: the workspace template omits ``CIRCUITPY_WIFI_*`` keys, so CP's
firmware auto-connect never fires.
"""

__chumicro_runtimes__ = ("circuitpython",)

from chumicro_wifi._adapters.base import WifiAdapter


class CpWifiAdapter(WifiAdapter):
    """CircuitPython ``wifi.radio`` adapter.

    Args:
        radio: Optional radio substrate. When ``None`` (default), uses the
            live ``wifi.radio`` singleton (CircuitPython only). Tests inject
            a fake matching the subset of ``wifi.radio`` the adapter touches:
            ``hostname``, ``connect(ssid, password, timeout=...)``,
            ``stop_station()``, ``connected``, ``ipv4_address``.
    """

    name = "cp"

    def __init__(self, radio=None):
        if radio is None:
            radio = self._acquire_runtime_radio()
        self.radio = radio

    @staticmethod
    def _acquire_runtime_radio():
        try:
            import wifi  # pragma: no cover - CP runtime path
        except ImportError as error:
            raise RuntimeError(
                "CpWifiAdapter requires CircuitPython (wifi.radio). "
                "On a host, pass `radio=<fake>` to test the wire format."
            ) from error
        return wifi.radio  # pragma: no cover - CP runtime path

    def configure(self, config):
        """Apply the substrate knobs before the first connect.

        Sets ``wifi.radio.hostname`` (which must be set before
        ``connect()`` to advertise on the AP). Power-save and static-IP
        aren't exposed by ``wifi.radio`` in 10.x, so those config fields
        are accepted for cross-runtime parity but ignored here.
        """
        if config.hostname is not None:
            self.radio.hostname = config.hostname

    def connect(self, config):
        """Clear stale station state, then block on ``wifi.radio.connect``.

        CircuitPython's connect blocks (no non-blocking variant exists)
        and takes its timeout in seconds, converted from
        ``connect_timeout_ms``. Returns ``True`` on link-up, ``False`` when
        the attempt times out or the AP refuses.
        """
        # Already linked (e.g. a live association survived a soft-reload):
        # nothing to do, and poking the radio would only destabilise it.
        if self.radio.connected:
            return True
        # Reset the station before each attempt: on the ESP32-S3 a failed
        # connect leaves it half-open and the next attempt slow-fails.
        try:
            self.radio.stop_station()
        except OSError:
            pass
        # After stop_station (so the clear doesn't reset it) and before connect.
        if config.tx_power_dbm is not None:
            self._apply_tx_power(config.tx_power_dbm)
        timeout_seconds = config.connect_timeout_ms / 1000
        try:
            self.radio.connect(
                config.ssid,
                config.password,
                timeout=timeout_seconds,
            )
        except OSError:
            # OSError (parent of CP's TimeoutError / ConnectionError; MP lacks
            # those builtins) means the AP refused or timed out, so retry.
            return False
        return self.radio.connected

    def _apply_tx_power(self, tx_power_dbm):
        # A build without a tx_power knob raises AttributeError (OSError if the
        # driver rejects the value); tolerate it and stay at default power.
        try:
            self.radio.tx_power = tx_power_dbm
        except (OSError, AttributeError):
            pass

    def is_linked(self):
        """``True`` when ``wifi.radio.connected`` reports an active link.

        Link-loss detection is laggy, not instant: ``connected`` flips only
        when the driver raises its disconnect event (a beacon-miss timeout
        seconds after an AP vanishes), so a dropped link can read ``True``
        for a few seconds. ``WifiService`` polls this every ``check()``.
        """
        return bool(self.radio.connected)

    def ip(self):
        """Return the IPv4 address as a string, or ``None``."""
        if not self.radio.connected:
            return None
        address = self.radio.ipv4_address
        return str(address) if address is not None else None
