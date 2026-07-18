__chumicro_runtimes__ = ("circuitpython",)

from chumicro_wifi._adapters.base import WifiAdapter


class CpWifiAdapter(WifiAdapter):
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
        # hostname must be set before connect() to advertise on the AP.
        if config.hostname is not None:
            self.radio.hostname = config.hostname

    def connect(self, config):
        # Already linked (an association can survive a soft-reload); poking the radio would destabilise it.
        if self.radio.connected:
            return True
        # Reset the station: on ESP32-S3 a failed connect leaves it half-open, slow-failing the next attempt.
        try:
            self.radio.stop_station()
        except OSError:
            pass
        # Apply after stop_station (so the reset doesn't clear it) and before connect.
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
            # OSError (parent of CP's TimeoutError/ConnectionError) means refused or timed out.
            return False
        return self.radio.connected

    def _apply_tx_power(self, tx_power_dbm):
        # A build without the tx_power knob raises AttributeError (OSError if the driver rejects it).
        try:
            self.radio.tx_power = tx_power_dbm
        except (OSError, AttributeError):
            pass

    def is_linked(self):
        # Link-loss is laggy: connected flips only on the driver's beacon-miss timeout, seconds late.
        return bool(self.radio.connected)

    def ip(self):
        if not self.radio.connected:
            return None
        address = self.radio.ipv4_address
        return str(address) if address is not None else None
