# User Guide

## Overview

`chumicro-wifi` keeps a board on a wifi network.  A program builds one `WifiService` and adds it to its `Runner`.  The service then joins the network, notices when the link drops, and rejoins.  After each failed try, it doubles the pause before the next one, up to one minute.  The same code runs on CircuitPython, on MicroPython with an ESP32 or Pi Pico W radio, and on CPython.

- `WifiConfig` holds the network name, the password, and the retry settings.
- `WifiService` joins, watches the link, and rejoins.
- `WifiState` names the service's five states.

`WifiService` expects to be the only code driving the radio, so `settings.toml` carries no `CIRCUITPY_WIFI_*` keys and no `boot.py` joins before the program starts.  With one owner, two pieces of code never fight over the radio.

## Getting started

This program joins the network and prints the state and IP address every five seconds, forever:

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiService

config = load_runtime_config()
wifi = WifiService.from_config(config)


def print_status(now_ms):
    print(f"state={wifi.state} ip={wifi.ip}")


runner = Runner()
runner.add(wifi)
runner.add_periodic(print_status, period_ms=5_000)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

- `load_runtime_config()` reads `/runtime_config.msgpack`, the file a workspace deploy builds from the workspace's `secrets.toml`.  [Configuration](#configuration) lists the `wifi.*` keys it can hold.
- `WifiService.from_config(config)` builds the service from those keys and picks the radio code for the runtime it runs on, so the program needs no `if circuitpython:` branches.  Joining starts on the first `tick()`.
- `Runner` comes from `chumicro-runner` and runs several jobs from one loop ([runner guide](https://chumicro.com/ChuMicro/runner/stable/guide/)).
- `runner.add_periodic(print_status, period_ms=5_000)` calls `print_status` every five seconds.
- `runner.wait(now_ms)` sleeps until the next job is due.  The wifi service tells the runner when it next needs a turn ([Runner integration](#runner-integration)).

[`examples/connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi/examples/connect_to_ap.py) is this program plus a printout of every state change.

A program outside a workspace builds the settings in code:

```python
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))
```

`WifiService.from_config(config)` also passes `adapter=` and `ticks=` through to the constructor.  Its `radio=` hands the CircuitPython adapter a specific radio object.

## State machine

`wifi.state` holds one of five `WifiState` values:

```
DISCONNECTED --> CONNECTING --> CONNECTED <-------+
                     |              |             |
                     |              | link drops  | rejoined
                     |              v             |
                     |         RECONNECTING ------+
                     |              |
                     v              v
                  FAILED <----------+   (only with reconnect_max set)
```

A failed try leaves the state where it was, `CONNECTING` before the first join and `RECONNECTING` after a drop.  The service waits out a pause and tries again.  The pause starts at `reconnect_backoff_start_ms` (one second) and doubles up to `reconnect_backoff_max_ms` (one minute).  After a drop, the first retry goes out straight away.  The service reaches `FAILED` only when `reconnect_max` is set and that many tries in a row fail.  `FAILED` is final.

The states are plain strings, because some MicroPython boards lack the `enum` module.  Code compares them with `==`:

```python
from chumicro_wifi import WifiState

if wifi.state == WifiState.RECONNECTING:
    print("link lost, retrying")
```

`wifi.connected` is shorthand for `wifi.state == WifiState.CONNECTED`.

## Reading IP and errors

```python
wifi.ip            # "192.168.1.42" while connected, otherwise None
wifi.last_error    # the last exception the service caught, or None
wifi.adapter.name  # the radio code in use: "cp", "mp_esp32", "mp_rp2", or "cpython"
```

`last_error` clears on every successful join.  What a failed join leaves there depends on the radio ([Platform notes](#platform-notes)).  A program decides what to do from `wifi.state` or `wifi.connected`, never from `last_error` alone.

## State-change notifications

`on_state_change(callback)` registers a function the service calls as `callback(old_state, new_state)` on every transition.  Any number of callbacks can be registered, and they run in registration order:

```python
def log_transition(old_state, new_state):
    print(f"wifi: {old_state} -> {new_state}")

wifi.on_state_change(log_transition)
```

Each part of the program that cares about wifi registers its own callback:

```python
wifi.on_state_change(status_led.on_wifi_state)
wifi.on_state_change(telemetry.on_wifi_state)
```

A callback that raises leaves the other callbacks and the loop running.  The service stores the exception in `last_error` when that slot is empty.

A [generator task](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-tasks) waits for the link through a `Signal` that a callback sets ([Waiting for a callback](https://chumicro.com/ChuMicro/runner/stable/guide/#waiting-for-a-callback)):

```python
from chumicro_timing.waits import Signal, wait_for
from chumicro_wifi import WifiState

link_up = Signal()


def signal_link_up(old_state, new_state):
    if new_state == WifiState.CONNECTED:
        link_up.set()


wifi.on_state_change(signal_link_up)


def fetch_weather():
    yield from wait_for(link_up)   # pauses here until wifi first connects
    print(f"online at {wifi.ip}")
    ...


runner.add_generator(fetch_weather())
```

## Configuration

`WifiConfig.from_config(config)` reads the `wifi.*` keys from a `RuntimeConfig` or a plain dict with the same keys.  `WifiService.from_config(config)` calls it.  `WifiConfig.try_from_config(config)` returns `None` instead of raising when no wifi section was deployed.

| Key | Required | Default | Notes |
|---|---|---|---|
| `ssid` | ✅ | none | Network name. |
| `password` | ✅ | none | WPA passphrase. |
| `hostname` | | `None` | Name the board reports to the network.  The router's device list shows it. |
| `connect_timeout_ms` | | `15_000` | How long one join try may take: a blocking wait on CircuitPython, the window in which MicroPython checks for the link. |
| `first_connect_timeout_ms` | | `None` (use `connect_timeout_ms`) | A longer allowance for the first try after the service is built. |
| `reconnect_backoff_start_ms` | | `1_000` | First pause after a failed try. |
| `reconnect_backoff_max_ms` | | `60_000` | Longest pause.  The pause doubles until it reaches this. |
| `reconnect_max` | | `None` (retry forever) | Failed tries in a row, the first join included, before the final `FAILED` state. |
| `power_save` | | `False` | `True` leaves the radio's power-save mode on.  `False` turns it off on both MicroPython radios, and CircuitPython ignores it. |
| `tx_power_dbm` | | `None` (radio default) | Transmit power in dBm. |

In a workspace, the keys live under `[wifi]` in `secrets.toml` or a project's `project_config.toml`.  The deploy flattens them to `wifi.ssid`, `wifi.password`, and so on:

```toml
[wifi]
ssid = "HomeNet"
password = "secret"
hostname = "back-porch"
power_save = false                  # the default
```

`power_save = false` matters most on a Pi Pico W.  The CYW43 chip's idle power-save adds 30 to 100 ms stalls to the loop, which visibly stutters an LED blink and can break sub-second control loops.

`tx_power_dbm` steadies boards that are unreliable at full transmit power.  Unexpected Maker [documents](https://help.unexpectedmaker.com/docs/boards/wifi-stability-issues/) its P4-revision ESP32-S3 boards as unstable at the full 20 dBm.  `tx_power_dbm = 15`, about a third of full power, gives them a clean join.  The library applies the value as set, with no board detection, and leaves the firmware default when the key is absent.  CircuitPython applies it through `wifi.radio.tx_power` and MicroPython through `sta.config(txpower=…)`.  Firmware without the setting ignores it.

`first_connect_timeout_ms` covers the cold start.  A radio's first join after power-up takes longer than the reconnects that follow.  Without extra time, it can run out `connect_timeout_ms`, count a failure toward `reconnect_max`, and sit out a pause before the now-warm radio joins on the retry.  A value above `connect_timeout_ms`, such as `45_000` against the default `15_000`, gives the first try that time.  Every later try, reconnects included, uses `connect_timeout_ms`.

### Leave `reconnect_max` unset on always-on boards

With `reconnect_max` at its `None` default, the service retries forever, with the pause capped at `reconnect_backoff_max_ms`.  A board then rides out a router reboot, a long outage, or a power cut, and rejoins without a reset.

A number belongs in `reconnect_max` only when the program has something better to do after that many failures, such as a watchdog reset or deep sleep.  The count includes the first join, so a low cap can fail for good after a power cut when the board boots faster than the router.

## Runner integration

`WifiService` is a [runner service](https://chumicro.com/ChuMicro/runner/stable/guide/#services).  Its `check(now_ms)` reads the state and asks the radio whether the link is up.  Its `handle(now_ms)` makes at most one join call.

`WifiService.next_deadline(now_ms)` tells `runner.wait()` when wifi next needs a turn:

| State | Next turn |
|---|---|
| Waiting out a reconnect backoff | when the next attempt is due |
| MicroPython join in flight | every 100 ms, until the join links or times out |
| Connected | once a second, to notice a dropped link |
| `FAILED` | never |

The service checks the link once a second, so it notices a drop within a second of the radio reporting it.  A MicroPython join that completes is noticed within a tenth of a second.  A runner that holds only wifi still sleeps between turns.

On MicroPython, `wlan.connect()` returns at once and the radio joins in the background.  `handle()` returns straight away, and later passes check whether the link came up.

On CircuitPython, `wifi.radio.connect()` blocks.  Each `handle()` that tries to join holds up the loop for up to `connect_timeout_ms`, 15 seconds by default.  An LED blink, an in-flight HTTP request, or MQTT keep-alives in the same runner pause for that long.  Once connected, every pass is quick on both runtimes.

A loop without a runner calls the pair itself:

```python
import time

from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))

while True:
    now_ms = ticks_ms()
    if wifi.check(now_ms):      # does wifi have work to do right now?
        wifi.handle(now_ms)     # then let it take one step
    # ... the rest of your program ...
    time.sleep(0.1)
```

## Adapter detection

At construction, `WifiService` picks its radio code, called an *adapter*, from `sys.implementation.name`:

| Runtime | Adapter | File |
|---|---|---|
| CircuitPython | `CpWifiAdapter` (drives `wifi.radio`) | `_adapters/cp.py` |
| MicroPython | `MpWifiAdapter` (ESP32 and CYW43) | `_adapters/mp.py` |
| CPython | `CpythonWifiAdapter` (stand-in that reports a connection straight away) | `_adapters/cpython.py` |

`MpWifiAdapter` tells the radios apart by matching `sys.implementation._machine` against a list of known CYW43 boards, `CYW43_MACHINES` in `_adapters/mp.py`.  It treats any other board as ESP32.  Each radio gets its own settings:

* **ESP32 (ESP-IDF)**: `config(reconnects=0)` after the first link turns off the firmware's own auto-reconnect, so `chumicro-wifi` is the only code retrying.  `config(pm=0)` before the first join turns off power-save when `power_save=False`.
* **CYW43 (Pi Pico W)**: `config(pm=0xa11140)` before the first join turns off idle power-save when `power_save=False`.

Both radios share the MicroPython `network.WLAN` calls (`active`, `connect`, `isconnected`, `ifconfig`), so one adapter covers both.

## Platform notes

| Runtime and radio | When the access point is unreachable | What `last_error` holds |
|---|---|---|
| CircuitPython `wifi.radio` | `connect()` blocks until `timeout=` expires, then raises `TimeoutError` or `ConnectionError`, both `OSError` subclasses. | `None`, because `CpWifiAdapter.connect` turns an `OSError` into a plain failed try.  Only an exception outside `OSError` lands here. |
| MicroPython on ESP32 (`network.WLAN`) | `connect()` returns at once, then raises `OSError("Wifi Internal State Error")` on the next call. | That `OSError`. |
| MicroPython on CYW43 (Pi Pico W) | `connect()` returns at once.  `isconnected()` stays `False` and nothing raises. | `None`, while the service keeps retrying. |

Each adapter reads the radio's own connected flag after a join try, instead of trusting a `connect()` that raised nothing.  All three cases therefore end as a failed try that the service retries.

On ESP32-S3 under CircuitPython, a failed or timed-out `wifi.radio.connect()` can leave the station half-open.  A retry on a half-open station fails slowly.  It takes the whole `connect_timeout_ms` and raises `ConnectionError: Unknown failure 205`, where a clean try takes about 4 seconds.  `CpWifiAdapter.connect` therefore calls `wifi.radio.stop_station()` before every fresh try.  It skips the try when the radio already reports a link.  The half-open station comes and goes with a marginal signal.

## Testing with `FakeWifi`

[`chumicro_wifi.testing.FakeWifi`](testing.md) is a `WifiService` on a pretend radio, for testing code that depends on wifi without a board.  `set_connect_outcome`, `drop_link`, and `restore_link` script the radio, and `calls` records what the service asked of it.

## Examples

| Example | What it shows |
|---|---|
| [`examples/connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi/examples/connect_to_ap.py) | Joins the network, prints every state change, and prints the state and IP address every five seconds.  Switching the access point off and on shows it reconnect.  Runs on CircuitPython and MicroPython boards, reading the credentials from the config a workspace deploy puts on the board. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
