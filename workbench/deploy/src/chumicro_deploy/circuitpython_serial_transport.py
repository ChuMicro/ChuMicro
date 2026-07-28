"""Drive-less CircuitPython transport: deploy over the serial raw REPL.

A classic ESP32 (no native USB) running CircuitPython exposes **no
CIRCUITPY drive**: the board reaches the host only through a UART-USB
bridge, and there is no USB-MSC volume to rsync onto.  The stock
:class:`~chumicro_deploy.circuitpython_transport.CircuitpythonTransport`
flash mode copies files to that drive, so it cannot reach such a board.

This transport fills the gap.  It **subclasses**
:class:`CircuitpythonTransport` so every pyserial raw-REPL primitive is
reused verbatim (``connect``, ``execute``, ``execute_scripts``,
``soft_reset``, ``recover``, ``disconnect``, the probes,
``_read_until`` / ``_send_repl_command`` / ``_read_code_py_output``) and
overrides only the six methods that used to touch the CIRCUITPY drive
(:meth:`stage`, :meth:`deploy_files`, :meth:`list_files_in_scope`,
:meth:`delete_files`, :meth:`clear_entrypoints`, :meth:`wipe_filesystem`).
Those overrides do their filesystem work *on the device* over the raw
REPL instead of on a host-mounted volume.

Two mechanics carry it:

- **File write over the raw REPL** (the spike's ``open('/f','wb').write``
  path).  Content is base64-chunked and streamed as
  ``_f.write(binascii.a2b_base64(...))`` submissions.  Base64 is 1.33x
  (vs. ~4x for a Python ``bytes`` repr of binary msgpack) and pure-ASCII,
  so it never trips raw-REPL escaping.  Large files span multiple
  submissions against a file handle persisted in the raw-REPL globals.
- **Device-side scope / delete / clear scripts** reused from
  :mod:`._device_scripts`, the same stdlib-only generators the
  MicroPython transport runs over *its* raw REPL.  They are runtime
  neutral (``os.listdir`` / ``os.stat`` / ``os.remove``), so the diff
  primitives share one implementation across both runtimes.

CircuitPython-specific quirks handled here (all observed on-bench,
tinypico-cp, CP 10.2.0, 2026-07-05):

1. **Safe mode.**  A board in safe mode gives a working REPL but runs
   nothing.  :meth:`_raise_if_safe_mode` probes
   ``supervisor.runtime.safe_mode_reason`` up front and fails loudly with
   the reason instead of letting a later step time out.
2. **Status-bar OSC noise.**  CP's serial console emits
   ``ESC ] 0 ; ... BEL`` title / status escape sequences (and CSI cursor
   sequences) that pollute reads.  :func:`_strip_terminal_noise` removes
   them, wired in via the :meth:`_parse_raw_repl_response` /
   :meth:`_extract_code_output` overrides so every inherited read path
   sees clean bytes.
3. **Soft-reboot semantics.**  A Ctrl-D from *raw* REPL re-enters raw
   REPL without running ``code.py``.  :meth:`deploy_files` exits to the
   friendly REPL (Ctrl-B) first, then Ctrl-D, so the freshly-written
   ``code.py`` actually runs, reusing the parent's
   :meth:`_read_code_py_output`.
4. **Autoreload.**  :meth:`_disable_autoreload` turns autoreload off
   before a multi-file push, handling both the CP 8+
   ``supervisor.runtime.autoreload = False`` spelling and the older
   ``supervisor.disable_autoreload()`` one.

The boot.py ``storage.remount()`` handshake that a *native-USB* board
would need to make its own filesystem VM-writable is deliberately **out
of scope** (workstream phase 3): this board has no USB host owning the
filesystem, so the VM can already write ``/`` freely.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from . import flash_drive, source_minify
from ._device_scripts import (
    CLEAR_ENTRYPOINTS_SCRIPT,
    LIST_ALL_SCRIPT,
    LIST_SCOPE_SCRIPT,
    clean_slate_script,
    delete_files_script,
    parse_scope_listing,
)
from .circuitpython_transport import (
    _CTRL_B,
    _CTRL_D,
    _ENTER_DELAY,
    _WIPE_REBOOT_SETTLE_SECONDS,
    CircuitpythonTransport,
    CircuitpythonTransportError,
)
from .protocol import validate_entrypoint_in_files, write_files_to_staging

if TYPE_CHECKING:  # pragma: no cover - type-only
    from collections.abc import Callable


#: Raw payload bytes per ``_f.write(...)`` call.  Small enough that a
#: single base64 literal stays comfortably inside the raw-REPL line
#: budget, big enough that a typical minified module is one or two
#: writes.
_FILE_WRITE_RAW_CHUNK = 512

#: Soft cap on the source text of one raw-REPL submission during a file
#: write.  A file larger than this is split across submissions that
#: append to the ``_f`` handle persisted in the raw-REPL globals.  Kept
#: well under the ~48 KB the RAM-mode chunker already drives over the
#: same plain raw REPL, so the flow-control envelope is proven.
_MAX_WRITE_SUBMISSION_BYTES = 12 * 1024

#: Idle-timeout (seconds) for a file-write submission's response.  The
#: response itself is a few bytes (``OK\x04\x04>``); the budget only has
#: to cover on-device compile of a chunked write script, so it is short.
_WRITE_IDLE_TIMEOUT = 30.0

#: Sentinel a board prints when it still carries a ``settings.toml``.
_HAS_SETTINGS_MARKER = "__CHU_HAS_SETTINGS__"

#: Marker line the safe-mode probe prints its reason behind.
_SAFE_MODE_MARKER = "__CHU_SAFE__:"

#: Matches an ANSI OSC sequence (``ESC ] ... BEL`` or ``ESC ] ... ST``),
#: which is CircuitPython's terminal title / status-bar writes, and a CSI
#: sequence (``ESC [ ... final-byte``).  Both are stripped from serial
#: reads so they never contaminate parsed stdout or the raw-REPL framing.
_TERMINAL_NOISE_RE = re.compile(
    rb"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL | ST
    rb"|\x1b\[[0-9;?]*[ -/]*[@-~]",  # CSI ... final
)


def _strip_terminal_noise(data: bytes) -> bytes:
    """Remove CP status-bar OSC / CSI escape sequences from *data*."""
    return _TERMINAL_NOISE_RE.sub(b"", data)


class CircuitpythonSerialTransport(CircuitpythonTransport):
    """Drive-less CircuitPython transport writing files over the raw REPL.

    Constructed with ``mode="serial"``, a third mode label alongside
    the parent's ``"ram"`` / ``"flash"``.  ``mode`` is deliberately not
    a :class:`~chumicro_deploy.protocol.DeployMode` value: serial is a
    *transport variant* orthogonal to the ram/flash deploy-mode axis
    (it is the persistent-flash path for a board that has no drive), and
    :meth:`chumicro_deploy.device.Device.create_transport` selects it
    from the ``deploy_transport`` field, not from ``deploy_mode``.

    Args:
        address: Serial port path (e.g. ``/dev/cu.usbserial-01B97DDC``).
        baudrate: Serial baud rate.  Defaults to 115200.
        **kwargs: Forwarded to :class:`CircuitpythonTransport` (``timeout``,
            ``serial_port_factory``, ``time``, ``drive_scanner``).
    """

    def __init__(self, address: str, **kwargs: object) -> None:
        kwargs.pop("mode", None)
        super().__init__(address, mode="serial", **kwargs)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Overridden interface methods (were drive-based on the parent)
    # ------------------------------------------------------------------

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
        extra_files: dict[str, bytes] | None = None,
        include_test_support: bool = False,
    ) -> None:
        """Write the library / harness / test tree onto device flash over serial.

        Mirrors flash mode's clean-slate + push, but the "push" is a
        raw-REPL file-write instead of a drive rsync: assemble the same
        host-side staging tree flash mode builds
        (:meth:`_build_local_staging_tree`, with libs + harness under
        ``lib/``, test files and ``extra_files`` at the root), then
        stream every file to the matching absolute device path.  The
        board's importer sees the files immediately because the VM that
        wrote them owns the filesystem (no USB-MSC cache to refresh).

        Unlike RAM mode, ``extra_files`` (a ``runtime_config.msgpack``)
        is fully supported: a drive-less board still has a writable
        device filesystem.
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before stage()",
            )
        self._raise_if_safe_mode()
        self._include_test_support = include_test_support
        # Serial mode never runs the RAM-inline bootstrap, so no source
        # collection is needed; files import from flash like flash mode.
        self._staged_sources = []

        self._enter_raw_repl()
        self._disable_autoreload()

        with TemporaryDirectory(prefix="chumicro-serial-stage-") as staging_directory:
            staging_path = Path(staging_directory)
            self._build_local_staging_tree(
                staging_path,
                source_dirs,
                test_files,
                harness_source,
                extra_modules=extra_modules,
                extra_files=extra_files,
            )
            self._notice_settings_toml_eviction_device()
            self._clean_slate_device()
            self._write_tree_over_repl(staging_path)

        self._staged = True

    def deploy_files(
        self,
        files: dict[str, bytes],
        entrypoint: str,
        *,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        tail_seconds: float | None = None,
        clean: bool = False,
    ) -> str:
        """Write *files* onto device flash over serial and run *entrypoint*.

        The persistent-flash counterpart of flash mode's drive push.
        Files are minified, streamed to their absolute device paths over
        the raw REPL, and then the entrypoint runs.  When it is
        ``code.py`` / ``main.py`` the board is soft-rebooted into it
        (Ctrl-B to the friendly REPL, then Ctrl-D, because a bare
        raw-REPL Ctrl-D re-enters raw REPL without running it), and the
        parent's :meth:`_read_code_py_output` captures the boot output.
        Any other entrypoint is ``exec(open(...).read())``-ed over the
        live raw REPL and its stdout returned.

        Args:
            files: On-device-path -> bytes mapping.
            entrypoint: On-device path, must be a key of *files*.
            on_file_staged: Per-file callback, fired as each file lands.
            on_execute_line: Per-output-line callback, fired after the
                entrypoint runs.
            tail_seconds: Soft-reboot capture window override (``None``
                uses :attr:`timeout`).  Ignored for non-boot entrypoints.
            clean: When ``True``, clean-slate the device (keep set only)
                before writing.
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before deploy_files()",
            )
        validate_entrypoint_in_files(
            files, entrypoint, error_cls=CircuitpythonTransportError,
        )
        self._raise_if_safe_mode()

        self._enter_raw_repl()
        self._disable_autoreload()
        if clean:
            self._notice_settings_toml_eviction_device()
            self._clean_slate_device()

        with TemporaryDirectory(prefix="chumicro-serial-deploy-") as staging_directory:
            staging_path = Path(staging_directory)
            write_files_to_staging(staging_path, files, on_file_staged)
            source_minify.minify_python_tree(staging_path)
            self._write_tree_over_repl(staging_path)

        relative_entrypoint = entrypoint.lstrip("/")
        if relative_entrypoint in ("code.py", "main.py"):
            # Soft-reboot into the freshly-written entrypoint.  Ctrl-B to
            # the friendly REPL first so the following Ctrl-D is a
            # soft-reboot (which runs code.py) and not a raw-REPL
            # re-entry (which would not).
            self._port.write(_CTRL_B)
            self._time.sleep(_ENTER_DELAY)
            self._port.write(_CTRL_D)
            output = self._read_code_py_output(tail_seconds=tail_seconds)
        else:
            output = self._send_repl_command(
                f"exec(open({entrypoint!r}).read())",
            )

        if on_execute_line is not None:
            for output_line in output.splitlines():
                on_execute_line(output_line)
        return output

    def list_files_in_scope(self, *, clean_slate: bool = False) -> list[str]:
        """Enumerate in-scope device files by walking the FS over the raw REPL.

        Reuses the runtime-neutral walk scripts from
        :mod:`._device_scripts` (the MicroPython transport runs the same
        ones over its raw REPL).  ``clean_slate=True`` widens to the whole
        device minus :data:`flash_drive.DEVICE_KEEP_SET` and dot-prefixed
        paths; ``False`` is the additive entrypoint/state + ``/lib``
        scope.  Returns an empty list when the port is not open.
        """
        if self._port is None:
            return []
        script = LIST_ALL_SCRIPT if clean_slate else LIST_SCOPE_SCRIPT
        try:
            output = self._send_repl_command(script)
        except CircuitpythonTransportError:
            return []
        listed = parse_scope_listing(output)
        if not clean_slate:
            return listed
        keep = set(flash_drive.DEVICE_KEEP_SET)
        return [
            path
            for path in listed
            if not any(part.startswith(".") for part in path.split("/") if part)
            and path.rsplit("/", 1)[-1] not in keep
        ]

    def delete_files(self, paths: list[str]) -> None:
        """Delete *paths* over the raw REPL, reaping directories left empty.

        Runs the shared :func:`._device_scripts.delete_files_script`
        (``os.remove`` each path, then an ``os.rmdir`` reap of every
        now-empty non-dot directory).  Best-effort: a swallowed error
        just retries next deploy, and the stale set is recomputed each
        time.  No-op on an empty list or a closed port.
        """
        if not paths or self._port is None:
            return
        try:
            self._send_repl_command(delete_files_script(paths))
        except CircuitpythonTransportError:
            # A transient hiccup here must not block the deploy that
            # follows; the stale set is recomputed on the next pass.
            pass

    def clear_entrypoints(self) -> None:
        """Remove ``code.py`` / ``main.py`` and confirm they are gone.

        Runs :data:`._device_scripts.CLEAR_ENTRYPOINTS_SCRIPT`, which
        re-``stat``s each path after ``os.remove`` so a still-present
        entrypoint raises *on the device*.  Call once before a
        soft-reboot so a stale entrypoint can't race the reset.  No-op
        on a closed port.
        """
        if self._port is None:
            return
        self._send_repl_command(CLEAR_ENTRYPOINTS_SCRIPT)

    def wipe_filesystem(self) -> None:
        """Erase the device filesystem via ``storage.erase_filesystem()``.

        The CircuitPython nuclear option: reformat the flash volume and
        hard-reset.  Unlike the parent (which then polls for a CIRCUITPY
        *drive* to remount, one that never appears on a drive-less
        board), this reconnects over serial only.  The UART-USB bridge
        keeps the host port enumerated across the CP reset, so a settle
        pause plus a fresh raw-REPL entry is all that's needed.
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before wipe_filesystem()",
            )
        try:
            self._send_repl_command(
                "import storage\nstorage.erase_filesystem()\n",
            )
        except Exception:  # noqa: BLE001 - the reset tears down the REPL mid-call
            pass
        try:
            self._port.close()
        except Exception:  # pragma: no cover - port may already be torn down
            pass
        self._port = None
        self._time.sleep(_WIPE_REBOOT_SETTLE_SECONDS)
        self.connect()

    # ------------------------------------------------------------------
    # CP quirk handling
    # ------------------------------------------------------------------

    def _parse_raw_repl_response(self, raw_response: bytes) -> str:  # type: ignore[override]
        """Strip CP terminal noise, then parse via the inherited framing rules.

        Every inherited read path (``execute``, ``_send_repl_command``,
        the probes) funnels through ``self._parse_raw_repl_response``, so
        this one override cleans OSC / CSI escapes out of *all* of them
        before the ``OK<stdout>\\x04<stderr>\\x04>`` framing is parsed.
        """
        return CircuitpythonTransport._parse_raw_repl_response(
            _strip_terminal_noise(raw_response),
        )

    @staticmethod
    def _extract_code_output(raw_boot_output: bytes) -> str:  # type: ignore[override]
        """Strip CP terminal noise before extracting soft-reboot output.

        The soft-reboot capture is the noisiest path, because CP writes
        its status bar as it re-runs ``code.py``, so noise is stripped here
        before the parent's ``code.py output:`` / ``Code done running.``
        boundary logic runs.
        """
        return CircuitpythonTransport._extract_code_output(
            _strip_terminal_noise(raw_boot_output),
        )

    def _raise_if_safe_mode(self) -> None:
        """Fail loudly when the board is in safe mode instead of timing out.

        A safe-mode board answers the REPL but runs no user code, so a
        deploy would silently produce no output and blow a marker budget.
        Probes ``supervisor.runtime.safe_mode_reason`` (an enum whose
        ``NONE`` member means "not in safe mode") and raises with the
        reason when it is anything else.  Firmware too old to expose the
        attribute reports an empty reason and is treated as "not safe."
        """
        script = (
            "import supervisor\n"
            "_r = getattr(supervisor.runtime, 'safe_mode_reason', None)\n"
            f"print({_SAFE_MODE_MARKER!r} + ('' if _r is None else str(_r)))\n"
        )
        output = self._send_repl_command(script)
        reason = ""
        for line in output.splitlines():
            if line.startswith(_SAFE_MODE_MARKER):
                reason = line[len(_SAFE_MODE_MARKER):].strip()
        # ``SafeModeReason.NONE`` (and a bare empty / ``None``) mean the
        # board is running normally; anything else is a live safe-mode
        # reason worth surfacing verbatim.
        if reason and reason not in ("None",) and not reason.endswith("NONE"):
            raise CircuitpythonTransportError(
                f"CircuitPython board {self.address} is in safe mode "
                f"({reason}).  It will answer the REPL but run no code.  "
                "Clear the safe-mode cause (check boot.py / a brownout / a "
                "hard fault) and reset the board, then redeploy.",
            )

    def _disable_autoreload(self) -> None:
        """Turn autoreload off, tolerating both CP spellings.

        CP 8+ exposes ``supervisor.runtime.autoreload`` (a writable
        attribute); older builds expose ``supervisor.disable_autoreload()``.
        Autoreload watches for *host* filesystem writes, which a
        drive-less board never sees, but a multi-file push is exactly
        the window where a stray reset would wedge things, so it is
        disabled defensively either way.
        """
        self._send_repl_command(
            "import supervisor\n"
            "try:\n"
            "    supervisor.runtime.autoreload = False\n"
            "except (AttributeError, NameError):\n"
            "    try:\n"
            "        supervisor.disable_autoreload()\n"
            "    except AttributeError:\n"
            "        pass\n",
        )

    # ------------------------------------------------------------------
    # File-write-over-REPL mechanics
    # ------------------------------------------------------------------

    def _write_tree_over_repl(self, local_root: Path) -> None:
        """Stream every file under *local_root* to its matching device path.

        A file at ``<local_root>/lib/foo/bar.py`` lands at
        ``/lib/foo/bar.py`` on the device.
        """
        files: dict[str, bytes] = {}
        for path in sorted(local_root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(local_root).as_posix()
                files["/" + relative] = path.read_bytes()
        self._write_files_over_repl(files)

    def _write_files_over_repl(self, files: dict[str, bytes]) -> None:
        """Create parent dirs, then write each of *files* over the raw REPL."""
        needed_dirs: set[str] = set()
        for device_path in files:
            parts = [part for part in device_path.split("/") if part]
            for depth in range(1, len(parts)):
                needed_dirs.add("/" + "/".join(parts[:depth]))
        if needed_dirs:
            # Shallowest first so a parent exists before its child.
            self._mkdirs_over_repl(
                sorted(needed_dirs, key=lambda directory: directory.count("/")),
            )
        for device_path in sorted(files):
            self._write_file_over_repl(device_path, files[device_path])

    def _mkdirs_over_repl(self, directories: list[str]) -> None:
        """``os.mkdir`` each of *directories* on the device, tolerating existing."""
        listed = ", ".join(repr(directory) for directory in directories)
        self._send_repl_command(
            "import os\n"
            f"for _d in ({listed},):\n"
            "    try:\n"
            "        os.mkdir(_d)\n"
            "    except OSError:\n"
            "        pass\n",
        )

    def _write_file_over_repl(self, device_path: str, content: bytes) -> None:
        """Write *content* to *device_path* on the device over the raw REPL.

        Opens the file in one submission, streams base64-encoded chunks
        as ``_f.write(binascii.a2b_base64(...))`` across as many
        submissions as the per-submission size cap requires (the ``_f``
        handle persists in the raw-REPL globals between them), and closes
        it.  An empty file is a bare open + close.
        """
        submissions = self._build_write_submissions(device_path, content)
        for submission in submissions:
            self._exec_repl(submission, idle_timeout=_WRITE_IDLE_TIMEOUT)

    @staticmethod
    def _build_write_submissions(device_path: str, content: bytes) -> list[str]:
        """Return the ordered raw-REPL submissions that write *content*.

        First submission opens the handle; subsequent ones only append
        writes; the closing ``_f.close()`` rides on the last submission
        so a small file is a single round trip.
        """
        header = f"import binascii\n_f = open({device_path!r}, 'wb')"
        submissions: list[str] = []
        current: list[str] = [header]
        current_size = len(header)
        for offset in range(0, len(content), _FILE_WRITE_RAW_CHUNK):
            chunk = content[offset:offset + _FILE_WRITE_RAW_CHUNK]
            encoded = base64.b64encode(chunk).decode("ascii")
            line = f"_f.write(binascii.a2b_base64({encoded!r}))"
            if current_size + len(line) + 1 > _MAX_WRITE_SUBMISSION_BYTES:
                submissions.append("\n".join(current))
                current = []
                current_size = 0
            current.append(line)
            current_size += len(line) + 1
        current.append("_f.close()")
        submissions.append("\n".join(current))
        return submissions

    def _exec_repl(self, script: str, *, idle_timeout: float | None = None) -> str:
        """Run *script* over the raw REPL with an explicit idle timeout.

        Sibling of the parent's :meth:`_send_repl_command` that lets a
        caller widen the per-response idle timeout (file-write
        submissions can carry a chunked write body that takes the board a
        moment to compile).
        """
        if self._port is None:
            raise CircuitpythonTransportError(
                "connect() must be called before sending REPL commands",
            )
        self._port.write(script.encode("utf-8"))
        self._port.write(_CTRL_D)
        raw_response = self._read_until(b"\x04>", idle_timeout=idle_timeout)
        return self._parse_raw_repl_response(raw_response)

    # ------------------------------------------------------------------
    # Device-side housekeeping
    # ------------------------------------------------------------------

    def _clean_slate_device(self) -> None:
        """Remove every device-root entry except the keep set (recursively).

        The serial analogue of flash mode's ``rsync --delete``: reconcile
        away a stale ``/lib`` tree, an old ``code.py``, or a board
        ``settings.toml`` before writing the new payload, preserving only
        :data:`flash_drive.DEVICE_KEEP_SET` (``boot.py`` / ``boot_out.txt``
        / ``_chu_kv.msgpack``).  Best-effort, since a hard failure here would
        mask the staging it precedes.
        """
        try:
            self._send_repl_command(clean_slate_script(flash_drive.DEVICE_KEEP_SET))
        except CircuitpythonTransportError:  # pragma: no cover - best-effort
            pass

    def _notice_settings_toml_eviction_device(self) -> None:
        """Warn once when a clean-slate is about to evict a board ``settings.toml``.

        A board-resident ``settings.toml`` is a competing wifi authority
        against chumicro's config-driven wifi
        (``runtime_config.msgpack`` from the host ``secrets.toml``), so it
        is evicted on every clean push.  Correct, but invisible unless a
        user who hand-edited it is told.  Emitted at most once per
        transport instance.
        """
        if self._settings_eviction_notified:
            return
        try:
            output = self._send_repl_command(
                "import os\n"
                "try:\n"
                "    os.stat('/settings.toml')\n"
                f"    print({_HAS_SETTINGS_MARKER!r})\n"
                "except OSError:\n"
                "    pass\n",
            )
        except CircuitpythonTransportError:  # pragma: no cover - best-effort
            return
        if _HAS_SETTINGS_MARKER not in output:
            return
        self._settings_eviction_notified = True
        print(
            "WARNING: removing the board's settings.toml.  chumicro "
            "drives wifi from the host-side secrets.toml "
            "(runtime_config.msgpack), and a board-resident "
            "settings.toml is a competing authority.  Put credentials "
            "in the workspace's secrets.toml, not on the board.",
        )
