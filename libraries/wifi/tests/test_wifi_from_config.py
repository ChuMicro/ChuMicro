"""``WifiService.from_config``: service-level construction from runtime config.

Cross-runtime: runs on CPython pytest, and under MicroPython +
CircuitPython unix-ports via the ``chumicro-pytest-device`` unix-port
backend.  Every test injects ``adapter=`` unless it is explicitly
exercising the runtime-adapter selection, which only CPython can do
off-board.
"""

import sys

from chumicro_config import MissingConfigKey, RuntimeConfig
from chumicro_test_harness import raises, skip
from chumicro_timing.testing import FakeTicks
from chumicro_wifi import WifiService
from chumicro_wifi.testing import FakeWifiAdapter

_REQUIRED_KEYS = {"wifi.ssid": "HomeNet", "wifi.password": "secret"}


def test_from_config_loads_wifi_section() -> None:
    """from_config reads the flat ``wifi.*`` keys through the WifiConfig
    loader and hands the result to the service."""
    service = WifiService.from_config(
        {
            "wifi.ssid": "HomeNet",
            "wifi.password": "secret",
            "wifi.reconnect_backoff_start_ms": 250,
        },
        adapter=FakeWifiAdapter(),
    )
    assert service._config.ssid == "HomeNet"  # noqa: SLF001
    assert service._config.password == "secret"  # noqa: SLF001
    assert service._config.reconnect_backoff_start_ms == 250  # noqa: SLF001


def test_from_config_via_runtime_config_wrapper() -> None:
    """A real ``RuntimeConfig`` reads the same flat keys as a plain dict."""
    service = WifiService.from_config(
        RuntimeConfig(_REQUIRED_KEYS), adapter=FakeWifiAdapter(),
    )
    assert service._config.ssid == "HomeNet"  # noqa: SLF001


def test_from_config_missing_required_key_raises() -> None:
    """A config without ``wifi.password`` raises MissingConfigKey from the
    WifiConfig loader before any service state exists."""
    with raises(MissingConfigKey):
        WifiService.from_config(
            {"wifi.ssid": "HomeNet"}, adapter=FakeWifiAdapter(),
        )


def test_constructor_kwargs_pass_through() -> None:
    """adapter= and ticks= ride ``from_config`` verbatim to the constructor."""
    adapter = FakeWifiAdapter()
    ticks = FakeTicks()
    service = WifiService.from_config(
        _REQUIRED_KEYS, adapter=adapter, ticks=ticks,
    )
    assert service.adapter is adapter
    assert service._ticks is ticks  # noqa: SLF001


def test_explicit_adapter_wins_over_radio() -> None:
    """An explicit adapter= keyword beats the radio-driven selection, so
    the radio handle goes unused."""
    adapter = FakeWifiAdapter()
    service = WifiService.from_config(
        _REQUIRED_KEYS, radio="board-radio", adapter=adapter,
    )
    assert service.adapter is adapter


def test_construction_is_side_effect_free() -> None:
    """from_config touches no radio: the adapter records zero calls until
    the first handle() tick attempts a connect."""
    adapter = FakeWifiAdapter()
    service = WifiService.from_config(_REQUIRED_KEYS, adapter=adapter)
    assert adapter.calls == []
    now_ms = service._ticks.ticks_ms()  # noqa: SLF001
    if service.check(now_ms):
        service.handle(now_ms)
    assert ("configure", service._config) in adapter.calls  # noqa: SLF001


def test_default_adapter_selection_without_radio() -> None:
    """With no adapter= and no radio, from_config selects the runtime
    adapter (the CPython host adapter here).  CPython-only: the MP/CP
    unix-port adapters demand real station hardware."""
    if sys.implementation.name != "cpython":
        skip("runtime-adapter selection needs the CPython host adapter")
    service = WifiService.from_config(_REQUIRED_KEYS)
    assert service.adapter.name == "cpython"
