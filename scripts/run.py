"""Repo-level task runner for humans, agents, and CI.

Usage::

    python scripts/run.py <task> [options]

Run ``python scripts/run.py -h`` to see available tasks.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from check_api import main as _check_api_main
from check_version import main as _check_version_main
from discovery import (
    ROOT,
    coverage_args_for,
    discover_package_dirs,
    discover_ruff_paths,
    filter_by_platform,
    find_publishable_packages,
    pythonpath_env,
    resolve_scope,
)
from ide import sync_ide
from prepare import VERSIONS, resolve_circuitpython_binary, resolve_micropython_binary
from prepare_circuitpython import prepare_circuitpython as _prepare_circuitpython
from prepare_micropython import prepare_micropython as _prepare_micropython
from scaffold import new_library
from verify_examples import verify_examples

PYTHON = sys.executable
COMPAT_SCRIPT = "support/test_harness/run_cross_runtime.py"


def _run(command: list[str], env: dict[str, str] | None = None) -> int:
    """Run a command from the repo root and return its exit code."""
    printable_command = " ".join(command)
    print(f"+ {printable_command}")
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    return completed.returncode


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def _install_command() -> list[str]:
    """Return the pip-install command prefix, preferring uv when available."""
    if shutil.which("uv"):
        return ["uv", "pip", "install"]
    return [PYTHON, "-m", "pip", "install"]


def setup() -> int:
    """Install development dependencies and regenerate IDE configuration."""
    cp_version = VERSIONS["circuitpython"]["version"]
    mp_version = VERSIONS["micropython"]["version"].lstrip("v")

    # Static deps from requirements-dev.txt, dynamic stubs appended here.
    req_file = str(ROOT / "requirements-dev.txt")
    stubs = [
        f"circuitpython-stubs=={cp_version}",
        f"micropython-esp32-stubs=={mp_version}.*",
    ]

    result = _run([*_install_command(), "-U", "-r", req_file, *stubs])
    if result != 0:
        return result
    return sync_ide()


def lint() -> int:
    """Run Ruff across all discovered source, test, and script paths."""
    return _run([PYTHON, "-m", "ruff", "check", *discover_ruff_paths()])


def _parse_library_filters(
    filter_expr: str,
) -> dict[str, list[tuple[str | None, str]]]:
    """Parse a ``-k`` expression into per-library test filters.

    Every entry must be library-scoped.  Supported formats::

        library/expression              filter by name within a library
        library/file/expression         filter within a specific test file
        lib1/a,lib2/b                   comma-separated entries

    Returns ``{library_name: [(file_or_None, expression), ...]}``.
    Multiple unscoped entries for the same library are combined with
    ``or`` at run time.  File-scoped entries each get their own pytest
    invocation.

    Raises :class:`SystemExit` for entries missing a library prefix.
    """
    entries = [e.strip() for e in filter_expr.split(",") if e.strip()]
    result: dict[str, list[tuple[str | None, str]]] = {}

    for entry in entries:
        parts = entry.split("/")
        if len(parts) == 2:
            lib, expr = parts
            result.setdefault(lib, []).append((None, expr))
        elif len(parts) == 3:
            lib, file, expr = parts
            result.setdefault(lib, []).append((file, expr))
        else:
            print(f"Invalid -k format: {entry}")
            print(
                "Use library/test, library/file/test, "
                "or comma-separated entries."
            )
            raise SystemExit(1)

    return result


def test_cpython(
    pkg_dirs: list[Path],
    *,
    filter_expr: str | None = None,
    exitfirst: bool = False,
    verbose: bool = False,
    no_cov: bool = False,
) -> int:
    """Run the CPython test suite for the given packages.

    Runs pytest separately for each package to avoid test-directory name
    collisions (Decision 0009), then combines and reports coverage.  Each
    library must independently meet the coverage threshold (90%) unless
    *filter_expr* is set (filtering naturally reduces coverage) or *no_cov*
    skips coverage entirely.

    *filter_expr* requires library-scoped syntax::

        timing/test_heartbeat                 # by name in a library
        timing/test_ticks/test_add            # by file and name
        timing/test_a,runner/test_b      # comma-separated
    """
    # Parse library-scoped filters from filter_expr.
    # When -k is set, library names extracted from the filter expression
    # completely replace pkg_dirs (from --all / --libraries / change
    # detection).  -k takes precedence over scope flags.
    per_library: dict[str, list[tuple[str | None, str]]] | None = None
    if filter_expr:
        per_library = _parse_library_filters(filter_expr)
        # Library prefixes override pkg_dirs.
        all_dirs = discover_package_dirs()
        by_name = {d.name: d for d in all_dirs}
        resolved: list[Path] = []
        for name in per_library:
            if name not in by_name:
                available = ", ".join(sorted(by_name))
                print(f"Unknown library in -k: {name}")
                print(f"Available: {available}")
                return 1
            resolved.append(by_name[name])
        pkg_dirs = resolved

    # Keep only packages that actually have a tests/ directory.
    testable = [d for d in pkg_dirs if (d / "tests").is_dir()]
    if not testable:
        print("No test directories found for the selected packages.")
        return 0

    env = pythonpath_env()

    # Clean stale coverage data so combine starts fresh.  Two globs are
    # needed: `.coverage` (the default combined file) and `.coverage.*`
    # (the per-run files we create below with unique suffixes).
    for f in ROOT.glob(".coverage"):
        f.unlink()
    for f in ROOT.glob(".coverage.*"):
        f.unlink()

    # Relax coverage gates when either:
    #   - filter_expr is set (selecting a subset of tests naturally
    #     reduces branch coverage below the 90% threshold), or
    #   - no_cov is set (user explicitly opted out of coverage).
    relax_coverage = bool(filter_expr) or no_cov
    cov_gate_args = ["--cov-fail-under=0"] if relax_coverage else []

    overall_rc = 0
    run_counter = 0

    for pkg_dir in testable:
        # Determine what pytest runs are needed for this library.
        #
        # Filter entries split into two categories:
        #   - "global" (no file specified): combined with `or` into a
        #     single pytest invocation across the whole tests/ dir.
        #   - "file-scoped" (library/file/expr): each gets its own
        #     pytest invocation targeting a specific test file.
        #
        # Each invocation writes to a unique COVERAGE_FILE to avoid
        # overwriting coverage data from other runs.
        if per_library is not None:
            entries = per_library.get(pkg_dir.name, [])

            # Split into file-scoped and global entries.
            global_exprs = [expr for f, expr in entries if f is None]
            file_entries = [(f, expr) for f, expr in entries if f is not None]

            # Global expressions combine into a single run.
            runs: list[tuple[str, str]] = []
            if global_exprs:
                test_path = str((pkg_dir / "tests").relative_to(ROOT))
                combined = " or ".join(global_exprs)
                runs.append((test_path, combined))

            # File-scoped entries each get their own run.
            for file_name, expr in file_entries:
                test_file = pkg_dir / "tests" / f"{file_name}.py"
                if not test_file.exists():
                    rel = test_file.relative_to(ROOT)
                    print(f"Test file not found: {rel}")
                    return 1
                runs.append((str(test_file.relative_to(ROOT)), expr))
        else:
            # No filter — run the entire tests/ directory.
            test_path = str((pkg_dir / "tests").relative_to(ROOT))
            runs = [(test_path, "")]

        for test_target, expr in runs:
            extra_args: list[str] = []
            if expr:
                extra_args.extend(["-k", expr])
            if exitfirst:
                extra_args.append("-x")
            if verbose:
                extra_args.append("-v")

            cov_args = [] if no_cov else coverage_args_for([pkg_dir])

            # Unique coverage file per run.
            cov_name = f".coverage.{pkg_dir.name}.{run_counter}"
            run_env = {**env, "COVERAGE_FILE": str(ROOT / cov_name)}
            run_counter += 1

            rc = _run(
                [
                    PYTHON, "-m", "pytest",
                    "-W", "error",
                    *cov_args,
                    "--cov-report=",
                    *cov_gate_args,
                    test_target,
                    *extra_args,
                ],
                env=run_env,
            )
            # Exit code 5 means no tests were collected (e.g. -k filter
            # matched nothing in this library) — not an error.
            if rc not in (0, 5):
                overall_rc = rc

    # Combine per-library coverage into one data file and report.
    if not no_cov and list(ROOT.glob(".coverage.*")):
        _run([PYTHON, "-m", "coverage", "combine"])

        report_args = [PYTHON, "-m", "coverage", "report", "--show-missing"]
        if relax_coverage:
            report_args.append("--fail-under=0")

        report_rc = _run(report_args)
        if report_rc != 0 and overall_rc == 0:
            overall_rc = report_rc

    return overall_rc


def build() -> int:
    """Build all publishable package distributions."""
    packages = find_publishable_packages()
    if not packages:
        print("No publishable packages found (no VERSION + pyproject.toml pairs).")
        return 1

    for package in packages:
        print(f"== build {package} ==")
        result = _run([PYTHON, "-m", "build", package])
        if result != 0:
            print(f"Build failed: {package}")
            return result

    print(f"Built {len(packages)} package(s): {', '.join(packages)}")
    return 0



def _copy_shared_docs_css(pkg_dirs: list[Path]) -> None:
    """Copy ``support/docs/extra.css`` into each library's ``docs/stylesheets/``.

    Zensical does not support mkdocs hooks, so we handle the copy here
    before building.  The generated copies are gitignored.
    """
    import shutil

    shared = ROOT / "support" / "docs" / "extra.css"
    if not shared.exists():
        return
    for pkg_dir in pkg_dirs:
        dest = pkg_dir / "docs" / "stylesheets" / "extra.css"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shared, dest)


def docs(pkg_dirs: list[Path], *, serve: bool = False) -> int:
    """Build docs for selected libraries using Zensical.

    If *serve* is True, starts a live-reload dev server for the first
    selected library instead of building static output.
    """
    # Keep only packages that have a mkdocs.yml
    doc_dirs = [d for d in pkg_dirs if (d / "mkdocs.yml").exists()]
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    _copy_shared_docs_css(doc_dirs)

    if serve:
        # Serve the first selected library
        pkg_dir = doc_dirs[0]
        rel = pkg_dir.relative_to(ROOT)
        print(f"Serving docs for {rel} (Ctrl+C to stop)...")
        return _run(
            [PYTHON, "-m", "zensical", "serve",
             "-f", str(pkg_dir / "mkdocs.yml")],
        )

    overall_rc = 0
    for pkg_dir in doc_dirs:
        rel = pkg_dir.relative_to(ROOT)
        site_dir = pkg_dir / "site"
        print(f"== docs {rel} ==")
        rc = _run(
            [PYTHON, "-m", "zensical", "build",
             "-f", str(pkg_dir / "mkdocs.yml")],
        )
        if rc != 0:
            print(f"Docs build failed: {rel}")
            overall_rc = rc
        else:
            print(f"  Built: {site_dir.relative_to(ROOT)}/")

    return overall_rc


def preflight(
    mp_binary: str | None = None,
    cp_binary: str | None = None,
) -> int:
    """Run the full check suite that CI requires on every pull request.

    Covers lint, all CPython tests, example verification, MicroPython and
    CircuitPython cross-runtime unit tests, and package builds.  Functional
    tests are excluded — they require physical hardware.
    """
    all_pkgs = discover_package_dirs()
    steps: tuple[tuple[str, object], ...] = (
        ("lint", lint),
        ("test", lambda: test_cpython(all_pkgs)),
        ("verify-examples", lambda: verify_examples(all_pkgs)),
        ("test-micropython-compatibility", lambda: test_micropython_compatibility(mp_binary)),
        ("test-circuitpython-compatibility", lambda: test_circuitpython_compatibility(cp_binary)),
        ("build", build),
    )

    for step_name, step in steps:
        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Preflight failed at: {step_name}")
            return result

    print("Preflight passed — required CI checks should pass.")
    return 0


def prepare_micropython() -> int:
    """Prepare the repo-local MicroPython unix-port runtime."""
    return _prepare_micropython()


def prepare_circuitpython() -> int:
    """Prepare the repo-local CircuitPython unix-port runtime."""
    return _prepare_circuitpython()


def _test_runtime_compat(
    platform: str,
    label: str,
    resolve_binary,
    prepare_fn,
) -> int:
    """Run cross-runtime unit tests for a single runtime.

    Shared implementation for :func:`test_micropython_compatibility` and
    :func:`test_circuitpython_compatibility`.  Resolves the binary,
    auto-prepares when missing, then runs the compat script for libraries
    that target *platform*.
    """
    binary = resolve_binary()
    if binary is None:
        print(f"{label} binary not found. Preparing unix-port runtime first.")
        prepare_result = prepare_fn()
        if prepare_result != 0:
            print(f"{label} preparation failed.")
            return prepare_result

        binary = resolve_binary()
        if binary is None:
            print(
                f"Preparation completed without the expected binary. "
                f"Pass --{platform}-bin <path> and retry."
            )
            return 1

    # Only publishable libraries under libraries/ are tested against
    # non-CPython runtimes.  support/ packages are CPython-only
    # infrastructure and are excluded from cross-runtime validation.
    lib_dirs = [d for d in discover_package_dirs() if d.parent.name == "libraries"]
    platform_libs = filter_by_platform(lib_dirs, platform)
    lib_names = [d.name for d in platform_libs]
    return _run([binary, COMPAT_SCRIPT, *lib_names])


def test_micropython_compatibility(binary: str | None = None) -> int:
    """Run the cross-runtime unit tests with the MicroPython Unix binary.

    Skips libraries that do not target MicroPython.
    """
    return _test_runtime_compat(
        "micropython", "MicroPython",
        lambda: resolve_micropython_binary(binary), prepare_micropython,
    )


def test_circuitpython_compatibility(binary: str | None = None) -> int:
    """Run the cross-runtime unit tests with a configured or repo-managed CircuitPython binary.

    Skips libraries that do not target CircuitPython.
    """
    return _test_runtime_compat(
        "circuitpython", "CircuitPython",
        lambda: resolve_circuitpython_binary(binary), prepare_circuitpython,
    )


def test_runtime_matrix(
    mp_binary: str | None = None,
    cp_binary: str | None = None,
) -> int:
    """Run host tests and cross-runtime unit tests across all proven runtimes."""
    all_pkgs = discover_package_dirs()
    steps = (
        ("test", lambda: test_cpython(all_pkgs)),
        ("test-micropython-compatibility", lambda: test_micropython_compatibility(mp_binary)),
        ("test-circuitpython-compatibility", lambda: test_circuitpython_compatibility(cp_binary)),
    )

    for step_name, step in steps:
        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Step failed: {step_name}")
            return result

    return 0


def test_device() -> int:
    """Point users to the current manual-only device validation path."""
    devices_path = ROOT / "devices.yml"
    if devices_path.exists():
        print(f"Manual device validation remains user-driven. Config: {devices_path}")
    else:
        print(
            "Copy devices.example.yml to devices.yml and fill in your board details."
        )

    print("Use libraries/timing/functional_tests/ with support/test_harness/ on the target board.")
    return 2


def check_version() -> int:
    """Check VERSION enforcement for changed libraries (PR check)."""
    return _check_version_main([])


def check_api() -> int:
    """Check API breakages against last release tag (PR check)."""
    return _check_api_main([])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _scope_parent() -> argparse.ArgumentParser:
    """Parent parser providing ``--all`` / ``--libraries`` scope flags."""
    parent = argparse.ArgumentParser(add_help=False)
    group = parent.add_mutually_exclusive_group()
    group.add_argument(
        "--all", action="store_true", dest="all_packages",
        help="run for all packages",
    )
    group.add_argument(
        "--libraries", metavar="LIB,...",
        help="run for specific packages (comma-separated names)",
    )
    return parent


def _binary_parent() -> argparse.ArgumentParser:
    """Parent parser providing runtime binary override flags."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--micropython-bin", metavar="PATH",
        help="path to MicroPython binary (overrides auto-detection)",
    )
    parent.add_argument(
        "--circuitpython-bin", metavar="PATH",
        help="path to CircuitPython binary (overrides auto-detection)",
    )
    return parent


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="python scripts/run.py",
        description="Repo-level task runner for humans, agents, and CI.",
    )
    sub = parser.add_subparsers(dest="task")
    scope = _scope_parent()
    binary = _binary_parent()

    # No-arg tasks
    sub.add_parser("setup", help="install deps and regenerate IDE config")
    sub.add_parser("sync-ide", help="regenerate IDE config files")
    sub.add_parser("lint", help="run Ruff across the workspace")
    sub.add_parser("build", help="build all publishable packages")
    sub.add_parser("preflight", parents=[binary], help="lint + test + examples + compat + build")
    sub.add_parser("prepare-micropython", help="prepare MicroPython unix-port")
    sub.add_parser("prepare-circuitpython", help="prepare CircuitPython unix-port")
    sub.add_parser(
        "test-micropython-compatibility",
        parents=[binary],
        help="MicroPython cross-runtime unit tests",
    )
    sub.add_parser(
        "test-circuitpython-compatibility",
        parents=[binary],
        help="CircuitPython cross-runtime unit tests",
    )
    sub.add_parser(
        "test-runtime-matrix",
        parents=[binary],
        help="test all packages on CPython + MicroPython + CircuitPython",
    )
    sub.add_parser("test-device", help="device validation info")
    sub.add_parser("check-version", help="check VERSION enforcement for changed libraries")
    sub.add_parser("check-api", help="check API breakages against last release tag")

    # Scoped tasks
    test_p = sub.add_parser(
        "test", parents=[scope],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="CPython tests (only changed packages by default)",
        epilog=(
            "examples:\n"
            "  run.py test                                       "
            "# changed packages\n"
            "  run.py test --all                                 "
            "# all packages\n"
            "  run.py test -k timing/test_heartbeat              "
            "# by library and test\n"
            "  run.py test -k timing/test_ticks/test_add         "
            "# by library, file, and test\n"
            "  run.py test -k timing/test_a,runner/test_b   "
            "# per-library filters\n"
            "  run.py test --no-cov -x                           "
            "# quick, stop on failure"
        ),
    )
    test_p.add_argument(
        "-k", dest="filter_expr", metavar="FILTER",
        help=(
            "library/test or library/file/test "
            "(comma-separated for multiple)"
        ),
    )
    test_p.add_argument(
        "-x", "--exitfirst", action="store_true",
        help="stop on first failure",
    )
    test_p.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output",
    )
    test_p.add_argument(
        "--no-cov", action="store_true",
        help="skip coverage collection",
    )
    sub.add_parser("verify-examples", parents=[scope], help="import-check examples")

    docs_p = sub.add_parser("docs", parents=[scope], help="build library docs")
    docs_p.add_argument(
        "--serve", action="store_true", help="start live-reload dev server",
    )

    # new-library
    nl = sub.add_parser("new-library", help="scaffold a new library")
    nl.add_argument("name", help="library name (e.g. gpio)")

    return parser


