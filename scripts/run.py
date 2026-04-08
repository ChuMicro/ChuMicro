"""Repository-level task runner for humans, agents, and CI.

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
from docs_deploy import (
    MIKE,
    copy_shared_docs_assets,
    inject_landing_page,
)
from docs_deploy import (
    docs_deploy as _docs_deploy,
)
from ide import sync_ide
from prepare import VERSIONS, resolve_circuitpython_binary, resolve_micropython_binary
from prepare_circuitpython import prepare_circuitpython as _prepare_circuitpython
from prepare_micropython import prepare_micropython as _prepare_micropython
from scaffold import new_library
from verify_examples import verify_examples

PYTHON = sys.executable
# Script that runs a library's tests/ directory under a non-CPython interpreter
# (MicroPython or CircuitPython unix-port) to verify cross-runtime compatibility.
COMPAT_SCRIPT = "support/test_harness/run_cross_runtime.py"


def _run(command: list[str], env: dict[str, str] | None = None) -> int:
    """Run a command from the repository root and return its exit code."""
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
    circuitpython_version = VERSIONS["circuitpython"]["version"]
    micropython_version = VERSIONS["micropython"]["version"].lstrip("v")

    # Static dependencies come from requirements-dev.txt.  Type stubs for
    # CircuitPython and MicroPython are pinned to the runtime versions
    # in target-runtimes.toml so IDE type-checking matches the actual
    # runtime APIs (Decision 0012).
    requirements_file = str(ROOT / "requirements-dev.txt")
    stubs = [
        f"circuitpython-stubs=={circuitpython_version}",
        f"micropython-esp32-stubs=={micropython_version}.*",
    ]

    result = _run([*_install_command(), "-U", "-r", requirements_file, *stubs])
    if result != 0:
        return result
    return sync_ide()


def lint() -> int:
    """Run Ruff across all discovered source, test, and script paths."""
    return _run([PYTHON, "-m", "ruff", "check", *discover_ruff_paths()])


def _parse_library_filters(
    filter_expression: str,
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
    entries = [entry.strip() for entry in filter_expression.split(",") if entry.strip()]
    result: dict[str, list[tuple[str | None, str]]] = {}

    for entry in entries:
        parts = entry.split("/")
        if len(parts) == 2:
            library_name, expression = parts
            result.setdefault(library_name, []).append((None, expression))
        elif len(parts) == 3:
            library_name, file_name, expression = parts
            result.setdefault(library_name, []).append((file_name, expression))
        else:
            print(f"Invalid -k format: {entry}")
            print(
                "Use library/test, library/file/test, "
                "or comma-separated entries."
            )
            raise SystemExit(1)

    return result


def test_cpython(
    package_dirs: list[Path],
    *,
    filter_expression: str | None = None,
    exit_first: bool = False,
    verbose: bool = False,
    no_cov: bool = False,
) -> int:
    """Run the CPython test suite for the given packages.

    Runs pytest separately for each package to avoid test-directory name
    collisions (Decision 0009), then combines and reports coverage.  Each
    library must independently meet the coverage threshold (94%) unless
    *filter_expression* is set (filtering naturally reduces coverage) or *no_cov*
    skips coverage entirely.

    *filter_expression* requires library-scoped syntax::

        timing/test_heartbeat                 # by name in a library
        timing/test_ticks/ticks_add           # by file and name
        timing/ticks_diff,runner/task_handle  # comma-separated
    """
    # Parse library-scoped filters from filter_expression.
    # When -k is set, library names extracted from the filter expression
    # completely replace package_dirs (from --all / --libraries / change
    # detection).  -k takes precedence over scope flags.
    per_library: dict[str, list[tuple[str | None, str]]] | None = None
    if filter_expression:
        per_library = _parse_library_filters(filter_expression)
        # Library prefixes override package_dirs.
        all_package_dirs = discover_package_dirs()
        by_name = {package_dir.name: package_dir for package_dir in all_package_dirs}
        resolved: list[Path] = []
        for name in per_library:
            if name not in by_name:
                available = ", ".join(sorted(by_name))
                print(f"Unknown library in -k: {name}")
                print(f"Available: {available}")
                return 1
            resolved.append(by_name[name])
        package_dirs = resolved

    # Keep only packages that actually have a tests/ directory.
    testable = [package_dir for package_dir in package_dirs if (package_dir / "tests").is_dir()]
    if not testable:
        print("No test directories found for the selected packages.")
        return 0

    env = pythonpath_env()

    # Clean stale coverage data so combine starts fresh.  Two globs are
    # needed: `.coverage` (the default combined file) and `.coverage.*`
    # (the per-run files we create below with unique suffixes).
    for coverage_file in ROOT.glob(".coverage"):
        coverage_file.unlink()
    for coverage_file in ROOT.glob(".coverage.*"):
        coverage_file.unlink()

    # Relax coverage gates when either:
    #   - filter_expression is set (selecting a subset of tests naturally
    #     reduces branch coverage below the 94% threshold), or
    #   - no_cov is set (user explicitly opted out of coverage).
    relax_coverage = bool(filter_expression) or no_cov
    cov_gate_args = ["--cov-fail-under=0"] if relax_coverage else []

    overall_exit_code = 0
    run_counter = 0

    for package_dir in testable:
        # Determine what pytest runs are needed for this library.
        #
        # Filter entries split into two categories:
        #   - "global" (no file specified): combined with `or` into a
        #     single pytest invocation across the whole tests/ dir.
        #   - "file-scoped" (library/file/expression): each gets its own
        #     pytest invocation targeting a specific test file.
        #
        # Each invocation writes to a unique COVERAGE_FILE to avoid
        # overwriting coverage data from other runs.
        if per_library is not None:
            entries = per_library.get(package_dir.name, [])

            # Split into file-scoped and global entries.
            global_expressions = [
                expression for file_name, expression in entries
                if file_name is None
            ]
            file_entries = [
                (file_name, expression) for file_name, expression in entries
                if file_name is not None
            ]

            # Global expressions combine into a single run.
            runs: list[tuple[str, str]] = []
            if global_expressions:
                test_path = str((package_dir / "tests").relative_to(ROOT))
                combined = " or ".join(global_expressions)
                runs.append((test_path, combined))

            # File-scoped entries each get their own run.
            for file_name, expression in file_entries:
                test_file = package_dir / "tests" / f"{file_name}.py"
                if not test_file.exists():
                    relative_path = test_file.relative_to(ROOT)
                    print(f"Test file not found: {relative_path}")
                    return 1
                runs.append((str(test_file.relative_to(ROOT)), expression))
        else:
            # No filter — run the entire tests/ directory.
            test_path = str((package_dir / "tests").relative_to(ROOT))
            runs = [(test_path, "")]

        for test_target, expression in runs:
            extra_args: list[str] = []
            if expression:
                extra_args.extend(["-k", expression])
            if exit_first:
                extra_args.append("-x")
            if verbose:
                extra_args.append("-v")

            cov_args = [] if no_cov else coverage_args_for([package_dir])

            # Unique coverage file per run.
            coverage_name = f".coverage.{package_dir.name}.{run_counter}"
            run_env = {**env, "COVERAGE_FILE": str(ROOT / coverage_name)}
            run_counter += 1

            exit_code = _run(
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
            if exit_code not in (0, 5):
                overall_exit_code = exit_code

    # Combine per-library coverage into one data file and report.
    if not no_cov and list(ROOT.glob(".coverage.*")):
        _run([PYTHON, "-m", "coverage", "combine"])

        report_args = [PYTHON, "-m", "coverage", "report", "--show-missing"]
        if relax_coverage:
            report_args.append("--fail-under=0")

        report_exit_code = _run(report_args)
        if report_exit_code != 0 and overall_exit_code == 0:
            overall_exit_code = report_exit_code

    return overall_exit_code


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


def docs(package_dirs: list[Path], *, serve: bool = False) -> int:
    """Build docs for selected libraries using Zensical.

    If *serve* is True, starts a live-reload dev server for the first
    selected library instead of building static output.

    The build captures stderr and fails if griffe emits any warnings
    (e.g. missing or malformed docstring type annotations).  This
    enforces Decision 0021 (docstring type policy).
    """
    # Keep only packages that have a mkdocs.yml
    doc_dirs = [
        package_dir for package_dir in package_dirs
        if (package_dir / "mkdocs.yml").exists()
    ]
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    copy_shared_docs_assets(doc_dirs)

    if serve:
        # Serve the first selected library
        library_dir = doc_dirs[0]
        relative_path = library_dir.relative_to(ROOT)
        print(f"Serving docs for {relative_path} (Ctrl+C to stop)...")
        return _run(
            [PYTHON, "-m", "zensical", "serve",
             "-f", str(library_dir / "mkdocs.yml")],
        )

    overall_exit_code = 0
    for library_dir in doc_dirs:
        relative_path = library_dir.relative_to(ROOT)
        site_dir = library_dir / "site"
        print(f"== docs {relative_path} ==")
        command = [
            PYTHON, "-m", "zensical", "build",
            "-f", str(library_dir / "mkdocs.yml"),
        ]
        printable_command = " ".join(command)
        print(f"+ {printable_command}")
        completed = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
        )
        # Print stdout/stderr so the user sees build progress.
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="")

        if completed.returncode != 0:
            print(f"Docs build failed: {relative_path}")
            overall_exit_code = completed.returncode
        else:
            # Fail on griffe warnings (Decision 0021).
            griffe_warnings = [
                line for line in completed.stderr.splitlines()
                if "griffe" in line.lower()
            ]
            if griffe_warnings:
                print(f"Docs build has griffe warnings: {relative_path}")
                for warning in griffe_warnings:
                    print(f"  {warning}")
                overall_exit_code = 1
            else:
                print(f"  Built: {site_dir.relative_to(ROOT)}/")

    return overall_exit_code


def docs_preview(package_dirs: list[Path]) -> int:
    """Build docs from the current working tree and serve a local preview.

    The preview branch is seeded from ``gh-pages`` (if it exists) so that
    already-deployed stable versions appear alongside the current working
    tree content.  The working tree is then deployed on top as
    ``dev`` / ``experimental``.

    For each library, ``mike deploy`` with ``--deploy-prefix`` mirrors the
    production layout (Decision 0013).  The landing page is injected via a
    git-plumbing commit.  ``mike serve`` then serves the result.
    """
    preview_branch = "_docs-preview"
    source_branch = "gh-pages"

    doc_dirs = [
        package_dir for package_dir in package_dirs
        if (package_dir / "mkdocs.yml").exists()
    ]
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    copy_shared_docs_assets(doc_dirs)

    # Delete any previous preview branch so we start fresh.
    subprocess.run(
        ["git", "branch", "-D", preview_branch],
        capture_output=True, cwd=ROOT,
    )

    # Fetch the latest gh-pages from origin so the preview reflects
    # recently promoted versions (CI pushes directly to gh-pages).
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", source_branch],
        capture_output=True, cwd=ROOT,
    )
    if fetch_result.returncode == 0:
        # Fast-forward the local tracking branch to match the remote.
        subprocess.run(
            ["git", "branch", "-f", source_branch, f"origin/{source_branch}"],
            capture_output=True, cwd=ROOT,
        )

    # Seed from gh-pages so existing stable/versioned deploys are present.
    # If gh-pages doesn't exist yet, mike's --allow-empty will create the
    # branch from scratch (first-time setup).
    has_source = subprocess.run(
        ["git", "rev-parse", "--verify", source_branch],
        capture_output=True, cwd=ROOT,
    ).returncode == 0

    if has_source:
        subprocess.run(
            ["git", "branch", preview_branch, source_branch],
            capture_output=True, cwd=ROOT, check=True,
        )
        print(f"Seeded {preview_branch} from {source_branch}.")

    for library_dir in doc_dirs:
        relative_path = library_dir.relative_to(ROOT)
        library_name = library_dir.name
        print(f"== deploy {relative_path} ==")
        # --deploy-prefix puts each library's docs in a subdirectory
        # (e.g. /timing/) matching the production gh-pages layout.
        # --allow-empty lets mike create the branch from scratch when
        # gh-pages doesn't exist yet.  "dev" is the version label,
        # "experimental" is the URL alias.
        deploy_args = [
            MIKE, "deploy",
            "--deploy-prefix", library_name,
            "-b", preview_branch,
            "-F", str(library_dir / "mkdocs.yml"),
            "--alias-type", "redirect",
            "--update-aliases",
            "dev", "experimental",
        ]
        # Only needed when gh-pages doesn't exist and the branch is new.
        if not has_source:
            deploy_args.append("--allow-empty")

        exit_code = _run(deploy_args)
        if exit_code != 0:
            print(f"Docs deploy failed: {relative_path}")
            return exit_code

    inject_landing_page(preview_branch)

    return _run([
        MIKE, "serve",
        "-b", preview_branch,
        "-F", str(doc_dirs[0] / "mkdocs.yml"),
    ])


def _base_ref_reachable(base_ref: str) -> bool:
    """Return True if *base_ref* is a valid git ref that can be diffed against."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", base_ref],
        capture_output=True, cwd=ROOT, check=False,
    )
    return result.returncode == 0


