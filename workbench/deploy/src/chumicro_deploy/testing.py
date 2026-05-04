"""Test fakes for the device transport layer.

Provides three fakes for host-side tests of ``chumicro-deploy``:

- :class:`FakeTransport` — a transport implementation that records
  all calls and returns configurable output.  Drop-in replacement for
  ``MicropythonTransport`` / ``CircuitpythonTransport`` in unit tests.
- :class:`FakeSerialPort` — simulates a ``serial.Serial`` instance
  without real hardware, for testing ``CircuitpythonTransport``
  internals.
- :class:`FakeTime` — deterministic seconds-domain time source that
  satisfies the ``TimeSource`` protocol the transport accepts via
  constructor injection, so tests never touch wall-clock time::

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

from .protocol import DeviceImplementation

__all__ = ["FakeSerialPort", "FakeTime", "FakeTransport"]


class FakeTime:
    """Deterministic seconds-domain time source for host-side tests.

    Bundles ``monotonic()`` and ``sleep()`` into a single injectable
    object that satisfies the ``TimeSource`` protocol used by
    :class:`~chumicro_deploy.CircuitpythonTransport`.  The clock is
    stable — ``monotonic()`` returns the same value until ``advance()``
    or ``sleep()`` is called — and ``sleep()`` does not actually wait,
    so tests run instantly regardless of production timeouts.

    Design decisions:

    - ``monotonic()`` is **stable**: repeated calls return the same
      value until the clock is explicitly advanced.
    - ``sleep(duration)`` auto-advances the clock by *duration*, so
      production code that sleeps moves the fake clock forward without
      any real wait.
    - ``advance(seconds)`` moves the clock forward explicitly, for
      scenarios where production does not sleep but the test needs to
      simulate elapsed time (e.g., timeout expiry).

    This mirrors the semantics of Kotlin's ``TestCoroutineScheduler``:
    time only moves when the test (or a sleep call) says it does.

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
        """Return the current fake time in seconds.

        The value is stable — calling ``monotonic()`` repeatedly
        returns the same value until ``advance()`` or ``sleep()``
        is called.
        """
        return self._current

    def sleep(self, duration: float) -> None:
        """Advance the clock by *duration* seconds (no wall-clock wait).

        Args:
            duration: Seconds to advance.
        """
        self._current += duration

    def advance(self, seconds: float) -> None:
        """Move the clock forward by *seconds*.

        Use this when production does not sleep but the test needs to
        simulate elapsed time — for example, pushing past a timeout
        deadline.

        Args:
            seconds: Seconds to advance.
        """
        self._current += seconds


