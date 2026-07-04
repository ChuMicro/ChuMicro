"""On-device tests for ``CpWifiAdapter`` against real ``wifi.radio``.

Runs only on CircuitPython boards.  The module-level
``__chumicro_runtimes__`` marker tells the pytest-device plugin to
skip the wrong-runtime parametrization, so MP boards don't even try
to import the file.

These tests do **not** attempt to associate with a real AP.  They
target the contract between the adapter and the substrate (configure
/ connect / is_linked / ip), using a deliberate non-existent SSID so
the connect call returns ``False`` within the configured timeout
without needing live wifi credentials.

Each test resets the radio to a known state at the end so the next
test starts clean.
"""

__chumicro_runtimes__ = ("circuitpython",)

import wifi
from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.cp import CpWifiAdapter


def _stop_station_quietly():
    """Drop any active association without complaining if there is none."""
    try:
        wifi.radio.stop_station()
    except (OSError, RuntimeError):
        pass


def test_adapter_constructs_against_real_radio() -> None:
    """Default-arg construction picks up ``wifi.radio`` cleanly on CP."""
    adapter = CpWifiAdapter()
    assert adapter.name == "cp"
    assert adapter.radio is wifi.radio


def test_configure_sets_hostname_on_real_radio() -> None:
    """Hostname write reaches the substrate before any connect attempt."""
    _stop_station_quietly()
    adapter = CpWifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="chu-test"))
    assert wifi.radio.hostname == "chu-test"


def test_is_linked_reflects_radio_state_when_disconnected() -> None:
    """Without an active association the adapter reports ``False``."""
    _stop_station_quietly()
    adapter = CpWifiAdapter()
    assert adapter.is_linked() is False


def test_ip_returns_none_when_not_connected() -> None:
    """No IP without a link, regardless of any prior state."""
    _stop_station_quietly()
    adapter = CpWifiAdapter()
    assert adapter.ip() is None


def test_connect_to_nonexistent_ssid_returns_false_within_timeout() -> None:
    """Substrate timeout/refusal maps to a clean ``False``.

    Exercises the substrate's failure path with a deliberate non-
    existent SSID + short timeout.  Answers "how long does CP's
    blocking connect stall on a routable-but-unresponsive AP?" on
    real hardware without needing live wifi.  Wraps the call in
    ``stop_station`` cleanup so the next test starts fresh.
    """
    _stop_station_quietly()
    adapter = CpWifiAdapter()
    # CP enforces WPA password length 8-64 chars at the substrate
    # level (raises ValueError before any radio activity), so the
    # bogus value still has to be in-range.
    config = WifiConfig(
        ssid="chumicro-test-no-such-ap-12345",
        password="bogus-but-long-enough",
        connect_timeout_ms=2000,
    )
    result = adapter.connect(config)
    assert result is False
    assert adapter.is_linked() is False
    _stop_station_quietly()
