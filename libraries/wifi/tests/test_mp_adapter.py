"""Host-side tests for the unified ``MpWifiAdapter``.

Exercises the adapter's contract with the MicroPython
``network.WLAN(network.STA_IF)`` station handle without hardware,
on both wifi stacks the adapter supports:

* **ESP-IDF** (``stack="espidf"``) — ESP32, S2, S3, etc.
* **CYW43** (``stack="cyw43"``) — Pi Pico W, etc.

The fake mirrors the subset of the WLAN shape the adapter touches:
``active(state=None)`` (getter / setter), ``connect(ssid, password)``
(non-blocking), ``disconnect()``, ``isconnected()``, ``ifconfig()``,
``config(**kwargs)`` (the substrate's tuning knob — used to disable
the firmware auto-reconnect supervisor on ESP-IDF, the CYW43 PM-disable
knob on CYW43, and ``dhcp_hostname`` on both).

Hardware-side coverage (real WLAN against a real AP) lives under
``functional_tests/``.
"""

#: Host-lane only — exercises a runtime-specific adapter through host
#: fakes and asserts off-target behaviour; never staged to a device.
__chumicro_host_only__ = True

from chumicro_test_harness import raises
from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.mp import CYW43_PM_DISABLE, MpWifiAdapter


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
# Construction + stack detection
# ---------------------------------------------------------------------------


def test_runtime_acquisition_raises_clear_error_on_cpython() -> None:
    """Default-arg construction raises ``RuntimeError`` outside MicroPython."""
    with raises(RuntimeError):
        MpWifiAdapter(stack="cyw43")


def test_default_stack_detection_on_host_is_espidf() -> None:
    """Auto-detect falls through to ``espidf`` when machine isn't whitelisted.

    On any host (CPython, MicroPython unix-port, CircuitPython unix-port)
    the reported machine string is not a Pi Pico W entry, so the
    auto-detect path lands on ``espidf`` (the safe default — its
    ESP-specific knob has its own try/except guard).
    """
    assert MpWifiAdapter._detect_stack() == "espidf"


def test_default_stack_detection_picks_cyw43_for_pico_w_machine() -> None:
    """A whitelisted CYW43 machine string routes ``_detect_stack`` to ``cyw43``.

    Patches the module-level :func:`_get_machine_name` helper to simulate
    the Pi Pico W firmware string, then asserts ``_detect_stack`` returns
    ``cyw43`` against the whitelist.  Avoids pytest's ``monkeypatch``
    fixture so the test runs unchanged under MicroPython and CircuitPython
    unix-port runners.
    """
    import chumicro_wifi._adapters.mp as mp_mod
    original = mp_mod._get_machine_name
    mp_mod._get_machine_name = lambda: "Raspberry Pi Pico W with RP2040"
    try:
        assert MpWifiAdapter._detect_stack() == "cyw43"
    finally:
        mp_mod._get_machine_name = original


def test_construction_with_default_stack_uses_auto_detect() -> None:
    """``stack=None`` (default) routes through ``_detect_stack``.

    On any host (CPython, MP/CP unix-port) the reported machine string
    isn't in the CYW43 whitelist, so auto-detect lands on ``espidf`` and
    the resulting adapter has ``name == "mp_esp32"``.  Explicit injection
    of the wlan fake sidesteps the runtime acquisition path so the test
    runs on the host.
    """
    adapter = MpWifiAdapter(wlan=_FakeWlan())
    assert adapter.name == "mp_esp32"


def test_invalid_stack_raises_value_error() -> None:
    """``stack=`` outside the two valid identifiers raises clearly."""
    with raises(ValueError):
        MpWifiAdapter(wlan=_FakeWlan(), stack="bogus")


def test_injected_wlan_accepted_on_espidf() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    assert adapter._wlan is wlan  # noqa: SLF001 - test introspection
    assert adapter.name == "mp_esp32"


def test_injected_wlan_accepted_on_cyw43() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    assert adapter._wlan is wlan  # noqa: SLF001 - test introspection
    assert adapter.name == "mp_rp2"


# ---------------------------------------------------------------------------
# configure — radio activation, hostname (both stacks); PM knob (cyw43 only)
# ---------------------------------------------------------------------------


def test_configure_activates_radio_on_espidf() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert wlan.active() is True


def test_configure_activates_radio_on_cyw43() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert wlan.active() is True


def test_configure_sets_dhcp_hostname_when_provided_on_espidf() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert {"dhcp_hostname": "back-porch"} in wlan.config_calls


def test_configure_sets_dhcp_hostname_when_provided_on_cyw43() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert {"dhcp_hostname": "back-porch"} in wlan.config_calls


