# chumicro-pytest-device

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Pytest plugin that runs your tests on a CircuitPython or MicroPython board and reports each result in pytest.**

A board test is a plain `def test_...():` function in a `functional_tests/` folder.  Running `pytest` on that folder hands the file to this plugin.  The plugin copies the test and the ChuMicro libraries it imports to the board listed in `devices.yml`, runs the file on the board, and reads the results back over USB serial.  pytest then marks each test PASSED or FAILED, the same as a test that ran on the laptop.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md): it runs on your laptop and drives the boards over serial.

## Install

```bash
pip install chumicro-pytest-device chumicro-test-harness
```

`chumicro-test-harness` is the small test runner the plugin copies to the board beside each test file.  `chumicro-pytest-device` brings `pytest`, `chumicro-deploy`, `chumicro-workspace`, `msgpack`, and `cryptography` with it.  pytest loads the plugin through its `pytest11` entry point, so `conftest.py` needs no `pytest_plugins` line.

Copies to a CircuitPython board's flash go through `rsync`, which the [`chumicro-deploy` install notes](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy#install) cover.  Native Windows is unsupported because `chumicro-deploy` raises `WindowsNotSupportedError` there.  WSL2 works.

## Quick example

The board needs an entry in the workspace's `devices.yml`.  `chumicro-workspace add-device <id> --address <port>` probes the board and writes that entry.

Save a test in the project's `functional_tests/` folder:

```python
# projects/greenhouse/functional_tests/test_board_clock.py
from chumicro_timing import Deadline, ticks_ms


def test_deadline_expires_on_the_board_clock():
    deadline = Deadline(50, ticks_ms())
    while not deadline.expired(ticks_ms()):
        pass
    assert deadline.remaining(ticks_ms()) == 0
```

pytest stays on the laptop.  The board runs the file with the ChuMicro test harness.  A board test is a plain function, or a `test_` method on a `class Test...:`, with plain `assert` lines.  It imports nothing from `pytest`.  `raises` and `skip` come from `chumicro_test_harness` instead.

Run the folder from the workspace root:

```bash
pytest projects/greenhouse/functional_tests --runtime circuitpython
```

`--runtime` names the runtime on the board: `micropython`, `circuitpython`, or `both`.  Without it, the plugin reads `defaults.ide_runtime` from `devices.yml`.  A new `devices.yml` sets that to `micropython`.  pytest reports `no tests collected` for a runtime with no registered board.

A passing run with `-v` prints one line per step:

```text
projects/greenhouse/functional_tests/test_board_clock.py::Setup: CircuitPython PASSED [ 33%]
projects/greenhouse/functional_tests/test_board_clock.py::Run overhead: CircuitPython PASSED [ 66%]
projects/greenhouse/functional_tests/test_board_clock.py::test_deadline_expires_on_the_board_clock PASSED [100%]
```

pytest ends the run with `3 passed`.  Each file adds two steps for each board.  `Setup` connects to the board and copies the files.  `Run overhead` runs the whole file on the board once.  Each `test_` function then reports its own line from that run.  Without `-v`, pytest prints a dot for each line.

A failing test prints `Device test FAIL:` and the test name, then everything the board printed, traceback included.  An unplugged board fails `Setup` with `Transport connection failed`.  Every test in that file then fails with the same message.

## What runs on the board

pytest sends a project's board tests to the board only when the command names that `functional_tests` folder or a file inside it.  `pytest` alone, or `pytest projects`, leaves them out.

Pick tests by folder or by file.  The board runs every test in a file in one pass, so it also runs the tests a `test_board_clock.py::test_name` or `-k` selection leaves out.  The plugin fails a run that reports a test it did not collect, with `Device ran test(s) the host never collected`.

Each run copies these to the board:

- the test file
- every module beside it whose name starts with an underscore, such as `_greenhouse.py`, for helper code the tests share
- each ChuMicro library the test imports, plus the ChuMicro libraries those depend on, from the workspace's `libraries/` folder or the `library_sources:` map in `workspace.yml`
- the `testing` module of fakes from each of those libraries
- the test harness

The rest of the project folder, `app.py` included, stays on the laptop.

## Hand a test its settings

A board test reads settings through `chumicro_config.load_runtime_config()`, the same call a deployed project makes.  A `conftest.py` in the `functional_tests` folder builds the settings on the laptop and passes them to `set_runtime_config`.  The plugin writes them to `/runtime_config.msgpack` on the board before the tests run.

```toml
# projects/greenhouse/project_config.toml
[greenhouse]
target_celsius = 21.5
```

```python
# projects/greenhouse/functional_tests/conftest.py
from pathlib import Path

from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config


def pytest_configure(config):
    payload = compose_runtime_config(
        secrets_toml=config.rootpath / "secrets.toml",
        project_config=Path(__file__).parent.parent / "project_config.toml",
    )
    set_runtime_config(config, payload, required_keys=["greenhouse.target_celsius"])
```

```python
# projects/greenhouse/functional_tests/test_settings.py
from chumicro_config import load_runtime_config


def test_target_temperature_reaches_the_board():
    config = load_runtime_config()
    assert config["greenhouse.target_celsius"] == 21.5
```

