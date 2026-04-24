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
from check_whitespace import main as check_whitespace_main
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
    install_workspace,
    resolve_circuitpython_binary,
    resolve_micropython_binary,
    run_command,
)
from validate_mip_install import validate_local_staging, validate_mip_install
from verify_examples import verify_examples
from workspace import (
    ROOT,
    coverage_args_for,
    detect_changed_packages,
    discover_doc_dirs,
    discover_library_dirs,
    discover_package_dirs,
    discover_ruff_paths,
    discover_workbench_dirs,
    filter_by_platform,
    find_publishable_packages,
    is_ref_reachable,
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
    """Install development dependencies, libraries, and IDE configuration.

    Thin CLI wrapper around :func:`shared.install_workspace`, which is the
    single source of truth shared with ``scripts/prepare_workspace.py``.
    See [Decision 0012](../plans/decisions/0012-ide-type-stubs.md) for the
    runtime-pinned type-stub policy.
    """
    return install_workspace()


def lint() -> int:
    """Run Ruff, the single-letter name check, and whitespace checks across all source paths."""
    ruff_result = run_command([PYTHON, "-m", "ruff", "check", *discover_ruff_paths()])
    if ruff_result != 0:
        return ruff_result
    names_result = check_names_main()
    if names_result != 0:
        return names_result
    return check_whitespace_main()


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


def _resolve_filter_and_scope(
    filter_expression: str | None,
    package_dirs: list[Path],
) -> tuple[list[Path], dict[str, list[tuple[str | None, str]]] | None] | None:
    """Narrow ``package_dirs`` and build the per-library filter plan.

    Handles both filter forms:

    - **Bare** (``heartbeat``) — standard pytest ``-k``.  ``package_dirs``
      is untouched; every selected library runs with this expression.
    - **Library-scoped** (``timing/test_heartbeat``) — the named
      libraries replace whatever scope was selected by ``--all`` /
      ``--libraries`` / change detection.

    Args:
        filter_expression: Raw ``-k`` argument, or ``None``.
        package_dirs: Initial scope from the CLI.

    Returns:
        ``(package_dirs, per_library)`` on success, or ``None`` when an
        unknown library was named in a library-scoped filter (the
        caller should return exit code 1; the error message has
        already been printed).
    """
    if not filter_expression:
        return package_dirs, None

    entries = [entry.strip() for entry in filter_expression.split(",") if entry.strip()]
    if entries and all("/" not in entry for entry in entries):
        # Bare pytest-style filter — leave package_dirs alone.
        return package_dirs, {
            package_dir.name: [(None, filter_expression)]
            for package_dir in package_dirs
        }

    # Library-scoped — library names override package_dirs.
    parsed = _parse_library_filters(filter_expression)
    by_name = {package_dir.name: package_dir for package_dir in discover_package_dirs()}
    resolved: list[Path] = []
    for name in parsed:
        if name not in by_name:
            available = ", ".join(sorted(by_name))
            print(f"Unknown library in -k: {name}")
            print(f"Available: {available}")
            return None
        resolved.append(by_name[name])
    return resolved, parsed


def _coverage_gate_args(
    package_name: str,
    *,
    skip_coverage_gate: bool,
    coverage_threshold: int | None,
    elevated_packages: set[str] | None,
) -> list[str]:
    """Return the pytest ``--cov-fail-under`` args for one library.

    When ``elevated_packages`` is set, only those libraries get the
    overridden threshold; the rest fall back to the ``pyproject.toml``
    default (no ``--cov-fail-under`` flag added).
    """
    if skip_coverage_gate:
        return ["--cov-fail-under=0"]
    if coverage_threshold is None:
        return []
    if elevated_packages is None or package_name in elevated_packages:
        return [f"--cov-fail-under={coverage_threshold}"]
    return []


def _plan_test_runs_for_library(
    package_dir: Path,
    per_library: dict[str, list[tuple[str | None, str]]] | None,
) -> list[tuple[str, str]] | None:
    """Build the ordered list of pytest invocations for one library.

    Filter entries split into two categories:

    - **Global** (no file specified) — combined with ``or`` into a single
      pytest invocation across the whole ``tests/`` directory.
    - **File-scoped** (``library/file/expression``) — each gets its own
      pytest invocation targeting a specific test file so coverage data
      stays attributable.

    Args:
        package_dir: The library's root directory.
        per_library: Parsed filter plan keyed by library name, or
            ``None`` to run the entire ``tests/`` directory.

    Returns:
        List of ``(test_target, expression)`` tuples, or ``None`` when
        a file-scoped entry names a test file that doesn't exist (the
        caller should return exit code 1; the error message has
        already been printed).
    """
    test_path = str((package_dir / "tests").relative_to(ROOT))

    if per_library is None:
        return [(test_path, "")]

    entries = per_library.get(package_dir.name, [])
    global_expressions = [
        expression for file_name, expression in entries if file_name is None
    ]
    file_entries = [
        (file_name, expression) for file_name, expression in entries
        if file_name is not None
    ]

    runs: list[tuple[str, str]] = []
    if global_expressions:
        runs.append((test_path, " or ".join(global_expressions)))

    for file_name, expression in file_entries:
        test_file = package_dir / "tests" / f"{file_name}.py"
        if not test_file.exists():
            print(f"Test file not found: {test_file.relative_to(ROOT)}")
            return None
        runs.append((str(test_file.relative_to(ROOT)), expression))

    return runs


def _combine_and_report_coverage(
    *,
    skip_coverage_gate: bool,
    coverage_threshold: int | None,
    elevated_packages: set[str] | None,
    overall_exit_code: int,
) -> int:
    """Combine per-run coverage files, report, and return the final exit code.

    The per-library ``--cov-fail-under`` gates enforced inside the main
    loop are the primary mechanism.  The combined report additionally
    applies the override when every library was held to the same
    threshold (no ``elevated_packages`` scoping) — when it *is* scoped,
    the combined report uses the ``pyproject.toml`` default because
    the unchanged libraries shouldn't be held to the higher bar.
    """
    if not list(ROOT.glob(".coverage.*")):
        return overall_exit_code

    run_command([PYTHON, "-m", "coverage", "combine"])

    report_args = [PYTHON, "-m", "coverage", "report", "--show-missing"]
    if skip_coverage_gate:
        report_args.append("--fail-under=0")
    elif coverage_threshold is not None and elevated_packages is None:
        report_args.append(f"--fail-under={coverage_threshold}")

    report_exit_code = run_command(report_args)
    if report_exit_code == 0 or overall_exit_code != 0:
        return overall_exit_code

    if not skip_coverage_gate:
        print(
            "\nHint: check the Missing column above to find uncovered"
            " lines.  If the gap is in code you didn't change, note it"
            " in your PR — a maintainer can help."
        )
    return report_exit_code


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

    *filter_expression* accepts two forms::

        heartbeat                             # bare pytest -k — applied to all selected libraries
        timing/test_heartbeat                 # library-scoped: by name in one library
        timing/test_ticks/ticks_add           # library-scoped: by file and name
        timing/ticks_diff,runner/task_handle  # comma-separated library-scoped entries

    Bare filters (no ``/``) match vanilla pytest's ``-k`` semantics and
    preserve whatever scope was already selected (``--all``,
    ``--libraries``, or change detection).  Library-scoped filters
    override the scope and target only the named libraries.
    """
    resolved = _resolve_filter_and_scope(filter_expression, package_dirs)
    if resolved is None:
        return 1
    package_dirs, per_library = resolved

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
        runs = _plan_test_runs_for_library(package_dir, per_library)
        if runs is None:
            return 1

        cov_gate_args = _coverage_gate_args(
            package_dir.name,
            skip_coverage_gate=skip_coverage_gate,
            coverage_threshold=coverage_threshold,
            elevated_packages=elevated_packages,
        )

        for test_target, expression in runs:
            extra_args: list[str] = []
            if expression:
                extra_args.extend(["-k", expression])
            if exit_first:
                extra_args.append("-x")
            if verbose:
                extra_args.append("-v")

            cov_args = [] if no_cov else coverage_args_for([package_dir])

            # Unique coverage file per run keeps data attributable.
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

    if no_cov:
        return overall_exit_code
    return _combine_and_report_coverage(
        skip_coverage_gate=skip_coverage_gate,
        coverage_threshold=coverage_threshold,
        elevated_packages=elevated_packages,
        overall_exit_code=overall_exit_code,
    )


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


def _selected_library_dirs(package_dirs: list[Path] | None) -> list[Path]:
    """Return the selected publishable library directories.

    Args:
        package_dirs: Optional scoped package directories from the CLI.
            ``None`` means "all publishable libraries".
    """
    if package_dirs is None:
        return discover_library_dirs()
    libraries_root = ROOT / "libraries"
    return [
        package_dir for package_dir in package_dirs
        if package_dir.parent == libraries_root
    ]


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
    doc_dirs = discover_doc_dirs(package_dirs)
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

    doc_dirs = discover_doc_dirs(package_dirs)
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


def preflight(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    coverage_threshold: int | None = None,
    with_functional: bool = False,
) -> int:
    """Run the full check suite that CI requires on every pull request.

    Mirrors the CI matrix as closely as possible on the local machine:
    lint, build, docs (with griffe warning detection), CPython tests,
    scripts infrastructure tests, example verification, version-check,
    api-check, MicroPython and CircuitPython cross-runtime unit tests.

    Pass *coverage_threshold* to override the ``pyproject.toml`` default
    (85 %).  Agents should pass ``--coverage-threshold 94`` (Decision 0025).

    Tests run once with the current Python interpreter (CI runs 3.11,
    3.12, and 3.13 separately).  Version-check and api-check require
    ``origin/main`` to be reachable; they skip gracefully if it is not.

    Functional tests on real hardware are skipped by default — they
    require a connected board.  Pass *with_functional* to append
    ``test-libraries-functional`` and ``test-workbench-functional``
    (running with ``devices.yml`` defaults) to the end of the sweep.
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
    can_diff = is_ref_reachable(base_reference)

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
            "test-micropython",
            lambda: test_micropython(micropython_binary),
        ),
        (
            "test-circuitpython",
            lambda: test_circuitpython(circuitpython_binary),
        ),
    ]

    if with_functional:
        steps.append(("test-libraries-functional", test_libraries_functional))
        steps.append(("test-workbench-functional", test_workbench_functional))

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
    package_dirs: list[Path] | None = None,
) -> int:
    """Run cross-runtime unit tests for a single runtime.

    Shared implementation for :func:`test_micropython` and
    :func:`test_circuitpython`.  Resolves the binary,
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
    library_dirs = _selected_library_dirs(package_dirs)
    platform_libraries = filter_by_platform(library_dirs, platform)
    if not platform_libraries:
        print(f"No publishable {label} libraries selected for compatibility tests.")
        return 0
    library_names = [library_dir.name for library_dir in platform_libraries]
    return run_command([binary, COMPAT_SCRIPT, *library_names])


def test_micropython(
    binary: str | None = None,
    package_dirs: list[Path] | None = None,
) -> int:
    """Run the cross-runtime unit tests with the MicroPython Unix binary.

    Skips libraries that do not target MicroPython.
    """
    return _test_runtime_compat(
        "micropython", "MicroPython",
        lambda: resolve_micropython_binary(binary), prepare_micropython,
        package_dirs,
    )


def test_circuitpython(
    binary: str | None = None,
    package_dirs: list[Path] | None = None,
) -> int:
    """Run the cross-runtime unit tests with a configured or repo-managed CircuitPython binary.

    Skips libraries that do not target CircuitPython.
    """
    return _test_runtime_compat(
        "circuitpython", "CircuitPython",
        lambda: resolve_circuitpython_binary(binary), prepare_circuitpython,
        package_dirs,
    )


def test_all_runtimes(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    package_dirs: list[Path] | None = None,
) -> int:
    """Run host tests and cross-runtime unit tests across all proven runtimes.

    CPython tests run first (often the source of failures and the
    fastest signal).  The two unix-port compatibility phases then run
    **in parallel** since they're independent subprocess invocations
    against different runtime binaries.  Output is buffered per phase
    and printed when each phase finishes so phase logs don't interleave.
    """
    all_packages = package_dirs if package_dirs is not None else discover_package_dirs()

    print("== test ==")
    cpython_result = test_cpython(all_packages)
    if cpython_result != 0:
        print("Step failed: test")
        return cpython_result

    parallel_phases: tuple[tuple[str, Callable[[], int]], ...] = (
        (
            "test-micropython",
            lambda: test_micropython(
                micropython_binary, package_dirs,
            ),
        ),
        (
            "test-circuitpython",
            lambda: test_circuitpython(
                circuitpython_binary, package_dirs,
            ),
        ),
    )
    return _run_phases_in_parallel(parallel_phases)


def _run_phases_in_parallel(
    phases: tuple[tuple[str, Callable[[], int]], ...],
) -> int:
    """Run the given phases concurrently with buffered output.

    Each phase's print output is captured into a buffer and flushed in
    submission order once all phases complete, so the on-screen log
    reads as if they ran sequentially.  Returns the first non-zero exit
    code (in submission order), or 0 if all phases succeed.
    """
    import contextlib
    import io
    from concurrent.futures import ThreadPoolExecutor

    def run_phase(label: str, work: Callable[[], int]) -> tuple[int, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            try:
                exit_code = work()
            except Exception as error:  # pragma: no cover - defensive
                print(f"Phase {label!r} crashed: {error}")
                exit_code = 1
        return exit_code, buffer.getvalue()

    with ThreadPoolExecutor(max_workers=len(phases)) as executor:
        futures = [
            executor.submit(run_phase, label, work) for label, work in phases
        ]
        results = [future.result() for future in futures]

    first_failure: int = 0
    for (label, _), (exit_code, captured) in zip(phases, results, strict=True):
        print(f"== {label} ==")
        if captured:
            print(captured, end="")
        if exit_code != 0 and first_failure == 0:
            first_failure = exit_code
            print(f"Step failed: {label}")
    return first_failure


def test_functional(
    *,
    verbose: bool = False,
    exit_first: bool = False,
) -> int:
    """Run every hardware-gated functional suite end-to-end.

    Composes :func:`test_libraries_functional` (library code on
    connected MCUs) and :func:`test_workbench_functional` (host-side
    CPython tests that drive a board).  Both phases use ``devices.yml``
    defaults — for narrower runs, call the individual commands directly.
    """
    steps: list[tuple[str, Callable[[], int]]] = [
        ("test-libraries-functional", test_libraries_functional),
        (
            "test-workbench-functional",
            lambda: test_workbench_functional(
                verbose=verbose, exit_first=exit_first,
            ),
        ),
    ]

    for step_name, step in steps:
        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Step failed: {step_name}")
            return result

    return 0


def test_libraries_functional(
    runtime: str | None = None,
    micropython_device: str | None = None,
    circuitpython_device: str | None = None,
    library: str | None = None,
    file_filter: str | None = None,
    function_filter: str | None = None,
    deploy_mode: str | None = None,
) -> int:
    """Run functional tests on connected devices.

    Thin wrapper that invokes ``pytest libraries/<name>/functional_tests/``
    with the ``--chumicro-*`` flags the :mod:`pytest_device` plugin
    exposes.  The plugin owns collection, routing, transport caching,
    and the PR-summary block — the IDE play-button path uses exactly
    the same hooks, so CLI and IDE runs are now byte-for-byte
    equivalent in behavior (device selection, mode overrides,
    reporting).

    Args:
        runtime: Override ``defaults.ide_runtime`` (``micropython`` /
            ``circuitpython`` / ``both``).
        micropython_device: Override ``defaults.micropython`` device ID.
        circuitpython_device: Override ``defaults.circuitpython`` device ID.
        library: Limit to one library's ``functional_tests/``.
        file_filter: Substring added to pytest ``-k`` to narrow by test
            file name.  Composed with *function_filter* via ``and``.
        function_filter: Substring added to pytest ``-k`` to narrow by
            test-function name.  Composed with *file_filter* via ``and``.
        deploy_mode: Override the per-device deploy mode (``ram`` /
            ``flash``).  Falls back to ``devices.yml`` per-device or
            defaults when omitted.

    Returns:
        The pytest exit code — ``0`` on all-pass, ``1`` on failures,
        ``2`` for configuration problems (unknown library, collection
        errors).
    """
    if library is not None:
        library_dir = ROOT / "libraries" / library
        if not (library_dir / "functional_tests").is_dir():
            print(
                f"No functional_tests/ directory found for "
                f"--library {library!r}."
            )
            return 2
        suites = [library_dir / "functional_tests"]
    else:
        suites = [
            library_dir / "functional_tests"
            for library_dir in discover_library_dirs()
            if (library_dir / "functional_tests").is_dir()
        ]
    if not suites:
        print("No functional tests to run.")
        return 0

    keyword_parts: list[str] = []
    if file_filter:
        keyword_parts.append(file_filter)
    if function_filter:
        keyword_parts.append(function_filter)

    command = [PYTHON, "-m", "pytest", *[str(path) for path in suites]]
    if keyword_parts:
        command.extend(["-k", " and ".join(keyword_parts)])
    if runtime is not None:
        command.extend(["--chumicro-runtime", runtime])
    if micropython_device is not None:
        command.extend(["--chumicro-micropython-device", micropython_device])
    if circuitpython_device is not None:
        command.extend(["--chumicro-circuitpython-device", circuitpython_device])
    if deploy_mode is not None:
        command.extend(["--chumicro-deploy-mode", deploy_mode])
    command.extend([
        "--chumicro-pr-summary",
        "--chumicro-pr-summary-command",
        _format_test_libraries_functional_command(
            runtime, micropython_device, circuitpython_device,
            library, file_filter, function_filter, deploy_mode,
        ),
    ])
    return run_command(command, environment=pythonpath_environment())


def _format_test_libraries_functional_command(
    runtime: str | None,
    micropython_device: str | None,
    circuitpython_device: str | None,
    library: str | None,
    file_filter: str | None,
    function_filter: str | None,
    deploy_mode: str | None,
) -> str:
    """Reconstruct the ``test-libraries-functional`` CLI invocation from its args.

    Only includes flags the caller explicitly passed (non-``None`` values)
    so the rendered command matches what the user actually typed.  Used
    by the plugin's PR-summary block to render the ``- Command:`` line.
    """
    parts = ["python scripts/run.py test-libraries-functional"]
    if runtime is not None:
        parts.append(f"--runtime {runtime}")
    if micropython_device is not None:
        parts.append(f"--micropython-device {micropython_device}")
    if circuitpython_device is not None:
        parts.append(f"--circuitpython-device {circuitpython_device}")
    if library is not None:
        parts.append(f"--library {library}")
    if file_filter is not None:
        parts.append(f"--file {file_filter}")
    if function_filter is not None:
        parts.append(f"--function {function_filter}")
    if deploy_mode is not None:
        parts.append(f"--deploy-mode {deploy_mode}")
    return " ".join(parts)


def test_workbench_functional(
    workbench: str | None = None,
    file_filter: str | None = None,
    function_filter: str | None = None,
    verbose: bool = False,
    exit_first: bool = False,
) -> int:
    """Run functional tests for workbench packages against real hardware.

    Counterpart to :func:`test_libraries_functional` for workbench packages.  Each
    ``workbench/<name>/functional_tests/`` directory is a plain
    host-side pytest suite that drives a connected board through the
    public ``chumicro_deploy`` API (or each workbench's own entrypoint)
    — no test-harness plugin routes these, since workbench code is
    CPython-only and talks to hardware itself.

    Device selection happens inside each suite's ``conftest.py``
    (typically by reading ``devices.yml``), so this task exposes no
    runtime or device flags.  Change the default board by editing
    ``devices.yml`` defaults, or pass through the fixtures the test
    suite documents.

    Args:
        workbench: Name of one workbench package (``deploy``, etc.) to
            limit the run to.  ``None`` runs every workbench package
            that ships a ``functional_tests/`` directory.
        file_filter: Substring passed to pytest ``-k`` that narrows
            collection to test files whose filename contains this
            string.  Composed with *function_filter* via ``and``.
        function_filter: Substring passed to pytest ``-k`` that
            narrows collection to test functions whose name contains
            this string.  Composed with *file_filter* via ``and``.
        verbose: Forward ``-v`` to pytest for per-test PASS/FAIL lines.
        exit_first: Forward ``-x`` to pytest so the run stops at the
            first failure.

    Returns:
        ``0`` when every selected suite passes; the first non-zero
        pytest exit code otherwise.  ``0`` with a warning when no
        workbench package has a ``functional_tests/`` directory.
    """
    workbench_dirs = discover_workbench_dirs()
    if workbench is not None:
        workbench_dirs = [
            package_dir for package_dir in workbench_dirs
            if package_dir.name == workbench
        ]
        if not workbench_dirs:
            print(f"No workbench package matches --workbench {workbench!r}.")
            return 1

    suites = [
        package_dir / "functional_tests"
        for package_dir in workbench_dirs
        if (package_dir / "functional_tests").is_dir()
    ]
    if not suites:
        scope = f"--workbench {workbench!r}" if workbench else "any workbench package"
        print(f"No functional_tests/ directory found for {scope}.")
        return 0

    keyword_parts: list[str] = []
    if file_filter:
        keyword_parts.append(file_filter)
    if function_filter:
        keyword_parts.append(function_filter)

    extra_args: list[str] = []
    if exit_first:
        extra_args.append("-x")
    if verbose:
        extra_args.append("-v")
    if keyword_parts:
        extra_args.extend(["-k", " and ".join(keyword_parts)])

    # Unlike host-only ``test``, this task does not pass ``-W error``
    # — hardware-interacting tests routinely surface warnings from
    # upstream libraries (mpremote's mount/unmount leaves a file
    # finalizer; pyserial's cleanup) that are out of our control.
    # Matches ``test-libraries-functional``'s behavior for the same reason.
    first_failure = 0
    environment = pythonpath_environment()
    for suite in suites:
        print(f"== test-workbench-functional ({suite.parent.name}) ==")
        result = run_command(
            [
                PYTHON, "-m", "pytest",
                str(suite),
                *extra_args,
            ],
            environment=environment,
        )
        if result != 0 and first_failure == 0:
            first_failure = result
    return first_failure


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
            package_dir.name for package_dir in discover_library_dirs()
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
    preflight_parser = subparsers.add_parser(
        "preflight", parents=[binary],
        help="lint + test + examples + compatibility + build",
    )
    preflight_parser.add_argument(
        "--coverage-threshold", type=int, metavar="PCT",
        help=(
            "override coverage fail-under percentage "
            "(default: from pyproject.toml)"
        ),
    )
    preflight_parser.add_argument(
        "--with-functional", action="store_true",
        help=(
            "also run test-libraries-functional and "
            "test-workbench-functional after the unit-test phases "
            "(requires connected hardware)"
        ),
    )
    subparsers.add_parser("prepare-micropython", help="prepare MicroPython unix-port")
    subparsers.add_parser("prepare-circuitpython", help="prepare CircuitPython unix-port")
    subparsers.add_parser(
        "prepare-mpy-cross",
        help="build mpy-cross compilers for both runtimes (no unix-port)",
    )
    subparsers.add_parser(
        "test-micropython",
        parents=[scope, binary],
        help="MicroPython cross-runtime unit tests",
    )
    subparsers.add_parser(
        "test-circuitpython",
        parents=[scope, binary],
        help="CircuitPython cross-runtime unit tests",
    )
    subparsers.add_parser(
        "test-all-runtimes",
        parents=[scope, binary],
        help="test all packages on CPython + MicroPython + CircuitPython",
    )
    test_functional_parser = subparsers.add_parser(
        "test-functional",
        description=(
            "Run every hardware-gated functional suite in the workspace: "
            "test-libraries-functional (library code on connected MCUs) "
            "followed by test-workbench-functional (host-side workbench "
            "tests that drive a board).  Both phases use devices.yml "
            "defaults — for narrower runs, use the individual commands."
        ),
        help=(
            "run all hardware-gated functional tests "
            "(libraries + workbench, devices.yml defaults)"
        ),
    )
    test_functional_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output (forwarded to test-workbench-functional)",
    )
    test_functional_parser.add_argument(
        "-x", "--exit-first", action="store_true",
        help="stop the workbench phase on first failure",
    )
    test_libraries_functional_parser = subparsers.add_parser(
        "test-libraries-functional",
        description=(
            "Run functional tests on connected devices. When runtime and "
            "runtime-specific device flags are omitted, the command uses the default target "
            "device(s) from devices.yml. Pass --runtime to override the "
            "runtime set, and --micropython-device / --circuitpython-device "
            "to override the default board for each runtime."
        ),
        help=(
            "run functional tests on connected devices "
            "(uses devices.yml defaults when unfiltered)"
        ),
    )
    test_libraries_functional_parser.add_argument(
        "--runtime",
        choices=["micropython", "circuitpython", "both"],
        help=(
            "override the default runtime set, or use 'both' for the "
            "defaults-backed dual-runtime target set"
        ),
    )
    test_libraries_functional_parser.add_argument(
        "--micropython-device",
        help="override the default MicroPython device ID",
    )
    test_libraries_functional_parser.add_argument(
        "--circuitpython-device",
        help="override the default CircuitPython device ID",
    )
    test_libraries_functional_parser.add_argument(
        "--library",
        help="limit to one library's functional tests",
    )
    test_libraries_functional_parser.add_argument(
        "--file",
        dest="file_filter",
        help="limit to test files whose name contains this substring",
    )
    test_libraries_functional_parser.add_argument(
        "--function",
        dest="function_filter",
        help="limit to test functions whose name contains this substring",
    )
    test_libraries_functional_parser.add_argument(
        "--deploy-mode",
        dest="deploy_mode",
        choices=["ram", "flash"],
        default=None,
        help="deploy mode: ram (default, no flash wear) or flash (persistent). "
             "Overrides the per-device deploy_mode in devices.yml.",
    )
    test_workbench_functional_parser = subparsers.add_parser(
        "test-workbench-functional",
        description=(
            "Run functional tests for workbench packages against "
            "connected hardware.  Counterpart to test-libraries-functional, for "
            "the host-only CPython tools under workbench/ that drive "
            "boards through the public chumicro_deploy API.  Device "
            "selection lives inside each suite's conftest.py — "
            "change the target board via devices.yml defaults."
        ),
        help=(
            "run workbench functional tests "
            "(hardware-gated via devices.yml fixtures)"
        ),
    )
    test_workbench_functional_parser.add_argument(
        "--workbench",
        help="limit to one workbench package (e.g. deploy)",
    )
    test_workbench_functional_parser.add_argument(
        "--file",
        dest="file_filter",
        help="limit to test files whose name contains this substring",
    )
    test_workbench_functional_parser.add_argument(
        "--function",
        dest="function_filter",
        help="limit to test functions whose name contains this substring",
    )
    test_workbench_functional_parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="verbose test output",
    )
    test_workbench_functional_parser.add_argument(
        "-x", "--exit-first", action="store_true",
        help="stop on first failure",
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


def _resolve_optional_scope(args) -> list[Path] | None:
    """Resolve package scope only when explicit scope flags were provided."""
    if args.all_packages or args.libraries:
        return _resolve_scoped_packages(args)
    return None


def main(argv: list[str]) -> int:
    """Dispatch a named repository-level task."""
    parser = _build_parser()
    args = parser.parse_args(argv[1:])

    if not args.task:
        parser.print_help()
        return 1

    # --- scoped tasks (--all / --libraries) ---

    if args.task == "test":
        if args.filter_expression and "/" in args.filter_expression:
            # Library-scoped -k provides its own library scope via the
            # filter expression, so skip resolve_scope() to avoid a
            # misleading "Running for all packages" message that would
            # immediately be overridden.  Bare -k falls through and
            # honors --all / --libraries / change detection.
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
            with_functional=args.with_functional,
        )

    if args.task == "test-micropython":
        package_dirs = _resolve_optional_scope(args)
        return test_micropython(args.micropython_binary, package_dirs)

    if args.task == "test-circuitpython":
        package_dirs = _resolve_optional_scope(args)
        return test_circuitpython(args.circuitpython_binary, package_dirs)

    if args.task == "test-all-runtimes":
        package_dirs = _resolve_optional_scope(args)
        return test_all_runtimes(
            args.micropython_binary, args.circuitpython_binary, package_dirs,
        )

    if args.task == "test-functional":
        return test_functional(
            verbose=args.verbose, exit_first=args.exit_first,
        )

    if args.task == "test-libraries-functional":
        return test_libraries_functional(
            runtime=args.runtime,
            micropython_device=args.micropython_device,
            circuitpython_device=args.circuitpython_device,
            library=args.library,
            file_filter=args.file_filter,
            function_filter=args.function_filter,
            deploy_mode=args.deploy_mode,
        )

    if args.task == "test-workbench-functional":
        return test_workbench_functional(
            workbench=args.workbench,
            file_filter=args.file_filter,
            function_filter=args.function_filter,
            verbose=args.verbose,
            exit_first=args.exit_first,
        )

    # --- no-arg tasks ---
    no_arg: dict[str, Callable[[], int]] = {
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

    if args.task in no_arg:
        return no_arg[args.task]()

    # Defense in depth: argparse rejects unknown subcommands before
    # reaching here, so this branch is unreachable in normal CLI use.
    print(f"Unknown task: {args.task}")  # pragma: no cover
    return 1  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
