"""Lightweight verification lanes that mostly delegate to sibling scripts."""

from __future__ import annotations

from pathlib import Path

from repo_layout import discover_library_dirs, discover_ruff_paths, is_parked
from shared import run_command

from run_tasks._dispatch import _DEFAULT_PACKAGE_PARALLEL_WORKERS, PYTHON


def lint() -> int:
    """Run Ruff plus the chumicro-specific CHU lint checks.

    Every CHU rule lives in the `chumicro-checks` package; this
    function shells out to its CLI after ruff finishes.
    """
    ruff_result = run_command([PYTHON, "-m", "ruff", "check", *discover_ruff_paths()])
    if ruff_result != 0:
        return ruff_result
    return run_command([PYTHON, "-m", "chumicro_checks"])


def verify_examples(package_dirs: list[Path]) -> int:
    """Verify examples have valid syntax and resolvable imports."""
    from verify_examples import verify_examples as _verify
    return _verify(package_dirs)


def verify_demos() -> int:
    """Compile-check every ``.py`` under ``demos/``."""
    from verify_demos import verify_demos as _verify
    return _verify()


def check_version(*, base: str = "origin/main") -> int:
    """Check VERSION enforcement for changed libraries (PR check)."""
    from check_version import main as check_version_main
    return check_version_main(["--base", base])


def check_api(
    *,
    max_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    base: str = "origin/main",
) -> int:
    """Check API breakages against last release tag (PR check)."""
    from check_api import main as check_api_main
    return check_api_main(
        ["--base", base, "--max-workers", str(max_workers)],
    )


def check_dep_graph() -> int:
    """Verify the committed dependency-graph SVG matches the current
    ``libraries/*/pyproject.toml`` deps.  Fails if a contributor changed
    a library's deps without re-running ``python scripts/render_dep_graph.py``
    and committing the regenerated SVG.
    """
    from render_dep_graph import main as render_dep_graph_main
    return render_dep_graph_main(["--check"])


def check_size() -> int:
    """Fail when a device library outgrows its committed size budget.

    Measures each library's stripped-source and mpy-cross byte
    footprint and compares against the per-library ceilings in
    ``size-budgets.toml``.  Host-only, hermetic (no boards, no network),
    and fast.  FAILs — never skips — when the prepared mpy-cross is
    missing (with the ``prepare-mpy-cross`` remedy).  See
    ``scripts/check_size.py``.
    """
    from check_size import main as check_size_main
    return check_size_main([])


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
        # Auto-discover publishable libraries.  Parked libraries
        # (Decision 0107) are excluded — they are not staged into the
        # bundle, so there is nothing to validate a mip install against.
        library_names = [
            package_dir.name
            for package_dir in discover_library_dirs()
            if not is_parked(package_dir)
        ]
    if not library_names:
        print("No libraries found to validate.")
        return 1

    if staging_dir:
        from validate_mip_install import validate_local_staging
        return validate_local_staging(
            staging_dir=staging_dir,
            library_names=library_names,
            binary=micropython_binary,
        )

    if bundle_repo:
        from validate_mip_install import validate_mip_install
        return validate_mip_install(
            bundle_repo=bundle_repo,
            library_names=library_names,
            binary=micropython_binary,
        )

    print("Either --bundle-repo or --staging-dir is required.")
    return 1


def register(subparsers, parents):
    """Register the verification subcommands."""
    scope = parents["scope"]
    subparsers.add_parser("lint", help="run Ruff across the workspace")
    check_version_parser = subparsers.add_parser(
        "check-version", help="check VERSION enforcement for changed libraries",
    )
    check_version_parser.add_argument(
        "--base", default="origin/main",
        help="git ref to diff against (default: origin/main)",
    )
    check_api_parser = subparsers.add_parser(
        "check-api", help="check API breakages against last release tag",
    )
    check_api_parser.add_argument(
        "--base", default="origin/main",
        help="git ref to detect changed packages (default: origin/main)",
    )
    check_api_parser.add_argument(
        "--max-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent griffe subprocesses "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS})"
        ),
    )
    subparsers.add_parser(
        "check-dep-graph",
        help="verify support/docs/dependency-graph.svg matches current pyproject deps",
    )
    subparsers.add_parser(
        "check-size",
        help="fail when a device library outgrows its size-budgets.toml ceiling",
    )
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
    subparsers.add_parser("verify-examples", parents=[scope], help="import-check examples")
    subparsers.add_parser("verify-demos", help="compile-check the demos/ tree")
