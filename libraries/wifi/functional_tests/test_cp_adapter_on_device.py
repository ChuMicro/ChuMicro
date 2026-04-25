"""On-device tests for ``CpWifiAdapter`` against real ``wifi.radio``.

Runs only on CircuitPython boards.  These tests do **not** attempt
to associate with a real AP — they target the contract between the
adapter and the substrate (configure / connect / is_linked /
disconnect / ip), using a deliberate non-existent SSID so the
connect call returns ``False`` within the configured timeout
without needing live wifi credentials.

Each test resets the radio to a known state at the end so the next
test starts clean.
"""

import sys

from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.cp import CpWifiAdapter

_IS_CIRCUITPYTHON = sys.implementation.name == "circuitpython"

if _IS_CIRCUITPYTHON:
    import wifi


def _stop_station_quietly():
    """Drop any active association without complaining if there is none."""
    try:
        wifi.radio.stop_station()
    except (OSError, RuntimeError):
        pass


def test_adapter_constructs_against_real_radio() -> None:
    """Default-arg construction picks up ``wifi.radio`` cleanly on CP."""
    if not _IS_CIRCUITPYTHON:
        return
    adapter = CpWifiAdapter()
    assert adapter.name == "cp"
    assert adapter._radio is wifi.radio  # noqa: SLF001 - test introspection


def test_configure_sets_hostname_on_real_radio() -> None:
    """Hostname write reaches the substrate before any connect attempt."""
    if not _IS_CIRCUITPYTHON:
        return
    _stop_station_quietly()
    adapter = CpWifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="chu-test"))
    assert wifi.radio.hostname == "chu-test"


def test_is_linked_reflects_radio_state_when_disconnected() -> None:
    """Without an active association the adapter reports ``False``."""
    if not _IS_CIRCUITPYTHON:
        return
    _stop_station_quietly()
    adapter = CpWifiAdapter()
    assert adapter.is_linked() is False


def test_ip_returns_none_when_not_connected() -> None:
    """No IP without a link, regardless of any prior state."""
    if not _IS_CIRCUITPYTHON:
        return
    _stop_station_quietly()
    adapter = CpWifiAdapter()
    assert adapter.ip() is None


def test_connect_to_nonexistent_ssid_returns_false_within_timeout() -> None:
    """Substrate timeout/refusal maps to a clean ``False``.

    Targets one of the open device-verification questions in the
    workstream Phase 3a doc: "How long does CP's blocking connect
    stall on a routable-but-unresponsive AP?"  Using a deliberate
    non-existent SSID with a short timeout exercises the
    substrate's failure path on real hardware without needing live
    wifi.  Wraps the call in ``stop_station`` cleanup so the next
    test starts fresh.
    """
    if not _IS_CIRCUITPYTHON:
        return
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


def test_disconnect_after_failed_connect_is_safe() -> None:
    """Disconnect must succeed even when no association is live."""
    if not _IS_CIRCUITPYTHON:
        return
    _stop_station_quietly()
    adapter = CpWifiAdapter()
    # Should not raise even though there's nothing to disconnect.
    adapter.disconnect()
    assert adapter.is_linked() is False
