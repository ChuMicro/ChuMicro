"""Shared infrastructure helpers — subprocess wrappers, package installation,
runtime preparation, and binary resolution.

This module provides:

- Generic subprocess helpers: :func:`run_command`, :func:`install_command`
- Editable-install logic: :func:`install_editable`
- Build utilities shared by the MicroPython and CircuitPython preparation
  modules: :func:`run_build_command`, :func:`ensure_tool`, :func:`ensure_source_tree`, etc.
- Binary resolution: :func:`resolve_micropython_binary`,
  :func:`resolve_circuitpython_binary`, :func:`resolve_cp_mpy_cross`,
  :func:`resolve_mp_mpy_cross`
"""

from __future__ import annotations

import dataclasses
import functools
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from workspace import (
    ROOT,
    TOOLS,
    find_publishable_packages,
    find_support_packages,
    read_runtime_versions,
)

# ---------------------------------------------------------------------------
# Generic subprocess helpers
# ---------------------------------------------------------------------------

#: Path to the ``scripts/templates/`` directory containing ``.template`` files.
TEMPLATES_DIR = Path(__file__).parent / "templates"


def load_template(filename: str) -> str:
    """Read a template file from the ``scripts/templates/`` directory.

    Args:
        filename: Template filename (e.g. ``"pyproject.toml.template"``).
    """
    return (TEMPLATES_DIR / filename).read_text()


def run_command(command: list[str], environment: dict[str, str] | None = None) -> int:
    """Run a command from the repository root and return its exit code.

    Args:
        command: Command and arguments to run.
        environment: Optional environment variables to pass to the subprocess.

    Returns:
        Process exit code.
    """
    printable = " ".join(command)
    print(f"+ {printable}")
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


def install_command(python: str | Path | None = None) -> list[str]:
    """Return the pip-install command prefix, preferring uv when available.

    Args:
        python: Interpreter to target.  When *None*, targets the running
            interpreter.  With ``uv`` this becomes ``--python <path>``;
            without ``uv`` it replaces ``sys.executable``.
    """
    if shutil.which("uv"):
        command = ["uv", "pip", "install"]
        if python is not None:
            command.extend(["--python", str(python)])
        return command
    interpreter = str(python) if python is not None else sys.executable
    return [interpreter, "-m", "pip", "install"]


def install_editable(python: str | Path | None = None) -> int:
    """Install all workspace packages as editable.

    Installs publishable libraries (under ``libraries/``) and support
    packages (under ``support/``) so that imports work in any tool
    (editors, debuggers, REPLs, scripts) without manual PYTHONPATH
    setup.  Changes to source files are reflected immediately — no
    reinstall needed.

    Args:
        python: Interpreter to install into.  Defaults to the running
            interpreter when *None*.

    Returns:
        Process exit code (0 on success).
    """
    packages = find_publishable_packages() + find_support_packages()
    if not packages:
        return 0

    editable_args: list[str] = []
    for package in packages:
        editable_args.extend(["-e", package])

    return run_command([*install_command(python), *editable_args])


#: Directory where the embedded-runtime type stubs live, outside the
#: interpreter's ``site-packages``.  ``circuitpython-stubs`` and
#: ``micropython-esp32-stubs`` ship bare ``time.pyi`` / ``gc.pyi`` /
#: ``sys.pyi`` files at the package root (they predate PEP 561's
#: ``<pkg>-stubs`` convention); dropping those into ``site-packages``
#: shadows the real stdlib stubs for every CPython script that pyright
#: analyzes.  Isolating them into ``typings/`` preserves embedded
#: autocomplete for library code (via the ``extraPaths`` exposed only
#: under ``libraries/`` and ``support/test_harness/`` in
#: ``pyrightconfig.json``) without polluting the workspace-wide
#: stdlib view.
TYPINGS_DIR = ROOT / "typings" / "embedded-stubs"


