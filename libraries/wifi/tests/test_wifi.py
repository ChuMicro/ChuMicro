"""Tests for ``chumicro_wifi``: config + state machine + reconnect supervisor.

Cross-runtime: runs on CPython pytest, and under MicroPython +
CircuitPython unix-ports via ``pytest libraries/wifi/tests --target
unix-port`` (the ``chumicro-pytest-device`` plugin's unix-port
backend).

Three test surfaces:

1. ``WifiConfig`` round-trips through ``from_config`` /
   ``try_from_config`` against the flat-key runtime config the
   ``chumicro-config`` library exposes.
2. ``WifiService`` state machine drives correctly through
   DISCONNECTED → CONNECTING → CONNECTED → RECONNECTING transitions
   under a ``FakeWifiAdapter``.
3. The reconnect supervisor's exponential-backoff math + the
   ``reconnect_max`` cap fire as documented.
"""

import sys

from chumicro_config import MissingConfigKey, RuntimeConfig
from chumicro_test_harness import raises, skip
from chumicro_timing.testing import FakeTicks
from chumicro_wifi import WifiConfig, WifiService, WifiState
from chumicro_wifi.testing import FakeWifi, FakeWifiAdapter

_IS_CPYTHON = sys.implementation.name == "cpython"


# ---------------------------------------------------------------------------
# WifiConfig: direct construction + from_config via chumicro-config
# ---------------------------------------------------------------------------


def test_wifi_config_direct_construction_with_required_only() -> None:
    """Direct kwargs construction with just required keys works."""
    config = WifiConfig(ssid="HomeNet", password="secret")
    assert config.ssid == "HomeNet"
    assert config.password == "secret"
    assert config.hostname is None
    assert config.connect_timeout_ms == 15_000
    assert config.power_save is False
    assert config.tx_power_dbm is None


def test_wifi_config_from_config_required_only_via_dict() -> None:
    """``from_config`` reads ``wifi.<key>`` flat keys + applies defaults."""
    config = WifiConfig.from_config(
        {"wifi.ssid": "HomeNet", "wifi.password": "secret"},
    )
    assert config.ssid == "HomeNet"
    assert config.password == "secret"
    assert config.hostname is None
    assert config.reconnect_backoff_max_ms == 60_000


def test_wifi_config_from_config_via_runtime_config_wrapper() -> None:
    """Reads through the ``RuntimeConfig`` wrapper too, with the same semantics."""
    runtime = RuntimeConfig(
        {"wifi.ssid": "HomeNet", "wifi.password": "secret"},
    )
    config = WifiConfig.from_config(runtime)
    assert config.ssid == "HomeNet"
    assert config.password == "secret"


def test_wifi_config_from_config_all_keys() -> None:
    """Optional keys override their defaults when present."""
    config = WifiConfig.from_config(
        {
            "wifi.ssid": "HomeNet",
            "wifi.password": "secret",
            "wifi.hostname": "back-porch",
            "wifi.connect_timeout_ms": 5_000,
            "wifi.reconnect_backoff_start_ms": 500,
            "wifi.reconnect_backoff_max_ms": 30_000,
            "wifi.reconnect_max": 10,
            "wifi.power_save": True,
            "wifi.tx_power_dbm": 15,
        },
    )
    assert config.hostname == "back-porch"
    assert config.connect_timeout_ms == 5_000
    assert config.reconnect_backoff_start_ms == 500
    assert config.reconnect_max == 10
    assert config.power_save is True
    assert config.tx_power_dbm == 15


def test_wifi_config_from_config_missing_ssid_raises() -> None:
    """Missing required ``wifi.ssid`` raises via ``load_section``."""
    with raises(MissingConfigKey):
        WifiConfig.from_config({"wifi.password": "secret"})


def test_wifi_config_from_config_missing_password_raises() -> None:
    """Missing required ``wifi.password`` raises via ``load_section``."""
    with raises(MissingConfigKey):
        WifiConfig.from_config({"wifi.ssid": "HomeNet"})


