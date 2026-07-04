"""On-device tests for the unified ``MpWifiAdapter`` against real ``network.WLAN``.

Runs on every MicroPython board with a wifi chip, covering both
ESP-IDF stacks (Lolin S2, ESP32 family) and CYW43 stacks (Pi Pico W).
The module-level ``__chumicro_runtimes__ = ("micropython",)`` marker
keeps CP boards out at collection time.  Every supported MP target
ships ``network``, so the module imports it directly.  If a future
target lacks it we'll add ``__chumicro_features__ = ("mp_network",)``
and probe for it.

Stack-specific assertions (PM constant value, supervisor-disable
knob) are guarded by the detected stack so they only run on the
relevant board.

These tests do **not** attempt to associate with a real AP.  They
target the adapter's contract with the substrate (configure /
connect / is_linked / ip / per-stack knobs), using a deliberate
non-existent SSID so the connect call returns ``False`` without
needing live wifi credentials.

Each test drops the station link at the end (``_disconnect_quietly``,
reaching the WLAN substrate directly) so the next test starts fresh.
"""

__chumicro_runtimes__ = ("micropython",)

import network
from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.mp import CYW43_PM_DISABLE, MpWifiAdapter

try:
    import esp32  # noqa: F401
    _DETECTED_STACK = "espidf"
except ImportError:
    _DETECTED_STACK = "cyw43"


def _disconnect_quietly():
    """Drop any active station association without complaining."""
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.disconnect()
    except (OSError, RuntimeError):
        pass


def test_adapter_constructs_against_real_wlan() -> None:
    """Default-arg construction picks up the WLAN station handle cleanly.

    Auto-detects the stack and surfaces the corresponding ``name``
    string: ``"mp_esp32"`` on ESP-IDF, ``"mp_rp2"`` on CYW43.
    """
    adapter = MpWifiAdapter()
    expected_name = "mp_esp32" if _DETECTED_STACK == "espidf" else "mp_rp2"
    assert adapter.name == expected_name
    assert adapter._wlan is not None  # noqa: SLF001 - test introspection


def test_configure_activates_radio_on_real_hardware() -> None:
    """Configure brings the station up before the first connect attempt.

    On CYW43 it also applies the PM-disable knob.  On ESP-IDF that
    branch is a no-op.  Either way the substrate accepts the
    config calls without raising.
    """
    _disconnect_quietly()
    adapter = MpWifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="chu-test"))
    assert adapter._wlan.active() is True  # noqa: SLF001 - test introspection


def test_is_linked_reflects_substrate_state_when_disconnected() -> None:
    """No association means the adapter reports ``False``."""
    _disconnect_quietly()
    adapter = MpWifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert adapter.is_linked() is False


def test_ip_returns_none_when_not_linked() -> None:
    """No IP without an active link, even if the radio is active."""
    _disconnect_quietly()
    adapter = MpWifiAdapter()
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert adapter.ip() is None


def test_connect_to_nonexistent_ssid_returns_false_without_link() -> None:
    """Substrate dispatches the request but isconnected stays False.

    MP's ``connect`` is non-blocking, so the call returns immediately
    after dispatch.  ``isconnected`` then reports ``False`` until /
    unless the AP responds.  Against a non-existent SSID it never
    flips, so the adapter reports ``False`` correctly on either
    stack.
    """
    _disconnect_quietly()
    adapter = MpWifiAdapter()
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
    """Pin ``CYW43_PM_DISABLE`` against accidental drift."""
    assert CYW43_PM_DISABLE == 0xA11140
