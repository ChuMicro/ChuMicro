"""Host-side tests for ``CpWifiAdapter`` via radio injection.

Exercises the adapter's contract with ``wifi.radio`` without a
CircuitPython board.  The fake mirrors the subset of the
``wifi.radio`` shape the adapter touches: ``hostname`` (settable
str), ``connect(ssid, password, timeout=...)`` (blocking, may
raise), ``stop_station()``, ``connected`` (bool), ``ipv4_address``
(stringifiable or ``None``).

Hardware-side coverage (real ``wifi.radio`` against a real AP)
lives under ``functional_tests/``.
"""

#: Host-lane only: exercises a runtime-specific adapter through host
#: fakes and asserts off-target behaviour.  Never staged to a device.
__chumicro_host_only__ = True

from chumicro_test_harness import raises
from chumicro_wifi import WifiConfig
from chumicro_wifi._adapters.cp import CpWifiAdapter


class _FakeRadio:
    """Minimal stand-in for ``wifi.radio`` for host tests."""

    def __init__(self, *, ipv4="10.0.0.42"):
        self.hostname = None
        self.connected = False
        self._ipv4 = ipv4
        self._connect_outcome = True
        self._connect_exception = None
        self._stop_exception = None
        self._tx_power = None
        self._tx_power_exception = None
        self.calls = []

    @property
    def ipv4_address(self):
        return self._ipv4 if self.connected else None

    @property
    def tx_power(self):
        return self._tx_power

    @tx_power.setter
    def tx_power(self, value):
        # Record the set into the shared call log so tests can assert
        # both the value and its ordering relative to stop_station /
        # connect.  A port lacking the knob is modelled by
        # ``_tx_power_exception``.
        self.calls.append(("tx_power", value))
        if self._tx_power_exception is not None:
            raise self._tx_power_exception
        self._tx_power = value

    def connect(self, ssid, password, timeout=None):
        self.calls.append(("connect", ssid, password, timeout))
        if self._connect_exception is not None:
            raise self._connect_exception
        self.connected = bool(self._connect_outcome)

    def stop_station(self):
        self.calls.append(("stop_station",))
        if self._stop_exception is not None:
            raise self._stop_exception
        self.connected = False

    def set_outcome(self, *, ok=None, exception=None):
        self._connect_outcome = ok if ok is not None else True
        self._connect_exception = exception


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_runtime_acquisition_raises_clear_error_on_cpython() -> None:
    """Default-arg construction raises ``RuntimeError`` outside CircuitPython."""
    with raises(RuntimeError):
        CpWifiAdapter()


def test_injected_radio_accepted() -> None:
    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.radio is radio
    assert adapter.name == "cp"


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------


def test_configure_sets_hostname_when_provided() -> None:
    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    adapter.configure(WifiConfig(ssid="x", password="y", hostname="back-porch"))
    assert radio.hostname == "back-porch"


def test_configure_leaves_hostname_unset_when_none() -> None:
    """``hostname=None`` (default) means "don't touch the substrate knob."""
    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    adapter.configure(WifiConfig(ssid="x", password="y"))
    assert radio.hostname is None


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


def test_connect_calls_radio_with_credentials_and_timeout() -> None:
    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    config = WifiConfig(ssid="HomeNet", password="secret", connect_timeout_ms=5_000)
    assert adapter.connect(config) is True
    assert radio.calls[-1] == ("connect", "HomeNet", "secret", 5.0)


def test_connect_clears_station_before_each_attempt() -> None:
    """Each fresh attempt calls ``stop_station()`` before ``connect()``.

    On the ESP32-S3 a failed attempt leaves the station half-open; the
    adapter drops it first so a retry starts clean instead of inheriting
    the poisoned state that slow-fails as ``ConnectionError 205``.  The
    contract is the *ordering*: stop precedes the connect on every
    attempt while the radio is not already linked.
    """
    radio = _FakeRadio()
    radio.set_outcome(ok=False)  # every attempt fails, so we retry
    adapter = CpWifiAdapter(radio=radio)
    config = WifiConfig(ssid="HomeNet", password="secret")

    assert adapter.connect(config) is False
    assert adapter.connect(config) is False

    # Two attempts, each a stop_station immediately followed by a connect.
    assert radio.calls == [
        ("stop_station",),
        ("connect", "HomeNet", "secret", 15.0),
        ("stop_station",),
        ("connect", "HomeNet", "secret", 15.0),
    ]


def test_connect_short_circuits_when_already_linked() -> None:
    """A live association returns ``True`` without re-issuing connect().

    Re-calling ``wifi.radio.connect()`` against an up station
    destabilises the ESP32 driver (it tears down and re-joins), so when
    the radio already reports linked the adapter reports the link
    instead of touching the radio at all.
    """
    radio = _FakeRadio()
    radio.connected = True
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True
    assert radio.calls == []  # no stop_station, no connect


def test_connect_tolerates_stop_station_oserror() -> None:
    """A ``stop_station()`` that raises ``OSError`` doesn't abort the attempt.

    Some ports raise when asked to stop an already-stopped station; the
    adapter swallows that and proceeds to the fresh ``connect()`` rather
    than failing the attempt on the cleanup step.
    """
    radio = _FakeRadio()
    radio._stop_exception = OSError("nothing to stop")  # noqa: SLF001
    radio.set_outcome(ok=True)
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True
    assert ("connect", "x", "y", 15.0) in radio.calls


