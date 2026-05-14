"""MicroPython device transport using mpremote.

Two execution paths:

- **Persistent serial transport** (mount mode and per-execute path):
  uses ``mpremote.transport_serial.SerialTransport`` directly — opens
  the serial port once per session, enters raw REPL once, mounts the
  staging directory once, and runs each bootstrap via ``exec_raw``.
  Eliminates the ~2-3 s cold-start cost of spawning ``mpremote`` per
  ``execute()`` call.
- **Subprocess fallback** (copy mode staging, reset/recover): uses the
  ``mpremote`` CLI for operations that are one-shot and easier to express
  via the CLI.  The serial port is closed before these calls and
  reopened on the next ``execute()``.

"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time as _time_module
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from .protocol import (
    PROBE_IMPLEMENTATION_SCRIPT,
    DeviceImplementation,
    parse_probe_output,
    validate_entrypoint_in_files,
)
from .runtime_marker import file_targets_runtime

if TYPE_CHECKING:  # pragma: no cover - type-only
    from mpremote.transport_serial import SerialTransport

    from .circuitpython_transport import TimeSource


#: Idle timeout (seconds) for ``exec_raw`` on the test-bootstrap path —
#: ``execute()`` and ``deploy_files()``.  Mirrors
#: :data:`chumicro_deploy.circuitpython_transport._EXECUTE_IDLE_TIMEOUT`
#: but bigger because MicroPython boards we test on have larger heaps
#: than the CP boards (e.g. Lolin S2 MP exposes the full 2 MB SPIRAM,
#: vs ~150 KB on CP boards), and the on-device fragmentation tests'
#: histogram bisection scales its silent allocation loop to whatever
#: heap is available.
#:
#: mpremote's ``SerialTransport.exec_raw(command, timeout=N)`` passes
#: ``N`` straight through to ``follow()`` → ``read_until(timeout=N)``,
#: where ``timeout`` is documented as "between characters" — i.e. an
#: idle-between-bytes timeout, **not** wall-clock.  Bytes received by
#: the host reset the clock; only ``N`` seconds of *consecutive
#: silence* end the wait.  See ``transport_serial.read_until`` in the
#: vendored mpremote source for the implementation.
#:
#: Failure mode this avoids: the on-device fragmentation tests'
#: ``_count_blocks_of_size`` runs ``while True: holders.append(
#: bytearray(size))`` in a tight Python loop until ``MemoryError``,
#: with no intermediate output.  On a 2 MB heap at the 256-byte tier
#: that's ~7,500 silent allocations; the surrounding ``gc.collect()``
#: calls on a fragmented heap can each take seconds on Xtensa-class
#: MCUs.  The previous ``timeout=120`` was hit mid-bisection on Lolin
#: S2 MP, surfacing as ``TransportError: timeout waiting for first
#: EOF reception`` from mpremote's ``follow()``.  Other exec paths
#: (probe, scope listing, delete, wipe, bootloader) are short
#: interactive ops and keep their original short timeouts.
_EXECUTE_IDLE_TIMEOUT: float = 300.0


class MicropythonTransportError(Exception):
    """Raised when an mpremote command fails."""


class MicropythonMidDeployDisconnected(MicropythonTransportError):
    """Raised when the device drops mid-deploy.

    Subclass so callers can ``except`` "the cable came out" without
    conflating it with other mpremote transport errors (mount
    failure, copy failure, bootstrap exec failed).  Mirrors
    :class:`CircuitpythonMidDeployDisconnected` and
    :class:`chumicro_repl.session.ReplSessionDisconnected`.

    The original :class:`OSError` is attached as :attr:`cause` so
    callers that need the underlying errno can read it without
    re-parsing :func:`str` of the wrapper.
    """

    def __init__(self, cause: OSError, context: str = "") -> None:
        prefix = f"device disconnected during {context}" if context else (
            "device disconnected"
        )
        super().__init__(f"{prefix}: {cause}")
        self.cause = cause


#: Sentinel prefix the on-device scope-listing script emits in front of
#: every found file path.  Host-side parsing scans for this marker so
#: any incidental ``print()`` from an autorun ``boot.py`` etc. doesn't
#: contaminate the listing.
_SCOPE_LISTING_MARKER: str = "__CHU_F:"


#: Directory / file basenames the test-harness staging path skips when
#: copying library `src/` trees into the device-bound staging dir.
#: Mirrors the exclude set used by `chumicro_deploy.sources.PackageSource`
#: and `flash_drive.rsync` — keeps host-only build artifacts off device
#: flash.  ``*.pyc`` and ``*.egg-info`` are matched by suffix elsewhere.
_STAGE_EXCLUDED_NAMES: frozenset[str] = frozenset(
    {"__pycache__", ".DS_Store", ".git", ".pytest_cache", ".mypy_cache"},
)


#: On-device script that walks the deploy's managed scope and prints a
#: marker-prefixed listing of every file in scope.  Pure stdlib —
#: ``os.listdir`` + ``os.stat`` — so it runs on every CP / MP build
#: without preinstalling helper libs.
#:
#: The four canonical entrypoint / state files are probed at the
#: device root; ``/lib/`` is walked recursively.  Missing dirs and
#: per-file ``OSError`` are tolerated so a fresh-flashed board (no
#: ``/lib/`` yet) returns an empty listing instead of erroring out.
#:
#: Kept in sync with :data:`chumicro_deploy.protocol.DEPLOY_SCOPE_FILES`
#: + :data:`chumicro_deploy.protocol.DEPLOY_SCOPE_PREFIXES`.  The mirror
#: is intentional — embedding the constants directly in the on-device
#: script keeps each side self-contained and the host doesn't need to
#: marshal a values list every call.
_LIST_SCOPE_SCRIPT: str = (
    "import os\n"
    "def _walk(p):\n"
    "    try:\n"
    "        names = os.listdir(p)\n"
    "    except OSError:\n"
    "        return\n"
    "    for name in names:\n"
    "        full = p + '/' + name if p != '/' else '/' + name\n"
    "        try:\n"
    "            stat = os.stat(full)\n"
    "        except OSError:\n"
    "            continue\n"
    "        if stat[0] & 0x4000:\n"
    "            _walk(full)\n"
    "        else:\n"
    "            print('__CHU_F:' + full)\n"
    "for path in ('/code.py', '/main.py', '/active.py', '/runtime_config.msgpack'):\n"
    "    try:\n"
    "        os.stat(path)\n"
    "    except OSError:\n"
    "        continue\n"
    "    print('__CHU_F:' + path)\n"
    "_walk('/lib')\n"
)


#: Wipe the user filesystem by reformatting the LittleFS volume the
#: runtime is mounted on, then soft-reset so the new (empty) volume
#: gets remounted on boot.
#:
#: A plain recursive ``os.remove`` walk leaves LittleFS metadata
#: blocks + wear-leveling artifacts on flash, so a board that
#: filled up over many test runs (Pi Pico W LittleFS partition is
#: ~850 KB; lolin-s2-mp's ``vfs`` partition is 2 MB) can still hit
#: ``ENOSPC`` mid-deploy after a "wipe."  ``VfsLfs2.mkfs`` reformats
#: the partition, which is the only reliable way to recover the
#: full block budget.
#:
#: Substrate-dispatched: each MicroPython port exposes its flash /
#: data partition through a different module.  The dispatch covers
#: the two substrates chumicro supports today (rp2, esp32); other
#: ports raise ``RuntimeError`` so the failure has a name instead
#: of surfacing as "mkfs got no block device."  Firmware lives on a
#: separate partition (``factory`` on esp32, the bootloader region
#: on rp2), untouched by the LFS-only reformat.
_WIPE_FILESYSTEM_SCRIPT: str = (
    "import os, sys, machine\n"
    "if sys.platform == 'rp2':\n"
    "    import rp2\n"
    "    _block_dev = rp2.Flash()\n"
    "elif sys.platform == 'esp32':\n"
    "    import esp32\n"
    "    _block_dev = esp32.Partition.find("
    "esp32.Partition.TYPE_DATA, label='vfs')[0]\n"
    "else:\n"
    "    raise RuntimeError("
    "'chumicro_deploy.wipe_filesystem: unsupported MicroPython "
    "platform ' + sys.platform)\n"
    "try:\n"
    "    os.umount('/')\n"
    "except OSError:\n"
    "    pass\n"
    "os.VfsLfs2.mkfs(_block_dev)\n"
    "machine.soft_reset()\n"
)


#: Wall-clock pause between issuing ``machine.soft_reset()`` (inside
#: :data:`_WIPE_FILESYSTEM_SCRIPT`) and re-opening the persistent
#: serial transport.  rp2 and esp32 both keep their host-side USB-CDC
#: alive across a soft reset, so this is just settle time for the
#: runtime to remount ``/`` on the freshly-formatted volume — not a
#: full USB-CDC re-enumeration like CircuitPython's
#: ``storage.erase_filesystem`` triggers.  Two seconds is comfortable
#: on hardware in practice (1 s also worked but had no margin).
_WIPE_REBOOT_SETTLE_SECONDS: float = 2.0


def _parse_scope_listing(output: str) -> list[str]:
    """Extract device paths from the scope-listing script's stdout.

    Filters to lines starting with :data:`_SCOPE_LISTING_MARKER` so
    surrounding output (raw-REPL banner, autorun prints) doesn't
    contaminate the result.  Returns deduplicated paths in the
    order they appear.
    """
    seen: set[str] = set()
    result: list[str] = []
    for line in output.splitlines():
        if not line.startswith(_SCOPE_LISTING_MARKER):
            continue
        path = line[len(_SCOPE_LISTING_MARKER):].strip()
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _resolve_mpremote_binary() -> str:
    """Return the ``mpremote`` executable path to invoke via subprocess.

    ``mpremote`` is a ``requirements-dev.txt`` dependency, so it lands in
    ``.venv/bin/mpremote`` after workspace setup.  Shelling out with the
    bare name only works when ``.venv/bin`` is on ``PATH``
    (i.e. after ``source .venv/bin/activate``), which fails for direct
    ``.venv/bin/python`` invocations and for IDE play buttons that
    launch via the interpreter path without an activated shell.

    Prefer the binary next to the running interpreter; fall back to the
    bare name so a system-wide or externally-managed ``mpremote`` still
    works.  Windows resolution is handled via ``shutil.which`` since the
    binary there is ``mpremote.exe``.
    """
    import shutil

    interpreter_bin = Path(sys.executable).parent
    for candidate in (interpreter_bin / "mpremote", interpreter_bin / "mpremote.exe"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    resolved = shutil.which("mpremote")
    return resolved or "mpremote"


def _decode_exec_result(result: Any) -> str:
    """Normalize an ``mpremote.SerialTransport.exec_raw`` return value to text.

    mpremote returns ``(stdout_bytes, stderr_bytes)`` in newer versions and
    raw ``bytes`` (or already-decoded ``str``) in older ones.  Tracebacks
    land on stderr, so both streams are merged — callers downstream parse
    the combined output with ``result_parser.parse_output``.

    Args:
        result: Return value from ``exec_raw`` (tuple, bytes, or str).

    Returns:
        UTF-8 decoded text with stderr appended to stdout.
    """
    if isinstance(result, tuple):
        stdout_bytes, stderr_bytes = result
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        return stdout + stderr
    if isinstance(result, bytes):
        return result.decode("utf-8", errors="replace")
    return result


def _default_transport_factory(address: str, baudrate: int) -> SerialTransport:
    """Default :class:`SerialTransport` factory.

    Importing inside the call so test environments that monkey-patch
    the factory don't need ``mpremote`` installed.

    Args:
        address: Serial port path (e.g. ``/dev/cu.usbmodem1234``).
        baudrate: Serial baud rate.
    """
    # pragma: no cover - exercised on real hardware only
    from mpremote.transport_serial import SerialTransport

    return SerialTransport(address, baudrate=baudrate)


class MicropythonTransport:
    """Transport for MicroPython boards.

    Args:
        address: Serial port or network address of the device.
        baudrate: Serial baud rate (default 115200).  Only used for the
            persistent serial transport — subprocess ``mpremote``
            invocations negotiate baud rate themselves.
        mode: ``"mount"`` (default) or ``"copy"``.
        runner: Callable that executes subprocess commands.  Accepts
            the same signature as ``subprocess.run``.  Defaults to
            ``subprocess.run``.  Inject a fake for testing.
        transport_factory: Callable that builds a :class:`SerialTransport`
            given ``(address, baudrate)``.  Defaults to
            :func:`_default_transport_factory`.  Inject a fake to avoid
            opening real serial ports in tests.
        time: Object providing ``monotonic()`` and ``sleep()``.  Defaults
            to Python's ``time`` module.  Inject :class:`FakeTime` (from
            :mod:`chumicro_deploy.testing`) to eliminate wall-clock waits
            in tests that exercise :meth:`wipe_filesystem`'s post-reset
            settle.
    """

    def __init__(
        self,
        address: str,
        *,
        baudrate: int = 115200,
        mode: str = "mount",
        timeout: float = 10.0,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        transport_factory: Callable[[str, int], Any] | None = None,
        time: TimeSource | None = None,
    ) -> None:
        self.address = address
        self.baudrate = baudrate
        self.mode = mode
        #: Wall-clock budget for the soft-reboot read in
        #: :meth:`deploy_files` ``follow="soft_reboot"``.  Mirrors
        #: :class:`CircuitpythonTransport`'s ``timeout`` (10 s default)
        #: so the partial-output window for ``while True`` app code
        #: feels the same on both runtimes.  ``follow="exec"`` ignores
        #: this — that path uses :data:`_EXECUTE_IDLE_TIMEOUT` (an
        #: inter-byte idle timeout, not a wall-clock budget) for raw-
        #: REPL EOF reception.
        self.timeout = timeout
        self._runner = runner or subprocess.run
        self._transport_factory = transport_factory or _default_transport_factory
        self._time: TimeSource = time or cast("TimeSource", _time_module)
        self._staging_dir: tempfile.TemporaryDirectory | None = None
        self._staging_path: Path | None = None
        self._serial: Any = None
        self._mounted: bool = False
        #: Selecting :class:`MicropythonTransport` means the deployment
        #: target is MicroPython, so files marked for another runtime
        #: via ``__chumicro_runtimes__`` are filtered out of the staging
        #: tree.  Sub-runtime markers (``micropython_esp32`` /
        #: ``micropython_rp2``) fold into ``"micropython"``.
        self._target_runtime: str = "micropython"

    def connect(self) -> None:
        """Verify the device is reachable by running a no-op command.

        Uses subprocess so the persistent serial transport is opened
        lazily on the first ``execute()`` (or eagerly during mount-mode
        ``stage()``).  Avoids holding the serial port during the gap
        between ``connect()`` and ``stage()``.
        """
        self._run_mpremote(["exec", "print('ok')"])

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
        extra_files: dict[str, bytes] | None = None,
    ) -> None:
        """Prepare a staging directory with library sources, tests, and harness.

        In mount mode, the staging directory is mounted on the device
        via the persistent serial transport.  In copy mode, it is
        recursively copied to flash via ``mpremote fs cp -r``.

        Safe to call repeatedly on the same transport (RAM-mode
        orchestration re-stages per file).  On re-stage in mount mode
        the existing mount is dropped first — otherwise mpremote's
        ``mount_local`` hits ``OSError: [Errno 1] EPERM`` because the
        device-side mount hook refuses to replace a live mount.

        Args:
            source_dirs: Library ``src/`` directories to include.
            test_files: Test files to stage.
            harness_source: Path to the test harness ``src/`` directory.
            extra_modules: Optional sibling Python files to copy to
                the staging root next to the test files.
            extra_files: Non-Python files to land at named device paths
                (typically ``{"/runtime_config.msgpack": <bytes>}``) so
                test code can call ``chumicro_config.load_runtime_config()``.
                Both ``copy`` and ``mount`` modes support this — the
                staging-tree write below lands the bytes wherever the
                mode-specific transfer step picks them up from.
                MicroPython has a writable filesystem in both modes;
                no equivalent of CircuitPython's ``UnsupportedExtraFilesError``
                applies here.
        """
        # Drop any mount/tempdir left from a prior stage() on this
        # transport so re-staging is idempotent.
        if self._mounted and self._serial is not None:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._mounted = False
        if self._staging_dir is not None:
            self._staging_dir.cleanup()
            self._staging_dir = None
            self._staging_path = None

        self._staging_dir = tempfile.TemporaryDirectory(prefix="chumicro_device_")
        staging_path = Path(self._staging_dir.name)
        self._staging_path = staging_path

        # Copy source packages into staging.
        for source_dir in source_dirs:
            self._copy_tree(source_dir, staging_path)

        # Copy harness source.
        self._copy_tree(harness_source, staging_path)

        # Copy test files into staging root.
        for test_file in test_files:
            destination = staging_path / test_file.name
            destination.write_bytes(test_file.read_bytes())

        # Copy extra sibling modules into the staging root so the test
        # source's `from _foo import ...` line resolves against a real
        # file on the device.
        if extra_modules:
            for module_path in extra_modules:
                destination = staging_path / module_path.name
                destination.write_bytes(module_path.read_bytes())

        # Land binary extra_files at their declared device paths inside
        # the staging tree.  Copy mode rsync's the whole tree to flash;
        # mount mode mounts the tree as the device filesystem.  Either
        # way, the file appears at the requested device path.  Leading
        # slash stripped to make the device-path → staging-path
        # translation reversible.
        if extra_files:
            for device_path, content in extra_files.items():
                relative = device_path.lstrip("/")
                if not relative:
                    raise MicropythonTransportError(
                        f"extra_files key {device_path!r} has no path "
                        "component; expected a leading-slash path like "
                        '"/runtime_config.msgpack"',
                    )
                destination = staging_path / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)

        if self.mode == "copy":
            # Subprocess `fs cp -r` — release the serial port if held.
            self._close_serial()
            self._run_mpremote([
                "fs", "cp", "-r",
                str(staging_path) + "/.",
                ":",
            ])
        else:
            # Mount mode — open the persistent transport now and mount
            # the staging dir so every subsequent execute() reuses both.
            self._ensure_serial()
            self._serial.mount_local(str(staging_path))
            self._mounted = True

    def execute(self, bootstrap_script: str) -> str:
        """Execute a bootstrap script on the device and return captured output.

        Uses the persistent serial transport's ``exec_raw`` so each call
        amortizes the one-time mpremote-cold-start cost.  In copy mode
        the serial transport is opened lazily (since ``stage()`` released
        it for the ``fs cp`` subprocess).

        Args:
            bootstrap_script: Python code to execute on the device.

        Returns:
            Captured stdout from the device.
        """
        if self._staging_path is None:
            raise MicropythonTransportError(
                "stage() must be called before execute()"
            )
        self._ensure_serial()
        try:
            result = self._serial.exec_raw(
                bootstrap_script, timeout=_EXECUTE_IDLE_TIMEOUT,
            )
        except Exception as error:
            raise MicropythonTransportError(
                f"Device exec failed: {error}"
            ) from error
        return _decode_exec_result(result)

    def run_script(self, script: str, *, timeout: float = 10.0) -> str:
        """Run *script* via the persistent serial REPL with no staging.

        Mirrors :meth:`probe_implementation` — opens the raw REPL if
        needed and runs the script directly via ``exec_raw``.  The
        ``stage()``-first precondition that :meth:`execute` enforces
        is bypassed because *script* is expected to be self-contained
        (no imports of staged modules).

        Args:
            script: Self-contained Python source to run.
            timeout: Idle-timeout for the script's output, in seconds.

        Returns:
            Captured stdout from the device.
        """
        self._ensure_serial()
        try:
            result = self._serial.exec_raw(script, timeout=timeout)
        except Exception as error:
            raise MicropythonTransportError(
                f"Device run_script failed: {error}"
            ) from error
        return _decode_exec_result(result)

    def soft_reset(self) -> None:
        """Soft-reset the device to clear interpreter state.

        Sends Ctrl-D through the persistent raw REPL.  This clears
        ``sys.modules`` and the device heap without toggling USB, so
        it is safe to run between every file.

        The mount is **not** restored by this method.  The caller (the
        device orchestration layer) always calls ``stage()`` next, and
        ``stage()`` owns the fresh mount.  Restoring the mount here
        instead would double-wrap mpremote's ``SerialIntercept``
        (``mount_local`` unconditionally wraps ``self.serial``) and
        garble subsequent I/O — that was the cause of the
        ``ImportError: no module named 'chumicro_test_harness'`` seen
        on the second file of an IDE folder run.

        Used between test groups so each group starts with a clean
        interpreter and an un-wrapped serial.  If no persistent
        transport is open, falls back to a subprocess ``mpremote
        reset``.
        """
        if self._serial is None:
            self._run_mpremote(["reset"])
            return

        # Umount while the device-side mount state is still live — after
        # Ctrl-D the ``os`` module and mount hook are gone and
        # ``umount_local`` would error when it tries to run
        # ``os.umount(...)``.  umount_local also unwraps the
        # SerialIntercept on the host side, which is required before
        # the next mount_local wraps again.
        if self._mounted:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._mounted = False
        try:
            self._serial.exit_raw_repl()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        self._serial.enter_raw_repl(soft_reset=True)

    def recover(self) -> None:
        """Attempt to recover after a failed test.

        Closes the persistent transport (if open) and reconnects from
        scratch — more aggressive than :meth:`soft_reset` because the
        previous failure might have left the raw REPL in an unknown
        state where ``exit_raw_repl`` itself could hang.
        """
        self._close_serial()
        # Subprocess reset so we don't immediately try to grab the port
        # again — mpremote handles the whole open/reset/close cycle.
        try:
            self._run_mpremote(["reset"])
        except MicropythonTransportError:  # pragma: no cover - hardware-only
            pass

    def reset_into_bootloader(self) -> bool:
        """Issue ``machine.bootloader()`` to drop into the UF2 bootloader.

        Whether the call actually puts the chip in bootloader mode
        depends on the board's MicroPython build — RP2040 / RP2350
        ports wire ``machine.bootloader()`` to the native UF2 ROM
        bootloader and it just works; other ports may not implement
        the function at all, or may implement it as a plain reset
        that boots straight back into the app.  We try blindly
        rather than maintain a board / firmware-version table: a
        successful entry shows up as a new ROM-bootloader serial
        port for the caller's drive-poll to spot, and an
        unsuccessful entry surfaces as no-new-port → fall back to
        the manual-entry prompt.  Don't add board-specific
        branching here; the try-and-poll architecture is the right
        abstraction.
        """
        try:
            self._ensure_serial()
            try:
                self._serial.exec_raw(
                    "import machine\nmachine.bootloader()\n", timeout=5,
                )
            except Exception:
                # Reset drops the serial link before a clean response
                # comes back — expected on success.  We can't easily
                # distinguish that from "bootloader attr missing" here,
                # so trust the exec_raw fired and let the caller's
                # drive-poll be the authoritative signal.
                pass
        except Exception:
            return False
        return True

    def probe_implementation(self) -> DeviceImplementation | None:
        """Query ``sys.implementation`` on the board for PR-summary metadata.

        Opens the persistent raw REPL if needed and runs a short inline
        script — no staging required because ``sys.implementation`` is a
        built-in attribute.  Failures are swallowed (``None`` returned)
        so a flaky or unusual firmware never blocks the real test run.

        Returns:
            :class:`DeviceImplementation` on success, or ``None`` if the
            probe could not complete or its output did not contain the
            expected marker line.
        """
        try:
            self._ensure_serial()
            result = self._serial.exec_raw(
                PROBE_IMPLEMENTATION_SCRIPT, timeout=10,
            )
        except Exception:  # pragma: no cover - hardware-only error paths
            return None
        return parse_probe_output(_decode_exec_result(result))

    def disconnect(self) -> None:
        """Clean up staging directory and close the persistent serial transport."""
        self._close_serial()
        if self._staging_dir is not None:
            self._staging_dir.cleanup()
            self._staging_dir = None
            self._staging_path = None

    def deploy_files(
        self,
        files: dict[str, bytes],
        entrypoint: str,
        *,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        follow: Literal["exec", "soft_reboot"] = "exec",
        clean: bool = False,
    ) -> str:
        """Write *files* onto the device and execute *entrypoint*.

        Mount mode writes the file tree to a host-side staging dir,
        mounts it through the persistent raw REPL, and execs the
        entrypoint from the mount point.  Copy mode writes to the
        host-side staging dir and uses ``mpremote fs cp -r`` to push
        to the device's flash, then runs the entrypoint via one of two
        follow modes selected by the *follow* parameter.

        Args:
            files: On-device-path -> bytes mapping.  Paths may start
                with ``/``; the leading slash is stripped before
                joining with the staging dir / device root.
            entrypoint: On-device path (must be a key of *files*).
            on_file_staged: Per-file callback invoked with the
                on-device path as each file is written to staging.
            on_execute_line: Callback invoked once per line of the
                execute output (in order) after execution completes.
            follow: Selects how the staged entrypoint is run + how
                its output is captured.

                ``"exec"`` (default) — raw-REPL synchronous execution.
                The entrypoint is wrapped in an ``exec(open(...).read())``
                bootstrap and run via ``self._serial.exec_raw`` with
                ``timeout=_EXECUTE_IDLE_TIMEOUT`` (inter-byte idle).
                Captures full stdout once the script returns and raw
                REPL emits the EOF (``\\x04``) marker.  Right for
                return-bounded scripts (test-harness ``test_*.py``
                files); breaks for ``while True`` app code because
                the EOF marker never fires.

                ``"soft_reboot"`` — friendly-REPL soft-reboot pattern,
                analog of :class:`CircuitpythonTransport`'s flash
                mode.  Sends ``Ctrl-B + Ctrl-D`` from the persistent
                serial connection, lets MicroPython auto-run
                ``/main.py``, reads serial output up to
                :attr:`timeout` seconds (returning partial output for
                infinite-loop bodies).  Mount mode is rejected — the
                soft-reboot pattern requires the entrypoint at
                ``/main.py`` on flash, not via mount, because
                MicroPython only auto-runs files at known boot paths
                on flash, never from a host-mounted directory.
            clean: When ``True`` and ``mode="copy"``, wipe the
                device's ``/lib`` tree before pushing the new staging
                contents — mirrors the CP transport's ``rsync --delete``
                semantics for the most common accumulation site.
                Top-level user-managed files (``boot.py``, ``main.py``,
                ``settings.toml``, etc.) live outside ``/lib`` and
                survive unchanged.  No-op for ``mode="mount"`` (mount
                mode is transient by design — nothing on the device's
                flash to clean).  Default ``False`` preserves the
                additive-by-default contract that ``chumicro-workspace
                deploy`` relies on; ``chumicro-workspace deploy-example``
                passes ``True`` so each demo lands fresh.

        Returns:
            Combined stdout captured from the entrypoint execution.
            For ``follow="soft_reboot"`` and an infinite-loop entry
            point, this is whatever accumulated up to *self.timeout*.

        Raises:
            MicropythonTransportError: ``follow="soft_reboot"`` was
                requested with ``mode="mount"`` (unsupported) or with
                an entrypoint other than ``/main.py``.
        """
        validate_entrypoint_in_files(
            files, entrypoint, error_cls=MicropythonTransportError,
        )

        if follow == "soft_reboot":
            if self.mode != "copy":
                raise MicropythonTransportError(
                    "follow='soft_reboot' requires mode='copy'; got "
                    f"mode={self.mode!r}.  The soft-reboot pattern auto-runs "
                    "/main.py from flash — mount mode (mpremote mount_local) "
                    "lands files at /remote and the runtime won't auto-run "
                    "them on soft-reboot."
                )
            if entrypoint.lstrip("/") != "main.py":
                raise MicropythonTransportError(
                    "follow='soft_reboot' requires entrypoint '/main.py'; "
                    f"got {entrypoint!r}.  MicroPython auto-runs /main.py "
                    "(after /boot.py) on soft-reboot — other entrypoint "
                    "names won't run automatically."
                )

        if self._staging_dir is not None:
            self._staging_dir.cleanup()
        if self._mounted and self._serial is not None:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover — best-effort cleanup
                pass
            self._mounted = False

        self._staging_dir = tempfile.TemporaryDirectory(prefix="chumicro_deploy_")
        staging_path = Path(self._staging_dir.name)
        self._staging_path = staging_path

        for device_path in sorted(files.keys()):
            relative = device_path.lstrip("/")
            destination = staging_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(files[device_path])
            if on_file_staged is not None:
                on_file_staged(device_path)

        relative_entrypoint = entrypoint.lstrip("/")
        if self.mode == "copy":
            # Copy mode pushes files to the device's real filesystem,
            # so on-device paths start at ``/`` as written.  MP does
            # not include /lib on sys.path by default; add it so a
            # callers' ``from helper import x`` resolves without
            # boilerplate.
            self._close_serial()
            if clean:
                # Mirror CP's ``rsync --delete`` clean-deploy semantics
                # for the actual accumulation site: chumicro_* and
                # other library packages under ``/lib``.  Without this,
                # each deploy stacks new packages onto the previous
                # deploy's tree and a Pi Pico W MP fills its 860 KB
                # flash after enough rotation between examples.
                # ``boot.py`` / ``main.py`` / ``settings.toml`` /
                # ``runtime_config.msgpack`` and other top-level
                # user-managed files live outside ``/lib`` and survive
                # unchanged.
                self._clean_device_lib()
            self._run_mpremote([
                "fs", "cp", "-r",
                str(staging_path) + "/.",
                ":",
            ])
            self._ensure_serial()
            entrypoint_on_device = f"/{relative_entrypoint}"
            sys_path_prefix = "import sys\nsys.path.insert(0, '/lib')\n"
        else:
            # mpremote mount_local mounts the staging dir at /remote
            # (not /), so entrypoint paths the caller wrote as
            # ``/main.py`` resolve to ``/remote/main.py`` on device.
            # Add /remote and /remote/lib to sys.path so relative
            # imports inside the user's code work the same way copy
            # mode and CircuitPython flash mode do.
            self._ensure_serial()
            self._serial.mount_local(str(staging_path))
            self._mounted = True
            entrypoint_on_device = f"/remote/{relative_entrypoint}"
            sys_path_prefix = (
                "import sys\n"
                "sys.path.insert(0, '/remote/lib')\n"
                "sys.path.insert(0, '/remote')\n"
            )

        if follow == "soft_reboot":
            # Caller validated mode == "copy" + entrypoint == "/main.py"
            # at the top.  Files are now on flash; the persistent
            # serial connection is open in raw REPL.  Hand off to the
            # CP-flash-style soft-reboot read.
            try:
                output = self._trigger_soft_reboot_and_read()
            except Exception as error:
                raise MicropythonTransportError(
                    f"Device deploy soft-reboot read failed: {error}"
                ) from error
            # Leave the board in friendly REPL with main.py running.
            # Subsequent transport ops re-enter raw REPL on demand via
            # _ensure_serial; disconnect tolerates either REPL state.
            if on_execute_line is not None:
                for output_line in output.splitlines():
                    on_execute_line(output_line)
            return output

        script = f"{sys_path_prefix}exec(open({entrypoint_on_device!r}).read())"
        try:
            result = self._serial.exec_raw(script, timeout=_EXECUTE_IDLE_TIMEOUT)
        except Exception as error:
            raise MicropythonTransportError(
                f"Device deploy-execute failed: {error}"
            ) from error
        output = _decode_exec_result(result)
        if on_execute_line is not None:
            for output_line in output.splitlines():
                on_execute_line(output_line)
        return output

    def list_files_in_scope(self) -> list[str]:
        """List on-device files within the deploy's managed scope.

        Walks ``/lib/`` recursively + checks the four canonical
        scope files (``/code.py``, ``/main.py``, ``/active.py``,
        ``/runtime_config.msgpack``).  Returns paths in
        leading-slash form.

        Mount-mode (RAM) deploys return an empty list — mount mode
        doesn't write to flash, so there's nothing persistent to
        diff between deploys.

        Raises :class:`MicropythonTransportError` on raw-REPL failure
        — :meth:`Deployer.deploy_diff` translates this to "skip the
        diff cleanup, fall through to a plain deploy_files" so a
        transient REPL hiccup doesn't block a deploy.
        """
        if self.mode != "copy":
            return []
        if self._mounted and self._serial is not None:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover — best-effort cleanup
                pass
            self._mounted = False
        self._ensure_serial()
        try:
            result = self._serial.exec_raw(_LIST_SCOPE_SCRIPT, timeout=30)
        except Exception as error:
            raise MicropythonTransportError(
                f"list_files_in_scope failed: {error}",
            ) from error
        output = _decode_exec_result(result)
        return _parse_scope_listing(output)

    def delete_files(self, paths: list[str]) -> None:
        """Delete *paths* from the device's filesystem.

        No-op in mount (RAM) mode — mount mode doesn't write to
        flash, so there's nothing to delete.  Otherwise sends a
        small script that calls ``os.remove`` on each path; missing
        paths and per-path errors are tolerated silently so the
        diff-cleanup pass never blocks the actual deploy.
        """
        if not paths:
            return
        if self.mode != "copy":
            return
        if self._mounted and self._serial is not None:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover — best-effort cleanup
                pass
            self._mounted = False
        self._ensure_serial()
        # `repr(paths)` round-trips a list of strings cleanly into
        # a Python literal — no manual escaping required.
        script = (
            "import os\n"
            f"_paths = {paths!r}\n"
            "for _path in _paths:\n"
            "    try:\n"
            "        os.remove(_path)\n"
            "    except OSError:\n"
            "        pass\n"
        )
        try:
            self._serial.exec_raw(script, timeout=30)
        except Exception as error:
            raise MicropythonTransportError(
                f"delete_files failed: {error}",
            ) from error

    def wipe_filesystem(self) -> None:
        """Reformat the LittleFS user partition and soft-reset the runtime.

        Mount-mode (RAM) is a no-op — nothing was written to flash.

        Otherwise dispatches :data:`_WIPE_FILESYSTEM_SCRIPT` which
        ``os.umount('/')`` s the live volume, calls
        ``os.VfsLfs2.mkfs(<block_device>)`` for the running platform
        (rp2 → ``rp2.Flash()``, esp32 → the ``vfs`` data partition),
        and ends with ``machine.soft_reset()`` so the runtime
        re-mounts the freshly formatted volume on boot.  An
        ``os.remove`` walk would leave LittleFS metadata + wear-
        leveling artifacts on flash, so a board that filled up over
        many test runs can still hit ``ENOSPC`` mid-deploy after a
        non-mkfs "wipe."  The mkfs path recovers the full block
        budget every time.

        The script is dispatched as a one-shot ``mpremote exec``
        subprocess rather than via the persistent :class:`SerialTransport`:
        ``machine.soft_reset()`` clears interpreter state and the
        ``raw_repl`` framing, so reusing the persistent transport
        across the reset would leave it in an inconsistent state.
        After the subprocess returns, the serial port is given
        :data:`_WIPE_REBOOT_SETTLE_SECONDS` to settle so the next
        :meth:`connect` / :meth:`stage` call sees a fully booted
        runtime ready to accept a fresh raw-REPL session.
        """
        if self.mode != "copy":
            return
        # Drop any active mount + persistent transport so the subprocess
        # below can claim the serial port.  The soft_reset inside the
        # script invalidates the raw-REPL framing on whatever transport
        # owns the port at the time, so we deliberately don't try to
        # reuse the persistent transport across the call.
        if self._mounted and self._serial is not None:
            try:
                self._serial.umount_local()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._mounted = False
        self._close_serial()
        try:
            self._run_mpremote(["exec", _WIPE_FILESYSTEM_SCRIPT])
        except MicropythonTransportError as error:
            raise MicropythonTransportError(
                f"wipe_filesystem failed: {error}",
            ) from error
        # Let the runtime finish booting on the freshly-formatted volume
        # before any follow-up call grabs the port.  rp2 and esp32 keep
        # their host-side USB-CDC alive across machine.soft_reset(), so
        # this is settle time for the runtime — not USB-CDC re-enumeration.
        self._time.sleep(_WIPE_REBOOT_SETTLE_SECONDS)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_serial(self) -> None:
        """Open the persistent serial transport and enter raw REPL if needed."""
        if self._serial is not None:
            return
        self._serial = self._transport_factory(self.address, self.baudrate)
        self._serial.enter_raw_repl(soft_reset=True)

    def _trigger_soft_reboot_and_read(self) -> str:
        """Exit raw REPL, soft-reboot, read main.py output, return user text.

        Mirror of :meth:`CircuitpythonTransport._read_code_py_output`'s
        flash-mode pattern.  Used by
        ``deploy_files(follow="soft_reboot")`` for app-code deploys
        whose entrypoint may be a ``while True`` body that never
        returns.  The raw-REPL ``exec_raw`` path (``follow="exec"``)
        works for return-bounded scripts because raw REPL emits the
        EOF (``\\x04``) marker when the script returns; for an
        infinite-loop body the EOF never fires and the deploy hangs.
        Soft-reboot bypasses raw REPL and reads serial directly with
        a wall-clock timeout, returning whatever accumulated.

        Sequence:

        1. Send ``\\r\\x02`` (Ctrl-B) — exit raw REPL into friendly REPL.
        2. Send ``\\x04`` (Ctrl-D) — soft-reboot.  MicroPython prints
           ``MPY: soft reboot``, runs ``boot.py`` (if present), then
           auto-runs ``/main.py``.
        3. Read serial bytes via ``mpremote.SerialTransport.read_until``
           with ``ending=b"\\r\\n>>> "`` (friendly-REPL prompt — the
           analog of CircuitPython's ``Code done running.`` end
           marker).  ``timeout_overall=self.timeout`` bounds the wait
           — for ``while True`` bodies the prompt never appears and
           the read returns whatever accumulated.

        Returns:
            User stdout from ``main.py`` execution, with the
            ``MPY: soft reboot`` start marker, friendly-REPL banner,
            and ``>>>`` prompt stripped.  See
            :meth:`_extract_main_py_output` for the trimming rules.
        """
        assert self._serial is not None
        port = self._serial.serial
        # Two-stage transition.  Sending Ctrl-B + Ctrl-D back-to-back
        # was bench-tested as racing on Pi Pico W MP — the firmware
        # didn't always see Ctrl-D as "soft-reboot from friendly REPL"
        # because it was still finishing the raw-REPL exit.  Wait for
        # the friendly-REPL prompt before issuing Ctrl-D so the
        # transition is observable.
        port.write(b"\r\x02")  # Ctrl-B: exit raw REPL into friendly REPL.
        self._serial.read_until(
            1, b">>> ", timeout=2.0, timeout_overall=2.0,
        )
        port.write(b"\x04")    # Ctrl-D: soft-reboot from friendly REPL.
        # Long inter-byte timeout (we don't care about idle gaps within
        # main.py output — only the overall budget); ``timeout_overall``
        # caps the total wait.
        raw = self._serial.read_until(
            1, b"\r\n>>> ",
            timeout=self.timeout,
            timeout_overall=self.timeout,
        )
        return self._extract_main_py_output(raw)

    @staticmethod
    def _extract_main_py_output(raw_boot_output: bytes) -> str:
        """Extract user output from a fresh-boot serial capture.

        Sync to the ``MPY: soft reboot`` start marker so any pre-reboot
        bytes still in the host's serial buffer are discarded.  Strip
        the trailing friendly-REPL banner (``MicroPython v...; <board>``
        line + ``Type "help()" for more information.`` line + ``>>> ``
        prompt) when ``main.py`` returned cleanly.  When ``main.py`` is
        a ``while True`` body the read times out without those markers
        and the trim is a no-op — partial accumulated output is
        returned verbatim.

        Tracebacks are kept (they're diagnostic for the user); only
        the post-traceback REPL banner is stripped.

        Args:
            raw_boot_output: Bytes captured from the soft-reboot read.
        """
        text = raw_boot_output.decode("utf-8", errors="replace")
        marker_index = text.find("MPY: soft reboot")
        if marker_index != -1:
            trailing_newline = text.find("\n", marker_index)
            if trailing_newline != -1:
                text = text[trailing_newline + 1:]
        # Trim trailing friendly-REPL output.  Two anchors, whichever
        # appears first wins:
        #   * ``\nMicroPython v`` — start of the friendly-REPL banner
        #     line (``MicroPython v1.28.0 on ...; <board>``).  Cuts
        #     before the banner so any preceding traceback is
        #     preserved.  This is the normal case after a clean
        #     return or an exception.
        #   * ``\n>>> `` (or bare ``>>> `` at start) — friendly-REPL
        #     prompt.  Backstop for cases where the banner wasn't
        #     captured (e.g. a quick return whose banner straddled
        #     the read window) — without this, the trailing prompt
        #     leaks into the returned text.
        candidates: list[int] = []
        for anchor in ("\nMicroPython v", "\n>>> "):
            position = text.find(anchor)
            if position != -1:
                candidates.append(position)
        if text.startswith(">>> "):
            candidates.append(0)
        if candidates:
            text = text[:min(candidates)]
        return text.strip("\r\n") + "\n"

    def _close_serial(self) -> None:
        """Close the persistent serial transport if open."""
        if self._serial is None:
            return
        try:
            if self._mounted:
                try:
                    self._serial.umount_local()
                except Exception:  # pragma: no cover - best-effort cleanup
                    pass
                self._mounted = False
            try:
                self._serial.exit_raw_repl()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
            self._serial.close()
        finally:
            self._serial = None

    def _clean_device_lib(self) -> None:
        """Remove ``:/lib`` from the device, tolerating a missing tree.

        Called from :meth:`deploy_files` when ``clean=True`` in copy
        mode.  The CP transport runs ``rsync --delete`` with
        ``settings.toml`` / ``boot.py`` / ``boot_out.txt`` excluded;
        on MP the analog is "wipe the most common accumulation site
        and let the rsync-equivalent ``mpremote fs cp -r`` repopulate
        it."  Top-level user-managed files (``boot.py``, ``main.py``,
        ``settings.toml``, ``runtime_config.msgpack``) live outside
        ``/lib`` and are untouched.

        Tolerates a missing ``/lib`` — first deploy on a clean device,
        or repeat deploys after a previous wipe.  mpremote exits
        non-zero in that case; we swallow it because "the dir we
        wanted gone is gone" is the desired post-condition either way.
        """
        try:
            self._run_mpremote(["fs", "rm", "-r", ":/lib"])
        except MicropythonTransportError:
            # /lib doesn't exist on the device — nothing to clean.
            pass

    def _run_mpremote(self, arguments: list[str]) -> subprocess.CompletedProcess:
        """Run an mpremote command and return the result.

        Args:
            arguments: Arguments to pass after ``mpremote connect <address>``.

        Raises:
            MicropythonTransportError: If the command exits with a non-zero code.
        """
        command = [_resolve_mpremote_binary(), "connect", self.address] + arguments
        result = self._runner(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise MicropythonTransportError(
                f"mpremote command failed (exit {result.returncode}):\n"
                f"  command: {' '.join(command)}\n"
                f"  stderr: {result.stderr.strip()}"
            )
        return result

    def _copy_tree(self, source: Path, destination: Path) -> None:
        """Recursively copy a directory tree into the destination.

        Copies top-level packages (directories with ``__init__.py``)
        from *source* into *destination*, preserving the package
        directory structure.

        Skips host-only build artifacts that have no business on a
        device: CPython bytecode caches (``__pycache__``, ``*.pyc``),
        editable-install metadata (``*.egg-info``), and other VCS /
        tooling dirs.  Without this filter, a Pi-Pico-W-MP flash
        deploy of the requests stack triples in size from CPython
        3.14 .pyc files alone.

        Also drops ``.py`` files whose ``__chumicro_runtimes__`` marker
        excludes MicroPython, so a wrong-runtime adapter (e.g. ``cp.py``)
        never lands on the MP device.

        Args:
            source: Source directory to copy from (e.g. a ``src/`` dir).
            destination: Destination directory to copy into.
        """
        if not source.is_dir():
            return
        for child in sorted(source.iterdir()):
            if self._should_exclude_from_stage(child):
                continue
            target = destination / child.name
            if child.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                self._copy_tree(child, target)
            elif child.is_file():
                target.write_bytes(child.read_bytes())

    def _should_exclude_from_stage(self, path: Path) -> bool:
        """Return True if *path* is host-only cruft that shouldn't deploy."""
        name = path.name
        if name in _STAGE_EXCLUDED_NAMES:
            return True
        if name.endswith(".pyc") or name.endswith(".egg-info"):
            return True
        if path.is_file() and path.suffix == ".py" and not file_targets_runtime(
            path, target_runtime=self._target_runtime,
        ):
            return True
        return False