class FakeSerialPort:
    """Simulates a pyserial Serial port for transport testing.

    Records all writes and returns canned responses for reads.
    Each entry in ``read_responses`` is either ``bytes`` (returned
    verbatim on the matching ``read()`` call) or an instance of
    ``BaseException`` (raised on that call) — the exception form
    lets tests script "first read returns bytes, second read drops
    the cable" scenarios without subclassing the fake.  Mirrors the
    pattern in :class:`chumicro_repl.testing.FakeSerialPort`.
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

    Implements both :class:`TransportProtocol` and the
    :class:`ExtendedTransportProtocol` (CircuitPython chunked-execution
    helpers) so tests for either path can use a single fake.  The
    chunked methods default to delegating to ``execute`` so callers
    that don't care about the chunked behavior get sensible defaults.

    Attributes:
        execute_output: The string returned by ``execute()``.
        mode: Deploy mode label (e.g. ``"ram"``, ``"flash"``, ``"mount"``,
            ``"copy"``).  Defaults to ``"ram"``.
        free_memory_bytes: The value returned by ``probe_free_memory()``
            and the basis for ``inline_script_budget_bytes()``.
        calls: List of ``(method_name, args_tuple)`` recording every call.
        connected: Whether ``connect()`` has been called without a
            subsequent ``disconnect()``.
    """

    execute_output: str = ""
    mode: str = "ram"
    #: Default ~64 KB matches the real CP transport's lower bound.
    free_memory_bytes: int = 64 * 1024
    #: Canned return value for ``probe_implementation``.  ``None``
    #: simulates a probe that couldn't complete.
    probe_result: DeviceImplementation | None = None
    #: Module sources to return from ``staged_sources``; matches the
    #: ``ExtendedTransportProtocol`` shape used by the RAM-mode path.
    staged_sources: list[tuple[str, str]] | None = None
    #: Canned return value for :meth:`reset_into_bootloader`.  ``True``
    #: simulates a successful dispatch; ``False`` exercises the
    #: flasher's interactive-manual-entry fallback path.
    bootloader_reset_result: bool = True
    #: Simulated on-device file state for the diff-deploy primitives
    #: (`list_files_in_scope` / `delete_files`).  Tests pre-populate this
    #: to assert what the deploy routine considers "stale" + verify
    #: deletion.  Mirrors the leading-slash device-path form
    #: :meth:`deploy_files` accepts.  See ``plans/next-up.md`` "Replace
    #: multi-project staging with scoped diff-deploy".
    device_files: dict[str, bytes] = field(default_factory=dict)
    #: Files staged via the ``extra_files`` keyword on :meth:`stage`.
    #: Keys are the device paths (``"/runtime_config.msgpack"``);
    #: values are the bytes the caller asked to land at that path.
    #: Tests assert on this dict to verify pytest-device's binary
    #: staging hook (Decision 0056).  In RAM mode (``mode == "ram"``)
    #: a non-empty ``extra_files`` argument raises
    #: :class:`UnsupportedExtraFilesError` and this dict stays empty.
    staged_extra_files: dict[str, bytes] = field(default_factory=dict)
    calls: list[tuple[str, tuple]] = field(default_factory=list)
    connected: bool = False

    def connect(self) -> None:
        """Record a connect call."""
        self.calls.append(("connect", ()))
        self.connected = True

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
        extra_files: dict[str, bytes] | None = None,
    ) -> None:
        """Record a stage call.

        Args:
            source_dirs: Library source directories.
            test_files: Test file paths.
            harness_source: Harness source directory.
            extra_modules: Sibling Python files (e.g. ``_test_creds.py``)
                to register as importable on the device.
            extra_files: Non-Python files to land at named device paths
                (typically ``{"/runtime_config.msgpack": <bytes>}`` so
                test code can call ``chumicro_config.load_runtime_config()``
                without committing a credentials shim — Decision 0056).
                A non-empty dict in RAM mode raises
                :class:`UnsupportedExtraFilesError`.

        Raises:
            UnsupportedExtraFilesError: ``mode == "ram"`` and
                *extra_files* is non-empty.  RAM mode bypasses the
                device filesystem entirely — there's nowhere to land
                bytes.  Caller should switch the device's
                ``deploy_mode`` to ``"flash"`` before calling.
        """
        from .protocol import UnsupportedExtraFilesError  # noqa: PLC0415

        self.calls.append(
            (
                "stage",
                (source_dirs, test_files, harness_source, extra_modules, extra_files),
            ),
        )
        if extra_files:
            if self.mode == "ram":
                raise UnsupportedExtraFilesError(
                    "FakeTransport(mode='ram') cannot stage extra_files — "
                    "RAM mode has no writable device-side filesystem.  "
                    "Set mode='flash' before calling stage(extra_files=...).",
                )
            for device_path, content in extra_files.items():
                self.staged_extra_files[device_path] = content

    def execute(self, bootstrap_script: str) -> str:
        """Record an execute call and return canned output.

        Args:
            bootstrap_script: The bootstrap code string.

        Returns:
            The configured ``execute_output``.
        """
        self.calls.append(("execute", (bootstrap_script,)))
        return self.execute_output

    def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
        """Record a chunked-execute call and return the configured output.

        Mirrors :meth:`CircuitpythonTransport.execute_scripts`.  Records
        the full list of scripts as one call, then synthetic per-script
        ``execute`` entries so existing tests that count ``execute``
        invocations still work.
        """
        self.calls.append(("execute_scripts", (list(bootstrap_scripts),)))
        last_output = self.execute_output
        for bootstrap_script in bootstrap_scripts:
            last_output = self.execute(bootstrap_script)
        return last_output

    def probe_free_memory(self) -> int:
        """Record a probe call and return the configured free-heap value."""
        self.calls.append(("probe_free_memory", ()))
        return self.free_memory_bytes

    def inline_script_budget_bytes(self) -> int:
        """Return half the configured free-memory budget (matches CP heuristic)."""
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
        """Record a recover call (post-failure recovery hook)."""
        self.calls.append(("recover", ()))

    def disconnect(self) -> None:
        """Record a disconnect call."""
        self.calls.append(("disconnect", ()))
        self.connected = False

    def reset_into_bootloader(self) -> bool:
        """Record the call and return the configured result.

        Defaults to ``True`` (pretending the dispatch succeeded) so
        tests that don't care about the branch get sensible
        behavior; override via :attr:`bootloader_reset_result` when
        exercising the "runtime doesn't support bootloader entry"
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
    ) -> str:
        """Record a deploy_files call and return the configured output.

        Emits ``on_file_staged`` per file (sorted to keep tests
        deterministic) and ``on_execute_line`` per line of
        ``execute_output`` before returning.  The ``calls`` entry uses
        a dict-of-bytes + entrypoint tuple so tests can assert on both
        the payload and the callback ordering.
        """
        self.calls.append(("deploy_files", (dict(files), entrypoint)))
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

    def list_files_in_scope(self) -> list[str]:
        """Return on-device paths in scope (mirrors `device_files`).

        Filters :attr:`device_files` to those paths that
        :func:`is_in_deploy_scope` accepts so a test can pre-populate
        a mix of in-scope and out-of-scope files and verify the
        diff-routine ignores the latter.
        """
        from .protocol import is_in_deploy_scope  # noqa: PLC0415 — avoid cycle

        self.calls.append(("list_files_in_scope", ()))
        return [path for path in self.device_files if is_in_deploy_scope(path)]

    def delete_files(self, paths: list[str]) -> None:
        """Remove *paths* from the simulated on-device state."""
        self.calls.append(("delete_files", (list(paths),)))
        for path in paths:
            self.device_files.pop(path, None)

    def wipe_filesystem(self) -> None:
        """Erase every simulated on-device file.

        Mirrors the real-transport contract: in flash/copy mode the
        whole user filesystem (in-scope + out-of-scope alike) is gone
        after this returns.  In RAM/mount mode the call is a no-op so
        tests for the ``deploy --wipe`` plumbing exercise both
        branches against the same fake.
        """
        self.calls.append(("wipe_filesystem", ()))
        if self.mode in ("flash", "copy"):
            self.device_files.clear()
