"""Host-side tests for ``MpEsp32WifiAdapter`` via WLAN injection.

Exercises the adapter's contract with the MicroPython
``network.WLAN(network.STA_IF)`` station handle without an
ESP32 board.  The fake mirrors the subset of the WLAN shape the
adapter touches: ``active(state=None)`` (getter / setter),
``connect(ssid, password)`` (non-blocking),
``disconnect()``, ``isconnected()``, ``ifconfig()``,
``config(**kwargs)`` (the substrate's tuning knob — used to
disable the firmware auto-reconnect supervisor and to set
``dhcp_hostname``).

Hardware-side coverage (real WLAN against a real AP) lives under
``functional_tests/``.
"""

from chumicro_test_harness import raises
from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.mp_esp32 import MpEsp32WifiAdapter


class _FakeWlan:
    """Minimal stand-in for ``network.WLAN`` for host tests."""

    def __init__(self, *, ip="10.0.0.42"):
        self._active = False
        self._connected = False
        self._ip = ip
        self._connect_outcome = True
        self._connect_exception = None
        self.calls = []
        self.config_calls = []

    def active(self, state=None):
        if state is not None:
            self._active = bool(state)
            self.calls.append(("active", state))
        return self._active

    def connect(self, ssid, password):
        self.calls.append(("connect", ssid, password))
        if self._connect_exception is not None:
            raise self._connect_exception
        self._connected = bool(self._connect_outcome)

    def disconnect(self):
        self.calls.append(("disconnect",))
        self._connected = False

    def isconnected(self):
        return self._connected

    def ifconfig(self):
        if not self._connected:
            return ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")
        return (self._ip, "255.255.255.0", "10.0.0.1", "10.0.0.1")

    def config(self, **kwargs):
        self.config_calls.append(kwargs)

    def set_outcome(self, *, ok=None, exception=None):
        self._connect_outcome = ok if ok is not None else True
        self._connect_exception = exception


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_runtime_acquisition_raises_clear_error_on_cpython() -> None:
    """Default-arg construction raises ``RuntimeError`` outside MicroPython."""
    with raises(RuntimeError):
        MpEsp32WifiAdapter()


def test_injected_wlan_accepted() -> None:
    wlan = _FakeWlan()
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    assert adapter._wlan is wlan  # noqa: SLF001 - test introspection
    assert adapter.name == "mp_esp32"


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------


def test_configure_activates_radio() -> None:
    wlan = _FakeWlan()
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert wlan.active() is True


def test_configure_sets_dhcp_hostname_when_provided() -> None:
    wlan = _FakeWlan()
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert {"dhcp_hostname": "back-porch"} in wlan.config_calls


def test_configure_skips_dhcp_hostname_when_none() -> None:
    wlan = _FakeWlan()
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert wlan.config_calls == []


def test_configure_tolerates_hostname_oserror() -> None:
    """Some MP builds reject hostname mid-flight; deploy must continue."""
    wlan = _FakeWlan()
    original_config = wlan.config

    def _explode_on_hostname(**kwargs):
        if "dhcp_hostname" in kwargs:
            raise OSError("simulated rejection")
        original_config(**kwargs)

    wlan.config = _explode_on_hostname
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    # Should not raise.
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert wlan.active() is True


# ---------------------------------------------------------------------------
# connect — non-blocking + supervisor-disable on first link
# ---------------------------------------------------------------------------


def test_connect_dispatches_credentials_to_wlan() -> None:
    wlan = _FakeWlan()
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    adapter.connect(WifiConfig(ssid="HomeNet", password="secret"))
    assert ("connect", "HomeNet", "secret") in wlan.calls


def test_connect_returns_true_when_isconnected_after_dispatch() -> None:
    """MP's connect is non-blocking; success means isconnected flipped to True."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True


def test_connect_returns_false_when_not_yet_connected() -> None:
    """Not-yet-associated is the substrate's "in progress" state — return False."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=False)
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is False


