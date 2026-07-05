"""CircuitPython ``wifi.radio`` adapter.

Wraps the native ``wifi.radio`` singleton.  The workspace template
omits ``CIRCUITPY_WIFI_*`` keys from ``settings.toml``, so CP's
firmware auto-connect never fires and this adapter drives the
connect path itself.

``radio`` defaults to the live ``wifi.radio`` singleton.  Tests
inject a fake to exercise the adapter contract without hardware.
"""

__chumicro_runtimes__ = ("circuitpython",)

from chumicro_wifi._adapters.base import WifiAdapter


class CpWifiAdapter(WifiAdapter):
    """CP ``wifi.radio`` adapter.

    Args:
        radio: Optional radio substrate.  When ``None`` (default),
            uses the live ``wifi.radio`` singleton, only available
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
        static-IP are not exposed by ``wifi.radio`` in 10.x, so the
        matching config fields are accepted for cross-runtime parity
        but ignored here.
        """
        if config.hostname is not None:
            self.radio.hostname = config.hostname

    def connect(self, config):
        """Clear stale station state, then block on ``wifi.radio.connect``.

        CP's connect is blocking.  The substrate doesn't expose a
        non-blocking variant.  ``timeout`` is in seconds, converted
        from the config's milliseconds.

        Two ESP32-family guards wrap the raw call, both because
        re-issuing ``wifi.radio.connect()`` against existing station
        state destabilises the driver rather than re-joining cleanly:

        * **Already linked** → return ``True`` without touching the
          radio.  A live association can survive a soft-reload, and the
          service only reaches ``connect()`` from a ``DISCONNECTED`` /
          ``RECONNECTING`` state, so a still-up link here means "nothing
          to do."  Mirrors the MP adapter's ``isconnected()`` guard.
        * **Reset the station first** on every fresh attempt.  On the
          ESP32-S3 a failed or timed-out ``connect()`` leaves the
          station half-open; the next attempt then inherits that state
          and slow-fails for the full ``connect_timeout_ms`` (surfacing
          as ``ConnectionError: Unknown failure 205``) instead of the
          ~4 s a clean attempt takes — so a single transient RF glitch
          cascades past the connect budget and the service never links.
          ``stop_station()`` drops that state so each attempt is
          independent.  It is a safe no-op on an already-stopped
          station; the ``OSError`` guard tolerates a port that raises
          when there is nothing to stop.

        Catches ``OSError`` (the parent of CircuitPython's
        ``TimeoutError`` / ``ConnectionError`` for the AP-refused
        and timeout cases) so the service can retry.  ``OSError`` is
        the catch rather than the targeted subclasses because
        MicroPython doesn't expose those names as builtins (the
        adapter source has to load on every runtime even though
        only CP instantiates it).  Anything else (RuntimeError,
        AttributeError, programmer errors, wrong board) propagates
        to ``WifiService.last_error``.

        When ``config.tx_power_dbm`` is set, applies it via
        ``wifi.radio.tx_power`` on every fresh attempt — after
        ``stop_station()`` (so the station-clear doesn't reset it) and
        before ``connect()`` — so each reconnect re-establishes the
        reduced power.  It is deliberately *not* applied on the
        already-linked short-circuit above, which touches no radio
        state at all because poking a live station destabilises it.
        """
        if self.radio.connected:
            return True
        try:
            self.radio.stop_station()
        except OSError:
            pass
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
            return False
        return self.radio.connected

    def _apply_tx_power(self, tx_power_dbm):
        """Set ``wifi.radio.tx_power`` to *tx_power_dbm* (a plain dBm value).

        Called from :meth:`connect` only when
        ``WifiConfig.tx_power_dbm`` is set — ``None`` leaves the radio
        at its firmware default and this never runs.  The value comes
        straight from config; the adapter carries no board-specific
        knowledge of which boards need a reduced power.

        A CP build that doesn't expose ``tx_power`` raises
        ``AttributeError`` (``OSError`` if the driver rejects the
        value); tolerate either and leave the radio at its default
        power rather than faulting the service, matching how the
        ``stop_station`` cleanup above degrades on ports that raise.
        """
        try:
            self.radio.tx_power = tx_power_dbm
        except (OSError, AttributeError):
            pass

    def is_linked(self):
        """``True`` when ``wifi.radio.connected`` reports an active association.

        Link-loss detection here is laggy, not instant.  ``connected``
        tracks the wifi driver's association flag, which flips only when
        the driver raises its disconnect event — a beacon-miss /
        inactivity timeout that runs seconds after an AP silently
        vanishes (powered off, carried out of range).  So a link that
        just dropped can keep reading ``True`` for a few seconds; a
        dependent's socket TX failing is frequently the earlier signal.
        ``WifiService`` polls this every ``check()`` while CONNECTED, so
        the drop transitions to RECONNECTING as soon as the driver
        admits it.
        """
        return bool(self.radio.connected)

    def ip(self):
        """Return the IPv4 address as a string, or ``None``."""
        if not self.radio.connected:
            return None
        address = self.radio.ipv4_address
        return str(address) if address is not None else None
