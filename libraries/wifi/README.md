# chumicro-wifi

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Wifi that auto-reconnects without freezing your loop.**  One service across CircuitPython, MicroPython, and CPython — register it with [`chumicro-runner`](../runner/) and your LED keeps blinking through every connect, drop, and reconnect.  This library owns the radio (no `CIRCUITPY_WIFI_*` settings, no firmware-level auto-reconnect competing with you), exposes a state machine you can introspect or hook into, and reads its config section via [`chumicro-config`](../config/).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-wifi

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_wifi

# CPython
pip install chumicro-wifi
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

User-app pattern (the canonical 4-line bring-up):

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
runner = Runner()
wifi = WifiService(WifiConfig.from_dict(config["wifi"]))
runner.add(wifi)
```

State + IP introspection any time:

```python
wifi.state          # "disconnected" | "connecting" | "connected" | "reconnecting" | "failed"
wifi.connected
wifi.ip
wifi.last_error
wifi.on_state_change(lambda old, new: print(f"{old} -> {new}"))
```

## What's included

| Symbol | What it does |
|---|---|
| `WifiConfig` | Typed connection settings (`ssid`, `password`, hostname, timeouts, reconnect tuning) with `from_dict` factory per [Decision 0036](../../plans/decisions/0036-chumicro-config-library.md). |
| `WifiService` | State machine + reconnect supervisor; implements `Runner.add()`-compatible `check`/`handle`. Auto-detects the runtime adapter at construction time (`FakeWifiAdapter` on CPython, `CpWifiAdapter` on CircuitPython, substrate-aware `MpWifiAdapter` on MicroPython — handles ESP-IDF + CYW43 transparently). |
| `WifiState` | String-sentinel state names: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `RECONNECTING`, `FAILED`. |
| `chumicro_wifi.testing.FakeWifi` | Drop-in `WifiService` wrapping a `FakeWifiAdapter` with `set_connect_outcome`, `drop_link`, `calls` hooks for downstream library tests. |
| `_templates/config.toml` | Per-library config template ([ADR 0036 §5](../../plans/decisions/0036-chumicro-config-library.md)) consumed by workspace tooling to scaffold a thing's `config.toml`. |

## Platform support

Works on CPython, MicroPython, and CircuitPython.  Ships three adapters: CircuitPython `wifi.radio` (`_adapters/cp.py`), MicroPython `network.WLAN` covering both ESP-IDF (ESP32 family) and CYW43 (Pi Pico W) stacks (`_adapters/mp.py`), and a `FakeWifiAdapter` for host-side tests.  The right adapter is selected at runtime via `sys.implementation.name`; the MP adapter then auto-detects ESP-IDF vs CYW43 internally via an `import esp32` probe.

## Examples

| Example | What it shows |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | Build a `WifiService`, register a state-change callback, drive one tick, observe the state transitions. Uses `FakeWifi` so it runs anywhere. |

## Configuring wifi for examples and functional tests

The acceptance test in `functional_tests/test_acceptance.py` connects to a real AP and skips silently when no credentials are configured.

### Inside the chumicro mono-repo

`python scripts/run.py setup` generates `chumicro-dev-config.toml` at the repo root (gitignored).  Uncomment and fill in:

```toml
[wifi]
ssid = "your-wifi-ssid"
password = "your-wifi-password"
```

`functional_tests/conftest.py` reads this file and materialises a `_test_creds.py` shim alongside the test.

### Using `chumicro-wifi` outside the mono-repo

Production apps load wifi config via `chumicro_config.load_runtime_config()` — see `chumicro-config` and Decision 0030.  Put your creds in your workspace's `secrets.yml`, run `chumicro-workspace deploy`, and the bake-and-deploy pipeline lands them on the device as `runtime_config.msgpack`.

The library itself never reads any TOML — it takes a `WifiConfig` and goes.  `WifiConfig.from_dict()` is the dict-construction path used by the standard pipeline.

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries wifi
python scripts/run.py test-libraries-functional --library wifi
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/wifi/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/wifi/experimental/)**

## Find this library

- **PyPI:** [chumicro-wifi](https://pypi.org/project/chumicro-wifi/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_wifi) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_wifi)
- **Source:** [libraries/wifi](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi)
