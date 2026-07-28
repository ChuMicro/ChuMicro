# chumicro-pytest-device

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Pytest plugin that runs your tests in a CircuitPython or MicroPython runtime, on a real board or in a unix-port subprocess.**

`--target` picks where a test runs.  The default, `device`, intercepts collection under any `functional_tests/` directory: it stages your library and test source onto the connected board via `chumicro-deploy`, executes the test in the device runtime, parses the result back, and passes or fails host-side pytest with the on-device outcome.  `device-unit` puts a library's ordinary `tests/` suite on the board instead, so the cross-runtime unit tests run against real firmware.  `unix-port` runs that same suite in a MicroPython or CircuitPython unix-port subprocess, which gives you runtime-accurate results with no board plugged in.  Device targets read `devices.yml` and follow the same workspace conventions as the rest of the ChuMicro tooling.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md): it runs on your laptop and drives the boards over serial.

## Install

```bash
pip install chumicro-pytest-device
```

That brings both ChuMicro dependencies with it: `chumicro-deploy` (plus its `pyserial` / `mpremote` deps) and `chumicro-workspace`, along with `msgpack` and `cryptography`.  The plugin auto-registers via the `pytest11` entry point, so you don't need a `pytest_plugins = [...]` line in `conftest.py`.  Native Windows isn't currently supported (the underlying `chumicro-deploy` raises `WindowsNotSupportedError`); WSL2 works.

## Quick example

A functional test reads like a normal unit test.  It just runs on the board:

```python
# libraries/mylib/functional_tests/test_heartbeat.py
import time
from chumicro_timing import Heartbeat
from chumicro_timing.ticks import ticks_ms


def test_heartbeat_fires_on_real_clock() -> None:
    heartbeat = Heartbeat(period_ms=10)
    deadline = time.monotonic() + 1.0
    fires = 0
    while time.monotonic() < deadline:
        if heartbeat.poll(ticks_ms()):
            fires += 1
    assert fires > 50
```

The `libraries/<name>/functional_tests/` layout is what triggers the routing, so put the file there and the plugin takes over from `pytest`.  Run it on every device your `devices.yml` defaults name:

```bash
pytest libraries/mylib/functional_tests --runtime both
```

The plugin discovers the board, stages `libraries/mylib/src/` plus the test, executes on-device, parses the on-device pytest result back, and reports PASS or FAIL through host-side pytest.

With no board attached, the same library's ordinary unit tests run in a unix-port interpreter instead:

```bash
pytest libraries/mylib/tests --target unix-port --runtime micropython
```

## What's included

### Plugin modules

| Module | Purpose |
|---|---|
| `chumicro_pytest_device.plugin` | The pytest plugin entry-point module: collection interception, deploy orchestration, result reporting |
| `chumicro_pytest_device.runtime_config` | `set_runtime_config()`, called from a `functional_tests/conftest.py`, hands the device a config payload staged at `/runtime_config.msgpack`.  Board-side code reads it through the usual `chumicro_config.load_runtime_config()` |
| `chumicro_pytest_device.features` | Per-board feature gating.  A test file that declares `__chumicro_features__ = ("esp32",)` is dropped from the plan for any board that doesn't probe as carrying that feature |
| `chumicro_pytest_device.fixtures` | Host-side fixtures for networking tests: `lan` (LAN address, free port, wait-until-listening), `mosquitto` (spawns a broker), `tcp_echo` / `udp_echo` / `tls_echo` (echo servers, TLS with a generated self-signed cert), and `host_driver` (an HTTP client that fires once the board prints its ready marker) |
| `chumicro_pytest_device.testing` | Public fakes and builders for testing code that drives the plugin: `FakeConfig`, `FakeSession`, `hot_path_device`, `prime_transport_cache`, `make_prepare_item`, `make_run_file_item`, `make_test_item` |
| `chumicro_pytest_device.result_parser` | Parses on-device test output back into `TestResult` objects |
| `chumicro_pytest_device.pr_summary` | Renders a Markdown PR-summary block from captured run results; drop it into a CI step |
| `chumicro_pytest_device.backends` | The execution backends behind `--target`: the board transport and the unix-port subprocess |

### Pytest options

| Option | Effect |
|---|---|
| `--target {device,device-unit,unix-port}` | Where tests run.  `device` (the default) runs `functional_tests/` on a board, `device-unit` runs `libraries/<name>/tests/` on a board, `unix-port` runs that same suite in a unix-port subprocess |
| `--runtime {micropython,circuitpython,both}` | Override `defaults.ide_runtime` |
| `--micropython-device <id>` | Override `defaults.micropython` |
| `--circuitpython-device <id>` | Override `defaults.circuitpython` |
| `--micropython-binary <path>` | unix-port only: the MicroPython binary to spawn, ahead of `.tools/micropython.path` and `PATH` |
| `--circuitpython-binary <path>` | unix-port only: the CircuitPython binary to spawn, ahead of `.tools/circuitpython.path` and `PATH` |
| `--unix-port-timeout <seconds>` | unix-port only: per-file wall-clock ceiling; a worker that overruns is killed and the file fails cleanly |
| `--unix-port-heapsize <size>` | unix-port only: heap ceiling for workers (`192K`, say).  Defaults to the per-runtime budgets in `target-runtimes.toml`; pass `0` or `off` for the port's native multi-MB heap |
| `--deploy-mode {ram,flash}` | Override the per-device deploy mode |
| `--per-file` | Device unit runs: soft-reset before each test *file* rather than once per library, so a big module starts on a fresh interpreter.  Worth it on a 256 KB board |
| `--pr-summary` | Append a Markdown summary block to stdout at end of session |
| `--pr-summary-command <text>` | The command that re-runs the failed tests, included in the summary |

## Where this fits

Two ChuMicro dependencies, both installed for you.  [`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) is the transport that stages tests on a board.  [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) supplies the device-orchestration primitives the collection layer dispatches to (transport build, bootstrap runner, library-source walking) and is also what writes the `devices.yml` this plugin reads.  Auto-registers via `pytest11`.

## Companions

| Workbench tool | Why you'd use it alongside |
|---|---|
| [`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) | The transport layer the plugin uses for staging.  Useful directly when you want to drive a board outside of pytest |
| [`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) | Tail a board's REPL after a deploy, which is where you go next when a functional test surprises you |
| [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) | The host CLI for project workspaces.  Reads the same `devices.yml` schema |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Find this library

- **PyPI:** [chumicro-pytest-device](https://pypi.org/project/chumicro-pytest-device/)
- **Source:** [workbench/pytest-device](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
