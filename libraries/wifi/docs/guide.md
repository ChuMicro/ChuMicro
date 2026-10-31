# User Guide

## Overview

`chumicro-wifi` keeps a board on your wifi network.  Create one `WifiService`, add it to your `Runner` loop, and it joins the network, notices when the link drops, and rejoins, doubling the pause between failed tries up to one minute.  The same code runs on CircuitPython, on MicroPython with an ESP32 or Pi Pico W radio, and on CPython.

`WifiService` expects to be the only code driving the radio: no `CIRCUITPY_WIFI_*` keys in `settings.toml`, no `boot.py` that joins before your program starts.  On ESP32 under MicroPython it also turns off the firmware's own auto-reconnect.  With one owner, two pieces of code never fight over the radio.

The public API is three names: `WifiConfig` holds the settings, `WifiService` does the work, and `WifiState` names its five states.  `chumicro_wifi.testing.FakeWifi` stands in for `WifiService` in tests.

## Getting started

This program joins the network and prints the state and IP address every five seconds.  Like any board program, it never ends:

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

Line by line:

- `load_runtime_config()` reads `/runtime_config.msgpack`, the file a workspace deploy builds from your `secrets.toml`.  [Configuration](#configuration) lists the `wifi.*` keys it can hold.
- `WifiService.from_config(config)` builds the service from those keys and picks the radio code for the runtime it runs on, so your program needs no `if circuitpython:` branches.  It does not start joining until the first `tick()`.
- `Runner` comes from `chumicro-runner`.  It is a loop helper that runs several jobs side by side: on every `tick()` it asks each registered service whether it has work (the service's `check(now_ms)` method) and, if so, runs one step of it (`handle(now_ms)`).  `now_ms` is the board's millisecond clock for that pass.
- `runner.add_periodic(print_status, period_ms=5_000)` calls `print_status` every five seconds.
- `runner.wait(now_ms)` sleeps until the next job is due, so the board idles instead of spinning.  Wifi tells the runner when it next needs a turn; [Runner integration](#runner-integration) lists when that is.

[`examples/connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi/examples/connect_to_ap.py) is this program plus a printout of every state change.

Without a workspace, build the settings in code instead of reading them from the board:

```python
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))
```

`WifiService.from_config(config)` also passes `adapter=` and `ticks=` through to the constructor, and `radio=` hands the CircuitPython code a specific radio object.

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

A failed try leaves the state where it was: `CONNECTING` before the first join, `RECONNECTING` after a drop.  The service waits out a pause and tries again, starting at `reconnect_backoff_start_ms` (one second) and doubling up to `reconnect_backoff_max_ms` (one minute).  After a drop, the first retry goes out straight away.  `FAILED` happens only when you set `reconnect_max` and that many tries in a row fail; nothing leaves it.

The states are plain strings, because `enum` is missing on some MicroPython boards.  Compare with `==`:

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

`last_error` clears on every successful join.  An exception raised by one of your [state-change callbacks](#state-change-notifications) lands in it on every runtime; what a failed join leaves there depends on the radio:

- **MicroPython on ESP32.**  The driver raises `OSError("Wifi Internal State Error")` when the access point is unreachable, and the service stores it here.
- **CircuitPython.**  `CpWifiAdapter.connect` turns a timeout or refusal (`TimeoutError`, `ConnectionError`, both `OSError` subclasses) into a plain failed try, so `last_error` usually stays `None`.  Only an exception that is not an `OSError` lands here.
- **MicroPython on Pi Pico W.**  A failed join raises nothing and leaves `isconnected()` false, so `last_error` stays `None` while the service keeps retrying.

Decide what to do from `wifi.state` or `wifi.connected`, never from `last_error` alone.

## State-change notifications

`on_state_change(callback)` registers a function the service calls as `callback(old_state, new_state)` on every transition.  Register as many as you like; they run in the order you added them:

```python
def log_transition(old_state, new_state):
    print(f"wifi: {old_state} -> {new_state}")

wifi.on_state_change(log_transition)
```

Each part of your program that cares about wifi registers its own callback, so there is no event bus to set up:

```python
wifi.on_state_change(status_led.on_wifi_state)
wifi.on_state_change(telemetry.on_wifi_state)
```

A callback that raises does not stop the others or the loop; the service stores the exception in `last_error` when that slot is empty.

To make a *generator task* wait for the link, set a `Signal` from a callback and wait on it with `wait_for` (both from `chumicro_timing.waits`).  A generator task is a function containing `yield`, registered with `runner.add_generator()`.  The runner resumes it on each pass, so it can pause at a `yield from` line while the rest of the loop keeps running:

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

`WifiConfig.from_config(config)` reads the `wifi.*` keys from a `RuntimeConfig` or a plain dict with the same keys, and `WifiService.from_config(config)` calls it for you.  `WifiConfig.try_from_config(config)` returns `None` instead of raising when no wifi section was deployed.  The keys:

| Key | Required | Default | Notes |
|---|---|---|---|
| `ssid` | ✅ | none | Network name. |
| `password` | ✅ | none | WPA passphrase. |
| `hostname` | | `None` | Name the board reports to the network; your router's device list shows it. |
| `connect_timeout_ms` | | `15_000` | How long one join try may take: a blocking wait on CircuitPython, the window in which MicroPython checks for the link. |
| `first_connect_timeout_ms` | | `None` (use `connect_timeout_ms`) | A longer allowance for the very first try after power-up.  Every later try, reconnects included, uses `connect_timeout_ms`. |
| `reconnect_backoff_start_ms` | | `1_000` | First pause after a failed try. |
| `reconnect_backoff_max_ms` | | `60_000` | Longest pause; the pause doubles until it reaches this. |
| `reconnect_max` | | `None` (never give up) | Failed tries in a row, the first join included, before the final `FAILED` state.  Leave `None` on always-on boards (see below). |
| `power_save` | | `False` | Leave the radio's power-save mode on.  `False` turns it off on both MicroPython radios (CYW43 on Pi Pico W, ESP-IDF on ESP32); CircuitPython ignores it. |
| `tx_power_dbm` | | `None` (radio default) | Transmit power in dBm.  `None` leaves the firmware default; set a lower value (such as `15`) on boards that are unstable at full power.  Applied through `wifi.radio.tx_power` on CircuitPython and `sta.config(txpower=…)` on MicroPython; ignored where the firmware lacks the setting. |

In a workspace the keys live under `[wifi]` in `secrets.toml` (or a project's `project_config.toml`), and the deploy flattens them to `wifi.ssid`, `wifi.password`, and so on:

```toml
[wifi]
ssid = "HomeNet"
password = "secret"
hostname = "back-porch"
power_save = false                  # the default; keeps Pico W from stalling the loop 30-100 ms at a time
```

`power_save = false` matters most on Pi Pico W: the CYW43 chip's idle power-save adds 30 to 100 ms stalls to the loop, which visibly stutters an LED blink and can break sub-second control loops.

`tx_power_dbm` is for boards that are unreliable at full transmit power.  Unexpected Maker's P4-revision ESP32-S3 boards are [documented by the vendor](https://help.unexpectedmaker.com/docs/boards/wifi-stability-issues/) as unstable at the full 20 dBm, and `tx_power_dbm = 15` (about 75 %) gives them a clean join.  The library never inspects the board; it applies the value you set and leaves the firmware default when the key is absent.

`first_connect_timeout_ms` is for the cold start.  A radio's first join after power-up takes longer than the reconnects that follow, and without extra time it can run out `connect_timeout_ms`, count a failure toward `reconnect_max`, and sit out a pause before the now-warm radio joins on the retry.  Set it above `connect_timeout_ms` (say `45_000` against the default `15_000`); only the first try uses it.

### Leave `reconnect_max` unset on always-on boards

With `reconnect_max` at its `None` default the service never gives up.  It keeps retrying, with the pause capped at `reconnect_backoff_max_ms`, so a board rides out a router reboot, a long outage, or a power cut and rejoins without a reset.

`FAILED` is final: nothing in the service leaves it.  Set a number only when your program has something better to do after that many failures, such as a watchdog reset or deep sleep.  The count includes the first join, so a low cap can fail for good after a power cut when the board boots faster than the router.

## Runner integration

`WifiService` has the two methods a `Runner` calls on every registered service: `check(now_ms)` answers whether wifi has work this pass, and `handle(now_ms)` does one step of it.  `check` reads the state and asks the radio whether the link is up; `handle` makes at most one join call.

```python
runner = Runner()
runner.add(wifi)
runner.add_periodic(print_status, period_ms=5_000)

while True:
    now_ms = runner.tick()   # every registered job takes one small step
    runner.wait(now_ms)      # then the board sleeps until the next job is due
```

**Wifi sets its own wake-ups.**  `WifiService.next_deadline(now_ms)` tells `runner.wait()` when wifi next needs a turn, and the runner sleeps until the earliest deadline any job reports:

| State | Next turn |
|---|---|
| Waiting out a reconnect backoff | when the next attempt is due |
| MicroPython join in flight | every 100 ms, until the join links or times out |
| Connected | once a second, to notice a dropped link |
| `failed` | never |

So a dropped link shows up within a second, a finished MicroPython join within a tenth of a second, and a runner holding only wifi still sleeps between turns.  Other jobs keep their own timing on top of that.

**How long a join blocks depends on the runtime.**  On MicroPython, `wlan.connect()` returns at once and the radio joins in the background: `handle()` returns straight away, later passes check whether the link came up, and other jobs keep their timing.  On CircuitPython, `wifi.radio.connect()` blocks, so each `handle()` that tries to join holds up the loop for up to `connect_timeout_ms` (15 seconds by default; the first try uses `first_connect_timeout_ms` when set).  An LED blink, an in-flight HTTP request, or MQTT keep-alives in the same runner pause for that long.  Once connected, every pass is quick on both runtimes.

No runner?  Call the pair from your own loop:

```python
import time

from chumicro_timing import ticks_ms

while True:
    now_ms = ticks_ms()
    if wifi.check(now_ms):      # does wifi have work to do right now?
        wifi.handle(now_ms)     # then let it take one step
    # ... the rest of your program ...
    time.sleep(0.1)
```

## Adapter detection

`WifiService` picks its radio code, called an *adapter*, from `sys.implementation.name` when you construct it:

| Runtime | Adapter | File |
|---|---|---|
| CircuitPython | `CpWifiAdapter` (drives `wifi.radio`) | `_adapters/cp.py` |
| MicroPython | `MpWifiAdapter` (ESP32 and CYW43) | `_adapters/mp.py` |
| CPython | `CpythonWifiAdapter` (stand-in that reports a connection straight away) | `_adapters/cpython.py` |

`MpWifiAdapter` tells the radios apart by matching `sys.implementation._machine` against a list of known CYW43 boards (`CYW43_MACHINES` in `_adapters/mp.py`); any other board is treated as ESP32.  It then applies the settings each radio needs:

* **ESP32 (ESP-IDF)**: `config(reconnects=0)` after the first link, which turns off the firmware's own auto-reconnect so `chumicro-wifi` is the only thing retrying.
* **CYW43 (Pi Pico W)**: `config(pm=0xa11140)` before the first join, which turns off idle power-save when `power_save=False`.

Both radios share the MicroPython `network.WLAN` calls (`active`, `connect`, `isconnected`, `ifconfig`), so one adapter covers both.

## Platform notes

Each runtime reports an unreachable access point differently:

| Runtime and radio | When the access point is unreachable |
|---|---|
| CircuitPython `wifi.radio` | Blocks inside `connect()` until `timeout=` expires, then raises `TimeoutError` or `ConnectionError` (both `OSError` subclasses). |
| MicroPython on ESP32 (`network.WLAN`) | Returns from `connect()` at once, then raises `OSError("Wifi Internal State Error")` on the next call. |
| MicroPython on CYW43 (Pi Pico W) | Returns at once; `isconnected()` stays `False` and nothing is raised. |

Each adapter reads the radio's own connected flag after a join try instead of trusting that a `connect()` which raised nothing succeeded, so all three cases end as a failed try that the service retries.

On ESP32-S3 under CircuitPython, a failed or timed-out `wifi.radio.connect()` can leave the station half-open.  Calling `connect()` again without clearing it makes the retry fail slowly: it takes the whole `connect_timeout_ms` and raises `ConnectionError: Unknown failure 205`, where a clean try takes about 4 seconds.  `CpWifiAdapter.connect` therefore calls `wifi.radio.stop_station()` before every fresh try, and skips the try when the radio already reports a link.  The failure comes and goes with a marginal signal; a clean station connects in seconds.

## Testing with `FakeWifi`

[`chumicro_wifi.testing.FakeWifi`](testing.md) is a `WifiService` on a pretend radio, for testing code that depends on wifi without a board.  `set_connect_outcome`, `drop_link`, `restore_link`, and `calls` script and record what the radio does.

## Examples

| Example | What it shows |
|---|---|
| [`examples/connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi/examples/connect_to_ap.py) | Joins your network, prints every state change, and prints the state and IP address every five seconds.  Switch the access point off and on to watch it reconnect.  Runs on CircuitPython and MicroPython boards; reads the credentials from the config a workspace deploy puts on the board. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
