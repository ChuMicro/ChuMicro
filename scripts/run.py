"""Repository-level task runner for humans, agents, and CI.

Usage::

    python scripts/run.py <task> [options]

Run ``python scripts/run.py -h`` to see available tasks.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from check_api import main as check_api_main
from check_names import main as check_names_main
from check_version import main as check_version_main
from docs_deploy import (
    MIKE,
    copy_shared_docs_assets,
    docs_deploy,
    inject_landing_page,
)
from ide_sync import sync_ide
from new_library_scaffold import new_library
from prepare_circuitpython import prepare_circuitpython
from prepare_micropython import prepare_micropython
from prepare_mpy_cross import prepare_mpy_cross
from shared import (
    install_command,
    install_editable,
    resolve_circuitpython_binary,
    resolve_micropython_binary,
    run_command,
    runtime_versions,
)
from validate_mip_install import validate_local_staging, validate_mip_install
from verify_examples import verify_examples
from workspace import (
    ROOT,
    coverage_args_for,
    detect_changed_packages,
    discover_package_dirs,
    discover_ruff_paths,
    filter_by_platform,
    find_publishable_packages,
    pythonpath_environment,
    resolve_scope,
)

PYTHON = sys.executable
# Script that runs a library's tests/ directory under a non-CPython interpreter
# (MicroPython or CircuitPython unix-port) to verify cross-runtime compatibility.
COMPAT_SCRIPT = "support/test_harness/run_cross_runtime.py"



# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def setup() -> int:
    """Install development dependencies and regenerate IDE configuration."""
    versions = runtime_versions()
    circuitpython_version = versions["circuitpython"]["version"]
    micropython_version = versions["micropython"]["version"].lstrip("v")

    # Static dependencies come from requirements-dev.txt.  Type stubs for
    # CircuitPython and MicroPython are pinned to the runtime versions
    # in target-runtimes.toml so IDE type-checking matches the actual
    # runtime APIs (Decision 0012).
    requirements_file = str(ROOT / "requirements-dev.txt")
    stubs = [
        f"circuitpython-stubs=={circuitpython_version}",
        f"micropython-esp32-stubs=={micropython_version}.*",
    ]

    result = run_command([*install_command(), "-U", "-r", requirements_file, *stubs])
    if result != 0:
        return result

    result = install_editable()
    if result != 0:
        return result

    return sync_ide()


def lint() -> int:
    """Run Ruff and the single-letter name check across all source paths."""
    ruff_result = run_command([PYTHON, "-m", "ruff", "check", *discover_ruff_paths()])
    if ruff_result != 0:
        return ruff_result
    return check_names_main()


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
    coverage_threshold: int | None = None,
    elevated_packages: set[str] | None = None,
) -> int:
    """Run the CPython test suite for the given packages.

    Runs pytest separately for each package to avoid test-directory name
    collisions (Decision 0009), then combines and reports coverage.  Each
    library must independently meet the coverage threshold unless
    *filter_expression* is set (filtering naturally reduces coverage) or *no_cov*
    skips coverage entirely.

    The default threshold comes from ``pyproject.toml`` (85 % — the human
    baseline).  Pass *coverage_threshold* to override it; agents use 94 %
    (Decision 0025).

    When *elevated_packages* is provided, only those libraries (by name)
    use *coverage_threshold*; all other libraries fall back to the
    ``pyproject.toml`` default.  This lets agents enforce a higher bar on
    the libraries they changed without failing on pre-existing coverage
    in libraries they didn't touch.

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
        parsed = _parse_library_filters(filter_expression)
        # Library prefixes override package_dirs.
        all_package_dirs = discover_package_dirs()
        by_name = {package_dir.name: package_dir for package_dir in all_package_dirs}
        resolved: list[Path] = []
        for name in parsed:
            if name not in by_name:
                available = ", ".join(sorted(by_name))
                print(f"Unknown library in -k: {name}")
                print(f"Available: {available}")
                return 1
            resolved.append(by_name[name])
        package_dirs = resolved
        per_library = parsed

    # Keep only packages that actually have a tests/ directory.
    testable = [package_dir for package_dir in package_dirs if (package_dir / "tests").is_dir()]
    if not testable:
        print("No test directories found for the selected packages.")
        return 0

    environment = pythonpath_environment()

    # Clean stale coverage data so combine starts fresh.  Two globs are
    # needed: `.coverage` (the default combined file) and `.coverage.*`
    # (the per-run files we create below with unique suffixes).
    for coverage_file in ROOT.glob(".coverage"):
        coverage_file.unlink()
    for coverage_file in ROOT.glob(".coverage.*"):
        coverage_file.unlink()

    # Skip coverage enforcement when either:
    #   - filter_expression is set (selecting a subset of tests naturally
    #     reduces branch coverage below the configured threshold), or
    #   - no_cov is set (user explicitly opted out of coverage).
    skip_coverage_gate = bool(filter_expression) or no_cov

    overall_exit_code = 0
    run_counter = 0

    for package_dir in testable:
        # Per-library coverage gate.  When elevated_packages is set, only
        # those libraries get the overridden threshold; the rest fall back
        # to the pyproject.toml default (no --cov-fail-under flag).
        if skip_coverage_gate:
            cov_gate_args = ["--cov-fail-under=0"]
        elif coverage_threshold is not None:
            if elevated_packages is None or package_dir.name in elevated_packages:
                cov_gate_args = [f"--cov-fail-under={coverage_threshold}"]
            else:
                cov_gate_args = []
        else:
            cov_gate_args = []
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
            run_environment = {**environment, "COVERAGE_FILE": str(ROOT / coverage_name)}
            run_counter += 1

            exit_code = run_command(
                [
                    PYTHON, "-m", "pytest",
                    "-W", "error",
                    *cov_args,
                    "--cov-report=",
                    *cov_gate_args,
                    test_target,
                    *extra_args,
                ],
                environment=run_environment,
            )
            # Exit code 5 means no tests were collected (e.g. -k filter
            # matched nothing in this library) — not an error.
            if exit_code not in (0, 5):
                overall_exit_code = exit_code

    # Combine per-library coverage into one data file and report.
    if not no_cov and list(ROOT.glob(".coverage.*")):
        run_command([PYTHON, "-m", "coverage", "combine"])

        report_args = [PYTHON, "-m", "coverage", "report", "--show-missing"]
        if skip_coverage_gate:
            report_args.append("--fail-under=0")
        elif coverage_threshold is not None and elevated_packages is None:
            # Apply the override to the combined report only when all
            # libraries share the same threshold (no elevated_packages
            # scoping).  When elevated_packages is set, per-library gates
            # already enforce the higher bar on changed libraries; the
            # combined report uses the pyproject.toml default.
            report_args.append(f"--fail-under={coverage_threshold}")

        report_exit_code = run_command(report_args)
        if report_exit_code != 0 and overall_exit_code == 0:
            if not skip_coverage_gate:
                print(
                    "\nHint: check the Missing column above to find uncovered"
                    " lines.  If the gap is in code you didn't change, note it"
                    " in your PR — a maintainer can help."
                )
            overall_exit_code = report_exit_code

    return overall_exit_code