def preflight(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
) -> int:
    """Run the full check suite that CI requires on every pull request.

    Mirrors the CI matrix as closely as possible on the local machine:
    lint, build, docs (with griffe warning detection), CPython tests,
    example verification, version-check, api-check, MicroPython and
    CircuitPython cross-runtime unit tests.

    Tests run once with the current Python interpreter (CI runs 3.11,
    3.12, and 3.13 separately).  Version-check and api-check require
    ``origin/main`` to be reachable; they skip gracefully if it is not.
    Functional tests are excluded — they require physical hardware.
    """
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    all_packages = discover_package_dirs()

    # version-check and api-check need a base ref to diff against.
    # If origin/main isn't reachable (detached HEAD, no remote, etc.),
    # skip them with a warning rather than crashing preflight.
    base_ref = "origin/main"
    can_diff = _base_ref_reachable(base_ref)

    steps: list[tuple[str, object]] = [
        ("lint", lint),
        ("build", build),
        ("docs", lambda: docs(all_packages)),
        (f"test (python {python_version})", lambda: test_cpython(all_packages)),
        ("verify-examples", lambda: verify_examples(all_packages)),
        ("check-version", check_version),
        ("check-api", check_api),
        (
            "test-micropython-compatibility",
            lambda: test_micropython_compatibility(micropython_binary),
        ),
        (
            "test-circuitpython-compatibility",
            lambda: test_circuitpython_compatibility(circuitpython_binary),
        ),
    ]

    for step_name, step in steps:
        # Skip diff-based checks when the base ref is unreachable.
        if step_name in ("check-version", "check-api") and not can_diff:
            print(f"== {step_name} ==")
            print(f"  SKIP: {base_ref} not reachable (fetch or set --base).")
            continue

        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Preflight failed at: {step_name}")
            return result

    print("Preflight passed — required CI checks should pass.")
    return 0


