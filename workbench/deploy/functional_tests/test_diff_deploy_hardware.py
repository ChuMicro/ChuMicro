"""Hardware-gated tests for the scoped diff-deploy primitive.

Verifies the multi-thing-staging-replacement primitives
(``list_files_in_scope`` / ``delete_files`` /
``Deployer.deploy_diff``) against plugged-in boards.

Two coverage paths, both exercised on CircuitPython and
MicroPython:

* **Flash mode** — full diff exercise: plant initial set, second
  deploy with mixed new + stale files, confirm the stale subset
  was reported via ``on_file_deleted``.  Second deploy's
  entrypoint imports both kept + added libs so the successful
  exec is end-to-end evidence the new payload landed.
* **RAM mode** — diff routine collapses to ``deploy_files`` since
  RAM mode never wrote to flash.  Confirms the primitive doesn't
  regress the existing RAM-mode flow.

Plus a non-hardware smoke test that the :class:`FakeTransport`
in-memory state stays in sync with the real-board contract.

Skipped cleanly when ``devices.yml`` has no matching device.
"""

from __future__ import annotations

import time
from pathlib import Path

from chumicro_deploy import (
    Deployer,
    Device,
    DeviceEntry,
    FakeTransport,
    FileMapSource,
)

#: Settle window between back-to-back deploys.  After a deploy
#: disconnects, the Pi Pico W's USB CDC stack needs ~1 s before
#: the next mpremote subprocess can re-open the port + enter raw
#: REPL reliably.  Without this delay, the second deploy
#: occasionally hits ``TransportError("could not enter raw repl")``
#: even though the previous deploy's exit_raw_repl + close
#: completed cleanly.
_BACK_TO_BACK_SETTLE_SECONDS: float = 1.5


def _build_device(entry: DeviceEntry, deploy_mode: str) -> Device:
    """Translate a DeviceEntry into a public Device for flash-mode use."""
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
# MicroPython flash mode
# ---------------------------------------------------------------------------


def test_micropython_diff_deploy_round_trip(
    micropython_device: DeviceEntry,
) -> None:
    """First deploy → second deploy with new + stale files → diff cleans correctly.

    Sequence:

    1. Plain ``deploy_diff`` to plant a known set of files
       (entrypoint + two libs).
    2. Second ``deploy_diff`` with a different file map (drops one
       lib, keeps another, adds a new one, replaces the entrypoint).
    3. The deploy's ``on_file_deleted`` callback must report
       ``/lib/drop.py`` as the stale file removed.  The second
       deploy's ``import``-driven entrypoint exercises both
       ``/lib/keep.py`` (still present) and ``/lib/added.py`` (newly
       written), which together prove the new payload landed.
    """
    device = _build_device(micropython_device, deploy_mode="flash")
    deployer = Deployer(device)

    # Step 1: plant the initial set.
    initial_payload = {
        "/main.py": b"print('initial')\n",
        "/lib/keep.py": b"VALUE_KEEP = 1\n",
        "/lib/drop.py": b"VALUE_DROP = 1\n",
    }
    initial = deployer.deploy_diff(
        FileMapSource(initial_payload, entrypoint="/main.py"),
    )
    assert initial.success, initial.execute_output
    time.sleep(_BACK_TO_BACK_SETTLE_SECONDS)

    # Step 2: second deploy — drop /lib/drop.py, add /lib/added.py,
    # replace /main.py + /lib/keep.py.  The new entrypoint imports
    # both kept + added libs so a successful exec is end-to-end
    # evidence the new payload arrived intact.
    new_payload = {
        "/main.py": (
            b"from keep import VALUE_KEEP\n"
            b"from added import VALUE_ADDED\n"
            b"print('updated', VALUE_KEEP, VALUE_ADDED)\n"
        ),
        "/lib/keep.py": b"VALUE_KEEP = 2\n",
        "/lib/added.py": b"VALUE_ADDED = 99\n",
    }
    deleted: list[str] = []
    second = deployer.deploy_diff(
        FileMapSource(new_payload, entrypoint="/main.py"),
        on_file_deleted=deleted.append,
    )
    assert second.success, second.execute_output
    assert "updated 2 99" in second.execute_output
    # The diff routine must have removed /lib/drop.py.
    assert "/lib/drop.py" in deleted


def test_micropython_diff_deploy_preserves_out_of_scope(
    micropython_device: DeviceEntry,
) -> None:
    """User-managed files outside scope (e.g. /user_data.txt) survive a diff-deploy.

    Plants a real out-of-scope file via the deploy's entrypoint
    itself, runs a second ``deploy_diff`` whose entrypoint reads the
    file back, and confirms the contents survived.  Uses the
    deployer's own transport for both halves so we don't hit the
    "port not yet released" race when re-opening immediately after
    a deploy.
    """
    device = _build_device(micropython_device, deploy_mode="flash")
    deployer = Deployer(device)

    # First deploy plants /user_data.txt and exits.  The path is
    # outside the deploy's managed scope so the next diff-deploy
    # won't touch it.
    plant = deployer.deploy_diff(
        FileMapSource(
            {
                "/main.py": (
                    b"with open('/user_data.txt', 'wb') as _f:\n"
                    b"    _f.write(b'user-managed-content')\n"
                    b"print('planted')\n"
                ),
            },
            entrypoint="/main.py",
        ),
    )
    assert plant.success, plant.execute_output
    time.sleep(_BACK_TO_BACK_SETTLE_SECONDS)

    # Second diff-deploy with a different entrypoint that reads back
    # the user file — survives means the diff routine respected
    # scope.  Cleans up the user file at the end so subsequent runs
    # start fresh.
    check = deployer.deploy_diff(
        FileMapSource(
            {
                "/main.py": (
                    b"import os\n"
                    b"with open('/user_data.txt', 'rb') as _f:\n"
                    b"    print('USER_FILE_CONTENT:' + _f.read().decode())\n"
                    b"os.remove('/user_data.txt')\n"
                ),
            },
            entrypoint="/main.py",
        ),
    )
    assert check.success, check.execute_output
    assert "USER_FILE_CONTENT:user-managed-content" in check.execute_output


