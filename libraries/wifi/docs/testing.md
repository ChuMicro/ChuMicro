# Testing Helpers

`chumicro_wifi.testing` provides `FakeWifi` and `FakeWifiAdapter` so your tests can drive connect, drop, and reconnect scenarios deterministically: no real radio, no real network, no real time. The fakes stay on the host: `chumicro-deploy` reads the test-support marker at the top of the module and leaves it out of every device bundle it builds.

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

    wifi.tick()                    # one runner-style check + handle
    assert wifi.state == "connected"
    assert my_service.ready
```

`FakeWifi` defaults to `ssid="testnet"` and `password="password"`, with a 10 ms first reconnect pause capped at 100 ms so tests never wait long.  Pass `config=` a custom `WifiConfig` if your test needs different settings.

## Test hooks

The hooks below live on `FakeWifiAdapter`, and `FakeWifi` forwards each one so a test can call it on the service directly:

| Hook | What it does |
|---|---|
| `set_connect_outcome(True)` | Every `connect()` from now on succeeds. |
| `set_connect_outcome(False)` | Every `connect()` from now on returns a clean refusal. |
| `set_connect_outcome(OSError)` | Every `connect()` from now on raises the given exception class. |
| `set_connect_outcomes([True, False, True])` | Queues outcomes for the next few `connect()` calls, one each; `set_connect_outcome` takes over once the queue is empty. |
| `set_connect_blocks(False)` | Switches between a blocking `connect()` (`True`, the default, like CircuitPython) and a non-blocking one (`False`, like MicroPython). |
| `set_deferred_link(link_after=3)` | Models a MicroPython-style background join: `connect()` returns `False`, and `is_linked()` turns `True` on its third call. |
| `drop_link()` | Simulates a link-down event: the next `is_linked()` returns `False`, which sends the service into its reconnect path. |
| `restore_link()` | Simulates the access point coming back on its own, with no `connect()` call. |
| `calls` | List of recorded adapter calls, `("configure", config)` and `("connect", config, timeout_ms)`.  Assert on it to check call order. |

## Simulating a reconnect

Use `drop_link()` to step through a reconnect.  After a drop, the service sends its first reconnect try straight away:

```python
def test_reconnect_after_link_drop():
    ticks = FakeTicks()
    wifi = FakeWifi(ticks)
    wifi.set_connect_outcome(True)

    wifi.tick()                    # connects
    assert wifi.state == "connected"

    wifi.drop_link()               # simulate link-down
    wifi.tick()                    # service notices, enters RECONNECTING
    assert wifi.state == "reconnecting"

    wifi.tick()                    # first reconnect try succeeds
    assert wifi.state == "connected"
```

To test the pause between failed tries, queue failures with `set_connect_outcomes` and move the clock with `ticks.advance(milliseconds)` between `tick()` calls.

## `FakeWifiAdapter` (lower level)

When you need to compose your own service shape (a test that wires `FakeWifiAdapter` into a real `WifiService` to check the supervisor's behavior, for example), use the adapter directly:

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
    # The exception is captured, not propagated: the service stays
    # in CONNECTING with a retry scheduled.
    assert isinstance(service.last_error, OSError)
    assert service.state == "connecting"
```

## Using these fakes in your own tests

Install `chumicro-wifi` and import the fakes straight into your test suite:

```python
from chumicro_wifi.testing import FakeWifi, FakeWifiAdapter
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

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