def test_scripts(
    *,
    exit_first: bool = False,
    verbose: bool = False,
) -> int:
    """Run pytest on scripts/tests/ — infrastructure test suite.

    Scripts tests run without a per-library coverage gate since scripts
    are subprocess-heavy orchestration code with a different coverage
    profile than publishable library code.
    """
    test_path = "scripts/tests"
    if not (ROOT / test_path).is_dir():
        print("No scripts/tests/ directory found.")
        return 0

    extra_args: list[str] = []
    if exit_first:
        extra_args.append("-x")
    if verbose:
        extra_args.append("-v")

    return run_command(
        [
            PYTHON, "-m", "pytest",
            "-W", "error",
            test_path,
            *extra_args,
        ],
        environment=pythonpath_environment(),
    )


def build() -> int:
    """Build all publishable package distributions.

    Uses ``--no-isolation`` to skip creating fresh virtual environments
    for each build, which dramatically speeds up builds (~10x faster).
    This is safe because the development environment already has
    ``hatchling`` installed via ``requirements-dev.txt``.
    """
    packages = find_publishable_packages()
    if not packages:
        print("No publishable packages found (no VERSION + pyproject.toml pairs).")
        return 1

    for package in packages:
        print(f"== build {package} ==")
        result = run_command([PYTHON, "-m", "build", "--no-isolation", package])
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
    (e.g. missing type annotations or malformed docstrings).  This
    enforces Decision 0021 (type documentation policy).
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
        return run_command(
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

        exit_code = run_command(deploy_args)
        if exit_code != 0:
            print(f"Docs deploy failed: {relative_path}")
            return exit_code

    inject_landing_page(preview_branch)

    return run_command([
        MIKE, "serve",
        "-b", preview_branch,
        "-F", str(doc_dirs[0] / "mkdocs.yml"),
    ])


def _base_ref_reachable(base_reference: str) -> bool:
    """Return True if *base_reference* is a valid git ref that can be diffed against."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", base_reference],
        capture_output=True, cwd=ROOT, check=False,
    )
    return result.returncode == 0


def preflight(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    coverage_threshold: int | None = None,
) -> int:
    """Run the full check suite that CI requires on every pull request.

    Mirrors the CI matrix as closely as possible on the local machine:
    lint, build, docs (with griffe warning detection), CPython tests,
    example verification, version-check, api-check, MicroPython and
    CircuitPython cross-runtime unit tests.

    Pass *coverage_threshold* to override the ``pyproject.toml`` default
    (85 %).  Agents should pass ``--coverage-threshold 94`` (Decision 0025).

    Tests run once with the current Python interpreter (CI runs 3.11,
    3.12, and 3.13 separately).  Version-check and api-check require
    ``origin/main`` to be reachable; they skip gracefully if it is not.
    Functional tests are excluded — they require physical hardware.
    """
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    all_packages = discover_package_dirs()

    # When --coverage-threshold is set, only apply the elevated threshold
    # to libraries the caller actually changed.  Libraries the caller
    # didn't touch keep the pyproject.toml default (85 %).  This prevents
    # agents from failing on pre-existing coverage in human-authored code.
    elevated_packages: set[str] | None = None
    if coverage_threshold is not None:
        changed = detect_changed_packages()
        if changed is not None:
            elevated_packages = {package_dir.name for package_dir in changed}
        # When changed is None (infrastructure change or no diff), all
        # packages are considered "changed" — leave elevated_packages as
        # None so the threshold applies everywhere.

    # version-check and api-check need a base ref to diff against.
    # If origin/main isn't reachable (detached HEAD, no remote, etc.),
    # skip them with a warning rather than crashing preflight.
    base_reference = "origin/main"
    can_diff = _base_ref_reachable(base_reference)

    steps: list[tuple[str, Callable[[], int]]] = [
        ("lint", lint),
        ("build", build),
        ("docs", lambda: docs(all_packages)),
        (
            f"test (python {python_version})",
            lambda: test_cpython(
                all_packages,
                coverage_threshold=coverage_threshold,
                elevated_packages=elevated_packages,
            ),
        ),
        ("test-scripts", test_scripts),
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
            print(f"  SKIP: {base_reference} not reachable (fetch or set --base).")
            continue

        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Preflight failed at: {step_name}")
            return result

    print("Preflight passed — required CI checks should pass.")
    return 0


def _test_runtime_compat(
    platform: str,
    label: str,
    resolve_binary: Callable[[], str | None],
    prepare_function: Callable[[], int],
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
        prepare_result = prepare_function()
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
    return run_command([binary, COMPAT_SCRIPT, *library_names])


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


def test_device(
    runtime: str | None = None,
    device: str | None = None,
    library: str | None = None,
    test_filter: str | None = None,
) -> int:
    """Run functional tests on connected devices.

    Delegates to ``device_testing.test_device`` — see that module for
    the full orchestration logic (Decision 0027).
    """
    from device_testing import test_device as _test_device

    return _test_device(
        runtime=runtime,
        device=device,
        library=library,
        test_filter=test_filter,
    )


def validate_mip(
    bundle_repo: str | None = None,
    libraries: str | None = None,
    micropython_binary: str | None = None,
    staging_dir: str | None = None,
) -> int:
    """Validate mip install and import for bundle packages.

    Tests both .py and .mpy6 formats against a live bundle repository
    or a locally staged bundle directory.
    Requires a MicroPython unix-port binary (auto-detected or explicit).
    """
    library_names = (
        [name.strip() for name in libraries.split(",") if name.strip()]
        if libraries else None
    )
    if library_names is None:
        # Auto-discover publishable libraries.
        library_names = [
            package_dir.name
            for package_dir in discover_package_dirs()
            if package_dir.parent.name == "libraries"
        ]
    if not library_names:
        print("No libraries found to validate.")
        return 1

    if staging_dir:
        return validate_local_staging(
            staging_dir=staging_dir,
            library_names=library_names,
            binary=micropython_binary,
        )

    if bundle_repo:
        return validate_mip_install(
            bundle_repo=bundle_repo,
            library_names=library_names,
            binary=micropython_binary,
        )

    print("Either --bundle-repo or --staging-dir is required.")
    return 1


def check_version() -> int:
    """Check VERSION enforcement for changed libraries (PR check)."""
    return check_version_main([])


def check_api() -> int:
    """Check API breakages against last release tag (PR check)."""
    return check_api_main([])


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
    ).add_argument(
        "--coverage-threshold", type=int, metavar="PCT",
        help=(
            "override coverage fail-under percentage "
            "(default: from pyproject.toml)"
        ),
    )
    subparsers.add_parser("prepare-micropython", help="prepare MicroPython unix-port")
    subparsers.add_parser("prepare-circuitpython", help="prepare CircuitPython unix-port")
    subparsers.add_parser(
        "prepare-mpy-cross",
        help="build mpy-cross compilers for both runtimes (no unix-port)",
    )
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
    test_device_parser = subparsers.add_parser(
        "test-device",
        help="run functional tests on connected devices",
    )
    test_device_parser.add_argument(
        "--runtime",
        choices=["micropython", "circuitpython"],
        help="filter devices by runtime",
    )
    test_device_parser.add_argument(
        "--device",
        help="target a specific device by ID",
    )
    test_device_parser.add_argument(
        "--library",
        help="limit to one library's functional tests",
    )
    test_device_parser.add_argument(
        "--test",
        dest="test_filter",
        help="filter to test files or functions matching this substring",
    )
    subparsers.add_parser("check-version", help="check VERSION enforcement for changed libraries")
    subparsers.add_parser("check-api", help="check API breakages against last release tag")

    validate_mip_parser = subparsers.add_parser(
        "validate-mip",
        help="validate mip install + import against a bundle repo or local staging",
    )
    validate_mip_source = validate_mip_parser.add_mutually_exclusive_group(
        required=True,
    )
    validate_mip_source.add_argument(
        "--bundle-repo",
        help="bundle repository name (e.g. ChuMicro-Bundle-Experimental)",
    )
    validate_mip_source.add_argument(
        "--staging-dir",
        help="path to a locally staged bundle directory",
    )
    validate_mip_parser.add_argument(
        "--libraries",
        help="comma-separated library names (default: all)",
    )
    validate_mip_parser.add_argument(
        "--micropython-binary", metavar="PATH",
        help="path to MicroPython binary (overrides auto-detection)",
    )

    test_scripts_parser = subparsers.add_parser(
        "test-scripts", help="run scripts/ infrastructure tests",
    )
    test_scripts_parser.add_argument(
        "-x", "--exit-first", action="store_true",
        help="stop on first failure",
    )
    test_scripts_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output",
    )

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
    test_parser.add_argument(
        "--coverage-threshold", type=int, metavar="PCT",
        help=(
            "override coverage fail-under percentage "
            "(default: from pyproject.toml)"
        ),
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


def _resolve_scoped_packages(args) -> list[Path]:
    """Resolve package directories for tasks that accept scope flags.

    Args:
        args: Parsed CLI arguments (must have ``all_packages`` and
            ``libraries``).
    """
    return resolve_scope(
        all_packages=args.all_packages, libraries=args.libraries,
    )


def main(argv: list[str]) -> int:
    """Dispatch a named repository-level task."""
    parser = _build_parser()
    args = parser.parse_args(argv[1:])

    if not args.task:
        parser.print_help()
        return 1

    # --- scoped tasks (--all / --libraries) ---

    if args.task == "test":
        if args.filter_expression:
            # -k provides its own library scope via the filter expression,
            # so skip resolve_scope() to avoid a misleading "Running for
            # all packages" message that would immediately be overridden.
            package_dirs = []
        else:
            package_dirs = _resolve_scoped_packages(args)
        return test_cpython(
            package_dirs,
            filter_expression=args.filter_expression,
            exit_first=args.exit_first,
            verbose=args.verbose,
            no_cov=args.no_cov,
            coverage_threshold=args.coverage_threshold,
        )

    if args.task == "verify-examples":
        return verify_examples(_resolve_scoped_packages(args))

    if args.task == "docs":
        return docs(_resolve_scoped_packages(args), serve=args.serve)

    if args.task == "docs-preview":
        return docs_preview(_resolve_scoped_packages(args))

    # --- tasks with specific arguments ---

    if args.task == "new-library":
        return new_library(args.name)

    if args.task == "test-scripts":
        return test_scripts(exit_first=args.exit_first, verbose=args.verbose)

    if args.task == "docs-deploy":
        library_filter = args.libraries.split(",") if args.libraries else None
        return docs_deploy(args.channel, libraries=library_filter)

    if args.task == "validate-mip":
        return validate_mip(
            bundle_repo=args.bundle_repo,
            libraries=args.libraries,
            micropython_binary=args.micropython_binary,
            staging_dir=args.staging_dir,
        )

    if args.task == "preflight":
        return preflight(
            args.micropython_binary,
            args.circuitpython_binary,
            coverage_threshold=args.coverage_threshold,
        )

    if args.task == "test-micropython-compatibility":
        return test_micropython_compatibility(args.micropython_binary)

    if args.task == "test-circuitpython-compatibility":
        return test_circuitpython_compatibility(args.circuitpython_binary)

    if args.task == "test-runtime-matrix":
        return test_runtime_matrix(
            args.micropython_binary, args.circuitpython_binary,
        )

    if args.task == "test-device":
        return test_device(
            runtime=args.runtime,
            device=args.device,
            library=args.library,
            test_filter=args.test_filter,
        )

    # --- no-arg tasks ---
    no_arg = {
        "setup": setup,
        "sync-ide": sync_ide,
        "lint": lint,
        "build": build,
        "prepare-micropython": prepare_micropython,
        "prepare-circuitpython": prepare_circuitpython,
        "prepare-mpy-cross": prepare_mpy_cross,
        "check-version": check_version,
        "check-api": check_api,
    }
    return no_arg[args.task]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
