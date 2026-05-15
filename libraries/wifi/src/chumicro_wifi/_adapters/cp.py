"""CircuitPython ``wifi.radio`` adapter.

Wraps the native ``wifi.radio`` singleton.  The library is the sole
supervisor — the workspace template's ``settings.toml`` omits
``CIRCUITPY_WIFI_*`` keys so CP's firmware auto-connect path never
fires; this adapter drives the connect itself.

``radio`` defaults to the live ``wifi.radio`` singleton; tests inject
a fake to exercise the adapter contract without hardware.
"""

__chumicro_runtimes__ = ("circuitpython",)

from chumicro_wifi._adapters.base import WifiAdapter


class CpWifiAdapter(WifiAdapter):
    """CP ``wifi.radio`` adapter.

    Args:
        radio: Optional radio substrate.  When ``None`` (default),
            uses the live ``wifi.radio`` singleton — only available
            under CircuitPython.  Tests inject a fake whose shape
            matches the subset of ``wifi.radio`` we touch:
            ``hostname`` (settable str), ``connect(ssid, password,
            timeout=...)`` (blocking, may raise), ``stop_station()``,
            ``connected`` (bool), ``ipv4_address`` (stringifiable
            or ``None``).
    """

    name = "cp"

    def __init__(self, radio=None):
        if radio is None:
            radio = self._acquire_runtime_radio()
        self.radio = radio

    @staticmethod
    def _acquire_runtime_radio():
        """Return ``wifi.radio`` or raise a clear error.

        Wraps the import so the host-side error is informative
        rather than a bare ``ImportError`` from ``wifi``.
        """
        try:
            import wifi  # pragma: no cover - CP runtime path
        except ImportError as error:
            raise RuntimeError(
                "CpWifiAdapter requires CircuitPython (wifi.radio). "
                "On a host, pass `radio=<fake>` to test the wire format."
            ) from error
        return wifi.radio  # pragma: no cover - CP runtime path

    def configure(self, config):
        """Apply the substrate-specific knobs before the first connect.

        CircuitPython's ``wifi.radio.hostname`` must be set before
        ``connect()`` to advertise on the AP.  Power-save and
        static-IP are not exposed by ``wifi.radio`` in 10.x — we
        accept the config field for cross-runtime parity but ignore
        them here (documented in the adapter docstring).
        """
        if config.hostname is not None:
            self.radio.hostname = config.hostname

    def connect(self, config):
        """Block on ``wifi.radio.connect`` budgeted by ``connect_timeout_ms``.

        CP's connect is blocking — the substrate doesn't expose a
        non-blocking variant.  ``timeout`` is in seconds; we
        convert from the config's milliseconds.

        Catches ``OSError`` (the parent of CircuitPython's
        ``TimeoutError`` / ``ConnectionError`` for the AP-refused
        and timeout cases) so the service can retry; we use
        ``OSError`` rather than the targeted subclasses because
        MicroPython doesn't expose those names as builtins (the
        adapter source has to load on every runtime even though
        only CP instantiates it).  Anything else (RuntimeError,
        AttributeError — programmer errors, wrong board) propagates
        to ``WifiService.last_error``.
        """
        timeout_seconds = config.connect_timeout_ms / 1000
        try:
            self.radio.connect(
                config.ssid,
                config.password,
                timeout=timeout_seconds,
            )
        except OSError:
            return False
        return self.radio.connected

    def disconnect(self):
        """Tear down the active station association."""
        self.radio.stop_station()

    def is_linked(self):
        """``True`` when the substrate reports an active association."""
        return bool(self.radio.connected)

    def ip(self):
        """Return the IPv4 address as a string, or ``None``."""
        if not self.radio.connected:
            return None
        address = self.radio.ipv4_address
        return str(address) if address is not None else None
