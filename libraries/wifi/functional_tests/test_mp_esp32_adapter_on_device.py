"""On-device tests for ``MpEsp32WifiAdapter`` against real ``network.WLAN``.

Runs only on MicroPython ESP32 boards.  Pi Pico W MP has no
``esp32`` module; the file's runtime guard short-circuits there
so each test is a no-op on non-ESP32 MP devices.

These tests do **not** attempt to associate with a real AP — they
target the adapter's contract with the substrate (configure /
connect / is_linked / disconnect / ip / supervisor-disable),
using a deliberate non-existent SSID so the connect call returns
``False`` without needing live wifi credentials.

Each test calls ``disconnect`` cleanup at the end so the next test
starts fresh.
"""

import sys

from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.mp_esp32 import MpEsp32WifiAdapter

_IS_MICROPYTHON = sys.implementation.name == "micropython"

if _IS_MICROPYTHON:
    try:
        import esp32  # noqa: F401
        import network
        _HAS_ESP32 = True
    except ImportError:
        _HAS_ESP32 = False
else:
    _HAS_ESP32 = False


def _disconnect_quietly():
    """Drop any active station association without complaining."""
    if not _HAS_ESP32:
        return
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.disconnect()
    except (OSError, RuntimeError):
        pass


def test_adapter_constructs_against_real_wlan() -> None:
    """Default-arg construction picks up the WLAN station handle cleanly."""
    if not _HAS_ESP32:
        return
    adapter = MpEsp32WifiAdapter()
    assert adapter.name == "mp_esp32"
    assert adapter._wlan is not None  # noqa: SLF001 - test introspection


def test_configure_activates_radio_on_real_hardware() -> None:
    """Configure brings the station up before the first connect attempt."""
    if not _HAS_ESP32:
        return
    _disconnect_quietly()
    adapter = MpEsp32WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="chu-test"))
    assert adapter._wlan.active() is True  # noqa: SLF001 - test introspection


def test_is_linked_reflects_substrate_state_when_disconnected() -> None:
    """No association → adapter reports False."""
    if not _HAS_ESP32:
        return
    _disconnect_quietly()
    adapter = MpEsp32WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert adapter.is_linked() is False


def test_ip_returns_none_when_not_linked() -> None:
    """No IP without an active link, even if the radio is active."""
    if not _HAS_ESP32:
        return
    _disconnect_quietly()
    adapter = MpEsp32WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert adapter.ip() is None


def test_connect_to_nonexistent_ssid_returns_false_without_link() -> None:
    """Substrate dispatches the request but isconnected stays False.

    MP's ``connect`` is non-blocking — the call returns immediately
    after dispatch.  ``isconnected`` then reports ``False`` until /
    unless the AP responds.  Against a non-existent SSID it never
    flips, so the adapter reports ``False`` correctly.
    """
    if not _HAS_ESP32:
        return
    _disconnect_quietly()
    adapter = MpEsp32WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    config = WifiConfig(
        ssid="chumicro-test-no-such-ap-12345",
        password="bogus-but-long-enough",
    )
    result = adapter.connect(config)
    assert result is False
    assert adapter.is_linked() is False
    _disconnect_quietly()


def test_disconnect_after_configure_is_safe() -> None:
    """Disconnect must succeed even when no association is live."""
    if not _HAS_ESP32:
        return
    _disconnect_quietly()
    adapter = MpEsp32WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    # Should not raise even though there's nothing to disconnect.
    adapter.disconnect()
    assert adapter.is_linked() is False
