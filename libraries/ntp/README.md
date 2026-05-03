# chumicro-ntp

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Runner-shaped SNTP client over an injected UDP socket — pure-Python, cross-runtime.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

circup is CircuitPython's package manager — it uses [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands) to find third-party packages. Register the ChuMicro bundle once, then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-ntp
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_ntp
```

> **Want pre-compiled `.mpy` bytecode?** Add `mpy6/` before the package name for faster startup and lower RAM usage on boards with mpy format v6 (MicroPython 1.24+):
> ```
> mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_ntp
> ```

### CPython (pip)

```bash
pip install chumicro-ntp
```

*Just getting started? Skip this — the install commands above are all you need.*

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped. Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-ntp

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_ntp

# CPython
pip install chumicro-ntp-experimental
```

</details>

## Quick example

```python
from chumicro_ntp import NTPClient
from chumicro_ntp.sockets_factory import chumicro_sockets_factory

sock = chumicro_sockets_factory()
client = NTPClient(socket=sock, server="pool.ntp.org")
request = client.query()
while not request.done:
    if client.check(now_ms()):
        client.handle(now_ms())
print("unix seconds:", request.unix_seconds)
```

`chumicro_sockets_factory` lives in its own submodule (Decision 0042 deploy-rule) so apps with a custom UDP transport don't pull `chumicro-sockets` into their device deploy.  Pass any `chumicro_sockets.UDPSocket`-shaped object to `NTPClient(socket=...)`.

## What's included

| Symbol | Purpose |
|---|---|
| `NTPClient(socket, *, server="pool.ntp.org", port=123, timeout_ms=5000, ticks_ms=None)` | Runner-shaped SNTP client.  Single in-flight query at a time; mirrors `HttpClient.busy`. |
| `NTPClient.query()` | Send a request; returns a `NTPResult` to poll. |
| `NTPClient.check(now_ms)` / `handle(now_ms)` | Runner contract — handle drains the recv socket and detects timeouts. |
| `NTPClient.cancel()` | Abort an in-flight query. |
| `NTPResult` | Per-query handle.  `done`, `unix_seconds`, `error`. |
| `NTPError` | OSError subclass raised on protocol-level failures (short/malformed response, kiss-of-death, timeout, cancel). |
| `chumicro_ntp.sockets_factory.chumicro_sockets_factory(radio=None, broadcast=False)` | One-line default UDP socket wired through `chumicro-sockets`.  Importable separately so the deploy graph doesn't pull `chumicro-sockets` for apps with a custom transport. |

## Platform support

Pure-Python; runs identically on CPython, MicroPython, and CircuitPython.  Hard dependency: `chumicro-sockets` (Decision 0042 "core infrastructure" rule — single `pip install chumicro-ntp` brings the stack).

## Examples

| Example | What it shows |
|---|---|
| [`examples/quickstart.py`](examples/quickstart.py) | Synthetic SNTP exchange against `FakeUDPSocket` — runs anywhere, no network. |
| [`examples/circuitpython_ntp_query.py`](examples/circuitpython_ntp_query.py) | Real query against `pool.ntp.org` — wifi up, UDP socket via factory, runner-shaped poll loop. |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries ntp
python scripts/run.py test-libraries-functional --library ntp
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/ntp/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/ntp/experimental/)**

## Find this library

- **PyPI:** [chumicro-ntp](https://pypi.org/project/chumicro-ntp/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_ntp) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_ntp)
- **Source:** [libraries/ntp](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp)
