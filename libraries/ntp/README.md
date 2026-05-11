# chumicro-ntp

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Runner-shaped SNTP client over an injected UDP socket — pure-Python, cross-runtime.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-ntp

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_ntp

# CPython
pip install chumicro-ntp
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

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

`chumicro_sockets_factory` lives in its own submodule so apps with a custom UDP transport don't pull `chumicro-sockets` into their device deploy.  Pass any `chumicro_sockets.UDPSocket`-shaped object to `NTPClient(socket=...)`.

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

Pure-Python; runs identically on CPython, MicroPython, and CircuitPython.  Hard dependency: `chumicro-sockets` (a single `pip install chumicro-ntp` brings the stack).

## Examples

| Example | What it shows |
|---|---|
| [`examples/ntp_query.py`](examples/ntp_query.py) | Real query against `pool.ntp.org` — wifi up, UDP socket via factory, runner-shaped poll loop.  Cross-runtime (CP + MP). |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
pip install -e .[test]
pytest tests/
pytest functional_tests/   # needs a registered board in devices.yml
```

Before running functional tests, register a board with `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/ntp/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/ntp/experimental/)**

## Find this library

- **PyPI:** [chumicro-ntp](https://pypi.org/project/chumicro-ntp/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_ntp) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_ntp)
- **Source:** [libraries/ntp](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
