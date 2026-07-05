"""Tests for CircuitpythonSerialTransport, the drive-less CP transport.

The transport writes files onto device flash over the raw REPL instead
of rsyncing to a CIRCUITPY drive, so these tests drive it against a
scripted raw-REPL board (:class:`ReplBoard`) rather than a mounted
volume.  ``ReplBoard`` auto-ACKs each submission with a well-formed
``OK<stdout>\\x04\\x04>`` frame, answers Ctrl-A with the raw-REPL prompt,
and serves a soft-reboot transcript on the friendly-REPL Ctrl-D, with
tailored stdout for the safe-mode / settings / scope-walk probes.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from chumicro_deploy import CircuitpythonSerialTransport, Device
from chumicro_deploy._device_scripts import SCOPE_LISTING_MARKER
from chumicro_deploy.circuitpython_serial_transport import (
    _SAFE_MODE_MARKER,
    _strip_terminal_noise,
)
from chumicro_deploy.circuitpython_transport import (
    _RAW_REPL_PROMPT,
    CircuitpythonTransportError,
)
from chumicro_deploy.testing import FakeTime, isolate_from_host_filesystem

_SAFE_NONE = "supervisor.SafeModeReason.NONE"

#: The static file-write chunker, named locally for readability.
_build_submissions = CircuitpythonSerialTransport._build_write_submissions


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the macOS xattr/dot_clean subprocess calls in staging.

    ``_build_local_staging_tree`` (inherited from the drive transport)
    strips extended attributes via a subprocess; this keeps the serial
    tests hermetic from the host the same way the drive-transport tests
    are.
    """
    isolate_from_host_filesystem(monkeypatch)


class ReplBoard:
    """A scripted CircuitPython raw-REPL board over a fake serial port.

    Instances are callable so they double as a ``serial_port_factory``.
    """

    def __init__(
        self,
        *,
        safe_reason: str = _SAFE_NONE,
        has_settings: bool = False,
        listing: tuple[str, ...] = (),
        code_output: str = "MARKER\n",
        wrap_osc: bool = False,
    ) -> None:
        self.writes: list[bytes] = []
        self.opens: list[int] = []
        self._pending = b""
        self._submission = b""
        self._last_ctrl: str | None = None
        self.safe_reason = safe_reason
        self.has_settings = has_settings
        self.listing = list(listing)
        self.code_output = code_output
        self.wrap_osc = wrap_osc
        self.closed = False
        self.open_count = 0

    def __call__(self, *_args: object, **_kwargs: object) -> ReplBoard:
        self.open_count += 1
        return self

    @property
    def in_waiting(self) -> int:
        return len(self._pending)

    def read(self, size: int = 1) -> bytes:
        del size  # transport reads in_waiting bytes; hand back everything
        data = self._pending
        self._pending = b""
        return data

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"\x01":  # Ctrl-A: enter raw REPL
            self._pending += self._maybe_osc() + _RAW_REPL_PROMPT
            self._submission = b""
            self._last_ctrl = "A"
        elif data == b"\x02":  # Ctrl-B: exit to friendly REPL
            self._submission = b""
            self._last_ctrl = "B"
        elif data == b"\x03":  # Ctrl-C: interrupt
            self._last_ctrl = "C"
        elif data == b"\x04":  # Ctrl-D: submit / soft-reboot
            if self._last_ctrl == "B":
                self._pending += self._boot_transcript()
            else:
                self._pending += self._frame(self._response_for(self._submission))
            self._submission = b""
            self._last_ctrl = "D"
        else:
            self._submission += data
        return len(data)

    def close(self) -> None:
        self.closed = True

    def reset_input_buffer(self) -> None:
        self._pending = b""

    # -- response synthesis -------------------------------------------------

    def _maybe_osc(self) -> bytes:
        return b"\x1b]0;CIRCUITPY\x07" if self.wrap_osc else b""

    def _frame(self, stdout: bytes) -> bytes:
        return self._maybe_osc() + b"OK" + stdout + b"\x04\x04>"

    def _response_for(self, submission: bytes) -> bytes:
        text = submission.decode("utf-8", "replace")
        if "safe_mode_reason" in text:
            return f"{_SAFE_MODE_MARKER}{self.safe_reason}\n".encode()
        if "os.stat('/settings.toml')" in text:
            return b"__CHU_HAS_SETTINGS__\n" if self.has_settings else b""
        if "def _walk" in text:  # scope-listing walk
            return "".join(
                f"{SCOPE_LISTING_MARKER}{path}\n" for path in self.listing
            ).encode()
        if "open(" in text:
            self.opens.append(len(self.writes))
        return b""

    def _boot_transcript(self) -> bytes:
        return self._maybe_osc() + (
            b"soft reboot\r\n"
            b"code.py output:\r\n"
            + self.code_output.encode()
            + b"Code done running.\r\n"
        )


