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

from discovery import (
    ROOT,
    coverage_args_for,
    discover_package_dirs,
    discover_ruff_paths,
    find_publishable_packages,
    pythonpath_env,
    resolve_scope,
)
from ide import sync_ide
from prepare import VERSIONS, resolve_circuitpython_binary, resolve_micropython_binary
from prepare_circuitpython import prepare_circuitpython as _prepare_circuitpython
from prepare_micropython import prepare_micropython as _prepare_micropython
from scaffold import new_library

PYTHON = sys.executable
SMOKE_SCRIPT = "support/test_harness/run_device_smoke.py"
SMOKE_EXEC = f'exec(open("{SMOKE_SCRIPT}").read())'


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
    dev_packages: list[str] = []
    req_file = ROOT / "requirements-dev.txt"
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                dev_packages.append(stripped)

    dev_packages.extend([
        f"circuitpython-stubs=={cp_version}",
        f"micropython-esp32-stubs=={mp_version}.*",
    ])

    result = _run([*_install_command(), "-U", *dev_packages])
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
    collisions, then combines and reports coverage.  Each library must
    independently meet the coverage threshold (90%) unless *filter_expr*
    is set (filtering naturally reduces coverage) or *no_cov* skips
    coverage entirely.

    *filter_expr* requires library-scoped syntax::

        timing/test_heartbeat                 # by name in a library
        timing/test_ticks/test_add            # by file and name
        timing/test_a,serviceable/test_b      # comma-separated
    """
    # Parse library-scoped filters from filter_expr.
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

    # Clean stale coverage data so combine starts fresh.
    for f in ROOT.glob(".coverage"):
        f.unlink()
    for f in ROOT.glob(".coverage.*"):
        f.unlink()

    # When filtering or skipping coverage, relax per-library coverage
    # gates — filtering naturally reduces coverage.
    relax_coverage = bool(filter_expr) or no_cov
    cov_gate_args = ["--cov-fail-under=0"] if relax_coverage else []

    overall_rc = 0
    run_counter = 0

    for pkg_dir in testable:
        # Determine what pytest runs are needed for this library.
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


def verify_examples(pkg_dirs: list[Path]) -> int:
    """Import-check examples to catch broken imports and syntax errors.

    Discovers ``examples/*.py`` in each selected library, then imports each
    module in a subprocess.  Examples must use ``if __name__ == "__main__":``
    guards so that import does not trigger long-running loops.
    """
    env = pythonpath_env()
    examples: list[tuple[str, Path]] = []

    for pkg_dir in pkg_dirs:
        ex_dir = pkg_dir / "examples"
        if not ex_dir.is_dir():
            continue
        for py_file in sorted(ex_dir.glob("*.py")):
            rel = py_file.relative_to(ROOT)
            examples.append((str(rel), py_file))

    if not examples:
        print("No examples found for the selected packages.")
        return 0

    failures = 0
    for rel_path, py_file in examples:
        rc = _run(
            [PYTHON, "-c", f"import importlib.util, sys; "
             f"spec = importlib.util.spec_from_file_location('_example', '{py_file}'); "
             f"mod = importlib.util.module_from_spec(spec); "
             f"spec.loader.exec_module(mod)"],
            env=env,
        )
        if rc != 0:
            print(f"  FAIL: {rel_path}")
            failures += 1
        else:
            print(f"  OK:   {rel_path}")

    if failures:
        print(f"\n{failures} example(s) failed import check.")
        return 1

    print(f"\nAll {len(examples)} example(s) passed import check.")
    return 0


def docs(pkg_dirs: list[Path], *, serve: bool = False) -> int:
    """Build docs for selected libraries using MkDocs.

    If *serve* is True, starts a live-reload dev server for the first
    selected library instead of building static output.
    """
    # Keep only packages that have a mkdocs.yml
    doc_dirs = [d for d in pkg_dirs if (d / "mkdocs.yml").exists()]
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    if serve:
        # Serve the first selected library
        pkg_dir = doc_dirs[0]
        rel = pkg_dir.relative_to(ROOT)
        print(f"Serving docs for {rel} (Ctrl+C to stop)...")
        return _run(
            [PYTHON, "-m", "mkdocs", "serve", "-f", str(pkg_dir / "mkdocs.yml")],
        )

    overall_rc = 0
    for pkg_dir in doc_dirs:
        rel = pkg_dir.relative_to(ROOT)
        site_dir = pkg_dir / "site"
        print(f"== docs {rel} ==")
        rc = _run(
            [PYTHON, "-m", "mkdocs", "build",
             "-f", str(pkg_dir / "mkdocs.yml"),
             "-d", str(site_dir)],
        )
        if rc != 0:
            print(f"Docs build failed: {rel}")
            overall_rc = rc
        else:
            print(f"  Built: {site_dir.relative_to(ROOT)}/")

    return overall_rc


def preflight() -> int:
    """Run the full check suite that CI requires on every pull request.

    Covers lint, all CPython tests, example verification, MicroPython and
    CircuitPython compatibility smoke tests, and package builds.  Device
    tests are excluded — they require physical hardware.
    """
    all_pkgs = discover_package_dirs()
    steps: tuple[tuple[str, object], ...] = (
        ("lint", lambda: lint()),
        ("test", lambda: test_cpython(all_pkgs)),
        ("verify-examples", lambda: verify_examples(all_pkgs)),
        ("test-micropython-compat", test_micropython_compat),
        ("test-circuitpython-compat", test_circuitpython_compat),
        ("build", lambda: build()),
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


def test_micropython_compat() -> int:
    """Run the sample device-test smoke script with the MicroPython Unix binary."""
    micropython_bin = resolve_micropython_binary()
    if micropython_bin is None:
        print("MicroPython binary not found. Preparing unix-port runtime first.")
        prepare_result = prepare_micropython()
        if prepare_result != 0:
            print("MicroPython preparation failed.")
            return prepare_result

        micropython_bin = resolve_micropython_binary()
        if micropython_bin is None:
            print(
                "Preparation completed without the expected binary. "
                "Set MICROPYTHON_BIN and retry."
            )
            return 1

    return _run([micropython_bin, "-c", SMOKE_EXEC])


def test_circuitpython_compat() -> int:
    """Run the shared smoke script with a configured or repo-managed CircuitPython binary."""
    circuitpython_bin = resolve_circuitpython_binary()
    if circuitpython_bin is None:
        print("CircuitPython binary not found. Preparing unix-port runtime first.")
        prepare_result = prepare_circuitpython()
        if prepare_result != 0:
            print("CircuitPython preparation failed.")
            return prepare_result

        circuitpython_bin = resolve_circuitpython_binary()
        if circuitpython_bin is None:
            print(
                "Preparation completed without the expected binary. "
                "Set CIRCUITPYTHON_BIN and retry."
            )
            return 1

    return _run([circuitpython_bin, "-c", SMOKE_EXEC])


def test_runtime_matrix() -> int:
    """Run host tests and compatibility smoke tests across all proven runtimes."""
    all_pkgs = discover_package_dirs()
    steps = (
        ("test", lambda: test_cpython(all_pkgs)),
        ("test-micropython-compat", test_micropython_compat),
        ("test-circuitpython-compat", test_circuitpython_compat),
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


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="python scripts/run.py",
        description="Repo-level task runner for humans, agents, and CI.",
    )
    sub = parser.add_subparsers(dest="task")
    scope = _scope_parent()

    # No-arg tasks
    sub.add_parser("setup", help="install deps and regenerate IDE config")
    sub.add_parser("sync-ide", help="regenerate IDE config files")
    sub.add_parser("lint", help="run Ruff across the workspace")
    sub.add_parser("build", help="build all publishable packages")
    sub.add_parser("preflight", help="lint + test + examples + compat + build")
    sub.add_parser("prepare-micropython", help="prepare MicroPython unix-port")
    sub.add_parser("prepare-circuitpython", help="prepare CircuitPython unix-port")
    sub.add_parser("test-micropython-compat", help="MicroPython smoke test")
    sub.add_parser("test-circuitpython-compat", help="CircuitPython smoke test")
    sub.add_parser(
        "test-runtime-matrix",
        help="test all packages on CPython + MicroPython + CircuitPython",
    )
    sub.add_parser("test-device", help="device validation info")

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
            "  run.py test -k timing/test_a,serviceable/test_b   "
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

    # --- no-arg tasks ---
    no_arg = {
        "setup": setup,
        "sync-ide": sync_ide,
        "lint": lint,
        "build": build,
        "preflight": preflight,
        "prepare-micropython": prepare_micropython,
        "prepare-circuitpython": prepare_circuitpython,
        "test-micropython-compat": test_micropython_compat,
        "test-circuitpython-compat": test_circuitpython_compat,
        "test-runtime-matrix": test_runtime_matrix,
        "test-device": test_device,
    }
    return no_arg[args.task]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
