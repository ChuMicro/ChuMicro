# Testing Helpers

`chumicro_wifi.testing` provides `FakeWifi` and `FakeWifiAdapter` for downstream libraries that depend on `chumicro-wifi` but want to drive connect / drop / reconnect scenarios deterministically from tests — no real radio, no real network, no real time.

## `FakeWifi`

A `WifiService` wrapping a `FakeWifiAdapter` with the test hooks exposed directly on the wrapper.  Use this when you want a drop-in `WifiService` your code-under-test treats like the real thing:

```python
from chumicro_wifi.testing import FakeWifi
from chumicro_timing.testing import FakeTicks

def test_my_service_waits_for_wifi():
    ticks = FakeTicks()
    wifi = FakeWifi(ticks)
    wifi.set_connect_outcome(True)

    my_service = MyService(wifi=wifi)
    my_service.start()

    ticks.advance(0)
    wifi.tick()                    # one runner-style check + handle
    assert wifi.state == "connected"
    assert my_service.ready
```

`FakeWifi` ships with sensible defaults (`ssid="testnet"`, `password="password"`, short reconnect backoffs).  Pass a custom `WifiConfig` to the constructor if your test needs different settings.

## Test hooks

The hooks below live on `FakeWifiAdapter` and are forwarded to `FakeWifi` for ergonomic test code:

| Hook | What it does |
|---|---|
| `set_connect_outcome(True)` | Next `connect()` succeeds. |
| `set_connect_outcome(False)` | Next `connect()` returns a clean refusal. |
| `set_connect_outcome(OSError)` | Next `connect()` raises the named exception class. |
| `set_connect_outcomes([True, False, True])` | Queue a one-shot sequence of outcomes; the default takes over after the queue drains. |
| `drop_link()` | Simulates a link-down event — the next `is_linked()` returns `False`, triggering the service's reconnect path. |
| `calls` | List of recorded adapter calls (`("configure", config)`, `("connect", config)`, `("disconnect",)`).  Assert on this to verify call ordering. |

## Simulating a reconnect

Use `drop_link()` plus `FakeTicks.advance()` to step through a real reconnect cycle:

```python
def test_reconnect_after_link_drop():
    ticks = FakeTicks()
    wifi = FakeWifi(ticks)
    wifi.set_connect_outcome(True)

    wifi.tick()                    # connects
    assert wifi.state == "connected"

    wifi.drop_link()               # simulate link-down
    wifi.tick()                    # service notices, enters RECONNECTING

    ticks.advance(200)             # past the first backoff window
    wifi.tick()                    # reconnect attempt fires
    assert wifi.state == "connected"
```

## `FakeWifiAdapter` (lower level)

When you need to compose your own service shape — for example, a test that wires `FakeWifiAdapter` into a real `WifiService` to verify the supervisor's behavior — use the adapter directly:

```python
from chumicro_wifi import WifiConfig, WifiService
from chumicro_wifi.testing import FakeWifiAdapter
from chumicro_timing.testing import FakeTicks

def test_supervisor_handles_exception_during_connect():
    ticks = FakeTicks()
    adapter = FakeWifiAdapter()
    adapter.set_connect_outcome(OSError)         # exception class to raise

    service = WifiService(
        WifiConfig(ssid="lab", password="lab-pw"),
        adapter=adapter,
        ticks=ticks,
    )
    service.handle(0)
    # Exception is captured rather than propagated — the service
    # stays in CONNECTING with a retry scheduled.
    assert isinstance(service.last_error, OSError)
    assert service.state == "connecting"
```

## Usage from other libraries

Libraries that depend on `chumicro-wifi` can import the fakes directly in their own test suites:

```python
from chumicro_wifi.testing import FakeWifi, FakeWifiAdapter
```

Libraries that expose injectable services ship their own test fakes alongside the production code, so every consumer uses the same shared fake.

## API Reference

::: chumicro_wifi.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