def test_configure_skips_dhcp_hostname_when_none_on_espidf() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    adapter.configure(WifiConfig(ssid="x", password="y"))
    # ESP-IDF stack with no hostname makes no config calls at all
    # at configure time (PM knob is CYW43-only).
    assert wlan.config_calls == []


def test_configure_disables_power_save_by_default_on_cyw43() -> None:
    """``power_save=False`` (default) ⇒ apply the CYW43 PM-disable magic value."""
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert {"pm": CYW43_PM_DISABLE} in wlan.config_calls


def test_configure_leaves_power_save_alone_when_user_opts_in_on_cyw43() -> None:
    """Explicit ``power_save=True`` ⇒ don't touch the firmware default."""
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    adapter.configure(WifiConfig(ssid="x", password="y", power_save=True))
    pm_calls = [call for call in wlan.config_calls if "pm" in call]
    assert pm_calls == []


def test_configure_does_not_touch_pm_knob_on_espidf() -> None:
    """ESP-IDF stack never issues the CYW43-specific PM-disable knob."""
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    adapter.configure(WifiConfig(ssid="x", password="y"))
    pm_calls = [call for call in wlan.config_calls if "pm" in call]
    assert pm_calls == []


def test_configure_tolerates_pm_oserror_on_cyw43() -> None:
    """Older MP firmware may not expose the pm knob; tolerate the failure."""
    wlan = _FakeWlan()
    original_config = wlan.config

    def _explode_on_pm(**kwargs):
        if "pm" in kwargs:
            raise OSError("simulated rejection")
        original_config(**kwargs)

    wlan.config = _explode_on_pm
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    # Should not raise.
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert wlan.active() is True


def test_configure_tolerates_hostname_oserror_on_espidf() -> None:
    """Some MP builds reject hostname mid-flight; deploy must continue."""
    wlan = _FakeWlan()
    original_config = wlan.config

    def _explode_on_hostname(**kwargs):
        if "dhcp_hostname" in kwargs:
            raise OSError("simulated rejection")
        original_config(**kwargs)

    wlan.config = _explode_on_hostname
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    # Should not raise.
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert wlan.active() is True


def test_configure_tolerates_hostname_oserror_on_cyw43() -> None:
    """Same hostname-rejection tolerance on the CYW43 branch."""
    wlan = _FakeWlan()
    original_config = wlan.config

    def _explode_on_hostname(**kwargs):
        if "dhcp_hostname" in kwargs:
            raise OSError("simulated rejection")
        original_config(**kwargs)

    wlan.config = _explode_on_hostname
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert wlan.active() is True


# ---------------------------------------------------------------------------
# connect — non-blocking on both stacks; supervisor-off only on espidf
# ---------------------------------------------------------------------------


def test_connect_dispatches_credentials_to_wlan_on_espidf() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    adapter.connect(WifiConfig(ssid="HomeNet", password="secret"))
    assert ("connect", "HomeNet", "secret") in wlan.calls


def test_connect_dispatches_credentials_to_wlan_on_cyw43() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    adapter.connect(WifiConfig(ssid="HomeNet", password="secret"))
    assert ("connect", "HomeNet", "secret") in wlan.calls


def test_connect_returns_true_when_isconnected_after_dispatch() -> None:
    """MP's connect is non-blocking; success means isconnected flipped to True."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True


def test_connect_returns_false_when_not_yet_connected() -> None:
    """Not-yet-associated is the substrate's "in progress" state — return False."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=False)
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is False


def test_connect_disables_firmware_supervisor_on_first_success_on_espidf() -> None:
    """``wlan.config(reconnects=0)`` fires once, after the first link.

    The library is the sole wifi supervisor on every runtime; the
    runtime's own auto-reconnect must be disabled at first link.
    """
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    adapter.connect(WifiConfig(ssid="x", password="y"))
    assert {"reconnects": 0} in wlan.config_calls


def test_connect_does_not_disable_supervisor_on_failed_attempt_on_espidf() -> None:
    """A failed connect leaves the substrate's auto-reconnect alone.

    The supervisor-off knob can only be set after a link is up
    (per ESP-IDF — the config is read at re-association time).
    Calling it before would silently no-op or raise.
    """
    wlan = _FakeWlan()
    wlan.set_outcome(ok=False)
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    adapter.connect(WifiConfig(ssid="x", password="y"))
    assert {"reconnects": 0} not in wlan.config_calls


