"""macOS FSKit / DiskArbitration wedge detection.

Recent macOS releases moved the FAT (``msdosfs``) driver out of the
kernel and into a user-space FSKit extension
(``com.apple.fskit.msdos.appex``).  When that extension hits an
internal error mid-probe — most often on small CIRCUITPY FAT12
volumes — it can leave ``diskarbitrationd`` stuck in an
uninterruptible kernel wait.  Symptoms:

- ``diskutil list`` hangs indefinitely.
- Newly inserted CIRCUITPY drives never appear under ``/Volumes``.
- Unplug / replug of the board does nothing; the bus enumerates
  fine (``system_profiler SPUSBDataType`` shows the device) but no
  mount ever happens.

The cheapest reliable signal is the state column of
``diskarbitrationd``: a healthy daemon sits in ``Ss`` (interruptible
sleep), a wedged one sits in ``Us`` / ``U*`` (uninterruptible wait).
:func:`detect_fskit_wedge` reads that state via ``pgrep`` + ``ps``
and reports the wedge.

Recovery requires ``sudo`` (killing system daemons), so this module
does not auto-run it — it just surfaces the exact command in
:data:`MACOS_FSKIT_RECOVERY_COMMAND` for :mod:`recovery` to paste
into the user-facing coaching output.
"""

from __future__ import annotations

import subprocess
import sys as _sys_module
from collections.abc import Callable

#: Commands to paste into a terminal to clear the wedge.  Two steps
#: because the system daemons respawn via ``KeepAlive`` but the
#: per-user ``DiskArbitrationAgent`` does not — killing it alone
#: leaves it dead, and ``launchctl kickstart -k`` is the correct
#: way to bounce it.
#:
#: Step 1 (sudo killall -9) targets:
#:
#: - ``com.apple.fskit.msdos`` — the user-space FAT filesystem
#:   extension that wedged in the first place.
#: - ``fskit_helper`` / ``fskitd`` / ``fskit_agent`` — FSKit support
#:   daemons whose XPC connections to the extension are now stale.
#: - ``diskarbitrationd`` — the system-level mount arbiter that has
#:   been stuck in uninterruptible wait.
#:
#: Step 2 (launchctl kickstart -k) bounces the per-user
#: ``DiskArbitrationAgent`` — the agent that registers volumes with
#: Finder's Locations sidebar.  Even after ``diskarbitrationd``
#: respawns cleanly this agent keeps its old XPC connection, so
#: drives mount at ``/Volumes/`` but don't appear in Finder until
#: the agent reconnects.  ``kickstart -k`` kills-and-restarts in one
#: step; a plain ``killall`` leaves the agent dead because its
#: launchd plist does not set ``KeepAlive=true``.
#:
#: A reboot is the always-safe alternative if the paste approach
#: doesn't stick.
MACOS_FSKIT_RECOVERY_COMMAND = (
    "sudo killall -9 com.apple.fskit.msdos fskit_helper "
    "fskitd fskit_agent diskarbitrationd && "
    "launchctl kickstart -k gui/$(id -u)/com.apple.DiskArbitrationAgent"
)


def detect_fskit_wedge(
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    platform: str = _sys_module.platform,
) -> bool:
    """Return ``True`` when macOS ``diskarbitrationd`` is wedged.

    Always returns ``False`` on non-macOS platforms — the FSKit
    rewrite is Apple-only, so the wedge mode does not exist
    elsewhere.

    Implementation:

    1. ``pgrep diskarbitrationd`` to find the PID.  No PID (daemon
       missing or in the process of respawning) → not wedged.
    2. ``ps -o state= -p <pid>`` reads the process state column.
       A state containing ``U`` means uninterruptible kernel wait,
       which is the wedge signature.  Healthy daemons sit in ``S``
       (interruptible sleep).

    Both subprocess calls get short timeouts — a wedged system
    can stall *other* commands too, and we don't want detection
    itself to hang.

    Args:
        runner: Subprocess runner (injected for tests).  Must match
            the ``subprocess.run`` signature closely enough for
            ``capture_output=True, text=True, check=False, timeout=…``
            to work.
        platform: ``sys.platform`` value (injected for tests).

    Returns:
        ``True`` if the daemon is in uninterruptible wait, else
        ``False``.  Any subprocess failure — missing ``pgrep``/``ps``,
        timeout, non-zero exit — is treated as "not wedged" so a
        false positive can never block a legitimate
        CIRCUITPY_DRIVE_MISSING retry.
    """
    if platform != "darwin":
        return False

    try:
        pgrep_result = runner(
            ["pgrep", "diskarbitrationd"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if pgrep_result.returncode != 0:
        return False
    pid_line = pgrep_result.stdout.strip().splitlines()
    if not pid_line:
        return False
    pid = pid_line[0].strip()
    if not pid.isdigit():
        return False

    try:
        ps_result = runner(
            ["ps", "-o", "state=", "-p", pid],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    if ps_result.returncode != 0:
        return False
    state = ps_result.stdout.strip()
    return "U" in state
