"""Hardware-gated tests for ``transport.wipe_filesystem`` across runtimes.

Verifies the per-runtime wipe recipes do what the
:meth:`chumicro_deploy.TransportProtocol.wipe_filesystem` docstring
promises on real boards:

- **MicroPython**: substrate-dispatched ``os.VfsLfs2.mkfs`` + soft
  reset.  Verified on rp2 and esp32 substrates.  A plain
  ``os.remove`` walk would leave LittleFS metadata / wear-leveling
  artifacts behind, so the test sets a baseline (one file written
  via ``mpremote fs cp``), wipes, then asserts the device root is
  empty *and* the free-block count returned to the expected
  near-pristine value.
- **CircuitPython** (flash mode): ``import storage;
  storage.erase_filesystem()`` reformats the FAT volume and
  triggers a hard reset.  Test seeds a sentinel file via the
  CIRCUITPY drive, calls ``wipe_filesystem``, then asserts the
  drive comes back without that file.

Skipped cleanly when ``devices.yml`` does not name a board for the
runtime, when MicroPython runs on a substrate without a verified
recipe (``sys.platform`` other than ``rp2`` / ``esp32``), or when a
CIRCUITPY drive is not visible to the host.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from chumicro_deploy import (
    Deployer,
    Device,
    DeviceEntry,
    FileMapSource,
)
from chumicro_deploy.circuitpython_transport import CircuitpythonTransport
from chumicro_deploy.micropython_transport import MicropythonTransport


def _resolve_mpremote() -> str:
    """Locate the ``mpremote`` binary the venv installs alongside pytest."""
    interpreter_bin = Path(sys.executable).parent
    candidate = interpreter_bin / "mpremote"
    if candidate.is_file():
        return str(candidate)
    import shutil

    return shutil.which("mpremote") or "mpremote"


def _mp_listdir(address: str, path: str = "/") -> list[str]:
    """Return ``os.listdir(path)`` on the MP board at *address*."""
    result = subprocess.run(
        [
            _resolve_mpremote(),
            "connect",
            address,
            "exec",
            f"import os; print(os.listdir({path!r}))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    rendered = result.stdout.strip().splitlines()[-1]
    return list(eval(rendered, {"__builtins__": {}}))  # noqa: S307


def _mp_statvfs(address: str, path: str = "/") -> tuple[int, ...]:
    """Return ``os.statvfs(path)`` on the MP board at *address*."""
    result = subprocess.run(
        [
            _resolve_mpremote(),
            "connect",
            address,
            "exec",
            f"import os; print(os.statvfs({path!r}))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    rendered = result.stdout.strip().splitlines()[-1]
    return tuple(eval(rendered, {"__builtins__": {}}))  # noqa: S307


def _mp_platform(address: str) -> str:
    """Return ``sys.platform`` on the MP board at *address*."""
    result = subprocess.run(
        [
            _resolve_mpremote(),
            "connect",
            address,
            "exec",
            "import sys; print(sys.platform)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def test_micropython_wipe_reformats_to_empty_filesystem(
    micropython_device: DeviceEntry,
) -> None:
    """MP wipe via ``mkfs`` lands the board in a fully empty / state.

    Substrate-dispatched: only ``rp2`` and ``esp32`` MP boards have
    verified recipes today; other substrates are skipped.
    """
    address = micropython_device.address
    platform = _mp_platform(address)
    if platform not in ("rp2", "esp32"):
        pytest.skip(
            f"MP substrate {platform!r} has no verified mkfs recipe yet — "
            "rp2 and esp32 only.",
        )

    # Seed a sentinel file so we can prove the wipe actually erased
    # something (would also catch a no-op bug masquerading as success
    # on a board that happened to already be empty).
    sentinel = "wipe_test_sentinel.py"
    subprocess.run(
        [
            _resolve_mpremote(),
            "connect",
            address,
            "exec",
            f"f = open({sentinel!r}, 'w'); f.write('marker'); f.close()",
        ],
        check=True,
    )
    pre_listing = _mp_listdir(address)
    assert sentinel in pre_listing

    transport = MicropythonTransport(address, mode="copy")
    transport.connect()
    try:
        transport.wipe_filesystem()
    finally:
        transport.disconnect()

    # Give the soft-reset a beat over the in-method settle so a slow
    # remount on the next `mpremote connect` doesn't race the listing.
    time.sleep(0.5)

    post_listing = _mp_listdir(address)
    assert post_listing == [], (
        f"wipe_filesystem left files behind on {platform}: {post_listing}"
    )

    # statvfs free-block count: an empty LittleFS volume reports
    # ``f_blocks - 2`` free (two metadata blocks).  Looser bound here
    # so partition-size tweaks across firmware versions don't break
    # the test.
    statvfs = _mp_statvfs(address)
    f_blocks, f_bfree = statvfs[2], statvfs[3]
    assert f_bfree >= f_blocks - 4, (
        f"wipe left more blocks in use than expected: "
        f"{f_blocks=} {f_bfree=} on {platform}"
    )


def test_circuitpython_wipe_reformats_circuitpy_drive(
    circuitpython_flash_device: DeviceEntry,
) -> None:
    """CP wipe via ``storage.erase_filesystem`` reformats the FAT volume.

    Plants a sentinel file via ``Deployer.deploy`` (which routes
    through rsync with autoreload disabled before the write and a
    settled soft-reboot after), then calls ``wipe_filesystem`` and
    asserts the sentinel is gone.

    Plant-via-deploy is load-bearing: a host-side ``write_bytes``
    directly to the CIRCUITPY mount point puts the board into a
    transient state where the next raw-REPL
    ``storage.erase_filesystem()`` call silently no-ops.  The FAT is
    not reformatted, the volume UUID is unchanged, ``wipe_filesystem``
    returns "successfully" because USB-CDC and USB-MSC both stayed
    alive, and this assertion sees the sentinel still on disk.  The
    deploy mechanism dodges that by suspending autoreload before the
    rsync, by going through a soft-reboot afterwards that returns the
    board to a known-quiet state, and by leaving no host-side write
    in flight when the wipe begins.
    """
    from chumicro_deploy.circuitpy_drive import _circuitpy_volume_candidates

    if not _circuitpy_volume_candidates():
        pytest.skip("no CIRCUITPY drive mounted on the host")

    plant_device = Device(
        transport=circuitpython_flash_device.runtime,
        address=circuitpython_flash_device.address,
        baudrate=circuitpython_flash_device.serial_baudrate,
        deploy_mode="flash",
    )
    plant_result = Deployer(plant_device).deploy_diff(
        FileMapSource(
            {
                "/code.py": b"# wipe-test plant: code.py is a no-op so the\n"
                            b"# board returns to friendly REPL quietly.\n",
                "/wipe_test_sentinel.txt": b"marker",
            },
            entrypoint="/code.py",
        ),
    )
    assert plant_result.success, plant_result.execute_output

    transport = CircuitpythonTransport(
        circuitpython_flash_device.address,
        baudrate=circuitpython_flash_device.serial_baudrate,
        mode="flash",
    )
    transport.connect()
    try:
        # Resolve the drive the way the transport does — first
        # candidate corrected by the board-identity probe.  A raw
        # ``candidates[0]`` watches whichever volume the OS mounted
        # first, which on a multi-board bench is a *different* board's
        # CIRCUITPY.
        drive_path = transport._verify_drive_for_board(
            transport._resolve_circuitpy_drive(),
        )
        sentinel = drive_path / "wipe_test_sentinel.txt"
        assert sentinel.is_file(), (
            f"sentinel did not land via deploy: "
            f"{sorted(child.name for child in drive_path.iterdir())}"
        )
        transport.wipe_filesystem()
    finally:
        transport.disconnect()

    assert not sentinel.exists(), (
        "storage.erase_filesystem should have removed the seeded sentinel"
    )
