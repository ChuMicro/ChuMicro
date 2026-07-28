"""Execution backends for harness-shaped test files.

A :class:`Backend` is the pluggable bit that knows *how* to run a
single ``functional_tests/`` or ``tests/`` file: where to send the
source, what to spawn, what to read back.  The caller (the pytest
items in :mod:`chumicro_pytest_device.plugin`) owns everything that
isn't backend-specific: batch-result caching, harness output
parsing, ``pytest.fail`` orchestration, PR-summary collection.

Two backends are defined:

- :class:`DeviceBackend`: runs the file on a real board via the
  ``chumicro-deploy`` transport.  Owns connect, stage, soft-reset,
  recover semantics.  Lives in :mod:`chumicro_pytest_device.plugin`
  itself because it depends on private helpers there.
- :class:`UnixPortBackend`: runs the file in a MicroPython /
  CircuitPython unix-port subprocess.  No transport, no staging.
  Resolves the runtime binary and spawns
  ``<binary> support/test_harness/run_cross_runtime.py --worker``.
  Lives here because it depends on nothing in :mod:`plugin`.

Both raise :class:`BackendPrepareError` or :class:`BackendExecuteError`
on failure so the caller can route the message through ``pytest.fail``
uniformly.

Note on the ``TYPE_CHECKING`` import: backends call back into the
plugin module to read session-scoped helpers like the transport cache
and library/harness paths.  At runtime that's a normal import (the
plugin module is already loaded when items are running). At type-check
time we defer it so static analysis doesn't see the cycle.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from chumicro_workspace.device_orchestration import chunk_boundaries_for

if TYPE_CHECKING:
    from chumicro_deploy import DeviceEntry

    from chumicro_pytest_device.plugin import DeviceRuntimeItem


class BackendPrepareError(Exception):
    """Raised by ``Backend.prepare`` when setup fails.

    The caller turns this into a ``pytest.fail`` with the message
    preserved. The file-level batch result is cached as a failure so
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
                ``DeviceBackend`` the entry names a real board. For
                ``UnixPortBackend`` it is a synthetic entry whose
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

#: Wall-clock ceiling for one ``UnixPortBackend.execute`` subprocess, in
#: seconds.  A single test file that infinite-loops or blocks (a
#: ``socket.recv`` / ``select`` regression a fake would paper over) would
#: otherwise hang the whole lane with no per-file attribution, since
#: ``subprocess.run`` waits forever without a ``timeout``.  The slowest
#: in-tree unit file runs in well under a second under either unix-port
#: binary, so 120 s clears any real file by a wide margin while still
#: bounding a wedged one.  Override per run via ``--unix-port-timeout``.
_DEFAULT_EXECUTE_TIMEOUT_SECONDS = 120.0

#: Sentinel for --unix-port-heapsize: read budgets from
#: target-runtimes.toml [heap].  "0" / "off" disables the ceiling.
HEAPSIZE_FROM_CONFIG = "config"


def _load_heap_budgets(workspace_root: Path) -> dict:
    """Read the ``[heap]`` table from ``target-runtimes.toml``.

    Returns the raw table (per-runtime defaults + ``overrides``
    sub-table), or an empty dict when the file or table is absent.
    Absent means "no ceiling", preserving pre-budget behavior for
    workspaces that haven't declared one.
    """
    config_path = workspace_root / "target-runtimes.toml"
    if not config_path.is_file():
        return {}
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    heap = data.get("heap", {})
    return heap if isinstance(heap, dict) else {}


