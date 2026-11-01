# chumicro-test-harness

**Small test runner that runs one test file unchanged on MicroPython, CircuitPython, and the Python on your laptop.**

pytest runs only on CPython.  On a board, this package takes its place: it finds the `test_` functions in a file, runs each one, and prints a `PASS`, `FAIL`, or `SKIP` line for it.  [`chumicro-pytest-device`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device) copies the harness to the board with each test file, runs the file there, and turns those lines back into pytest results.  The same file also runs under plain `pytest` on the laptop.

## Install

```bash
pip install chumicro-test-harness
```

Each ChuMicro library's `[test]` extra installs it, as in `pip install chumicro-mqtt[test]`.  `chumicro-pytest-device` needs it installed before it can run a test on a board.

## Quick example

A test file imports `raises` and `skip` from the harness.  `chumicro-pytest-device` calls the runner itself.

```python
import gc

from chumicro_test_harness import raises, skip
from chumicro_timing import Rate


def test_rate_rejects_a_zero_period():
    with raises(ValueError, match="greater than zero"):
        Rate(0, 0)


def test_board_reports_free_memory():
    if not hasattr(gc, "mem_free"):
        skip("gc.mem_free exists only on MicroPython and CircuitPython")
    assert gc.mem_free() > 0
```

On the laptop, `pytest` passes the first test and skips the second.  On MicroPython or CircuitPython the harness prints one line per test, a heap reading, and a summary:

```text
PASS test_board_reports_free_memory (0.000s, heap +0)
PASS test_rate_rejects_a_zero_period (0.000s, heap +0)
HEAP 2053280 bytes free (delta -224 bytes)
SUMMARY total=2 failed=0 time=0.001s
```

`chumicro-pytest-device` reads those lines and reports each test in pytest.  A test that cannot run on a runtime calls `skip()`.  A bare `return` reads as PASS on every runtime, which hides a test that checked nothing.

## Where a test file runs

| Runtime | What runs the file | Command |
|---|---|---|
| CPython on the laptop | pytest imports it like any test file | `pytest libraries/timing/tests` |
| MicroPython or CircuitPython unix port on the laptop | `chumicro-pytest-device` starts `support/test_harness/run_cross_runtime.py` once per file | `pytest libraries/timing/tests --target unix-port --runtime both` |
| A board | `chumicro-pytest-device` copies the harness and the file to the board and runs the file there | `pytest projects/greenhouse/functional_tests --runtime circuitpython` |

The unix-port row needs a ChuMicro source checkout, because `run_cross_runtime.py` sits beside the package rather than inside it.  The [`chumicro-pytest-device` README](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/pytest-device) covers the board row.

## What's included

| Name | What it does |
|---|---|
| `raises(expected, match=None)` | Context manager that fails the test unless its block raises `expected`.  `match` is a regular expression the error message must contain, as in `pytest.raises`. |
| `skip(reason)` | Ends the test as SKIP with `reason`.  pytest and the board runner both report it. |
| `chumicro_test_harness.patching` | `SwapAttribute` and `SwapItem` swap an attribute or a dict entry for the length of a `with` block.  `FakeModule` stands in for a module object.  The unix ports have no `unittest.mock` or `types`, so cross-runtime tests use these. |
| `chumicro_test_harness.network` | `runtime_config()` reads `/runtime_config.msgpack` on a board.  `wifi_up(ssid, password)` joins wifi through the runtime's own `wifi` or `network` module and returns the radio and the IP address. |
| `marker(name, **values)` | Prints a `NAME key=value` line for the laptop to parse, and raises when a value holds whitespace or `=`, which would make the laptop drop the line. |
| `run_module(module, name_filter=None)` | Runs every `test_` function and every `test_` method of a `Test` class on a module, and prints the result lines. |
| `run_one_file(test_file)` | Puts every `libraries/*/src` and `support/*/src` folder on `sys.path`, runs the file through `run_module`, and returns `0` when every test passed. |
| `chumicro_test_harness.discovery` | `discover_source_roots()` lists those `src` folders, and `setup_source_paths()` adds them to `sys.path`. |

## Find this package

- **PyPI:** [chumicro-test-harness](https://pypi.org/project/chumicro-test-harness/)
- **Source:** [support/test_harness](https://github.com/ChuMicro/ChuMicro/tree/main/support/test_harness)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
