# Testing Helpers

`chumicro_wifi.testing` stands in for the board's WiFi radio.  `FakeWifi` is a ready-made `WifiService` on a pretend radio, for code that takes a `WifiService`.  `FakeWifiAdapter` is the pretend radio itself, for a test that builds its own `WifiService`.  A test decides when a join succeeds, fails, or drops, with no radio, no network, and no waiting.  `pip install chumicro-wifi pytest` installs everything the tests on this page import, `chumicro-timing` included.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_uploader.py` and run `pytest test_uploader.py`:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_wifi.testing import FakeWifi


class Uploader:
    def __init__(self, wifi):
        self.wifi = wifi
        self.uploads = 0

    def tick(self):
        if self.wifi.connected:
            self.uploads += 1


def test_uploader_waits_for_wifi():
    wifi = FakeWifi(FakeTicks())
    uploader = Uploader(wifi)

    uploader.tick()
    assert uploader.uploads == 0

    wifi.tick()
    uploader.tick()
    assert wifi.ip == "192.168.0.42"
    assert uploader.uploads == 1
```

`Uploader` takes its `WifiService` as an argument, so the test hands it a `FakeWifi`.  The first `wifi.tick()` joins the pretend network.

## `FakeWifi`

`FakeWifi(ticks, *, config=None)` is a `WifiService`, so it has `state`, `connected`, `ip`, `last_error`, `check()`, `handle()`, and `on_state_change()`.  Without `config` it joins `"testnet"` with a 10 ms first retry pause that doubles up to 100 ms, so a retry test never waits long.  Pass a `WifiConfig` as `config` for other settings.

| Call or attribute | What it does |
|---|---|
| `tick()` | Runs one `check()` and `handle()` pass at the current `ticks` reading, as a `Runner` would. |
| `set_connect_outcome(outcome)` | Sets what every join does from now on: `True` joins, `False` is refused, an exception class such as `OSError` is raised.  The default is `True`. |
| `set_connect_outcomes([...])` | Queues one outcome per join for the next few joins.  `set_connect_outcome` takes over once the queue runs out. |
| `set_connect_blocks(blocks)` | `True`, the default, makes a refused join final at once, as on CircuitPython, where a join waits for its answer.  `False` treats a refused join as still in progress, and the service polls the link until the join times out, as on MicroPython. |
| `set_deferred_link(link_after=n)` | Plays a MicroPython join in the background: the join returns at once, and the link comes up on the `n`th poll. |
| `drop_link()` | Drops the link without warning.  The next pass sees it and starts rejoining. |
| `restore_link()` | Brings the link back without a join, as an access point that recovers on its own. |
| `calls` | The radio calls so far: `("configure", config)` and `("connect", config, timeout_ms)` tuples, in order. |

`drop_link()` walks a program through a lost connection.  The service tries its first rejoin at once:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_wifi import WifiState
from chumicro_wifi.testing import FakeWifi


def test_wifi_rejoins_after_the_link_drops():
    wifi = FakeWifi(FakeTicks())

    wifi.tick()
    assert wifi.state == WifiState.CONNECTED

    wifi.drop_link()
    wifi.tick()
    assert wifi.state == WifiState.RECONNECTING

    wifi.tick()
    assert wifi.state == WifiState.CONNECTED
```

`set_connect_outcomes` and `FakeTicks.advance()` step through the pause between failed joins:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_wifi import WifiState
from chumicro_wifi.testing import FakeWifi


def test_a_refused_join_waits_before_trying_again():
    ticks = FakeTicks()
    wifi = FakeWifi(ticks)
    wifi.set_connect_outcomes([False, True])

    wifi.tick()
    assert wifi.state == WifiState.CONNECTING

    wifi.tick()
    assert len([call for call in wifi.calls if call[0] == "connect"]) == 1

    ticks.advance(10)
    wifi.tick()
    assert wifi.state == WifiState.CONNECTED
```

The refused join leaves the service in `CONNECTING`.  A `tick()` during the 10 ms pause makes no second join.

## `FakeWifiAdapter`

`FakeWifiAdapter(*, ip="192.168.0.42")` is the pretend radio under `FakeWifi`.  It takes the same `set_connect_outcome`, `set_connect_outcomes`, `set_connect_blocks`, `set_deferred_link`, `drop_link`, and `restore_link` calls and keeps the same `calls` list.  `configured_with` holds the `WifiConfig` the service last configured it with.  A test passes it to a `WifiService` it builds itself:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_wifi import WifiConfig, WifiService, WifiState
from chumicro_wifi.testing import FakeWifiAdapter


def test_a_radio_error_is_kept_and_retried():
    adapter = FakeWifiAdapter()
    adapter.set_connect_outcome(OSError)
    service = WifiService(
        WifiConfig(ssid="lab", password="lab-password"),
        adapter=adapter,
        ticks=FakeTicks(),
    )

    service.handle(0)

    assert isinstance(service.last_error, OSError)
    assert service.state == WifiState.CONNECTING
    assert adapter.configured_with.ssid == "lab"
```

The service keeps the radio's exception in `last_error` and stays in `CONNECTING` with a retry scheduled.

## API reference

::: chumicro_wifi.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