def install_workspace(python: Path | None = None) -> int:
    """Install the full ChuMicro workspace into *python*.

    This is the canonical "set up everything" routine that both
    ``run.py setup`` and ``prepare_workspace.py`` delegate to.  Steps:

    1. Install ``requirements-dev.txt`` into the interpreter.
    2. Install runtime-pinned type stubs (``circuitpython-stubs``,
       ``micropython-esp32-stubs``) into ``typings/embedded-stubs/``
       so they don't shadow stdlib stubs in ``site-packages``.
    3. Editable-install every publishable library and support package.
    4. Generate starter ``devices.yml`` / ``device-config.yml`` if they
       don't already exist.
    5. Regenerate IDE configs for PyCharm and VS Code.

    Each step short-circuits on a non-zero exit code.

    Args:
        python: Interpreter to install into.  Defaults to the running
            interpreter when *None*.

    Returns:
        Process exit code (0 on success).
    """
    versions = runtime_versions()
    cp_version = versions["circuitpython"]["version"]
    mp_version = versions["micropython"]["version"].lstrip("v")
    requirements_file = str(ROOT / "requirements-dev.txt")

    result = run_command([*install_command(python), "-U", "-r", requirements_file])
    if result != 0:
        return result

    # Install embedded-runtime stubs into an isolated typings directory so
    # their top-level ``.pyi`` files (``time.pyi``, ``gc.pyi``, ``sys.pyi``)
    # cannot shadow stdlib stubs for the CPython task-runner code.
    TYPINGS_DIR.mkdir(parents=True, exist_ok=True)
    stubs = [
        f"circuitpython-stubs=={cp_version}",
        f"micropython-esp32-stubs=={mp_version}.*",
    ]
    # Use pip directly (not uv) for --target; uv pip lacks a --target flag.
    interpreter = str(python) if python is not None else sys.executable
    result = run_command([
        interpreter, "-m", "pip", "install",
        "--target", str(TYPINGS_DIR),
        "--upgrade",
        *stubs,
    ])
    if result != 0:
        return result

    result = install_editable(python=python)
    if result != 0:
        return result

    # Clean up stubs previously installed into site-packages by older
    # versions of this routine.  Keeps the interpreter's view of
    # ``time``, ``gc``, ``sys`` tied to typeshed / stdlib.
    _clean_stub_leftovers_from_site_packages(python)

    # Prune top-level stub files that shadow stdlib module names so
    # PyCharm (which lacks pyright's per-path ``executionEnvironments``)
    # can't resolve ``time``, ``gc``, ``sys`` etc. against the embedded
    # MicroPython / CircuitPython stubs.  Pyright ignores the deleted
    # files anyway because its ``executionEnvironments`` scope keeps
    # the stubs away from ``scripts/``.
    _prune_stdlib_shadows_from_typings()

    # Late imports — these modules are part of the workspace itself
    # (not third-party deps), but deferring keeps shared.py importable
    # on a fresh clone before requirements-dev have been installed.
    print("== generate config files ==")
    from generate_config_files import generate_config_files

    generate_config_files()

    from ide_sync import sync_ide

    return sync_ide()


def _prune_stdlib_shadows_from_typings() -> None:
    """Remove embedded stubs whose name shadows a CPython stdlib module.

    ``circuitpython-stubs`` and ``micropython-esp32-stubs`` ship
    ``.pyi`` files for names that exist in the standard library —
    ``time``, ``gc``, ``sys``, ``socket``, ``hashlib``, etc.  The
    MicroPython / CircuitPython variants drop or rename members that
    the CPython stdlib provides (``time.perf_counter`` isn't in
    MicroPython's ``time``, for instance), so leaving those files in
    ``typings/embedded-stubs/`` shadows typeshed everywhere PyCharm
    looks.

    Pyright's ``executionEnvironments`` already scopes the whole
    directory to ``libraries/`` and ``support/test_harness/``, so it
    doesn't need the stdlib shadows inside either — typeshed covers
    ``libraries/`` code that imports ``time`` etc. the same way it
    covers ``scripts/``.  Library code that needs MicroPython-only
    members (``time.ticks_ms``, ``gc.mem_free``) uses the
    ``getattr(time, "ticks_ms", None)`` idiom from
    ``chumicro_timing.ticks`` — no stub dependency.

    What we keep: every embedded-only stub (``board``, ``busio``,
    ``neopixel``, ``supervisor``, ``machine``, ``micropython``, the
    ``u``-prefixed MicroPython aliases like ``utime`` / ``usys`` which
    are not stdlib names, and every ``-stubs`` subdirectory).
    """
    if not TYPINGS_DIR.is_dir():
        return
    shadowed = set(sys.stdlib_module_names) | {"__builtins__"}
    removed: list[str] = []
    for path in TYPINGS_DIR.glob("*.pyi"):
        if path.stem in shadowed:
            path.unlink()
            removed.append(path.name)
    if removed:
        print(
            f"  Pruned {len(removed)} stdlib-shadow stub(s) from "
            f"{TYPINGS_DIR.relative_to(ROOT)}: {', '.join(sorted(removed))}",
        )


