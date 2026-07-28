"""macOS FSKit / DiskArbitration wedge detection.

Recent macOS releases moved the FAT (``msdosfs``) driver out of the
kernel and into a user-space FSKit extension
(``com.apple.fskit.msdos.appex``).  When that extension hits an
internal error mid-probe (most often on small CIRCUITPY FAT12
volumes), it can leave ``diskarbitrationd`` stuck in an
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
does not auto-run it.  It just surfaces the exact command in
:data:`MACOS_FSKIT_RECOVERY_COMMAND` for the user-facing coaching
output to paste verbatim.
"""

from __future__ import annotations

import subprocess
import sys as _sys_module
from collections.abc import Callable

#: Command to paste into a terminal to clear the wedge.  One
#: ``killall -9`` of the wedged FSKit / DiskArbitration processes;
#: launchd respawns each one in a clean state.
#:
#: Targets:
#:
#: - ``com.apple.fskit.msdos``, the user-space FAT filesystem
#:   extension that wedged in the first place.
#: - ``fskit_helper`` / ``fskitd`` / ``fskit_agent``, FSKit support
#:   daemons whose XPC connections to the extension are now stale.
#: - ``diskarbitrationd``, the system-level mount arbiter stuck in
#:   uninterruptible wait.
#: - ``DiskArbitrationAgent``, the per-user agent that registers
#:   volumes with Finder's Locations sidebar.  ``killall -9`` works
#:   against it because the per-user launchd respawns it on the next
#:   on-demand XPC load, even with ``KeepAlive=false``.  ``launchctl
#:   kickstart`` is SIP-blocked on modern macOS and won't substitute.
#:
#: ``-9`` is required because the wedged daemons are stuck in kernel
#: wait and can't handle a normal signal.  A reboot is the
#: always-safe alternative when the paste approach doesn't stick.
#:
#: The prose copy in ``docs/troubleshooting/macos-circuitpy.md``
#: pulls from this string, so the command text lives in one place.
MACOS_FSKIT_RECOVERY_COMMAND = (
    "sudo killall -9 com.apple.fskit.msdos fskit_helper "
    "fskitd fskit_agent diskarbitrationd DiskArbitrationAgent"
)


def detect_fskit_wedge(
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    platform: str = _sys_module.platform,
) -> bool:
    """Return ``True`` when macOS ``diskarbitrationd`` is wedged.

    Always returns ``False`` on non-macOS platforms, because the FSKit
    rewrite is Apple-only, so the wedge mode does not exist
    elsewhere.

    Implementation:

    1. ``pgrep diskarbitrationd`` to find the PID.  No PID (daemon
       missing or in the process of respawning) means not wedged.
    2. ``ps -o state= -p <pid>`` reads the process state column.
       A state containing ``U`` means uninterruptible kernel wait,
       which is the wedge signature.  Healthy daemons sit in ``S``
       (interruptible sleep).

    Both subprocess calls get short timeouts, because a wedged
    system can stall *other* commands too, and we don't want
    detection itself to hang.

    Args:
        runner: Injectable subprocess runner.  Must match the
            ``subprocess.run`` signature closely enough for
            ``capture_output=True, text=True, check=False, timeout=…``
            to work.
        platform: Injectable ``sys.platform`` value.

    Returns:
        ``True`` if the daemon is in uninterruptible wait, else
        ``False``.  Any subprocess failure (missing ``pgrep``/``ps``,
        timeout, non-zero exit) is treated as "not wedged" so a
        false positive can never block a legitimate retry.
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
