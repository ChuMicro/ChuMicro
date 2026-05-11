# chumicro-pytest-device

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Pytest plugin that runs your tests on a real CircuitPython or MicroPython board.**

Drop tests under any `functional_tests/` directory and the plugin intercepts collection: stages your library + test source onto the connected board via `chumicro-deploy`, executes the test in the device runtime, parses the result back, and fails / passes the host-side pytest with the on-device outcome.  Reads device targets from your `devices.yml`; respects the same workspace conventions the rest of the ChuMicro tooling uses.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — runs on your laptop, drives the boards over serial.

## Install

```bash
pip install chumicro-pytest-device
```

`chumicro-deploy` (and its `pyserial` / `mpremote` deps) come along.  Auto-registers via the `pytest11` entry point — no `pytest_plugins = [...]` line in `conftest.py` needed.  Native Windows isn't currently supported (the underlying `chumicro-deploy` raises `WindowsNotSupportedError`); WSL2 works.

## Quick example

A functional test reads like a normal unit test — it just runs on the board:

```python
# libraries/timing/functional_tests/test_heartbeat.py
import time
from chumicro_timing import Heartbeat


def test_heartbeat_fires_on_real_clock() -> None:
    heartbeat = Heartbeat(period_ms=10)
    deadline = time.monotonic() + 1.0
    fires = 0
    while time.monotonic() < deadline:
        if heartbeat.check(int(time.monotonic() * 1000)):
            fires += 1
    assert fires > 50
```

Run on every device targeted by your `devices.yml` defaults:

```bash
pytest libraries/timing/functional_tests --runtime both
```

The plugin discovers the board, stages `chumicro_timing/src/` + the test, executes on-device, parses the on-device pytest result back, and reports PASS / FAIL through host-side pytest.

## What's included

### Plugin modules

| Module | Purpose |
|---|---|
| `chumicro_pytest_device.plugin` | The pytest plugin entry-point module — collection interception, deploy orchestration, result reporting |
| `chumicro_pytest_device.result_parser` | Parses on-device test output back into `TestResult` objects |
| `chumicro_pytest_device.pr_summary` | Renders a markdown PR-summary block from captured run results — drop into a CI step |

### Pytest options

| Option | Effect |
|---|---|
| `--runtime {micropython,circuitpython,both}` | Override `defaults.ide_runtime` |
| `--micropython-device <id>` | Override `defaults.micropython` |
| `--circuitpython-device <id>` | Override `defaults.circuitpython` |
| `--deploy-mode {ram,flash}` | Override the per-device deploy mode |
| `--pr-summary` | Append a markdown summary block to stdout at end of session |
| `--pr-summary-command <text>` | The command that re-runs the failed tests, included in the summary |

## Where this fits

Depends on [`chumicro-deploy`](../deploy/) for staging tests on a board.  Auto-registers via `pytest11`; reads `devices.yml` written by [`chumicro-workspace`](../workspace/).

## Companions

| Workbench tool | Why you'd use it alongside |
|---|---|
| [`chumicro-deploy`](../deploy/) | The transport layer the plugin uses for staging.  Useful directly when you want to drive a board outside of pytest |
| [`chumicro-repl`](../repl/) | Tail a board's REPL after a deploy — handy for follow-up debugging when a functional test surprises you |
| [`chumicro-workspace`](../workspace/) | The host CLI for project workspaces.  Reads the same `devices.yml` schema |

## Contributing

Working on `chumicro-pytest-device` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
```

No hardware-side functional tests for this package itself — its job is to drive consumer libraries' functional tests via `pytest libraries/<name>/functional_tests/` against a board registered in `devices.yml`.

## Find this library

- **PyPI:** [chumicro-pytest-device](https://pypi.org/project/chumicro-pytest-device/)
- **Source:** [workbench/pytest-device](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