# ---------------------------------------------------------------------------
# CircuitPython flash mode
# ---------------------------------------------------------------------------


def test_circuitpython_diff_deploy_round_trip(
    circuitpython_flash_device: DeviceEntry,
) -> None:
    """CP flash diff-deploy: stale files dropped, new payload arrives intact.

    Same shape as the MP round-trip — second deploy's entrypoint
    imports both kept + added libs so the successful exec is
    end-to-end evidence the new payload landed.
    """
    device = _build_device(circuitpython_flash_device, deploy_mode="flash")
    deployer = Deployer(device)

    # Step 1: plant the initial set.
    initial_payload = {
        "/code.py": b"print('cp-initial')\n",
        "/lib/keep.py": b"VALUE_KEEP = 1\n",
        "/lib/drop.py": b"VALUE_DROP = 1\n",
    }
    initial = deployer.deploy_diff(
        FileMapSource(initial_payload, entrypoint="/code.py"),
    )
    assert initial.success, initial.execute_output
    time.sleep(_BACK_TO_BACK_SETTLE_SECONDS)

    # Step 2: second deploy — entrypoint imports both kept + added.
    new_payload = {
        "/code.py": (
            b"from keep import VALUE_KEEP\n"
            b"from added import VALUE_ADDED\n"
            b"print('cp-updated', VALUE_KEEP, VALUE_ADDED)\n"
        ),
        "/lib/keep.py": b"VALUE_KEEP = 2\n",
        "/lib/added.py": b"VALUE_ADDED = 99\n",
    }
    deleted: list[str] = []
    second = deployer.deploy_diff(
        FileMapSource(new_payload, entrypoint="/code.py"),
        on_file_deleted=deleted.append,
    )
    assert second.success, second.execute_output
    assert "cp-updated 2 99" in second.execute_output
    assert "/lib/drop.py" in deleted


# ---------------------------------------------------------------------------
# RAM-mode diff-deploy (collapses to plain deploy_files)
# ---------------------------------------------------------------------------


def test_micropython_ram_diff_deploy_collapses_to_plain(
    micropython_device: DeviceEntry,
) -> None:
    """MP mount-mode ``deploy_diff`` runs without scope cleanup.

    Mount-mode (RAM) ``list_files_in_scope`` returns ``[]`` so the
    diff routine doesn't attempt any deletions; the deploy
    proceeds exactly like the existing mount-mode ``deploy()``
    flow.  Confirms the new entry-point doesn't regress RAM mode.
    """
    device = _build_device(micropython_device, deploy_mode="ram")
    deployer = Deployer(device)
    deleted: list[str] = []
    result = deployer.deploy_diff(
        FileMapSource(
            {"/main.py": b"print('mp-ram-diff')\n"},
            entrypoint="/main.py",
        ),
        on_file_deleted=deleted.append,
    )
    assert result.success, result.execute_output
    assert "mp-ram-diff" in result.execute_output
    # No deletions in RAM mode — list_files_in_scope returns [].
    assert deleted == []


def test_circuitpython_ram_diff_deploy_collapses_to_plain(
    circuitpython_device: DeviceEntry,
) -> None:
    """CP RAM-mode ``deploy_diff`` runs without scope cleanup."""
    device = _build_device(circuitpython_device, deploy_mode="ram")
    deployer = Deployer(device)
    deleted: list[str] = []
    result = deployer.deploy_diff(
        FileMapSource(
            {"/code.py": b"print('cp-ram-diff')\n"},
            entrypoint="/code.py",
        ),
        on_file_deleted=deleted.append,
    )
    assert result.success, result.execute_output
    assert "cp-ram-diff" in result.execute_output
    assert deleted == []


# ---------------------------------------------------------------------------
# FakeTransport sanity (smoke test the fake matches the real-board contract)
# ---------------------------------------------------------------------------


def test_fake_transport_matches_real_contract() -> None:
    """Hardware-free check: FakeTransport's deploy_diff round-trip behaviour
    matches the real transport's contract (list/delete/deploy update
    the on-device state visibly).

    Lives in functional_tests/ so it runs alongside the hardware
    tests and confirms the fake stays in sync with the real
    primitives — surface-level integration without needing boards.
    """
    transport = FakeTransport(
        mode="copy",
        device_files={
            "/code.py": b"v1",
            "/lib/old.py": b"x = 1",
        },
    )
    listed = sorted(transport.list_files_in_scope())
    assert listed == ["/code.py", "/lib/old.py"]
    transport.delete_files(["/lib/old.py"])
    assert "/lib/old.py" not in transport.device_files
    transport.deploy_files({"/code.py": b"v2"}, "/code.py")
    assert transport.device_files["/code.py"] == b"v2"
    assert sorted(transport.list_files_in_scope()) == ["/code.py"]