def _clean_stub_leftovers_from_site_packages(python: Path | None) -> None:
    """Remove top-level ``.pyi`` files and stub dirs from site-packages.

    ``circuitpython-stubs`` and ``micropython-esp32-stubs`` ship bare
    ``time.pyi`` / ``gc.pyi`` / ``sys.pyi`` at the package root, which
    shadow stdlib stubs workspace-wide when installed into a regular
    ``site-packages``.  Older ``install_workspace`` runs put them there;
    this cleanup evicts them so the typings-dir install becomes the
    single source.

    The cleanup is best-effort — it only removes things whose RECORD
    lists them as coming from the two stub packages.  Any file not owned
    by those packages is left alone.
    """
    interpreter = str(python) if python is not None else sys.executable
    result = subprocess.run(
        [interpreter, "-c",
         "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return
    site_packages = Path(result.stdout.strip())
    if not site_packages.is_dir():
        return

    # Iterate over RECORD files for the two stub packages.
    for dist_info in site_packages.glob("*.dist-info"):
        name = dist_info.name.split("-", 1)[0].lower()
        if name not in ("circuitpython_stubs", "micropython_esp32_stubs"):
            continue
        record_file = dist_info / "RECORD"
        if not record_file.is_file():
            continue
        for line in record_file.read_text().splitlines():
            relative = line.split(",", 1)[0].strip()
            if not relative or relative.startswith(".."):
                continue
            target = site_packages / relative
            if target.is_file():
                try:
                    target.unlink()
                except OSError:  # pragma: no cover - best-effort cleanup
                    pass
        # Remove the dist-info metadata itself.
        try:
            shutil.rmtree(dist_info)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass


# ---------------------------------------------------------------------------
# Runtime preparation helpers
# ---------------------------------------------------------------------------


@functools.cache
def runtime_versions() -> dict:
    """Read and cache pinned runtime versions from ``target-runtimes.toml``.

    Lazy — importing :mod:`shared` no longer triggers a TOML read.
    """
    return read_runtime_versions()


def run_build_command(
    command: list[str], cwd: Path | None = None, environment: dict[str, str] | None = None
) -> None:
    """Run a build command and fail fast if it does not succeed.

    Args:
        command: Command and arguments to run.
        cwd: Working directory (defaults to repository root).
        environment: Optional environment variables for the subprocess.
    """
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd or ROOT, env=environment, check=True)


def ensure_tool(name: str) -> None:
    """Require a host tool before attempting to prepare a runtime.

    Args:
        name: Tool binary name to look up on PATH.

    Raises:
        RuntimeError: If the tool is not found.
    """
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")


def ensure_build_tools() -> None:
    """Require ``git``, ``make``, and ``cc`` on PATH.

    Convenience wrapper for the build-tool check shared by all three
    runtime preparation scripts (``prepare-micropython``,
    ``prepare-circuitpython``, ``prepare-mpy-cross``).

    Raises:
        RuntimeError: If any required tool is missing.
    """
    for tool_name in ("git", "make", "cc"):
        ensure_tool(tool_name)


def running_on_native_windows() -> bool:
    """Return whether the script is running on native Windows rather than WSL."""
    return os.name == "nt"


def build_jobs() -> str:
    """Return a conservative default parallelism level for local builds."""
    return str(min(os.cpu_count() or 2, 4))


def build_environment(*extra_cflags: str) -> dict[str, str]:
    """Return a copy of ``os.environ`` with additional ``CFLAGS`` flags.

    Flags already present in ``CFLAGS`` are not duplicated.

    Args:
        extra_cflags: Additional compiler flags to append.
    """
    environment = os.environ.copy()
    existing = environment.get("CFLAGS", "").split()
    for flag in extra_cflags:
        if flag not in existing:
            existing.append(flag)
    if existing:
        environment["CFLAGS"] = " ".join(existing)
    return environment


def macos_build_environment() -> dict[str, str]:
    """Return build environment with macOS-specific compiler flags.

    macOS Clang treats ``gnu-folding-constant`` as an error by default,
    which breaks the MicroPython build.  This helper adds the suppression
    flag when running on Darwin.  Not needed on Linux/GCC.
    """
    macos_flags = ["-Wno-error=gnu-folding-constant"] if sys.platform == "darwin" else []
    return build_environment(*macos_flags)


def ensure_source_tree(
    source_dir: Path,
    repo_url: str,
    release: str,
    *,
    init_submodules: bool = False,
) -> None:
    """Clone a pinned source tree if not already present.

    Args:
        source_dir: Target directory for the cloned repository.
        repo_url: Git repository URL to clone.
        release: Git tag or branch to check out.
        init_submodules: Whether to recursively initialize submodules after
            cloning.
    """
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    if not source_dir.exists():
        run_build_command([
            "git", "clone", "--depth", "1",
            "--branch", release, repo_url, str(source_dir),
        ])
    if init_submodules:
        run_build_command(
            ["git", "submodule", "update", "--init", "--recursive"], cwd=source_dir
        )


# ---------------------------------------------------------------------------
# Declarative runtime preparation pipeline
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RuntimePrepStep:
    """A single shell-out step in a runtime build pipeline.

    Attributes:
        command: Command + arguments to run.
        cwd: Working directory; ``None`` means use the source tree.
        environment: Override environment variables.
    """

    command: list[str | Path]
    cwd: Path | None = None
    environment: dict[str, str] | None = None


@dataclasses.dataclass(frozen=True)
class RuntimePrep:
    """Declarative description of one runtime's preparation pipeline.

    The same pipeline shape works for the full unix-port build
    (MicroPython / CircuitPython) and the lighter mpy-cross-only build,
    so all three ``prepare_*.py`` wrappers reduce to a single
    :func:`prepare_runtime` call.

    Attributes:
        label: Human-readable runtime name (e.g. ``"MicroPython"``).
        source_dir: Directory the source tree is cloned into.
        repo_url: Git repository URL.
        release: Git tag or branch to check out.
        init_submodules: Targeted submodule paths to initialize.  Empty
            tuple skips submodule init entirely.
        build_steps: Ordered build commands to run after the source
            tree is ready.
        expected_binary: Path that must exist after the build.  ``None``
            skips the post-build existence check.
        marker_file: Path to write the absolute binary path to so other
            commands can find it without recompiling.  ``None`` skips
            the marker write.
    """

    label: str
    source_dir: Path
    repo_url: str
    release: str
    init_submodules: tuple[str, ...] = ()
    build_steps: tuple[RuntimePrepStep, ...] = ()
    expected_binary: Path | None = None
    marker_file: Path | None = None


def prepare_runtime(prep: RuntimePrep) -> int:
    """Execute a runtime preparation pipeline.

    Returns the exit code suitable for surfacing from the CLI:
    0 on success, 2 when refused on native Windows, or the failing
    subprocess's exit code.

    Args:
        prep: Declarative pipeline description.
    """
    if running_on_native_windows():
        print(
            "Native Windows preparation is out of scope for this workspace phase. "
            "Use WSL2 for runtime preparation."
        )
        return 2

    try:
        ensure_build_tools()
        ensure_source_tree(prep.source_dir, prep.repo_url, prep.release)
        for submodule in prep.init_submodules:
            run_build_command(
                ["git", "submodule", "update", "--init", submodule],
                cwd=prep.source_dir,
            )
        for step in prep.build_steps:
            run_build_command(
                [str(arg) for arg in step.command],
                cwd=step.cwd or prep.source_dir,
                environment=step.environment,
            )
    except subprocess.CalledProcessError as error:
        print(f"Command failed with exit code {error.returncode}: {error.cmd}")
        return error.returncode or 1
    except RuntimeError as error:
        print(error)
        return 1

    if prep.expected_binary is not None and not prep.expected_binary.exists():
        print(
            f"Prepared source tree does not contain the expected binary: "
            f"{prep.expected_binary}"
        )
        return 1

    if prep.expected_binary is not None:
        print(f"Prepared {prep.label} binary: {prep.expected_binary}")
        if prep.marker_file is not None:
            prep.marker_file.write_text(str(prep.expected_binary))
    return 0


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def _read_prepared_binary(marker_name: str) -> str | None:
    """Read a binary path from a marker file written by a prepare step.

    The prepare-micropython and prepare-circuitpython scripts write the
    absolute path of the compiled binary to a marker file (e.g.
    ``.tools/micropython.path``) so other commands can find it without
    recompiling.
    """
    marker_file = TOOLS / marker_name
    if not marker_file.exists():
        return None
    candidate_file = Path(marker_file.read_text().strip())
    if candidate_file.exists():
        return str(candidate_file)
    return None


def _resolve_binary(
    *,
    label: str,
    binary: str | None,
    marker_name: str | None = None,
    prepared_path: Callable[[], Path | None] | None = None,
    path_lookup: str | None = None,
) -> str | None:
    """Resolve a binary path from CLI override, prepared tree, or PATH.

    Resolution order (first match wins):
      1. *binary* — explicit override; raises :class:`SystemExit` if it does
         not exist on disk.
      2. *marker_name* — read from ``.tools/<marker>`` if set.
      3. *prepared_path* — call to compute a candidate path under ``.tools/``
         (used when the candidate depends on ``runtime_versions()``).
      4. *path_lookup* — fall back to ``shutil.which(<name>)``.

    Args:
        label: Human-readable name used in error messages (e.g.
            ``"MicroPython binary"``).
        binary: Explicit override from the CLI (or ``None``).
        marker_name: Name of a file under ``.tools/`` that holds an absolute
            path to a prepared binary (written by the ``prepare-*`` scripts).
        prepared_path: Callable returning a :class:`Path` candidate (or
            ``None``) that is checked for existence before being returned.
        path_lookup: Name to look up via ``shutil.which`` as a last resort.
    """
    if binary:
        if not Path(binary).exists():
            print(f"{label} not found: {binary}")
            raise SystemExit(1)
        return binary
    if marker_name is not None:
        prepared = _read_prepared_binary(marker_name)
        if prepared:
            return prepared
    if prepared_path is not None:
        candidate = prepared_path()
        if candidate is not None and candidate.exists():
            return str(candidate)
    if path_lookup is not None:
        return shutil.which(path_lookup)
    return None


def resolve_micropython_binary(binary: str | None = None) -> str | None:
    """Resolve a MicroPython binary from an explicit path, prepared tree, or PATH."""
    return _resolve_binary(
        label="MicroPython binary",
        binary=binary,
        marker_name="micropython.path",
        path_lookup="micropython",
    )


def resolve_circuitpython_binary(binary: str | None = None) -> str | None:
    """Resolve a CircuitPython binary from an explicit path, prepared tree, or PATH."""
    return _resolve_binary(
        label="CircuitPython binary",
        binary=binary,
        marker_name="circuitpython.path",
        path_lookup="circuitpython",
    )


# ---------------------------------------------------------------------------
# mpy-cross resolution
# ---------------------------------------------------------------------------


def _mpy_cross_candidate(runtime_name: str) -> Path | None:
    """Return the prepared mpy-cross path for *runtime_name*, or ``None``."""
    version = runtime_versions().get(runtime_name, {}).get("version")
    if not version:
        return None
    return TOOLS / f"{runtime_name}-{version}" / "mpy-cross" / "build" / "mpy-cross"


def resolve_cp_mpy_cross(binary: str | None = None) -> str | None:
    """Resolve CircuitPython's mpy-cross from an explicit path or the prepared source tree.

    No PATH fallback — CircuitPython's mpy-cross is not pip-installable.
    """
    return _resolve_binary(
        label="CircuitPython mpy-cross",
        binary=binary,
        prepared_path=lambda: _mpy_cross_candidate("circuitpython"),
    )


def resolve_mp_mpy_cross(binary: str | None = None) -> str | None:
    """Resolve MicroPython's mpy-cross from an explicit path, prepared tree, or PATH."""
    return _resolve_binary(
        label="MicroPython mpy-cross",
        binary=binary,
        prepared_path=lambda: _mpy_cross_candidate("micropython"),
        path_lookup="mpy-cross",
    )
