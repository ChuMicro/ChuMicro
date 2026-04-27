# chumicro-pytest-device

Pytest plugin that drives connected CircuitPython and MicroPython boards.
When a test sits under a `functional_tests/` directory, the plugin
intercepts collection, stages the library + test source onto the board
via `chumicro-deploy`, executes the test on the device runtime, and
parses the result back to host-side pytest.

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

```bash
pip install chumicro-pytest-device
```

The plugin auto-registers via the `pytest11` entry point — no
`pytest_plugins = [...]` line in `conftest.py` needed.

## Quick example

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

```bash
# Run on every device targeted by your devices.yml defaults:
pytest libraries/timing/functional_tests --chumicro-runtime both
```

## What's included

| Symbol | Purpose |
|---|---|
| `chumicro_pytest_device.plugin` | The pytest plugin entry-point module |
| `chumicro_pytest_device.result_parser` | Parses on-device test output back into `TestResult` objects |
| `chumicro_pytest_device.pr_summary` | Renders a markdown PR-summary block from the captured run results |

The plugin reads device targets from `devices.yml` (schema owned by `chumicro-deploy`'s `chumicro_deploy.config.default`) and respects the `[wifi]` section of `chumicro-dev-config.toml` when functional tests need real wifi credentials.

## Pytest options

- `--chumicro-runtime {micropython,circuitpython,both}` — override `defaults.ide_runtime`.
- `--chumicro-micropython-device <id>` — override `defaults.micropython`.
- `--chumicro-circuitpython-device <id>` — override `defaults.circuitpython`.
- `--chumicro-deploy-mode {ram,flash}` — override the per-device deploy mode.
- `--chumicro-pr-summary` — append a markdown summary block to stdout at end of session.
- `--chumicro-pr-summary-command <text>` — the command that re-runs the failed tests, included in the summary.

## Platform support

Host-side only.  Pure Python; depends on `pytest`, `chumicro-deploy`, and (transitively via `chumicro-deploy`) `pyserial` + `mpremote`.
