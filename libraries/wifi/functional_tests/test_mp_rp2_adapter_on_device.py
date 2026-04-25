"""On-device tests for ``MpRp2WifiAdapter`` against real CYW43 ``network.WLAN``.

Runs only on MicroPython boards with a CYW43 chip (Pi Pico W and
similar).  Lolin S2 MP has the ``esp32`` module so the file's
runtime guard skips it there — each test is a no-op on
non-CYW43 boards.

These tests do **not** attempt to associate with a real AP — they
target the adapter's contract with the substrate (configure
including the CYW43 PM-disable knob / connect / is_linked /
disconnect / ip), using a deliberate non-existent SSID for the
substrate-failure path.
"""

import sys

from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.mp_rp2 import CYW43_PM_DISABLE, MpRp2WifiAdapter

_IS_MICROPYTHON = sys.implementation.name == "micropython"

if _IS_MICROPYTHON:
    import network
    try:
        import esp32  # noqa: F401
        _IS_CYW43_BOARD = False  # ESP32 boards have esp32; we want non-ESP32 MP only
    except ImportError:
        _IS_CYW43_BOARD = True
else:
    _IS_CYW43_BOARD = False


def _disconnect_quietly():
    """Drop any active station association without complaining."""
    if not _IS_CYW43_BOARD:
        return
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.disconnect()
    except (OSError, RuntimeError):
        pass


def test_adapter_constructs_against_real_wlan() -> None:
    """Default-arg construction picks up the CYW43 WLAN handle cleanly."""
    if not _IS_CYW43_BOARD:
        return
    adapter = MpRp2WifiAdapter()
    assert adapter.name == "mp_rp2"
    assert adapter._wlan is not None  # noqa: SLF001 - test introspection


def test_configure_activates_radio_and_sets_pm_knob() -> None:
    """Configure brings the station up + applies the PM-disable knob."""
    if not _IS_CYW43_BOARD:
        return
    _disconnect_quietly()
    adapter = MpRp2WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="chu-test"))
    assert adapter._wlan.active() is True  # noqa: SLF001 - test introspection
    # PM knob actually applied — substrate accepts the magic value.
    # (Can't directly observe the chip's mode, but the call having
    # not raised confirms the substrate accepted it.)


def test_is_linked_reflects_substrate_state_when_disconnected() -> None:
    """No association → adapter reports False."""
    if not _IS_CYW43_BOARD:
        return
    _disconnect_quietly()
    adapter = MpRp2WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert adapter.is_linked() is False


def test_ip_returns_none_when_not_linked() -> None:
    """No IP without an active link, even if the radio is active."""
    if not _IS_CYW43_BOARD:
        return
    _disconnect_quietly()
    adapter = MpRp2WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert adapter.ip() is None


def test_connect_to_nonexistent_ssid_returns_false_without_link() -> None:
    """Substrate dispatches the request but isconnected stays False.

    Same pattern as the ESP32 functional test: MP's connect is
    non-blocking, isconnected never flips against a non-existent
    SSID, the adapter reports False correctly.
    """
    if not _IS_CYW43_BOARD:
        return
    _disconnect_quietly()
    adapter = MpRp2WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    config = WifiConfig(
        ssid="chumicro-test-no-such-ap-12345",
        password="bogus-but-long-enough",
    )
    result = adapter.connect(config)
    assert result is False
    assert adapter.is_linked() is False
    _disconnect_quietly()


def test_pm_constant_value_matches_cyw43_disable_magic() -> None:
    """``CYW43_PM_DISABLE`` is the published magic value for power-save off.

    Confirms drift hasn't crept into the constant.  Value comes
    from CYW43 vendor docs; community measurements confirm the
    responsiveness improvement.
    """
    assert CYW43_PM_DISABLE == 0xA11140


def test_disconnect_after_configure_is_safe() -> None:
    """Disconnect must succeed even when no association is live."""
    if not _IS_CYW43_BOARD:
        return
    _disconnect_quietly()
    adapter = MpRp2WifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    adapter.disconnect()
    assert adapter.is_linked() is False