def test_connect_applies_tx_power_before_connect_when_set() -> None:
    """``tx_power_dbm`` is applied after the station-clear and before connect().

    The reduced power must survive the fresh-attempt flow, so it lands
    between ``stop_station()`` (which would otherwise reset it) and the
    ``connect()`` that uses it.  The contract is the *ordering* on every
    fresh attempt.
    """
    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    config = WifiConfig(ssid="HomeNet", password="secret", tx_power_dbm=15)
    assert adapter.connect(config) is True
    assert radio.calls == [
        ("stop_station",),
        ("tx_power", 15),
        ("connect", "HomeNet", "secret", 15.0),
    ]
    assert radio.tx_power == 15


def test_connect_leaves_tx_power_untouched_when_none() -> None:
    """The default ``tx_power_dbm=None`` never touches ``wifi.radio.tx_power``."""
    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True
    assert radio.tx_power is None
    assert not any(call[0] == "tx_power" for call in radio.calls)


def test_connect_tolerates_tx_power_unsupported_api() -> None:
    """A radio without a settable ``tx_power`` doesn't abort the attempt.

    A CP build lacking the knob raises ``AttributeError`` on assignment;
    the adapter swallows it (leaving the radio at its default power) and
    proceeds to the connect rather than faulting the service.
    """
    radio = _FakeRadio()
    radio._tx_power_exception = AttributeError("no tx_power on this build")  # noqa: SLF001
    adapter = CpWifiAdapter(radio=radio)
    config = WifiConfig(ssid="x", password="y", tx_power_dbm=15)
    assert adapter.connect(config) is True
    assert ("connect", "x", "y", 15.0) in radio.calls


def test_connect_does_not_set_tx_power_on_already_linked_short_circuit() -> None:
    """The already-linked short-circuit touches no radio state, TX power included.

    Poking a live station destabilises the ESP32 driver, so when the
    radio already reports linked the adapter returns without setting
    power — even though ``tx_power_dbm`` is configured.
    """
    radio = _FakeRadio()
    radio.connected = True
    adapter = CpWifiAdapter(radio=radio)
    config = WifiConfig(ssid="x", password="y", tx_power_dbm=15)
    assert adapter.connect(config) is True
    assert radio.calls == []  # no stop_station, no tx_power, no connect


def test_connect_returns_true_when_radio_links() -> None:
    radio = _FakeRadio()
    radio.set_outcome(ok=True)
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is True
    assert radio.connected is True


def test_connect_returns_false_on_oserror() -> None:
    """``OSError`` from the substrate (timeout, connection refused) maps to ``False``.

    CircuitPython raises both ``TimeoutError`` and
    ``ConnectionError`` on the failure paths the adapter cares
    about.  Both are subclasses of ``OSError``.  The adapter catches
    the parent because MicroPython doesn't expose the targeted
    subclasses as builtins, and the source has to load on every
    runtime.
    """
    radio = _FakeRadio()
    radio.set_outcome(exception=OSError("simulated substrate failure"))
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is False


def test_connect_propagates_unexpected_exceptions() -> None:
    """Non-Timeout/Connection errors flow through to ``WifiService.last_error``."""

    class _BoomError(Exception):
        pass

    radio = _FakeRadio()
    radio.set_outcome(exception=_BoomError("unexpected"))
    adapter = CpWifiAdapter(radio=radio)
    with raises(_BoomError):
        adapter.connect(WifiConfig(ssid="x", password="y"))


def test_connect_returns_false_when_radio_says_not_connected_after_call() -> None:
    """Defensive check: even with no exception, only count as success when linked."""
    radio = _FakeRadio()
    radio.set_outcome(ok=False)
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is False


# ---------------------------------------------------------------------------
# is_linked / ip
# ---------------------------------------------------------------------------


def test_is_linked_reflects_radio_connected() -> None:
    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.is_linked() is False
    radio.connected = True
    assert adapter.is_linked() is True


def test_ip_returns_none_when_not_linked() -> None:
    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.ip() is None


def test_ip_returns_str_when_linked() -> None:
    radio = _FakeRadio(ipv4="192.168.1.99")
    radio.connected = True
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.ip() == "192.168.1.99"


def test_ip_returns_none_if_radio_reports_no_address_even_when_linked() -> None:
    """Defensive: linked but no address yet (mid-DHCP) returns ``None``, doesn't crash."""
    radio = _FakeRadio(ipv4=None)
    radio.connected = True
    adapter = CpWifiAdapter(radio=radio)
    assert adapter.ip() is None


# ---------------------------------------------------------------------------
# Integration via WifiService: auto-detect path lazy-imports CpWifiAdapter
# ---------------------------------------------------------------------------


def test_service_drives_cp_adapter_through_full_lifecycle() -> None:
    """A WifiService backed by CpWifiAdapter (with fake radio) connects + drops cleanly."""
    from chumicro_timing.testing import FakeTicks
    from chumicro_wifi import WifiService, WifiState

    radio = _FakeRadio()
    adapter = CpWifiAdapter(radio=radio)
    config = WifiConfig(ssid="HomeNet", password="secret", reconnect_backoff_start_ms=10)
    ticks = FakeTicks()
    service = WifiService(config, adapter=adapter, ticks=ticks)

    assert service.state == WifiState.DISCONNECTED
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED
    assert service.ip == "10.0.0.42"

    radio.connected = False  # simulate link drop
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.RECONNECTING