def test_supervisor_disable_only_fires_once_on_espidf() -> None:
    """Subsequent successful connects don't re-issue the supervisor-off call."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    adapter.connect(WifiConfig(ssid="x", password="y"))
    adapter.connect(WifiConfig(ssid="x", password="y"))
    reconnects_calls = [call for call in wlan.config_calls if call == {"reconnects": 0}]
    assert len(reconnects_calls) == 1


def test_connect_tolerates_supervisor_disable_oserror_on_espidf() -> None:
    """Older MP firmware may not expose ``reconnects``; tolerate the failure."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    original_config = wlan.config

    def _explode_on_reconnects(**kwargs):
        if "reconnects" in kwargs:
            raise OSError("simulated rejection")
        original_config(**kwargs)

    wlan.config = _explode_on_reconnects
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    # Should not raise, should still report success.
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True


def test_connect_does_not_issue_supervisor_off_call_on_cyw43() -> None:
    """CYW43 has no firmware supervisor; no ``reconnects`` knob expected."""
    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    adapter.connect(WifiConfig(ssid="x", password="y"))
    reconnects_calls = [call for call in wlan.config_calls if "reconnects" in call]
    assert reconnects_calls == []


def test_connect_propagates_unexpected_exceptions() -> None:
    """Non-OSError errors flow through to ``WifiService.last_error``."""

    class _BoomError(Exception):
        pass

    wlan = _FakeWlan()
    wlan.set_outcome(exception=_BoomError("unexpected"))
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    with raises(_BoomError):
        adapter.connect(WifiConfig(ssid="x", password="y"))


# ---------------------------------------------------------------------------
# disconnect / is_linked / ip — same shape on both stacks
# ---------------------------------------------------------------------------


def test_disconnect_calls_wlan_disconnect() -> None:
    wlan = _FakeWlan()
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    adapter.disconnect()
    assert wlan.calls[-1] == ("disconnect",)
    assert wlan.isconnected() is False


def test_is_linked_reflects_isconnected() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    assert adapter.is_linked() is False
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    assert adapter.is_linked() is True


def test_ip_returns_none_when_not_linked() -> None:
    wlan = _FakeWlan()
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    assert adapter.ip() is None


def test_ip_returns_first_element_of_ifconfig_when_linked() -> None:
    wlan = _FakeWlan(ip="192.168.1.99")
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    assert adapter.ip() == "192.168.1.99"


def test_ip_returns_none_for_zero_address_sentinel() -> None:
    """``0.0.0.0`` is the post-association-pre-DHCP unset state — treat as None."""
    wlan = _FakeWlan(ip="0.0.0.0")
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    assert adapter.ip() is None


def test_ip_returns_none_when_ifconfig_is_empty() -> None:
    """Defensive branch: a substrate that returns falsy ``ifconfig`` reports None.

    Some MP firmware variants have been observed returning ``None``
    or ``()`` from ``ifconfig()`` mid-association.  The adapter
    treats either as "no IP yet".
    """
    wlan = _FakeWlan()
    wlan._connected = True  # noqa: SLF001 - direct fake state setup
    wlan.ifconfig = lambda: None
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    assert adapter.ip() is None


# ---------------------------------------------------------------------------
# Integration via WifiService
# ---------------------------------------------------------------------------


def test_service_drives_espidf_adapter_through_full_lifecycle() -> None:
    """A WifiService backed by the unified adapter on espidf cycles cleanly."""
    from chumicro_timing.testing import FakeTicks
    from chumicro_wifi import WifiService, WifiState

    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpWifiAdapter(wlan=wlan, stack="espidf")
    config = WifiConfig(ssid="HomeNet", password="secret", reconnect_backoff_start_ms=10)
    ticks = FakeTicks()
    service = WifiService(config, adapter=adapter, ticks=ticks)

    assert service.state == WifiState.DISCONNECTED
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED
    assert service.ip == "10.0.0.42"
    # Supervisor-off was issued exactly once (espidf-specific).
    assert {"reconnects": 0} in wlan.config_calls


def test_service_drives_cyw43_adapter_through_full_lifecycle() -> None:
    """A WifiService backed by the unified adapter on cyw43 cycles cleanly."""
    from chumicro_timing.testing import FakeTicks
    from chumicro_wifi import WifiService, WifiState

    wlan = _FakeWlan()
    wlan.set_outcome(ok=True)
    adapter = MpWifiAdapter(wlan=wlan, stack="cyw43")
    config = WifiConfig(ssid="HomeNet", password="secret", reconnect_backoff_start_ms=10)
    ticks = FakeTicks()
    service = WifiService(config, adapter=adapter, ticks=ticks)

    assert service.state == WifiState.DISCONNECTED
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED
    assert service.ip == "10.0.0.42"
    # Power-save was disabled at configure time (cyw43-specific).
    assert {"pm": CYW43_PM_DISABLE} in wlan.config_calls
    # No supervisor-off knob on cyw43.
    reconnects_calls = [call for call in wlan.config_calls if "reconnects" in call]
    assert reconnects_calls == []