class SilentBoard(ReplBoard):
    """A board that answers Ctrl-A with the prompt but goes silent afterward.

    Every raw-REPL submission gets an empty read, so ``_send_repl_command``
    idle-times-out and raises — driving the transport's best-effort
    error-handling branches (list / delete / clean-slate / settings /
    wipe).
    """

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if data == b"\x01":  # Ctrl-A still yields the prompt so connect works
            self._pending += _RAW_REPL_PROMPT
        # Any submission (Ctrl-D) yields nothing → the read times out.
        return len(data)


def _write_stream(board: ReplBoard) -> str:
    """Return every byte the transport wrote, decoded, for substring asserts."""
    return b"".join(board.writes).decode("utf-8", "replace")


def _connected(board: ReplBoard) -> CircuitpythonSerialTransport:
    transport = CircuitpythonSerialTransport(
        "/dev/cu.fake",
        serial_port_factory=board,
        time=FakeTime(),
    )
    transport.connect()
    return transport


def _make_library(root: Path) -> Path:
    """Stage a one-module library source tree and return its source dir."""
    source_dir = root / "src"
    package = source_dir / "chumicro_demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VERSION = 1\n")
    (package / "widget.py").write_text("def go():\n    return 42\n")
    return source_dir


def _make_harness(root: Path) -> Path:
    """Stage a minimal harness source tree and return its source dir."""
    source_dir = root / "harness_src"
    package = source_dir / "chumicro_test_harness"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "runner.py").write_text("def run_module(module):\n    pass\n")
    return source_dir


class TestSelection:
    """Serial transport is selected by mode / deploy_transport."""

    def test_constructor_sets_serial_mode(self) -> None:
        transport = CircuitpythonSerialTransport("/dev/null")
        assert transport.mode == "serial"

    def test_device_deploy_transport_serial_builds_serial(self) -> None:
        device = Device(
            transport="circuitpython",
            address="/dev/null",
            deploy_transport="serial",
        )
        transport = device.create_transport()
        assert isinstance(transport, CircuitpythonSerialTransport)

    def test_device_deploy_transport_drive_keeps_drive_transport(self) -> None:
        device = Device(
            transport="circuitpython",
            address="/dev/null",
            deploy_transport="drive",
        )
        transport = device.create_transport()
        assert type(transport).__name__ == "CircuitpythonTransport"


class TestStripTerminalNoise:
    """OSC / CSI status-bar escapes are removed from serial reads."""

    def test_strips_osc_bel(self) -> None:
        assert _strip_terminal_noise(b"\x1b]0;title\x07hi") == b"hi"

    def test_strips_osc_st(self) -> None:
        assert _strip_terminal_noise(b"a\x1b]0;t\x1b\\b") == b"ab"

    def test_strips_csi(self) -> None:
        assert _strip_terminal_noise(b"x\x1b[2Ky") == b"xy"

    def test_leaves_plain_bytes(self) -> None:
        assert _strip_terminal_noise(b"clean output\n") == b"clean output\n"