def test_connect_disables_firmware_supervisor_on_first_success() -> None:
    """``wlan.config(reconnects=0)`` fires once, after the first link.

    Decision 0029 §wifi-ownership-stance — library is the sole
    supervisor on every runtime.
    """
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    adapter.connect(WifiConfig(ssid="x", password="y"))
    assert {"reconnects": 0} in wlan.config_calls


def test_connect_does_not_disable_supervisor_on_failed_attempt() -> None:
    """A failed connect leaves the substrate's auto-reconnect alone.

    The supervisor-off knob can only be set after a link is up
    (per ESP-IDF — the config is read at re-association time).
    Calling it before would silently no-op or raise.
    """
    wlan = _FakeWlan()
    wlan.set_outcome(ok=False)
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    adapter.connect(WifiConfig(ssid="x", password="y"))
    assert {"reconnects": 0} not in wlan.config_calls


def test_supervisor_disable_only_fires_once() -> None:
    """Subsequent successful connects don't re-issue the supervisor-off call."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    adapter.connect(WifiConfig(ssid="x", password="y"))
    adapter.connect(WifiConfig(ssid="x", password="y"))
    reconnects_calls = [call for call in wlan.config_calls if call == {"reconnects": 0}]
    assert len(reconnects_calls) == 1


def test_connect_tolerates_supervisor_disable_oserror() -> None:
    """Older MP firmware may not expose ``reconnects``; tolerate the failure."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    original_config = wlan.config

    def _explode_on_reconnects(**kwargs):
        if "reconnects" in kwargs:
            raise OSError("simulated rejection")
        original_config(**kwargs)

    wlan.config = _explode_on_reconnects
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    # Should not raise, should still report success.
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True


def test_connect_propagates_unexpected_exceptions() -> None:
    """Non-OSError errors flow through to ``WifiService.last_error``."""

    class _BoomError(Exception):
        pass

    wlan = _FakeWlan()
    wlan.set_outcome(exception=_BoomError("unexpected"))
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    with raises(_BoomError):
        adapter.connect(WifiConfig(ssid="x", password="y"))


# ---------------------------------------------------------------------------
# disconnect / is_linked / ip
# ---------------------------------------------------------------------------


def test_disconnect_calls_wlan_disconnect() -> None:
    wlan = _FakeWlan()
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    adapter.disconnect()
    assert wlan.calls[-1] == ("disconnect",)
    assert wlan.isconnected() is False


def test_is_linked_reflects_isconnected() -> None:
    wlan = _FakeWlan()
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    assert adapter.is_linked() is False
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    assert adapter.is_linked() is True


def test_ip_returns_none_when_not_linked() -> None:
    wlan = _FakeWlan()
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    assert adapter.ip() is None


def test_ip_returns_first_element_of_ifconfig_when_linked() -> None:
    wlan = _FakeWlan(ip="192.168.1.99")
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    assert adapter.ip() == "192.168.1.99"


def test_ip_returns_none_for_zero_address_sentinel() -> None:
    """``0.0.0.0`` is the post-association-pre-DHCP unset state — treat as None."""
    wlan = _FakeWlan(ip="0.0.0.0")
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    assert adapter.ip() is None


# ---------------------------------------------------------------------------
# Integration via WifiService
# ---------------------------------------------------------------------------


def test_service_drives_mp_esp32_adapter_through_full_lifecycle() -> None:
    """A WifiService backed by the MP ESP32 adapter cycles cleanly with the fake."""
    from chumicro_timing.testing import FakeTicks
    from chumicro_wifi import WifiService, WifiState

    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpEsp32WifiAdapter(wlan=wlan)
    config = WifiConfig(ssid="HomeNet", password="secret", reconnect_backoff_start_ms=10)
    ticks = FakeTicks()
    service = WifiService(config, adapter=adapter, ticks=ticks)

    assert service.state == WifiState.DISCONNECTED
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED
    assert service.ip == "10.0.0.42"
    # Supervisor-off was issued exactly once.
    assert {"reconnects": 0} in wlan.config_calls
