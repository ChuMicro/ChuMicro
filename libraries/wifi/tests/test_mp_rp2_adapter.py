"""Host-side tests for ``MpRp2WifiAdapter`` via WLAN injection.

Exercises the adapter's contract with the MicroPython
``network.WLAN(network.STA_IF)`` station handle on a CYW43-based
board (Pi Pico W) without hardware.

Hardware-side coverage (real WLAN against a real AP) lives under
``functional_tests/``.
"""

from chumicro_test_harness import raises
from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.mp_rp2 import CYW43_PM_DISABLE, MpRp2WifiAdapter


class _FakeWlan:
    """Minimal stand-in for ``network.WLAN`` for host tests.

    Same shape as the ESP32 fake (the substrate API is identical
    between the two MP wifi stacks); duplicated here rather than
    importing the ESP32 file's fake to keep the per-substrate
    test files independent.
    """

    def __init__(self, *, ip="10.0.0.42"):
        self._active = False
        self._connected = False
        self._ip = ip
        self.calls = []
        self.config_calls = []

    def active(self, state=None):
        if state is not None:
            self._active = bool(state)
            self.calls.append(("active", state))
        return self._active

    def connect(self, ssid, password):
        self.calls.append(("connect", ssid, password))
        self._connected = True

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


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_runtime_acquisition_raises_clear_error_on_cpython() -> None:
    """Default-arg construction raises ``RuntimeError`` outside MicroPython."""
    with raises(RuntimeError):
        MpRp2WifiAdapter()


def test_injected_wlan_accepted() -> None:
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    assert adapter._wlan is wlan  # noqa: SLF001 - test introspection
    assert adapter.name == "mp_rp2"


# ---------------------------------------------------------------------------
# configure — radio activation, hostname, CYW43 power-save knob
# ---------------------------------------------------------------------------


def test_configure_activates_radio() -> None:
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert wlan.active() is True


def test_configure_sets_dhcp_hostname_when_provided() -> None:
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert {"dhcp_hostname": "back-porch"} in wlan.config_calls


def test_configure_disables_power_save_by_default() -> None:
    """``power_save=False`` (default) ⇒ apply the CYW43 PM-disable magic value."""
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert {"pm": CYW43_PM_DISABLE} in wlan.config_calls


def test_configure_leaves_power_save_alone_when_user_opts_in() -> None:
    """Explicit ``power_save=True`` ⇒ don't touch the firmware default."""
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    adapter.configure(WifiConfig(ssid="x", password="y", power_save=True))
    pm_calls = [call for call in wlan.config_calls if "pm" in call]
    assert pm_calls == []


def test_configure_tolerates_pm_oserror() -> None:
    """Older MP firmware may not expose the pm knob; tolerate the failure."""
    wlan = _FakeWlan()
    original_config = wlan.config

    def _explode_on_pm(**kwargs):
        if "pm" in kwargs:
            raise OSError("simulated rejection")
        original_config(**kwargs)

    wlan.config = _explode_on_pm
    adapter = MpRp2WifiAdapter(wlan=wlan)
    # Should not raise.
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert wlan.active() is True


def test_configure_tolerates_hostname_oserror() -> None:
    """Some MP builds reject hostname mid-flight; deploy must continue."""
    wlan = _FakeWlan()
    original_config = wlan.config

    def _explode_on_hostname(**kwargs):
        if "dhcp_hostname" in kwargs:
            raise OSError("simulated rejection")
        original_config(**kwargs)

    wlan.config = _explode_on_hostname
    adapter = MpRp2WifiAdapter(wlan=wlan)
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert wlan.active() is True


# ---------------------------------------------------------------------------
# connect — non-blocking, no supervisor-off (CYW43 has no firmware supervisor)
# ---------------------------------------------------------------------------


def test_connect_dispatches_credentials_to_wlan() -> None:
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    adapter.connect(WifiConfig(ssid="HomeNet", password="secret"))
    assert ("connect", "HomeNet", "secret") in wlan.calls


def test_connect_returns_true_when_isconnected() -> None:
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True


def test_connect_does_not_issue_supervisor_off_call() -> None:
    """CYW43 has no firmware supervisor; no ``reconnects`` knob expected."""
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    adapter.connect(WifiConfig(ssid="x", password="y"))
    reconnects_calls = [call for call in wlan.config_calls if "reconnects" in call]
    assert reconnects_calls == []


# ---------------------------------------------------------------------------
# disconnect / is_linked / ip
# ---------------------------------------------------------------------------


def test_disconnect_calls_wlan_disconnect() -> None:
    wlan = _FakeWlan()
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpRp2WifiAdapter(wlan=wlan)
    adapter.disconnect()
    assert wlan.calls[-1] == ("disconnect",)
    assert wlan.isconnected() is False


def test_is_linked_reflects_isconnected() -> None:
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    assert adapter.is_linked() is False
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    assert adapter.is_linked() is True


def test_ip_returns_none_when_not_linked() -> None:
    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    assert adapter.ip() is None


def test_ip_returns_first_element_of_ifconfig_when_linked() -> None:
    wlan = _FakeWlan(ip="192.168.1.99")
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpRp2WifiAdapter(wlan=wlan)
    assert adapter.ip() == "192.168.1.99"


def test_ip_returns_none_for_zero_address_sentinel() -> None:
    """``0.0.0.0`` is the post-association-pre-DHCP unset state — treat as None."""
    wlan = _FakeWlan(ip="0.0.0.0")
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpRp2WifiAdapter(wlan=wlan)
    assert adapter.ip() is None


# ---------------------------------------------------------------------------
# Integration via WifiService
# ---------------------------------------------------------------------------


def test_service_drives_mp_rp2_adapter_through_full_lifecycle() -> None:
    """A WifiService backed by the MP RP2 adapter cycles cleanly with the fake."""
    from chumicro_timing.testing import FakeTicks
    from chumicro_wifi import WifiService, WifiState

    wlan = _FakeWlan()
    adapter = MpRp2WifiAdapter(wlan=wlan)
    config = WifiConfig(ssid="HomeNet", password="secret", reconnect_backoff_start_ms=10)
    ticks = FakeTicks()
    service = WifiService(config, adapter=adapter, ticks=ticks)

    assert service.state == WifiState.DISCONNECTED
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED
    assert service.ip == "10.0.0.42"
    # Power-save was disabled at configure time.
    assert {"pm": CYW43_PM_DISABLE} in wlan.config_calls
