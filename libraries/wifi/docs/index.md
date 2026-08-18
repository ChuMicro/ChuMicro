---
title: "chumicro-wifi: WiFi that reconnects itself on CircuitPython and MicroPython"
---

# chumicro-wifi

**Wifi that auto-reconnects without freezing your loop.**

One wifi service across CircuitPython on Adafruit boards and MicroPython on both ESP32 and Pi Pico W. Register it with `chumicro-runner` and your LED keeps blinking through every connect, drop, and reconnect. This library owns the radio (no `CIRCUITPY_WIFI_*` settings, no firmware-level auto-reconnect competing with you). On CPython there is no radio to drive, so the service runs against a host stand-in adapter that reports success immediately, and your host tests exercise the same state machine.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_wifi

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_wifi

# CPython
pip install chumicro-wifi
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

## Quick example

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiService

config = load_runtime_config()
wifi = WifiService.from_config(config)

runner = Runner()
runner.add(wifi)
while True:
    runner.tick()
```

## Documentation

- [User Guide](guide.md): the connect and reconnect state machine, reading IP and errors, state-change notifications, configuration, and runner integration
- [API Reference](api.md): `WifiService`, `WifiConfig`, and the `WifiState` constants
- [Testing Helpers](testing.md): using `FakeWifi` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
