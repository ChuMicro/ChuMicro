---
title: "chumicro-wifi: wifi that reconnects itself on CircuitPython and MicroPython"
---

# chumicro-wifi

**Wifi that reconnects on its own, so your code doesn't have to.**

`WifiService` joins your network, watches the link, and rejoins after a drop, doubling the pause between failed tries up to one minute.  The same code runs on CircuitPython boards and on MicroPython boards with an ESP32 or a Pi Pico W radio.  It expects to drive the radio alone.  On CircuitPython, leave the `CIRCUITPY_WIFI_*` keys out of `settings.toml`, so the firmware's own auto-connect stays out of its way.  On CircuitPython each join attempt also pauses your loop.  [Platform notes](guide.md#platform-notes) says for how long.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_wifi

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_wifi

# CPython
pip install chumicro-wifi
```

The quick example runs on a `Runner` from `chumicro-runner`.  Install it the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Join the network, then print the state and IP address every five seconds, forever:

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiService

config = load_runtime_config()  # wifi.ssid and wifi.password, deployed to the board
wifi = WifiService.from_config(config)


def print_status(now_ms):
    print(f"state={wifi.state} ip={wifi.ip}")


runner = Runner()
runner.add(wifi)                # joins, watches the link, rejoins after a drop
runner.add_periodic(print_status, period_ms=5_000)

while True:
    now_ms = runner.tick()      # wifi and the status timer each take one small step
    runner.wait(now_ms)         # sleep until wifi or the status timer is due
```

`load_runtime_config()` reads the settings a `chumicro-workspace` deploy writes to the board.  [Wiring wifi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) shows that file, and the way to build the settings in code.

`runner.tick()` runs every job that is due.  `runner.wait(now_ms)` sleeps until the next one is.  `wifi` is a service, an object a loop drives through two methods.  `check(now_ms)` returns `True` when the service has work to do.  `handle(now_ms)` does one small step of that work.  `WifiService` tells `wait()` when it next needs `handle()`, so a loop holding wifi alone still sleeps between passes.  Put your own code in place of `print_status`, and wifi keeps reconnecting in the same loop.

## Documentation

- [User Guide](guide.md): the connect and reconnect state machine, reading the IP address and errors, state-change notifications, configuration, and the runner pattern
- [API Reference](api.md): `WifiService`, `WifiConfig`, and the `WifiState` constants
- [Testing Helpers](testing.md): `FakeWifi`, a `WifiService` on a pretend radio for your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
