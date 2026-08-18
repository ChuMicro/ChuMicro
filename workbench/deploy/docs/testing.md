# Testing Helpers

`chumicro_deploy.testing` ships three deterministic fakes for host-side unit tests of code that drives `chumicro-deploy`.  All three go into injection points the production code already exposes, so tests can exercise full deploy / probe / flash flows without touching real hardware.

| Fake | Replaces | Use it when |
|------|----------|-------------|
| `FakeTransport` | `MicropythonTransport` / `CircuitpythonTransport` | You're testing `Deployer` / `RecoveringDeployer` orchestration and don't care which physical transport runs underneath. |
| `FakeSerialPort` | `serial.Serial` | You're testing `CircuitpythonTransport` internals (the raw-REPL state machine, chunked execution, drive-flash timing) and want to script port behavior byte-for-byte. |
| `FakeTime` | Python's `time` module | The transport accepts a `TimeSource` via its `time=` parameter; pass `FakeTime()` so timeout-driven retry loops execute instantly instead of waiting on the real clock. |

## `FakeTransport`

Records every call (`connect`, `list_files_in_scope`, `deploy_files`, `disconnect`, and the rest) into a list and returns canned output for the execute step.  Implements both the basic `TransportProtocol` and `ExtendedTransportProtocol` (chunked execution + free-memory probing), so tests for either path can use the same fake.

`Deployer` takes a `Device`, not a transport, and calls `Device.create_transport()` once per deploy.  Set the device's `transport_factory` to hand back the fake instead:

```python
from chumicro_deploy import Device, Deployer, FileMapSource
from chumicro_deploy.testing import FakeTransport

def test_deploy_diff_lists_before_writing() -> None:
    """deploy_diff() should check what's on the board before staging."""
    transport = FakeTransport(execute_output="hello from device\n")
    device = Device(
        transport="micropython",
        address="/dev/fake",
        transport_factory=lambda _device: transport,
    )
    source = FileMapSource(
        {"/main.py": "print('hello from device')"}, entrypoint="/main.py",
    )

    result = Deployer(device).deploy_diff(source)

    assert result.execute_output == "hello from device\n"
    assert result.staged_files == ["/main.py"]
    method_names = [name for name, _args in transport.calls]
    assert method_names.index("connect") < method_names.index("list_files_in_scope")
    assert method_names.index("list_files_in_scope") < method_names.index("deploy_files")
```

`transport_factory` receives the owning `Device`, so one factory can serve several devices in the same test and still return a distinct fake per board.

Knobs you'll reach for most often:

- `execute_output`: string returned by `execute()`.
- `mode`: deploy-mode label (`"ram"`, `"flash"`, `"mount"`, `"copy"`).
- `free_memory_bytes`: value returned by `probe_free_memory()` (drives the chunked-RAM heuristic).
- `probe_result`: `DeviceImplementation` returned by `probe_implementation()`, or `None` to simulate a probe that couldn't complete.
- `bootloader_reset_result`: return value of `reset_into_bootloader()`; set to `False` to exercise the `flash_firmware` interactive-fallback branch.
- `calls`: the recorded call list (`[(method_name, args_tuple), ...]`) for assertions.

## `FakeSerialPort`

Simulates the subset of `serial.Serial` that `CircuitpythonTransport` uses: `read()`, `write()`, `close()`, `reset_input_buffer()`, and the `in_waiting` property.  Reads return canned responses you supply on construction; writes are recorded into a list.

```python
from chumicro_deploy.circuitpython_transport import CircuitpythonTransport
from chumicro_deploy.testing import FakeSerialPort, FakeTime

def test_circuitpython_transport_enters_raw_repl() -> None:
    """connect() should interrupt twice, then switch to raw REPL."""
    port = FakeSerialPort(read_responses=[b"\r\nraw REPL; CTRL-B to exit\r\n>"])
    transport = CircuitpythonTransport(
        address="/dev/cu.fake",
        serial_port_factory=lambda **_kwargs: port,
        time=FakeTime(),
    )

    transport.connect()

    # Two Ctrl-C bytes interrupt whatever the board was running, then
    # Ctrl-A enters raw REPL.
    assert port.writes[:3] == [b"\x03", b"\x03", b"\x01"]
```

Pass `open_error=...` to simulate a serial-port open failure (e.g. `PermissionError`), so the transport's classifier turns it into a `PORT_UNAVAILABLE` recovery hint.

## `FakeTime`

Deterministic seconds-domain time source that satisfies the `TimeSource` protocol `CircuitpythonTransport` accepts via its `time=` parameter.  The clock is **stable**: `monotonic()` returns the same value until you advance it.  `sleep()` does **not** actually wait, so a test that exercises a 30-second timeout completes in microseconds.

```python
from chumicro_deploy.testing import FakeTime

def test_clock_is_stable_until_advanced() -> None:
    """Repeated monotonic() calls return the same value with no advance."""
    fake = FakeTime()
    assert fake.monotonic() == fake.monotonic()  # stable

    fake.sleep(1.5)            # advances the clock without waiting
    assert fake.monotonic() == 1.5

    fake.advance(0.5)          # explicit advance for non-sleep timing tests
    assert fake.monotonic() == 2.0
```

Two ways to move the clock forward:

- `sleep(duration)`: the production code's `time.sleep()` analog.  Accepts the same float seconds and advances the fake clock in lockstep, so production code that genuinely calls `sleep` before checking a deadline behaves correctly under the fake.
- `advance(seconds)`: explicit clock movement when production does **not** sleep but the test needs to push past a deadline (e.g. simulating elapsed time between `connect()` and the next read).

Pass `start=` to begin at a non-zero timestamp.  Useful when production reads `monotonic()` once at startup and you want to verify it computes deltas correctly:

```python
fake = FakeTime(start=1_000_000.0)
```

## Why these fakes ship with the package

`chumicro-deploy` is a published workbench tool.  Third parties install it via `pip install chumicro-deploy` and write their own host-side tests against the public API.  Without published fakes, every consumer would either re-derive the transport contract from the source or pull in heavier dependencies like `freezegun`.  Shipping the fakes alongside the production code makes downstream testing the obvious path, and it keeps the fakes honest: they live in the same package as the protocols they satisfy, so a change to `TransportProtocol` or `TimeSource` breaks this package's own tests first.

## Companion fakes in chumicro-repl

If your tests cover the deploy → tail pipeline, [`chumicro-repl`](https://chumicro.com/ChuMicro/repl/stable/) ships parallel fakes (`FakeSerialPort`, `FakeKeyboard`, `FakeTime`) under `chumicro_repl.testing`.  The `FakeTime` shape is identical to the one here, so one fake clock can drive both halves of an integration test with no cross-package adapter code.

`Deployer` has no clock of its own; it delegates timing to the transport.  Wire the clock into the transport, and pass the same instance to `tail`:

```python
from chumicro_deploy import Device, Deployer
from chumicro_deploy.circuitpython_transport import CircuitpythonTransport
from chumicro_deploy.testing import FakeTime
from chumicro_repl import tail

clock = FakeTime()
device = Device(
    transport="circuitpython",
    address="/dev/cu.fake",
    transport_factory=lambda board: CircuitpythonTransport(
        board.address, time=clock,
    ),
)

Deployer(device).deploy_diff(source)
tail(device, seconds=10, time=clock)
```

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) · \
[PyPI](https://pypi.org/project/chumicro-deploy/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
