"""Test fakes for the device transport layer.

Exports :class:`FakeTransport`, :class:`FakeSerialPort`,
:class:`FakeTime`, and :func:`isolate_from_host_filesystem`.  See
each one's docstring for shape and usage.  Typical injection::

    from chumicro_deploy.testing import FakeSerialPort, FakeTime

    transport = CircuitpythonTransport(
        address="/dev/cu.fake",
        port_factory=lambda *_args, **_kwargs: FakeSerialPort(...),
        time=FakeTime(),
    )
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .protocol import DeviceImplementation

if TYPE_CHECKING:
    import pytest

__all__ = [
    "FakeSerialPort",
    "FakeTime",
    "FakeTransport",
    "isolate_from_host_filesystem",
]


def isolate_from_host_filesystem(
    monkeypatch: pytest.MonkeyPatch,
    *,
    circuitpy_drives: list[Path] | None = None,
) -> None:
    """Sever ``flash_drive``'s links to the real macOS host filesystem.

    Two cleanups in one, both load-bearing for hermetic tests:

    1. **macOS shell helpers → instant fakes.**  ``flash_drive`` calls
       ``subprocess.run(["sync"])`` / ``["xattr", ...]`` / ``["dot_clean",
       ...]`` / ``["mdutil", ...]`` on macOS.  Each blocks for seconds
       on a busy host (concurrent test workers, IDE indexing, git
       activity).  Real ``rsync`` is left intact, because tests rely
       on its file-copy side effect.
    2. **CIRCUITPY drive scanning → controllable.**  Production calls
       :func:`chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates`
       to find ``/Volumes/CIRCUITPY*`` mounts.  On a dev box with a real
       board plugged in, an unstubbed test will write+unlink probe files
       onto the real device's filesystem.  Pass *circuitpy_drives* to
       point at a test-controlled directory; pass ``None`` (default)
       to make scans return empty so tests don't depend on host state.

    Per-test monkeypatches override these.  Calling
    ``monkeypatch.setattr("chumicro_deploy.circuitpy_drive
    ._circuitpy_volume_candidates", ...)`` again later in the same test
    replaces the stub for that test only.

    Typical usage as a module-level autouse fixture::

        @pytest.fixture(autouse=True)
        def _isolate(monkeypatch):
            isolate_from_host_filesystem(monkeypatch)
    """
    import subprocess as _subprocess

    real_run = _subprocess.run
    skip = {"sync", "xattr", "dot_clean", "mdutil"}
    ok_result = _subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"", stderr=b"",
    )

    def fake_run(command, **kwargs):
        if command and str(command[0]) in skip:
            return ok_result
        return real_run(command, **kwargs)

    monkeypatch.setattr(
        "chumicro_deploy.flash_drive.subprocess.run", fake_run,
    )
    drives = list(circuitpy_drives) if circuitpy_drives is not None else []
    monkeypatch.setattr(
        "chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates",
        lambda: drives,
    )


class FakeTime:
    """Deterministic seconds-domain time source for host-side tests.

    Bundles ``monotonic()`` and ``sleep()`` into a single injectable
    object that satisfies :class:`chumicro_deploy.protocol.TimeSource`
    (both device transports take one).  ``monotonic()``
    is **stable**: repeated calls return the same value until the
    clock is explicitly advanced.  ``sleep(duration)`` auto-advances
    the clock by *duration* without any real wait, so production
    code that sleeps still moves the fake clock forward.
    ``advance(seconds)`` moves the clock forward explicitly, for
    scenarios where production does not sleep but the test needs to
    simulate elapsed time (e.g., timeout expiry).

    Example::

        fake = FakeTime()
        assert fake.monotonic() == 0.0

        fake.sleep(1.5)
        assert fake.monotonic() == 1.5

        fake.advance(0.5)
        assert fake.monotonic() == 2.0
    """

    __slots__ = ("_current",)

    def __init__(self, start: float = 0.0) -> None:
        """Create a fake time source starting at *start* seconds.

        Args:
            start: Initial monotonic value in seconds.
        """
        self._current = start

    def monotonic(self) -> float:
        """Return the current fake time in seconds."""
        return self._current

    def sleep(self, duration: float) -> None:
        """Advance the clock by *duration* seconds (no wall-clock wait)."""
        self._current += duration

    def advance(self, seconds: float) -> None:
        """Move the clock forward by *seconds*."""
        self._current += seconds


class FakeSerialPort:
    """Simulates a pyserial Serial port for transport testing.

    Records all writes and returns canned responses for reads.
    Each entry in ``read_responses`` is either ``bytes`` (returned
    verbatim on the matching ``read()`` call) or an instance of
    ``BaseException`` (raised on that call).  The exception form
    scripts "first read returns bytes, second read drops the cable"
    scenarios without subclassing the fake.

    Instances are callable and return themselves, so a
    ``FakeSerialPort`` instance can be passed directly as a transport's
    ``serial_port_factory`` kwarg with no wrapper closure needed.  Pass
    *open_error* to script "factory raises when the transport asks for
    a port" without writing a custom closure.
    """

    def __init__(
        self,
        *,
        read_responses: list[bytes | BaseException] | None = None,
        open_error: Exception | None = None,
        raise_on_write: BaseException | None = None,
    ) -> None:
        self.writes: list[bytes] = []
        self.closed = False
        self._read_responses: list[bytes | BaseException] = list(
            read_responses or [],
        )
        self._read_index = 0
        self._open_error = open_error
        self._raise_on_write = raise_on_write

    def __call__(self, *_args: object, **_kwargs: object) -> FakeSerialPort:
        """Return this port, or raise the scripted *open_error*.

        Lets the instance double as a ``serial_port_factory`` callable.
        Accepts both positional and keyword args (different transports
        call factories with different signatures); all are ignored.
        Use an explicit closure when factory-arg assertions are needed.
        """
        if self._open_error is not None:
            raise self._open_error
        return self

    @property
    def in_waiting(self) -> int:
        """Return how many bytes are available to read.

        Scripted ``BaseException`` entries are reported as having
        ``in_waiting == 1`` so polling loops actually call
        :meth:`read` (which then raises) instead of looping past
        the scripted disconnect.
        """
        if self._read_index < len(self._read_responses):
            entry = self._read_responses[self._read_index]
            if isinstance(entry, BaseException):
                return 1
            return len(entry)
        return 0

    def read(self, size: int = 1) -> bytes:
        """Return the next canned response, or raise the scripted exception."""
        if self._read_index < len(self._read_responses):
            entry = self._read_responses[self._read_index]
            self._read_index += 1
            if isinstance(entry, BaseException):
                raise entry
            return entry
        return b""

    def write(self, data: bytes) -> int:
        """Record a write, or raise the configured exception."""
        if self._raise_on_write is not None:
            raise self._raise_on_write
        self.writes.append(data)
        return len(data)

    def close(self) -> None:
        """Mark the port as closed."""
        self.closed = True

    def reset_input_buffer(self) -> None:
        """No-op for fake."""


@dataclass
class FakeTransport:
    """In-memory fake that records transport calls and returns canned output.

    Satisfies both :class:`TransportProtocol` and
    :class:`ExtendedTransportProtocol`, so the same fake stands in
    for either a MicroPython or CircuitPython transport.  The
    chunked-execute helpers fall back to :meth:`execute` when no
    chunked-specific behavior is configured.
    """

    #: Fallback string returned by ``execute()`` when :attr:`outputs`
    #: is empty.
    execute_output: str = ""
    #: Per-call output queue.  ``execute()`` and ``execute_scripts()``
    #: pop the head and return it; an empty list falls back to
    #: :attr:`execute_output`.  Scripts "first invocation returns X,
    #: second returns Y" without subclassing the fake.
    outputs: list[str] = field(default_factory=list)
    #: Deploy mode label (``"ram"``, ``"flash"``, ``"mount"``, ``"copy"``).
    mode: str = "ram"
    #: Default ~64 KB, a realistic floor for the boards this fake stands in for.
    free_memory_bytes: int = 64 * 1024
    #: Canned return value for ``probe_implementation``.  ``None``
    #: simulates a probe that couldn't complete.
    probe_result: DeviceImplementation | None = None
    #: Module sources returned by ``staged_sources``.  Defaults to an
    #: empty list (non-``None``) so the CP RAM bootstrap path's
    #: "stage() must be called first" assertion passes when sources
    #: are not injected explicitly.
    staged_sources: list[tuple[str, str]] = field(default_factory=list)
    #: Canned return value for :meth:`reset_into_bootloader`.  ``True``
    #: simulates a successful dispatch; ``False`` simulates the
    #: dispatch failing.
    bootloader_reset_result: bool = True
    #: When set, ``connect()`` records the call then raises this
    #: exception.  Failure-injection hook for the connect path.
    connect_raises: BaseException | None = None
    #: When set, ``execute()`` and ``execute_scripts()`` record the
    #: call then raise this exception.
    execute_raises: BaseException | None = None
    #: When set, ``recover()`` records the call then raises this
    #: exception.  Failure-injection hook for the recover path.
    recover_raises: BaseException | None = None
    #: Simulated on-device file state for the diff-deploy primitives
    #: (`list_files_in_scope` / `delete_files`).  Pre-populate to
    #: control what the deploy routine considers "stale".  Keys use
    #: the leading-slash device-path form :meth:`deploy_files` accepts.
    device_files: dict[str, bytes] = field(default_factory=dict)
    #: Files staged via the ``extra_files`` keyword on :meth:`stage`.
    #: Keys are the device paths (``"/runtime_config.msgpack"``);
    #: values are the bytes the caller asked to land at that path.
    #: In RAM mode (``mode == "ram"``) a non-empty ``extra_files``
    #: argument raises :class:`UnsupportedExtraFilesError` and this
    #: dict stays empty.
    staged_extra_files: dict[str, bytes] = field(default_factory=dict)
    #: Ordered ``(method_name, args_tuple)`` log of every call.
    calls: list[tuple[str, tuple]] = field(default_factory=list)
    #: ``True`` after ``connect()`` and before any ``disconnect()``.
    connected: bool = False

    def connect(self) -> None:
        """Record a connect call; raise :attr:`connect_raises` if set."""
        self.calls.append(("connect", ()))
        if self.connect_raises is not None:
            raise self.connect_raises
        self.connected = True

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
        """Record a stage call.

        Args:
            source_dirs: Library source directories.
            test_files: Test file paths.
            harness_source: Harness source directory.
            extra_modules: Sibling Python files to register as
                importable on the device.
            extra_files: Non-Python files to land at named device paths
                (typically ``{"/runtime_config.msgpack": <bytes>}``).
                A non-empty dict in RAM mode raises
                :class:`UnsupportedExtraFilesError`.

        Raises:
            UnsupportedExtraFilesError: ``mode == "ram"`` and
                *extra_files* is non-empty.  RAM mode bypasses the
                device filesystem entirely, so there's nowhere to land
                bytes.  Switch the device's ``deploy_mode`` to
                ``"flash"`` before calling.
        """
        from .protocol import UnsupportedExtraFilesError  # noqa: PLC0415

        self.calls.append(
            (
                "stage",
                (
                    source_dirs, test_files, harness_source,
                    extra_modules, extra_files, include_test_support,
                ),
            ),
        )
        if extra_files:
            if self.mode == "ram":
                raise UnsupportedExtraFilesError(
                    "FakeTransport(mode='ram') cannot stage extra_files: "
                    "RAM mode has no writable device-side filesystem.  "
                    "Set mode='flash' before calling stage(extra_files=...).",
                )
            for device_path, content in extra_files.items():
                self.staged_extra_files[device_path] = content

    def execute(
        self,
        bootstrap_script: str,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Record an execute call and return canned output.

        Returns the head of :attr:`outputs` when non-empty (popped),
        otherwise :attr:`execute_output`.  Raises :attr:`execute_raises`
        after recording when set.

        When *on_line* is provided, dispatches one call per line of the
        returned string (split via :meth:`str.splitlines`) before
        returning, the same shape the real transports use, so a test can
        drive marker-style stdout coordination against the fake without
        wiring a real serial stream.
        """
        self.calls.append(("execute", (bootstrap_script,)))
        if self.execute_raises is not None:
            raise self.execute_raises
        if self.outputs:
            output = self.outputs.pop(0)
        else:
            output = self.execute_output
        if on_line is not None and output:
            for output_line in output.splitlines():
                on_line(output_line)
        return output

    def run_script(self, script: str, *, timeout: float = 10.0) -> str:
        """Record a run_script call and return canned output.

        Args:
            script: Self-contained Python source to run with no
                staging.
            timeout: Recorded with the call but not enforced, since the
                fake transport's "device" responds instantly.

        Returns:
            The configured ``execute_output`` (``run_script`` shares
            the same canned-response slot; tests that need separate
            run_script / execute outputs can override after
            construction).
        """
        self.calls.append(("run_script", (script, timeout)))
        return self.execute_output

    def execute_scripts(
        self,
        bootstrap_scripts: list[str],
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Record a chunked-execute call and return the configured output.

        Raises :attr:`execute_raises` after recording when set.

        When :attr:`outputs` is non-empty, pops a single head value and
        returns it, treating the whole chunked execute as one batched
        operation, with no synthetic per-script ``execute`` entries.
        Otherwise records synthetic per-script ``execute`` entries (one
        per chunk) and returns :attr:`execute_output`.

        *on_line* mirrors the real-transport pass-through: the batched
        head dispatches one call per line; the per-script branch threads
        the callback into each :meth:`execute` call.
        """
        self.calls.append(("execute_scripts", (list(bootstrap_scripts),)))
        if self.execute_raises is not None:
            raise self.execute_raises
        if self.outputs:
            output = self.outputs.pop(0)
            if on_line is not None and output:
                for output_line in output.splitlines():
                    on_line(output_line)
            return output
        last_output = self.execute_output
        for bootstrap_script in bootstrap_scripts:
            last_output = self.execute(bootstrap_script, on_line=on_line)
        return last_output

    def probe_free_memory(self) -> int:
        """Record a probe call and return the configured free-heap value."""
        self.calls.append(("probe_free_memory", ()))
        return self.free_memory_bytes

    def inline_script_budget_bytes(self) -> int:
        """Return half the configured free-memory budget."""
        self.calls.append(("inline_script_budget_bytes", ()))
        return max(8 * 1024, self.free_memory_bytes // 2)

    def probe_implementation(self) -> DeviceImplementation | None:
        """Record a probe call and return the canned result."""
        self.calls.append(("probe_implementation", ()))
        return self.probe_result

    def soft_reset(self) -> None:
        """Record a soft_reset call."""
        self.calls.append(("soft_reset", ()))

    def recover(self) -> None:
        """Record a recover call; raise :attr:`recover_raises` if set."""
        self.calls.append(("recover", ()))
        if self.recover_raises is not None:
            raise self.recover_raises

    def disconnect(self) -> None:
        """Record a disconnect call."""
        self.calls.append(("disconnect", ()))
        self.connected = False

    def reset_into_bootloader(self) -> bool:
        """Record the call and return the configured result.

        Defaults to ``True`` (pretending the dispatch succeeded) for
        the common branch; override via :attr:`bootloader_reset_result`
        to simulate the "runtime doesn't support bootloader entry"
        fallback.
        """
        self.calls.append(("reset_into_bootloader", ()))
        return self.bootloader_reset_result

    def deploy_files(
        self,
        files: dict[str, bytes],
        entrypoint: str,
        *,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        follow: str = "exec",
        clean: bool = False,
        tail_seconds: float | None = None,
    ) -> str:
        """Record a deploy_files call and return the configured output.

        Emits ``on_file_staged`` per file (sorted for deterministic
        order) and ``on_execute_line`` per line of ``execute_output``
        before returning.  The ``calls`` entry uses a dict-of-bytes +
        entrypoint + follow tuple so the payload, callback ordering,
        and follow mode are all observable.

        The ``follow`` kwarg accepts the same values as
        :class:`MicropythonTransport.deploy_files` (``"exec"`` or
        ``"soft_reboot"``).  The fake records it but doesn't
        otherwise change behavior.

        ``tail_seconds`` is recorded on :attr:`last_tail_seconds` so
        tests can assert the capture-window override.
        """
        self.calls.append(("deploy_files", (dict(files), entrypoint, follow)))
        # Record `clean` and `tail_seconds` so a test can assert the
        # kwargs the transport actually received.
        self.last_clean = clean  # type: ignore[attr-defined]
        self.last_tail_seconds = tail_seconds  # type: ignore[attr-defined]
        # Update simulated on-device state so a subsequent
        # `list_files_in_scope` reflects what was just shipped.
        for device_path, payload in files.items():
            self.device_files[device_path] = payload
        for device_path in sorted(files.keys()):
            if on_file_staged is not None:
                on_file_staged(device_path)
        if on_execute_line is not None and self.execute_output:
            for output_line in self.execute_output.splitlines():
                on_execute_line(output_line)
        return self.execute_output

    def list_files_in_scope(self, *, clean_slate: bool = False) -> list[str]:
        """Return on-device paths in scope, drawn from :attr:`device_files`.

        ``clean_slate=True`` widens to every device file except the
        closed keep set (:data:`flash_drive.DEVICE_KEEP_SET`).
        ``False`` keeps the :func:`is_in_deploy_scope` filter so the
        additive path leaves out-of-scope files alone.
        """
        from .flash_drive import DEVICE_KEEP_SET  # noqa: PLC0415 - avoid cycle
        from .protocol import is_in_deploy_scope  # noqa: PLC0415 - avoid cycle

        self.calls.append(("list_files_in_scope", (clean_slate,)))
        if clean_slate:
            keep = set(DEVICE_KEEP_SET)
            return [
                path for path in self.device_files
                if path.lstrip("/").split("/")[-1] not in keep
            ]
        return [path for path in self.device_files if is_in_deploy_scope(path)]

    def delete_files(self, paths: list[str]) -> None:
        """Remove *paths* from the simulated on-device state."""
        self.calls.append(("delete_files", (list(paths),)))
        for path in paths:
            self.device_files.pop(path, None)

    def clear_entrypoints(self) -> None:
        """Drop the simulated ``code.py`` / ``main.py`` entrypoints."""
        self.calls.append(("clear_entrypoints", ()))
        for entrypoint in ("code.py", "main.py", "/code.py", "/main.py"):
            self.device_files.pop(entrypoint, None)

    def wipe_filesystem(self) -> None:
        """Erase every simulated on-device file.

        In flash/copy mode the whole user filesystem (in-scope + out-
        of-scope alike) is gone after this returns.  In RAM/mount mode
        the call is a no-op, so both branches exercise against the
        same fake.
        """
        self.calls.append(("wipe_filesystem", ()))
        if self.mode in ("flash", "copy"):
            self.device_files.clear()