def test_wifi_config_from_config_unknown_keys_ignored() -> None:
    """Unrelated flat keys pass through silently (forward-compat)."""
    config = WifiConfig.from_config(
        {
            "wifi.ssid": "x",
            "wifi.password": "y",
            "wifi.future_key": "ignored",
            "app.unrelated": "irrelevant",
        },
    )
    assert config.ssid == "x"
    assert not hasattr(config, "future_key")


def test_wifi_config_try_from_config_returns_config_when_keys_present() -> None:
    """``try_from_config`` builds the config when wifi keys are present."""
    runtime_config = {"wifi.ssid": "Net", "wifi.password": "pw"}
    result = WifiConfig.try_from_config(runtime_config)
    assert result is not None
    assert result.ssid == "Net"
    assert result.password == "pw"


def test_wifi_config_try_from_config_returns_none_when_runtime_config_is_none() -> None:
    """``runtime_config=None`` returns ``None`` (no /runtime_config.msgpack deployed)."""
    assert WifiConfig.try_from_config(None) is None


def test_wifi_config_try_from_config_returns_none_when_keys_missing() -> None:
    """A flat config with no ``wifi.*`` keys returns ``None``."""
    assert WifiConfig.try_from_config({"mqtt.broker.host": "x"}) is None


def test_wifi_config_try_from_config_returns_none_when_required_key_missing() -> None:
    """A flat config with only ``wifi.hostname`` returns ``None``."""
    assert WifiConfig.try_from_config({"wifi.hostname": "x"}) is None


# ---------------------------------------------------------------------------
# WifiState: sentinel constants
# ---------------------------------------------------------------------------


def test_wifi_state_constants_are_strings() -> None:
    """Plain-string sentinels for cross-runtime portability (no enum import)."""
    assert WifiState.DISCONNECTED == "disconnected"
    assert WifiState.CONNECTING == "connecting"
    assert WifiState.CONNECTED == "connected"
    assert WifiState.RECONNECTING == "reconnecting"
    assert WifiState.FAILED == "failed"


# ---------------------------------------------------------------------------
# WifiService: happy-path state machine via FakeWifiAdapter
# ---------------------------------------------------------------------------


def _service(*, config_overrides=None):
    """Build a WifiService against a FakeWifiAdapter + FakeTicks for tests."""
    base = {
        "ssid": "testnet",
        "password": "password",
        "reconnect_backoff_start_ms": 10,
        "reconnect_backoff_max_ms": 100,
    }
    if config_overrides is not None:
        base.update(config_overrides)
    config = WifiConfig(**base)
    ticks = FakeTicks()
    adapter = FakeWifiAdapter()
    service = WifiService(config, adapter=adapter, ticks=ticks)
    return service, ticks, adapter


def test_starts_in_disconnected_state() -> None:
    """Construction does not auto-connect."""
    service, _, adapter = _service()
    assert service.state == WifiState.DISCONNECTED
    assert service.connected is False
    assert service.ip is None
    assert ("configure",) == adapter.calls[0][:1]


def test_connect_succeeds_on_first_attempt() -> None:
    """Successful connect transitions DISCONNECTED → CONNECTING → CONNECTED."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcome(True)
    now = ticks.ticks_ms()
    assert service.check(now) is True
    service.handle(now)
    assert service.state == WifiState.CONNECTED
    assert service.connected is True
    assert service.ip == "192.168.0.42"
    assert service.last_error is None


def test_check_returns_false_when_connected_and_link_up() -> None:
    """A linked connection is steady-state, with no work for the runner."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcome(True)
    service.handle(ticks.ticks_ms())
    assert service.check(ticks.ticks_ms()) is False