`compose_runtime_config` merges `secrets.toml` with the project's `project_config.toml` into dotted keys such as `greenhouse.target_celsius`, the same merge `chumicro-workspace deploy` performs.  `required_keys` lists the keys the tests need.  When one is missing from the merged settings, the plugin skips the project's board tests with a message that names the key.  The settings file needs flash mode: a RAM-mode run with settings registered fails with `UnsupportedExtraFilesError`.

## Keep a file off the wrong board

A module-level marker in the test file limits where it runs:

| Marker | Effect |
|---|---|
| `__chumicro_runtimes__ = ("circuitpython",)` | Runs the file only on the listed runtimes. |
| `__chumicro_features__ = ("esp32",)` | Runs the file only on a board that has every listed feature.  The plugin asks each board for its features before the run.  It recognizes one feature, `esp32`. |

## What's included

### Pytest options

`pytest --help` lists these under "ChuMicro device-test plugin".

| Option | What it does |
|---|---|
| `--runtime {micropython,circuitpython,both}` | Runtime to test on.  Board targets default to `defaults.ide_runtime` in `devices.yml`.  The `unix-port` target defaults to `both`. |
| `--micropython-device <id>` | Runs on this `devices.yml` board in place of `defaults.micropython`. |
| `--circuitpython-device <id>` | Runs on this `devices.yml` board in place of `defaults.circuitpython`. |
| `--deploy-mode {ram,flash}` | Copies the tests to the board's flash, or runs them from RAM, in place of the `deploy_mode` in `devices.yml`. |
| `--per-file` | In flash mode, soft-resets the board and copies one test file at a time, so each file starts on a fresh interpreter.  The default resets once per library, which is faster.  Large suites on a 256 KB board need it. |
| `--target {device,device-unit,unix-port}` | Where the tests run.  `device`, the default, runs `functional_tests/` files on a board.  `device-unit` runs a library's own `libraries/<name>/tests/` suite on a board.  `unix-port` runs that suite in a MicroPython or CircuitPython unix-port subprocess on the laptop.  It needs the harness script `support/test_harness/run_cross_runtime.py` from a ChuMicro source checkout. |
| `--micropython-binary <path>` | `unix-port` target: the MicroPython binary to run, ahead of `.tools/micropython.path` and `PATH`. |
| `--circuitpython-binary <path>` | `unix-port` target: the CircuitPython binary to run, ahead of `.tools/circuitpython.path` and `PATH`. |
| `--unix-port-timeout <seconds>` | `unix-port` target: seconds one file may run before the plugin stops it and fails it.  Default 120. |
| `--unix-port-heapsize <size>` | `unix-port` target: heap size per run, such as `192K`.  The default is the `[heap]` budget in `target-runtimes.toml` at the workspace root.  `0`, `off`, or a workspace with no budget gives the port its own multi-megabyte heap. |
| `--pr-summary` | Prints a Markdown summary of the board results at the end of the run, ready to paste into a pull request. |
| `--pr-summary-command <text>` | The command the `--pr-summary` block shows.  Default `pytest`. |

### Modules

| Module | What it holds |
|---|---|
| `chumicro_pytest_device.runtime_config` | `set_runtime_config()`, which registers the settings a `functional_tests/conftest.py` hands the board. |
| `chumicro_pytest_device.fixtures` | Laptop-side helpers for network tests: `lan` (LAN address, free port, wait for a port to listen), `mosquitto` (starts an MQTT broker), `tcp_echo`, `udp_echo`, and `tls_echo` (echo servers, TLS with a generated self-signed certificate), and `host_driver` (an HTTP client that sends its request once the board prints its ready line). |
| `chumicro_pytest_device.result_parser` | Turns the board's `PASS`, `FAIL`, `SKIP`, `HEAP`, and `SUMMARY` lines into `TestResult` objects. |
| `chumicro_pytest_device.pr_summary` | Builds the `--pr-summary` Markdown block. |
| `chumicro_pytest_device.testing` | Fakes and builders for testing code that drives this plugin: `FakeConfig`, `FakeSession`, `hot_path_device`, `prime_transport_cache`, `make_prepare_item`, `make_run_file_item`, `make_test_item`. |
| `chumicro_pytest_device.plugin` | The pytest entry point: options, session setup, and reporting. |

## Where this fits

A ChuMicro library that takes a clock, socket, radio, or pin ships a `testing` module of fakes for tests that run on the laptop under plain `pytest`, with no board attached.  The [Testing Helpers page of `chumicro-timing`](https://chumicro.com/ChuMicro/timing/stable/testing/) shows one.  This plugin runs a test on the board itself, against the real clock, radio, and pins.

[`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) connects to the board and copies the files.  [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) finds the library folders a test needs.  Its `add-device` command writes the `devices.yml` this plugin reads.

## Companions

| Workbench tool | Why you'd use it alongside |
|---|---|
| [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) | Registers boards in `devices.yml` and deploys the project the tests cover. |
| [`chumicro-repl`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) | Opens the board's REPL and follows its output. |
| [`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) | Copies files to a board from a script, outside pytest. |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Find this library

- **PyPI:** [chumicro-pytest-device](https://pypi.org/project/chumicro-pytest-device/)
- **Source:** [workbench/pytest-device](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