class TestBuildWriteSubmissions:
    """Base64 file-write chunking round-trips and honours the size cap."""

    def _reconstruct(self, submissions: list[str]) -> bytes:
        """Decode every base64 payload in *submissions* back to bytes."""
        import re

        pattern = re.compile(r"a2b_base64\('([^']*)'\)")
        out = b""
        for submission in submissions:
            for match in pattern.findall(submission):
                out += base64.b64decode(match)
        return out

    def test_small_file_is_one_submission(self) -> None:
        submissions = _build_submissions("/code.py", b"print(1)\n")
        assert len(submissions) == 1
        assert submissions[0].startswith("import binascii")
        assert submissions[0].endswith("_f.close()")
        assert self._reconstruct(submissions) == b"print(1)\n"

    def test_empty_file_opens_and_closes(self) -> None:
        submissions = _build_submissions("/empty.py", b"")
        assert len(submissions) == 1
        assert "open('/empty.py', 'wb')" in submissions[0]
        assert self._reconstruct(submissions) == b""

    def test_large_file_spans_multiple_submissions(self) -> None:
        content = bytes(range(256)) * 400  # ~100 KB, well over the cap
        submissions = _build_submissions("/big.bin", content)
        assert len(submissions) > 1
        assert self._reconstruct(submissions) == content

    def test_binary_content_round_trips(self) -> None:
        content = b"\x00\x01\x02\xff\xfe msgpack-ish \x80\x81"
        submissions = _build_submissions("/rc.msgpack", content)
        assert self._reconstruct(submissions) == content


class TestSafeMode:
    """A safe-mode board fails loudly instead of timing out."""

    def test_stage_raises_on_safe_mode(self, tmp_path: Path) -> None:
        board = ReplBoard(safe_reason="supervisor.SafeModeReason.HARD_FAULT")
        transport = _connected(board)
        with pytest.raises(CircuitpythonTransportError, match="safe mode"):
            transport.stage(
                [_make_library(tmp_path)], [], _make_harness(tmp_path),
            )

    def test_deploy_files_raises_on_safe_mode(self) -> None:
        board = ReplBoard(safe_reason="supervisor.SafeModeReason.BROWNOUT")
        transport = _connected(board)
        with pytest.raises(CircuitpythonTransportError, match="safe mode"):
            transport.deploy_files({"/code.py": b"pass\n"}, "/code.py")

    def test_normal_board_is_not_flagged_safe(self) -> None:
        board = ReplBoard(safe_reason=_SAFE_NONE)
        transport = _connected(board)
        # Should not raise — SafeModeReason.NONE means "running normally".
        transport._raise_if_safe_mode()