def test_link_drop_triggers_reconnect_path() -> None:
    """A dropped link transitions CONNECTED → RECONNECTING."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcome(True)
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED

    adapter.drop_link()
    assert service.check(ticks.ticks_ms()) is True
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.RECONNECTING


def test_reconnect_backs_off_then_succeeds() -> None:
    """RECONNECTING attempts + backoff + eventual success returns to CONNECTED."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcomes([True, False, False, True])
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED

    adapter.drop_link()
    service.handle(ticks.ticks_ms())  # detect drop, schedule reconnect
    assert service.state == WifiState.RECONNECTING

    # First reconnect attempt (False), schedules backoff.
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.RECONNECTING

    # Advance past backoff, second attempt (False).
    ticks.advance(20)
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.RECONNECTING

    # Advance past doubled backoff, third attempt (True), back to CONNECTED.
    ticks.advance(50)
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED


# ---------------------------------------------------------------------------
# WifiService: failure paths
# ---------------------------------------------------------------------------


def test_adapter_exception_stored_in_last_error() -> None:
    """Adapter exceptions don't propagate.  They surface via ``last_error``."""

    class _BoomError(Exception):
        pass

    service, ticks, adapter = _service()
    adapter.set_connect_outcome(_BoomError)
    service.handle(ticks.ticks_ms())
    # Connect raised: state stays CONNECTING, error stored.
    assert isinstance(service.last_error, _BoomError)
    assert service.state == WifiState.CONNECTING


def test_reconnect_max_caps_attempts_at_failed() -> None:
    """Hitting ``reconnect_max`` failed attempts transitions to FAILED."""
    service, ticks, adapter = _service(config_overrides={"reconnect_max": 3})
    adapter.set_connect_outcome(False)

    for _ in range(3):
        service.handle(ticks.ticks_ms())
        ticks.advance(200)

    assert service.state == WifiState.FAILED
    assert service.check(ticks.ticks_ms()) is False


def test_failed_state_does_not_self_recover() -> None:
    """Once FAILED, neither ``check`` nor ``handle`` resumes attempts."""
    service, ticks, adapter = _service(config_overrides={"reconnect_max": 1})
    adapter.set_connect_outcome(False)
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.FAILED

    adapter.set_connect_outcome(True)
    ticks.advance(10_000)
    assert service.check(ticks.ticks_ms()) is False
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.FAILED


def test_check_handles_too_early_handle_call_idempotently() -> None:
    """Calling ``handle`` before ``check`` is true is a no-op."""
    service, ticks, _ = _service()
    # In DISCONNECTED, check is true immediately (next_attempt_due_ms == now).
    # But right after a failed attempt, check is false.  Verify handle does
    # nothing if invoked between scheduled attempts.
    service._next_attempt_due_ms = ticks.ticks_ms() + 1_000_000  # noqa: SLF001
    service.state = WifiState.RECONNECTING
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.RECONNECTING


# ---------------------------------------------------------------------------
# WifiService: backoff math
# ---------------------------------------------------------------------------


def test_backoff_doubles_until_max() -> None:
    """Successive failures double the backoff up to ``reconnect_backoff_max_ms``."""
    service, ticks, adapter = _service(
        config_overrides={
            "reconnect_backoff_start_ms": 10,
            "reconnect_backoff_max_ms": 80,
        },
    )
    adapter.set_connect_outcome(False)

    # First failed attempt, backoff is the start value.
    start = ticks.ticks_ms()
    service.handle(start)
    assert service._next_attempt_due_ms == start + 10  # noqa: SLF001

    # Second attempt, backoff doubled to 20.
    ticks.advance(20)
    service.handle(ticks.ticks_ms())
    assert service._next_attempt_due_ms == ticks.ticks_ms() + 20  # noqa: SLF001

    # Third attempt, doubled to 40.
    ticks.advance(40)
    service.handle(ticks.ticks_ms())
    assert service._next_attempt_due_ms == ticks.ticks_ms() + 40  # noqa: SLF001

    # Fourth attempt, capped at 80.
    ticks.advance(80)
    service.handle(ticks.ticks_ms())
    assert service._next_attempt_due_ms == ticks.ticks_ms() + 80  # noqa: SLF001

    # Fifth attempt, still capped at 80.
    ticks.advance(80)
    service.handle(ticks.ticks_ms())
    assert service._next_attempt_due_ms == ticks.ticks_ms() + 80  # noqa: SLF001