def prepare_micropython() -> int:
    """Prepare the repository-local MicroPython unix-port runtime."""
    return _prepare_micropython()


def prepare_circuitpython() -> int:
    """Prepare the repository-local CircuitPython unix-port runtime."""
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
    auto-prepares when missing, then runs the compatibility script for libraries
    that target *platform*.
    """
    # Try to find an existing binary (CLI override → repository-local build → PATH).
    # If none is found, build the unix-port automatically on first use.
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
                f"Pass --{platform}-binary <path> and retry."
            )
            return 1

    # Only publishable libraries under libraries/ are tested against
    # non-CPython runtimes.  support/ packages are CPython-only
    # infrastructure and are excluded from cross-runtime validation.
    library_dirs = [
        package_dir for package_dir in discover_package_dirs()
        if package_dir.parent.name == "libraries"
    ]
    platform_libraries = filter_by_platform(library_dirs, platform)
    library_names = [library_dir.name for library_dir in platform_libraries]
    return _run([binary, COMPAT_SCRIPT, *library_names])


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
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
) -> int:
    """Run host tests and cross-runtime unit tests across all proven runtimes."""
    all_packages = discover_package_dirs()
    steps = (
        ("test", lambda: test_cpython(all_packages)),
        (
            "test-micropython-compatibility",
            lambda: test_micropython_compatibility(micropython_binary),
        ),
        (
            "test-circuitpython-compatibility",
            lambda: test_circuitpython_compatibility(circuitpython_binary),
        ),
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
    devices_file = ROOT / "devices.yml"
    if devices_file.exists():
        print(f"Manual device validation remains user-driven. Config: {devices_file}")
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
        "--micropython-binary", metavar="PATH",
        help="path to MicroPython binary (overrides auto-detection)",
    )
    parent.add_argument(
        "--circuitpython-binary", metavar="PATH",
        help="path to CircuitPython binary (overrides auto-detection)",
    )
    return parent


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="python scripts/run.py",
        description="Repository-level task runner for humans, agents, and CI.",
    )
    subparsers = parser.add_subparsers(dest="task")
    scope = _scope_parent()
    binary = _binary_parent()

    # No-arg tasks
    subparsers.add_parser("setup", help="install dependencies and regenerate IDE configuration")
    subparsers.add_parser("sync-ide", help="regenerate IDE configuration files")
    subparsers.add_parser("lint", help="run Ruff across the workspace")
    subparsers.add_parser("build", help="build all publishable packages")
    subparsers.add_parser(
        "preflight", parents=[binary],
        help="lint + test + examples + compatibility + build",
    )
    subparsers.add_parser("prepare-micropython", help="prepare MicroPython unix-port")
    subparsers.add_parser("prepare-circuitpython", help="prepare CircuitPython unix-port")
    subparsers.add_parser(
        "test-micropython-compatibility",
        parents=[binary],
        help="MicroPython cross-runtime unit tests",
    )
    subparsers.add_parser(
        "test-circuitpython-compatibility",
        parents=[binary],
        help="CircuitPython cross-runtime unit tests",
    )
    subparsers.add_parser(
        "test-runtime-matrix",
        parents=[binary],
        help="test all packages on CPython + MicroPython + CircuitPython",
    )
    subparsers.add_parser("test-device", help="device validation information")
    subparsers.add_parser("check-version", help="check VERSION enforcement for changed libraries")
    subparsers.add_parser("check-api", help="check API breakages against last release tag")

    deploy_parser = subparsers.add_parser(
        "docs-deploy",
        help="deploy versioned docs to gh-pages (used by CI)",
    )
    deploy_parser.add_argument(
        "--channel", choices=["experimental", "stable"],
        required=True,
        help="docs channel to deploy",
    )
    deploy_parser.add_argument(
        "--libraries",
        help="comma-separated list of libraries to deploy (default: all)",
    )

    # Scoped tasks
    test_parser = subparsers.add_parser(
        "test", parents=[scope],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="CPython tests (only changed packages by default)",
        epilog=(
            "examples:\n"
            "  run.py test                                                "
            "# changed packages\n"
            "  run.py test --all                                          "
            "# all packages\n"
            "  run.py test -k timing/test_heartbeat                      "
            "# by library and test\n"
            "  run.py test -k timing/test_ticks/ticks_add                "
            "# by library, file, and test\n"
            "  run.py test -k timing/ticks_diff,runner/task_handle  "
            "# per-library filters\n"
            "  run.py test --no-cov -x                                   "
            "# quick, stop on failure"
        ),
    )
    test_parser.add_argument(
        "-k", dest="filter_expression", metavar="FILTER",
        help=(
            "library/test or library/file/test "
            "(comma-separated for multiple)"
        ),
    )
    test_parser.add_argument(
        "-x", "--exit-first", action="store_true",
        help="stop on first failure",
    )
    test_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output",
    )
    test_parser.add_argument(
        "--no-cov", action="store_true",
        help="skip coverage collection",
    )
    subparsers.add_parser("verify-examples", parents=[scope], help="import-check examples")

    docs_parser = subparsers.add_parser("docs", parents=[scope], help="build library docs")
    docs_parser.add_argument(
        "--serve", action="store_true", help="start live-reload dev server",
    )

    subparsers.add_parser(
        "docs-preview", parents=[scope],
        help="deploy docs to local gh-pages and serve versioned site",
    )

    # new-library
    new_library_parser = subparsers.add_parser("new-library", help="scaffold a new library")
    new_library_parser.add_argument("name", help="library name (e.g. gpio)")

    return parser


#: Tasks that accept ``--all`` / ``--libraries`` scope flags and operate
#: on a resolved list of package directories rather than the entire workspace.
_SCOPED_TASKS = frozenset({"test", "verify-examples", "docs", "docs-preview"})


def main(argv: list[str]) -> int:
    """Dispatch a named repository-level task."""
    parser = _build_parser()
    args = parser.parse_args(argv[1:])

    if not args.task:
        parser.print_help()
        return 1

    # --- scoped tasks ---
    if args.task in _SCOPED_TASKS:
        if args.task == "test" and args.filter_expression:
            # -k provides its own library scope via the filter expression,
            # so skip resolve_scope() to avoid a misleading "Running for
            # all packages" message that would immediately be overridden.
            package_dirs = []
        else:
            package_dirs = resolve_scope(
                all_packages=args.all_packages, libraries=args.libraries,
            )
        if args.task == "test":
            return test_cpython(
                package_dirs,
                filter_expression=args.filter_expression,
                exit_first=args.exit_first,
                verbose=args.verbose,
                no_cov=args.no_cov,
            )
        if args.task == "verify-examples":
            return verify_examples(package_dirs)
        if args.task == "docs-preview":
            return docs_preview(package_dirs)
        return docs(package_dirs, serve=args.serve)

    # --- new-library ---
    if args.task == "new-library":
        return new_library(args.name)

    # --- docs-deploy ---
    if args.task == "docs-deploy":
        library_filter = args.libraries.split(",") if args.libraries else None
        return _docs_deploy(args.channel, libraries=library_filter)

    # --- tasks that accept runtime binary overrides ---
    if args.task in {
        "preflight", "test-micropython-compatibility",
        "test-circuitpython-compatibility", "test-runtime-matrix",
    }:
        micropython_binary = args.micropython_binary
        circuitpython_binary = args.circuitpython_binary
        if args.task == "test-micropython-compatibility":
            return test_micropython_compatibility(micropython_binary)
        if args.task == "test-circuitpython-compatibility":
            return test_circuitpython_compatibility(circuitpython_binary)
        if args.task == "test-runtime-matrix":
            return test_runtime_matrix(micropython_binary, circuitpython_binary)
        return preflight(micropython_binary, circuitpython_binary)

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
