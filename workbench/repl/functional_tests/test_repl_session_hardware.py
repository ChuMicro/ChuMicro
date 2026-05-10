"""Hardware-gated tests for ``ReplSession`` against connected boards.

Open a REPL to at least one CP and one MP board, exchange Ctrl-C /
Ctrl-D, verify clean exit.

These tests open a real raw-REPL session over pyserial and exercise
the public API — ``exec``, ``call``, ``read_until`` — on each
runtime.  Skip cleanly when ``devices.yml`` has no matching entry,
so contributors without hardware run preflight + this directory and
just see "skipped".
"""

from __future__ import annotations

from chumicro_deploy import Device, DeviceEntry
from chumicro_repl import ReplSession


def _build_device(entry: DeviceEntry) -> Device:
    """Translate a chumicro ``DeviceEntry`` into a public ``Device``."""
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
    )


# ---------------------------------------------------------------------------
# MicroPython
# ---------------------------------------------------------------------------

def test_micropython_session_exec_returns_stdout(
    micropython_device: DeviceEntry,
) -> None:
    """Bottom-line acceptance: open raw REPL on MP, run code, get output."""
    device = _build_device(micropython_device)
    with ReplSession(device) as session:
        output = session.exec("print('chu-repl-mp')")
    assert "chu-repl-mp" in output


def test_micropython_session_call_round_trips_literal(
    micropython_device: DeviceEntry,
) -> None:
    """``call`` should round-trip a literal-eval-able value off the board."""
    device = _build_device(micropython_device)
    with ReplSession(device) as session:
        # ``sum`` is a built-in everywhere; literal-eval-friendly result.
        result = session.call("sum", [1, 2, 3, 4])
    assert result == 10


def test_micropython_session_exec_after_exec(  # noqa: CHU001 — `exec` matches the public ReplSession.exec API
    micropython_device: DeviceEntry,
) -> None:
    """Two execs in one session — verifies the framing recovers properly."""
    device = _build_device(micropython_device)
    with ReplSession(device) as session:
        first = session.exec("answer = 42")
        second = session.exec("print(answer)")
    assert first == ""  # assignment, no output
    assert "42" in second


# ---------------------------------------------------------------------------
# CircuitPython
# ---------------------------------------------------------------------------

def test_circuitpython_session_exec_returns_stdout(
    circuitpython_device: DeviceEntry,
) -> None:
    """Bottom-line acceptance: open raw REPL on CP, run code, get output."""
    device = _build_device(circuitpython_device)
    with ReplSession(device) as session:
        output = session.exec("print('chu-repl-cp')")
    assert "chu-repl-cp" in output


def test_circuitpython_session_call_round_trips_literal(
    circuitpython_device: DeviceEntry,
) -> None:
    device = _build_device(circuitpython_device)
    with ReplSession(device) as session:
        result = session.call("sum", [10, 20, 30])
    assert result == 60


def test_circuitpython_session_clean_exit_leaves_friendly_repl(
    circuitpython_device: DeviceEntry,
) -> None:
    """After ``ReplSession.__exit__`` the board is back at the friendly REPL.

    Validates the Ctrl-B that the context manager sends on exit —
    if it were skipped, a follow-up ``ReplSession`` (or any other
    consumer that expects friendly mode) would see raw-REPL bytes
    instead of ``>>>``.

    We verify by re-opening a second ``ReplSession`` immediately
    after the first; the handshake (Ctrl-C × 2 + Ctrl-A) only
    succeeds if the previous session left the device in a sane
    state.
    """
    device = _build_device(circuitpython_device)
    with ReplSession(device) as first_session:
        first_session.exec("first = 1")
    # Second session must be able to enter raw REPL again.
    with ReplSession(device) as second_session:
        output = second_session.exec("print('second-session-ok')")
    assert "second-session-ok" in output