class TestStage:
    """stage() writes the staging tree onto device flash over serial."""

    def test_stage_writes_tree_and_disables_autoreload(
        self, tmp_path: Path,
    ) -> None:
        board = ReplBoard()
        transport = _connected(board)
        app = tmp_path / "app.py"
        app.write_text("print('hello')\n")

        transport.stage(
            [_make_library(tmp_path)],
            [app],
            _make_harness(tmp_path),
            extra_files={"/runtime_config.msgpack": b"\x00\x01\x02\x80"},
        )

        stream = _write_stream(board)
        assert transport._staged is True
        # Autoreload disabled before the push (both spellings tolerated).
        assert "autoreload" in stream
        # Clean-slate + mkdir + library / app / config all land at their
        # absolute device paths.
        assert "_keep" in stream  # clean_slate_script
        assert "os.mkdir" in stream
        assert "open('/lib/chumicro_demo/__init__.py', 'wb')" in stream
        assert "open('/app.py', 'wb')" in stream
        assert "open('/runtime_config.msgpack', 'wb')" in stream
        # The binary runtime_config survives via base64 (a bytes-repr
        # would have mangled the high bytes).
        assert base64.b64encode(b"\x00\x01\x02\x80").decode() in stream

    def test_stage_requires_connect(self, tmp_path: Path) -> None:
        transport = CircuitpythonSerialTransport(
            "/dev/null", serial_port_factory=ReplBoard(), time=FakeTime(),
        )
        with pytest.raises(CircuitpythonTransportError, match="connect"):
            transport.stage([_make_library(tmp_path)], [], _make_harness(tmp_path))

    def test_stage_notices_settings_toml_eviction(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        board = ReplBoard(has_settings=True)
        transport = _connected(board)
        transport.stage(
            [_make_library(tmp_path)], [], _make_harness(tmp_path),
        )
        assert "settings.toml" in capsys.readouterr().out


class TestDeployFiles:
    """deploy_files() writes files then runs the entrypoint."""

    def test_code_py_soft_reboots_and_returns_output(self) -> None:
        board = ReplBoard(code_output="RESULT_MARKER\n")
        transport = _connected(board)
        lines: list[str] = []

        output = transport.deploy_files(
            {"/code.py": b"print('RESULT_MARKER')\n"},
            "/code.py",
            on_execute_line=lines.append,
        )

        stream = _write_stream(board)
        assert "open('/code.py', 'wb')" in stream
        # Ctrl-B then Ctrl-D — the soft-reboot dance that actually runs
        # code.py (a bare raw-REPL Ctrl-D would not).
        assert b"\x02" in board.writes
        assert output.strip() == "RESULT_MARKER"
        assert lines == ["RESULT_MARKER"]

    def test_non_boot_entrypoint_execs_over_repl(self) -> None:
        board = ReplBoard()
        transport = _connected(board)
        transport.deploy_files({"/active.py": b"pass\n"}, "/active.py")
        stream = _write_stream(board)
        assert "exec(open('/active.py').read())" in stream

    def test_deploy_files_clean_wipes_first(self) -> None:
        board = ReplBoard()
        transport = _connected(board)
        transport.deploy_files(
            {"/code.py": b"pass\n"}, "/code.py", clean=True,
        )
        assert "_keep" in _write_stream(board)  # clean_slate_script ran

    def test_deploy_files_rejects_missing_entrypoint(self) -> None:
        board = ReplBoard()
        transport = _connected(board)
        with pytest.raises(CircuitpythonTransportError, match="missing from files"):
            transport.deploy_files({"/code.py": b"pass\n"}, "/main.py")


class TestScopePrimitives:
    """list / delete / clear reuse the shared _device_scripts over the REPL."""

    def test_list_files_in_scope_parses_walk_output(self) -> None:
        board = ReplBoard(listing=("/code.py", "/lib/chumicro_demo/__init__.py"))
        transport = _connected(board)
        listed = transport.list_files_in_scope()
        assert listed == ["/code.py", "/lib/chumicro_demo/__init__.py"]

    def test_list_files_clean_slate_filters_keep_set(self) -> None:
        board = ReplBoard(
            listing=("/code.py", "/boot.py", "/boot_out.txt", "/lib/x.py"),
        )
        transport = _connected(board)
        listed = transport.list_files_in_scope(clean_slate=True)
        # boot.py / boot_out.txt are in DEVICE_KEEP_SET and drop out.
        assert "/boot.py" not in listed
        assert "/boot_out.txt" not in listed
        assert "/code.py" in listed
        assert "/lib/x.py" in listed

    def test_delete_files_sends_delete_script(self) -> None:
        board = ReplBoard()
        transport = _connected(board)
        transport.delete_files(["/lib/stale.py"])
        assert "/lib/stale.py" in _write_stream(board)

    def test_delete_files_empty_is_noop(self) -> None:
        board = ReplBoard()
        transport = _connected(board)
        before = len(board.writes)
        transport.delete_files([])
        assert len(board.writes) == before

    def test_clear_entrypoints_sends_clear_script(self) -> None:
        board = ReplBoard()
        transport = _connected(board)
        transport.clear_entrypoints()
        stream = _write_stream(board)
        assert "os.remove(_p)" in stream


class TestWipe:
    """wipe_filesystem erases and reconnects over serial (no FAT wait)."""

    def test_wipe_erases_and_reconnects(self) -> None:
        board = ReplBoard()
        transport = _connected(board)
        opens_before = board.open_count
        transport.wipe_filesystem()
        stream = _write_stream(board)
        assert "storage.erase_filesystem()" in stream
        # Reconnected: the factory was invoked again after the erase.
        assert board.open_count == opens_before + 1
        assert transport._port is not None


class TestNotConnectedGuards:
    """Every device op guards a closed port instead of crashing."""

    def _unconnected(self) -> CircuitpythonSerialTransport:
        return CircuitpythonSerialTransport(
            "/dev/null", serial_port_factory=ReplBoard(), time=FakeTime(),
        )

    def test_deploy_files_requires_connect(self) -> None:
        with pytest.raises(CircuitpythonTransportError, match="connect"):
            self._unconnected().deploy_files({"/code.py": b"x\n"}, "/code.py")

    def test_wipe_requires_connect(self) -> None:
        with pytest.raises(CircuitpythonTransportError, match="connect"):
            self._unconnected().wipe_filesystem()

    def test_list_files_without_connect_returns_empty(self) -> None:
        assert self._unconnected().list_files_in_scope() == []

    def test_clear_entrypoints_without_connect_is_noop(self) -> None:
        self._unconnected().clear_entrypoints()  # must not raise

    def test_delete_files_without_connect_is_noop(self) -> None:
        self._unconnected().delete_files(["/x"])  # must not raise


class TestBestEffortErrorPaths:
    """Best-effort ops swallow a raw-REPL failure rather than abort the deploy."""

    def _silent(self) -> CircuitpythonSerialTransport:
        transport = CircuitpythonSerialTransport(
            "/dev/cu.fake", serial_port_factory=SilentBoard(), time=FakeTime(),
        )
        transport.connect()
        return transport

    def test_list_swallows_repl_failure(self) -> None:
        assert self._silent().list_files_in_scope() == []

    def test_delete_swallows_repl_failure(self) -> None:
        self._silent().delete_files(["/lib/x.py"])  # must not raise

    def test_clean_slate_swallows_repl_failure(self) -> None:
        self._silent()._clean_slate_device()  # must not raise

    def test_settings_notice_swallows_repl_failure(self) -> None:
        self._silent()._notice_settings_toml_eviction_device()  # must not raise

    def test_wipe_tolerates_erase_repl_teardown(self) -> None:
        # erase_filesystem() send raises (silent board), which is expected
        # as the reset tears the REPL down; wipe then reconnects.
        transport = self._silent()
        transport.wipe_filesystem()
        assert transport._port is not None


class TestSafeModeParsing:
    """Safe-mode marker is found even amid surrounding console noise."""

    def test_marker_line_found_after_noise(self) -> None:
        board = ReplBoard(safe_reason="supervisor.SafeModeReason.WATCHDOG")
        # Prepend a non-marker line so the parse loop skips before matching.
        original = board._response_for

        def noisy(submission: bytes) -> bytes:
            base = original(submission)
            if _SAFE_MODE_MARKER.encode() in base:
                return b"boot noise line\n" + base
            return base

        board._response_for = noisy  # type: ignore[method-assign]
        transport = _connected(board)
        with pytest.raises(CircuitpythonTransportError, match="WATCHDOG"):
            transport._raise_if_safe_mode()


class TestOscTolerance:
    """OSC-polluted reads still parse cleanly through the overrides."""

    def test_execute_survives_osc_noise(self) -> None:
        board = ReplBoard(wrap_osc=True)
        transport = _connected(board)
        # A settings probe returns "" stdout wrapped in OSC noise; the
        # override strips it, so the parse succeeds instead of raising on
        # a malformed frame.
        transport._notice_settings_toml_eviction_device()

    def test_deploy_output_strips_osc(self) -> None:
        board = ReplBoard(wrap_osc=True, code_output="CLEAN_MARKER\n")
        transport = _connected(board)
        output = transport.deploy_files({"/code.py": b"pass\n"}, "/code.py")
        assert output.strip() == "CLEAN_MARKER"
        assert "\x1b" not in output