def _read_prepared_binary_marker(
    workspace_root: Path, runtime: str,
) -> str | None:
    """Read ``<workspace>/.tools/<runtime>.path`` if present.

    The firmware-preparation tooling that builds the unix-port binary
    writes the absolute path of the compiled binary to this marker so
    other commands can resolve it without recompiling.
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

    1. *override*: explicit path passed via ``--micropython-binary``
       or ``--circuitpython-binary``.  Returned as-is. Existence is
       checked at execute time.
    2. ``<workspace>/.tools/<runtime>.path`` marker written by the
       ``prepare-*`` tasks.
    3. ``shutil.which("micropython")`` / ``shutil.which("circuitpython")``:
       last-resort PATH lookup.

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

    No transport, no staging. The worker entry point in
    ``support/test_harness/run_cross_runtime.py`` sets ``sys.path``
    inside the spawned process so library sources resolve.  Each
    ``test_*.py`` file is one ``--worker`` subprocess so the heap
    starts clean per file, mirroring real-board behavior.

    Constructor args:
        workspace_root: Path to the mono-repo / workspace root.
        binaries: Optional ``{runtime: path}`` overrides from
            ``--micropython-binary`` / ``--circuitpython-binary``.
            ``None`` means "resolve via marker file / PATH at use time".
        execute_timeout_seconds: Per-file wall-clock ceiling for the
            worker subprocess.  A file that exceeds it is killed and
            surfaced as a :class:`BackendExecuteError` naming the file,
            so a single hanging test fails cleanly and the sweep
            continues.  Threaded in from ``--unix-port-timeout``.
    """

    def __init__(
        self,
        workspace_root: Path,
        binaries: dict[str, str | None] | None = None,
        execute_timeout_seconds: float = _DEFAULT_EXECUTE_TIMEOUT_SECONDS,
        heapsize: str = HEAPSIZE_FROM_CONFIG,
    ) -> None:
        self._workspace_root = workspace_root
        self._binary_overrides: dict[str, str | None] = binaries or {}
        self._resolved: dict[str, str] = {}
        self._execute_timeout_seconds = execute_timeout_seconds
        self._heapsize = heapsize
        self._heap_budgets: dict | None = None

    def _heap_budget(self, runtime: str, library_name: str | None) -> str | None:
        """Resolve the ``-X heapsize`` budget for one worker spawn.

        Precedence: the constructor / ``--unix-port-heapsize`` override
        ("0" or "off" disables the ceiling entirely), then the
        library's entry in ``target-runtimes.toml [heap.overrides]``,
        then the runtime's ``[heap]`` default.  ``None`` means spawn
        with the port's native multi-MB heap, the pre-budget behavior
        kept only for workspaces with no ``[heap]`` table.
        """
        if self._heapsize != HEAPSIZE_FROM_CONFIG:
            if self._heapsize in ("0", "off"):
                return None
            return self._heapsize
        if self._heap_budgets is None:
            self._heap_budgets = _load_heap_budgets(self._workspace_root)
        overrides = self._heap_budgets.get("overrides", {})
        if library_name and library_name in overrides:
            per_library = overrides[library_name]
            if isinstance(per_library, dict):
                budget = per_library.get(runtime)
                if budget is not None:
                    return str(budget)
            elif per_library is not None:
                return str(per_library)
        budget = self._heap_budgets.get(runtime)
        return None if budget is None else str(budget)

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

        The actual subprocess spawn happens in :meth:`execute`. ``prepare``
        just front-loads the failures that should fail the file fast
        without trying every test individually.
        """
        self._resolve(target.runtime)
        harness = self._harness_script()
        if not harness.exists():
            raise BackendPrepareError(
                f"Cross-runtime test harness not found at {harness}.  "
                f"The unix-port target requires the test harness's "
                f"worker script at support/test_harness/"
                f"run_cross_runtime.py, which is only present in development "
                f"checkouts of the chumicro libraries, not in installed "
                f"packages.",
            )

    def execute(
        self,
        item: DeviceRuntimeItem,
        target: DeviceEntry,
    ) -> str:
        """Spawn ``<binary> run_cross_runtime.py --worker <test_file>``.

        The worker entry point sets ``sys.path`` to include every
        ``libraries/*/src/`` + ``support/*/src/`` under the workspace
        and execs the file as a module.  Captures stdout. The
        harness prints ``PASS`` / ``FAIL`` / ``SKIP`` / ``HEAP`` /
        ``SUMMARY`` lines that :func:`parse_output` reads.

        On non-zero exit code we still return the captured output:
        a single test FAIL produces exit 1 but the per-test lines are
        what we want to report.  Only a fully empty output with a
        non-zero exit gets surfaced as :class:`BackendExecuteError`.

        A file that runs longer than ``execute_timeout_seconds`` is
        killed and surfaced as a :class:`BackendExecuteError` naming the
        file and the ceiling, so a hanging or infinite-looping test
        fails this one file cleanly instead of stalling the whole lane.
        """
        binary = self._resolve(target.runtime)
        harness = self._harness_script()
        command = [binary]
        budget = self._heap_budget(
            target.runtime, getattr(item, "library_name", None),
        )
        if budget is not None:
            # Board-shaped heap: an import chain or test workload that
            # cannot fit a real Pico W MemoryErrors HERE, in preflight,
            # instead of on first flash.
            command += ["-X", f"heapsize={budget}"]
        command += [
            str(harness),
            "--worker",
            str(item.test_file),
        ]
        boundaries = None
        if target.runtime == "micropython":
            # Chunked exec is the MicroPython fidelity shape (real MP
            # sweeps stage statement-chunked).  CircuitPython's
            # production default is flash mode, which execs whole
            # files, so CP runs whole-file, the faithful shape for
            # both runtimes.
            try:
                boundaries = chunk_boundaries_for(Path(item.test_file))
            except (OSError, SyntaxError):
                # Chunking is a fidelity optimization; a file the host
                # can't read or parse still runs whole-file so the
                # worker reports the real failure with its own
                # diagnostics.
                boundaries = None
        environment = None
        if boundaries:
            # Statement-chunked exec, same as real-board staging: the
            # whole-file compile transient of a large test module is a
            # host-lane artifact a chunk-staged board never pays.  The
            # CSV rides an env var because the MP unix port FATALs on
            # argv elements longer than a few hundred bytes.
            environment = dict(os.environ)
            environment["CHUMICRO_CHUNK_BOUNDARIES"] = ",".join(
                str(line_no) for line_no in boundaries
            )
        try:
            completed = subprocess.run(  # noqa: S603, args fully controlled
                command,
                cwd=self._workspace_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._execute_timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise BackendExecuteError(
                f"unix-port subprocess for {item.test_file} timed out "
                f"after {self._execute_timeout_seconds:g}s "
                f"({target.runtime}); the process was killed so a "
                f"hanging or infinite-looping test in this file fails "
                f"cleanly instead of stalling the lane.",
            ) from error
        except OSError as error:
            raise BackendExecuteError(
                f"unix-port subprocess failed to spawn "
                f"({target.runtime}): {error}",
            ) from error
        output = completed.stdout + completed.stderr
        if "MemoryError" in output and "SUMMARY " not in output:
            # The worker died on the board-shaped heap before the
            # harness could print its SUMMARY: this code would OOM a
            # real Pico W.  Name the budget so the failure reads as
            # policy, not mystery.
            budget = self._heap_budget(
                target.runtime, getattr(item, "library_name", None),
            )
            raise BackendExecuteError(
                f"unix-port worker for {item.test_file} hit MemoryError "
                f"under the board-shaped heap budget "
                f"({target.runtime} heapsize={budget}) before completing.  "
                f"An import chain or workload this size would OOM a "
                f"real Pico W.  Slim it, or raise the library's entry "
                f"in target-runtimes.toml [heap.overrides] with a "
                f"measured justification.\n\n{output}",
            )
        if not output.strip():
            raise BackendExecuteError(
                f"unix-port subprocess returned no output "
                f"(exit code {completed.returncode}, "
                f"runtime {target.runtime}).",
            )
        return output