_SCOPED_TASKS = frozenset({"test", "verify-examples", "docs"})


def main(argv: list[str]) -> int:
    """Dispatch a named repo-level task."""
    parser = _build_parser()
    args = parser.parse_args(argv[1:])

    if not args.task:
        parser.print_help()
        return 1

    # --- scoped tasks ---
    if args.task in _SCOPED_TASKS:
        pkg_dirs = resolve_scope(
            all_packages=args.all_packages, libraries=args.libraries,
        )
        if args.task == "test":
            return test_cpython(
                pkg_dirs,
                filter_expr=args.filter_expr,
                exitfirst=args.exitfirst,
                verbose=args.verbose,
                no_cov=args.no_cov,
            )
        if args.task == "verify-examples":
            return verify_examples(pkg_dirs)
        return docs(pkg_dirs, serve=args.serve)

    # --- new-library ---
    if args.task == "new-library":
        return new_library(args.name)

    # --- tasks that accept runtime binary overrides ---
    if args.task in {
        "preflight", "test-micropython-compatibility",
        "test-circuitpython-compatibility", "test-runtime-matrix",
    }:
        mp_bin = args.micropython_bin
        cp_bin = args.circuitpython_bin
        if args.task == "test-micropython-compatibility":
            return test_micropython_compatibility(mp_bin)
        if args.task == "test-circuitpython-compatibility":
            return test_circuitpython_compatibility(cp_bin)
        if args.task == "test-runtime-matrix":
            return test_runtime_matrix(mp_bin, cp_bin)
        return preflight(mp_bin, cp_bin)

    # --- no-arg tasks ---
    no_arg = {
        "setup": setup,
        "sync-ide": sync_ide,
        "lint": lint,
        "build": build,
        "prepare-micropython": prepare_micropython,
        "prepare-circuitpython": prepare_circuitpython,
        "test-device": test_device,
        "check-version": check_version,
        "check-api": check_api,
    }
    return no_arg[args.task]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
