"""Execution backends for harness-shaped test files.

A :class:`Backend` is the pluggable bit that knows *how* to run a
single ``functional_tests/`` or ``tests/`` file: where to send the
source, what to spawn, what to read back.  The caller (the pytest
items in :mod:`chumicro_pytest_device.plugin`) owns everything that
isn't backend-specific — batch-result caching, harness output
parsing, ``pytest.fail`` orchestration, PR-summary collection.

Two backends are defined:

- :class:`DeviceBackend` — runs the file on a real board via the
  ``chumicro-deploy`` transport.  Owns connect, stage, soft-reset,
  recover semantics.  Lives in :mod:`chumicro_pytest_device.plugin`
  itself because it depends on private helpers there.
- :class:`UnixPortBackend` — runs the file in a MicroPython /
  CircuitPython unix-port subprocess.  No transport, no staging;
  resolves the runtime binary and spawns
  ``<binary> support/test_harness/run_cross_runtime.py --worker``.
  Lives here because it depends on nothing in :mod:`plugin`.

Both raise :class:`BackendPrepareError` or :class:`BackendExecuteError`
on failure so the caller can route the message through ``pytest.fail``
uniformly.

Note on the ``TYPE_CHECKING`` import: backends call back into the
plugin module to read session-scoped helpers like the transport cache
and library/harness paths.  At runtime that's a normal import (the
plugin module is already loaded when items are running); at type-check
time we defer it so static analysis doesn't see the cycle.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from chumicro_deploy import DeviceEntry
    from chumicro_pytest_device.plugin import DeviceRuntimeItem


class BackendPrepareError(Exception):
    """Raised by ``Backend.prepare`` when setup fails.

    The caller turns this into a ``pytest.fail`` with the message
    preserved; the file-level batch result is cached as a failure so
    every per-test item from that file also fails fast.
    """


class BackendExecuteError(Exception):
    """Raised by ``Backend.execute`` when running the test batch fails.

    Backends handle their own best-effort recovery (transport recover,
    process cleanup) *before* raising so the next file can run
    independently of this failure.
    """


@runtime_checkable
class Backend(Protocol):
    """Pluggable execution backend protocol."""

    name: str
    """Short backend identifier — ``"device"`` or ``"unix-port"``."""

    def prepare(
        self,
        item: DeviceRuntimeItem,
        target: DeviceEntry,
    ) -> None:
        """Set up whatever the backend needs before executing tests.

        Args:
            item: The pytest item being prepared (gives access to
                ``test_file``, ``library_dir``, ``session``).
            target: The selected device entry for this item.  For
                ``DeviceBackend`` this is a real board; for
                ``UnixPortBackend`` it's a synthetic entry whose
                ``runtime`` field picks the binary.

        Raises:
            BackendPrepareError: On any setup failure.
        """

    def execute(
        self,
        item: DeviceRuntimeItem,
        target: DeviceEntry,
    ) -> str:
        """Run every ``test_*`` in ``item.test_file`` once.

        Args:
            item: As in :meth:`prepare`.
            target: As in :meth:`prepare`.

        Returns:
            Raw stdout from the harness, ready for
            :func:`chumicro_pytest_device.result_parser.parse_output`.

        Raises:
            BackendExecuteError: On any execution failure, after the
                backend's own recovery has run.
        """


_HARNESS_SCRIPT_RELATIVE = "support/test_harness/run_cross_runtime.py"
_TOOLS_DIR_NAME = ".tools"


def _read_prepared_binary_marker(
    workspace_root: Path, runtime: str,
) -> str | None:
    """Read ``<workspace>/.tools/<runtime>.path`` if present.

    The ``prepare-micropython`` / ``prepare-circuitpython`` scripts
    write the absolute path of the compiled unix-port binary to this
    marker so other commands can resolve it without recompiling.
    """
    marker = workspace_root / _TOOLS_DIR_NAME / f"{runtime}.path"
    if not marker.exists():
        return None
    candidate = Path(marker.read_text().strip())
    if not candidate.exists():
        return None
    return str(candidate)


def resolve_unix_port_binary(
    workspace_root: Path, runtime: str, override: str | None,
) -> str | None:
    """Resolve the unix-port binary for *runtime*, or ``None``.

    Resolution order (first match wins):

    1. *override* — explicit path passed via ``--micropython-binary``
       or ``--circuitpython-binary``.  Returned as-is; existence is
       checked at execute time.
    2. ``<workspace>/.tools/<runtime>.path`` marker written by the
       ``prepare-*`` tasks.
    3. ``shutil.which("micropython")`` / ``shutil.which("circuitpython")``
       — last-resort PATH lookup.

    Args:
        workspace_root: Workspace root (``session.config.rootpath``).
        runtime: ``"micropython"`` or ``"circuitpython"``.
        override: Explicit binary path, or ``None``.
    """
    if override:
        return override
    prepared = _read_prepared_binary_marker(workspace_root, runtime)
    if prepared:
        return prepared
    return shutil.which(runtime)


class UnixPortBackend:
    """Backend that runs tests in a MicroPython / CircuitPython unix-port subprocess.

    No transport, no staging — the worker entry point in
    ``support/test_harness/run_cross_runtime.py`` sets ``sys.path``
    inside the spawned process so library sources resolve.  Each
    ``test_*.py`` file is one ``--worker`` subprocess so the heap
    starts clean per file, mirroring real-board behaviour.

    Constructor args:
        workspace_root: Path to the mono-repo / workspace root.
        binaries: Optional ``{runtime: path}`` overrides from
            ``--micropython-binary`` / ``--circuitpython-binary``.
            ``None`` means "resolve via marker file / PATH at use time".
    """

    name = "unix-port"

    def __init__(
        self,
        workspace_root: Path,
        binaries: dict[str, str | None] | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._binary_overrides: dict[str, str | None] = binaries or {}
        self._resolved: dict[str, str] = {}

    def _resolve(self, runtime: str) -> str:
        cached = self._resolved.get(runtime)
        if cached is not None:
            return cached
        override = self._binary_overrides.get(runtime)
        resolved = resolve_unix_port_binary(
            self._workspace_root, runtime, override,
        )
        if not resolved:
            raise BackendPrepareError(
                f"{runtime} unix-port binary not found.  Pass "
                f"--{runtime}-binary <path>, run the prepare-{runtime} "
                f"task, or install the binary on PATH.",
            )
        if not Path(resolved).exists():
            raise BackendPrepareError(
                f"{runtime} unix-port binary path does not exist: "
                f"{resolved}",
            )
        self._resolved[runtime] = resolved
        return resolved

    def _harness_script(self) -> Path:
        return self._workspace_root / _HARNESS_SCRIPT_RELATIVE

    def prepare(
        self,
        item: DeviceRuntimeItem,
        target: DeviceEntry,
    ) -> None:
        """Resolve the runtime binary and verify the harness script exists.

        The actual subprocess spawn happens in :meth:`execute`; prepare
        just front-loads the failures that should fail the file fast
        without trying every test individually.
        """
        self._resolve(target.runtime)
        harness = self._harness_script()
        if not harness.exists():
            raise BackendPrepareError(
                f"Cross-runtime test harness not found at {harness}.  "
                f"The unix-port target requires "
                f"support/test_harness/run_cross_runtime.py — this is a "
                f"chumicro mono-repo internal path.",
            )

    def execute(
        self,
        item: DeviceRuntimeItem,
        target: DeviceEntry,
    ) -> str:
        """Spawn ``<binary> run_cross_runtime.py --worker <test_file>``.

        The worker entry point sets ``sys.path`` to include every
        ``libraries/*/src/`` + ``support/*/src/`` under the workspace
        and execs the file as a module.  Captures stdout — the
        harness prints ``PASS`` / ``FAIL`` / ``SKIP`` / ``HEAP`` /
        ``SUMMARY`` lines that :func:`parse_output` reads.

        On non-zero exit code we still return the captured output —
        a single test FAIL produces exit 1 but the per-test lines are
        what we want to report.  Only a fully empty output with a
        non-zero exit gets surfaced as :class:`BackendExecuteError`.
        """
        binary = self._resolve(target.runtime)
        harness = self._harness_script()
        command = [
            binary,
            str(harness),
            "--worker",
            str(item.test_file),
        ]
        try:
            completed = subprocess.run(  # noqa: S603 — args fully controlled
                command,
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise BackendExecuteError(
                f"unix-port subprocess failed to spawn "
                f"({target.runtime}): {error}",
            ) from error
        output = completed.stdout + completed.stderr
        if not output.strip():
            raise BackendExecuteError(
                f"unix-port subprocess returned no output "
                f"(exit code {completed.returncode}, "
                f"runtime {target.runtime}).",
            )
        return output
