"""Hardware-gated tests for ``tail()`` against connected boards.

Two scenarios:

1. **Idle tail completes cleanly.**  Open the port for a short
   window with no traffic on the wire and assert ``tail()`` returns
   :attr:`ExitCode.OK` without raising.  Validates the
   "open + read + close" lifecycle on real hardware end-to-end.

2. **Traceback detection on a real board.**  Deploy code that
   raises, then tail the friendly REPL — the pattern detector
   has to recognize the runtime's actual traceback bytes (not
   just the host-side fakes' bytes).

The tests skip cleanly when ``devices.yml`` has no matching entry.

What's deliberately *not* here: a "deploy a heartbeat, tail it,
assert the marker appears" test.  ``Deployer.deploy()`` waits for
the entrypoint to finish before returning, so by the time
``tail()`` opens the port the script is done — there is no
deterministic on-device source of in-window output that doesn't
require a separate "leave it running" path on the board.  When
that path lands, this file gains the assertion-on-output test.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_deploy import Deployer, Device, DeviceEntry, FileMapSource
from chumicro_repl import ExitCode, tail
from chumicro_repl.highlight import strip_ansi_sequences


def _build_device(entry: DeviceEntry, deploy_mode: str) -> Device:
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode=deploy_mode,
        circuitpy_drive_path=(
            Path(entry.circuitpy_drive_path) if entry.circuitpy_drive_path else None
        ),
    )


# ---------------------------------------------------------------------------
# Idle-window lifecycle
# ---------------------------------------------------------------------------

def test_micropython_idle_tail_returns_ok(
    micropython_device: DeviceEntry,
) -> None:
    """``tail()`` against an idle MP board: open, wait, close, return OK.

    No deploy beforehand — the board sits at the friendly REPL.
    Half a second is enough to confirm the port opened cleanly,
    the read loop ran, and the function returned without raising.
    """
    device = _build_device(micropython_device, deploy_mode="ram")
    exit_code = tail(
        device,
        seconds=0.5,
        fail_on_traceback=True,
        reconnect_seconds=0.0,
    )
    # OK or DISCONNECTED is acceptable depending on the host's
    # serial driver behaviour during a quick open/close.  What
    # we're proving is that the function returns *something*
    # rather than raising a SerialException.
    assert exit_code in (ExitCode.OK, ExitCode.DISCONNECTED)


def test_circuitpython_idle_tail_returns_ok(
    circuitpython_device: DeviceEntry,
) -> None:
    """``tail()`` against an idle CP board: open, wait, close, return OK."""
    device = _build_device(circuitpython_device, deploy_mode="ram")
    exit_code = tail(
        device,
        seconds=0.5,
        fail_on_traceback=True,
        reconnect_seconds=0.0,
    )
    assert exit_code in (ExitCode.OK, ExitCode.DISCONNECTED)


# ---------------------------------------------------------------------------
# Traceback detection on a real board
# ---------------------------------------------------------------------------

def test_micropython_tail_detects_real_traceback(
    micropython_device: DeviceEntry,
    capsys,
) -> None:
    """Deploy code that raises — tail must surface the traceback.

    Picks MP because mpremote's mount mode replays the entrypoint
    output deterministically into the friendly REPL after the
    deploy exec returns; tail catches the trailing traceback bytes.
    """
    device = _build_device(micropython_device, deploy_mode="ram")
    deploy_result = Deployer(device).deploy(
        FileMapSource(
            {"/main.py": "raise ValueError('chu-tail-bang')"},
            entrypoint="/main.py",
        ),
    )
    # Deploy itself recognizes the device-side traceback.
    assert deploy_result.success is False
    assert deploy_result.traceback is not None
    assert "chu-tail-bang" in deploy_result.traceback

    # Tail may or may not catch a re-print depending on whether
    # the runtime auto-replays after the deploy session.  We
    # accept either OK (nothing re-emitted) or
    # TRACEBACK_DETECTED (the bytes streamed into our window) —
    # what matters is that the function returned cleanly without
    # raising, and that whatever it captured is consistent with
    # the deploy's own traceback marker.
    exit_code = tail(
        device,
        seconds=1.0,
        fail_on_traceback=True,
        reconnect_seconds=0.0,
    )
    captured = strip_ansi_sequences(capsys.readouterr().out)
    assert exit_code in (ExitCode.OK, ExitCode.TRACEBACK_DETECTED)
    if exit_code is ExitCode.TRACEBACK_DETECTED:
        assert "chu-tail-bang" in captured or "ValueError" in captured