def test_successful_connect_resets_backoff() -> None:
    """A successful connect after retries resets the backoff to start_ms."""
    service, ticks, adapter = _service(
        config_overrides={
            "reconnect_backoff_start_ms": 10,
            "reconnect_backoff_max_ms": 80,
        },
    )
    adapter.set_connect_outcomes([False, False, True])

    service.handle(ticks.ticks_ms())  # fail 1
    ticks.advance(20)
    service.handle(ticks.ticks_ms())  # fail 2, backoff at 20
    ticks.advance(40)
    service.handle(ticks.ticks_ms())  # success, resets

    assert service._current_backoff_ms == 10  # noqa: SLF001
    assert service.state == WifiState.CONNECTED


# ---------------------------------------------------------------------------
# WifiService: state-change callback
# ---------------------------------------------------------------------------


def test_on_state_change_fires_for_each_transition() -> None:
    """Registered callbacks see every (old, new) transition in order."""
    transitions = []
    service, ticks, adapter = _service()
    service.on_state_change(lambda old, new: transitions.append((old, new)))
    adapter.set_connect_outcome(True)

    service.handle(ticks.ticks_ms())
    assert transitions == [
        (WifiState.DISCONNECTED, WifiState.CONNECTING),
        (WifiState.CONNECTING, WifiState.CONNECTED),
    ]


def test_multiple_callbacks_fire_in_registration_order() -> None:
    """Registration order is preserved across all callbacks."""
    log = []
    service, ticks, adapter = _service()
    service.on_state_change(lambda _o, _n: log.append("first"))
    service.on_state_change(lambda _o, _n: log.append("second"))
    adapter.set_connect_outcome(True)

    service.handle(ticks.ticks_ms())
    # 2 transitions × 2 callbacks = 4 entries, alternating.
    assert log == ["first", "second", "first", "second"]


def test_no_callback_for_no_op_transition() -> None:
    """Internal calls to ``_transition`` with the same state don't fire callbacks."""
    transitions = []
    service, _, _ = _service()
    service.on_state_change(lambda old, new: transitions.append((old, new)))
    service._transition(WifiState.DISCONNECTED)  # noqa: SLF001
    assert transitions == []


# ---------------------------------------------------------------------------
# WifiService: adapter selection + auto-detect
# ---------------------------------------------------------------------------


def test_adapter_name_field_reflects_injected_adapter() -> None:
    """``wifi.adapter.name`` is the stable identifier from the adapter."""
    service, _, _ = _service()
    assert service.adapter.name == "fake"


def test_default_adapter_on_cpython_is_fake() -> None:
    """``_select_adapter`` returns ``FakeWifiAdapter`` on CPython.

    The CP and MP adapters are exercised by the functional suites.
    This host-side test stays scoped to the CPython fake-adapter
    path.
    """
    if not _IS_CPYTHON:
        skip("CP/MP adapter selection is covered by the functional suites")
    config = WifiConfig(ssid="x", password="y")
    service = WifiService(config)
    assert service.adapter.name == "fake"


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


def test_public_attrs_resolve_through_package() -> None:
    """`from chumicro_wifi import X` works for every name in ``__all__``."""
    import chumicro_wifi

    assert chumicro_wifi.WifiConfig is WifiConfig
    assert chumicro_wifi.WifiService is WifiService
    assert chumicro_wifi.WifiState is WifiState


def test_unknown_attr_raises_attribute_error() -> None:
    """Asking for an unknown attribute fails fast (default Python behavior)."""
    import chumicro_wifi

    with raises(AttributeError):
        chumicro_wifi.NonExistentSymbol  # noqa: B018 - intentional attribute access


# ---------------------------------------------------------------------------
# FakeWifi (testing.py): wrapper ergonomics for downstream library tests
# ---------------------------------------------------------------------------


def test_fake_wifi_default_config_works_out_of_the_box() -> None:
    """Constructing FakeWifi with just a ticks source connects on tick."""
    ticks = FakeTicks()
    fake = FakeWifi(ticks)
    fake.set_connect_outcome(True)
    fake.tick()
    assert fake.state == WifiState.CONNECTED


def test_fake_wifi_records_adapter_calls() -> None:
    """``calls`` attribute exposes the adapter's recorded calls."""
    ticks = FakeTicks()
    fake = FakeWifi(ticks)
    fake.set_connect_outcome(True)
    fake.tick()
    call_names = [entry[0] for entry in fake.calls]
    assert "configure" in call_names
    assert "connect" in call_names


def test_fake_wifi_drop_link_triggers_reconnect() -> None:
    """``drop_link`` simulates a link-down and the service reacts."""
    ticks = FakeTicks()
    fake = FakeWifi(ticks)
    fake.set_connect_outcome(True)
    fake.tick()
    assert fake.state == WifiState.CONNECTED

    fake.drop_link()
    fake.tick()
    assert fake.state == WifiState.RECONNECTING


def test_fake_wifi_set_connect_outcomes_consumes_in_order() -> None:
    """Queued outcomes drive a multi-attempt scenario deterministically."""
    ticks = FakeTicks()
    fake = FakeWifi(ticks)
    fake.set_connect_outcomes([False, True])

    fake.tick()  # attempt 1: False
    assert fake.state == WifiState.CONNECTING
    ticks.advance(20)
    fake.tick()  # attempt 2: True
    assert fake.state == WifiState.CONNECTED


def test_fake_wifi_adapter_property_exposes_underlying_fake() -> None:
    """The wrapped FakeWifiAdapter is reachable for direct inspection."""
    ticks = FakeTicks()
    fake = FakeWifi(ticks)
    assert isinstance(fake.adapter, FakeWifiAdapter)


def test_fake_wifi_accepts_custom_config() -> None:
    """Tests that need specific config values can pass one in."""
    ticks = FakeTicks()
    custom = WifiConfig(ssid="custom-ssid", password="x", reconnect_backoff_start_ms=5)
    fake = FakeWifi(ticks, config=custom)
    fake.set_connect_outcome(True)
    fake.tick()
    assert fake._fake_adapter.configured_with is custom  # noqa: SLF001


# ---------------------------------------------------------------------------
# FakeWifiAdapter: direct adapter contract
# ---------------------------------------------------------------------------


def test_fake_adapter_drop_link_clears_link() -> None:
    """A simulated link-down drops the linked flag and clears the IP."""
    adapter = FakeWifiAdapter()
    config = WifiConfig(ssid="x", password="y")
    adapter.connect(config)
    assert adapter.is_linked() is True
    adapter.drop_link()
    assert adapter.is_linked() is False
    assert adapter.ip() is None


def test_fake_adapter_outcome_false_keeps_unlinked() -> None:
    """A False outcome from connect leaves the adapter unlinked."""
    adapter = FakeWifiAdapter()
    adapter.set_connect_outcome(False)
    config = WifiConfig(ssid="x", password="y")
    assert adapter.connect(config) is False
    assert adapter.is_linked() is False


def test_fake_adapter_records_every_call() -> None:
    """Every public call appends to ``calls`` for assertion."""
    adapter = FakeWifiAdapter()
    config = WifiConfig(ssid="x", password="y")
    adapter.configure(config)
    adapter.connect(config)
    names = [entry[0] for entry in adapter.calls]
    assert names == ["configure", "connect"]


# ---------------------------------------------------------------------------
# Adapter base class: abstract methods raise
# ---------------------------------------------------------------------------


def test_base_adapter_methods_raise_notimplementederror() -> None:
    """Concrete adapters must override every method.  Defaults raise loudly."""
    from chumicro_wifi._adapters.base import WifiAdapter
    adapter = WifiAdapter()
    config = WifiConfig(ssid="x", password="y")
    with raises(NotImplementedError):
        adapter.configure(config)
    with raises(NotImplementedError):
        adapter.connect(config)
    with raises(NotImplementedError):
        adapter.is_linked()
    with raises(NotImplementedError):
        adapter.ip()
