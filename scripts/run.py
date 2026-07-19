"""Repository-level task runner for humans, agents, and CI.

Usage::

    python scripts/run.py <task> [options]

Run ``python scripts/run.py -h`` to see available tasks.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import run_tasks
from repo_layout import resolve_scope
from run_tasks._dispatch import _RAW_OUTPUT_ENV_VAR, PYTHON
from run_tasks.bench import bench
from run_tasks.checks import (
    check_api,
    check_dep_graph,
    check_size,
    check_version,
    lint,
    validate_mip,
    verify_demos,
    verify_examples,
)
from run_tasks.docs_build import build, docs, docs_deploy, docs_preview
from run_tasks.env_scaffold import (
    new_library,
    prepare_circuitpython,
    prepare_micropython,
    prepare_mpy_cross,
    setup,
    sync_ide,
)
from run_tasks.functional import (
    sweep_devices,
    test_functional,
    test_libraries_functional,
    test_unit_on_device,
    test_workbench_functional,
)
from run_tasks.preflight import preflight
from run_tasks.testing_cpython import test_cpython, test_scripts
from run_tasks.testing_crossruntime import (
    test_all_runtimes,
    test_circuitpython,
    test_micropython,
)


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
    parents = {"scope": scope, "binary": binary}

    # ``add-device`` is a pass-through shim around ``chumicro-workspace
    # add-device``.  Keeps the mono-repo's ``run.py`` as the single
    # entry-point contributors learn while reusing the workspace
    # package's hardware-probe + three-zone-aware writer.
    # ``parse_known_args`` semantics: every argv after ``add-device``
    # is forwarded verbatim to ``python -m chumicro_workspace
    # add-device <argv>`` so flag drift is impossible.
    subparsers.add_parser(
        "add-device",
        add_help=False,
        help=(
            "register a board in devices.yml (probes hardware identity, "
            "fills in defaults on first registration); pass --help after "
            "the subcommand for the full chumicro-workspace flag list"
        ),
    )

    run_tasks.env_scaffold.register(subparsers, parents)
    run_tasks.checks.register(subparsers, parents)
    run_tasks.docs_build.register(subparsers, parents)
    run_tasks.preflight.register(subparsers, parents)
    run_tasks.testing_crossruntime.register(subparsers, parents)
    run_tasks.functional.register(subparsers, parents)
    run_tasks.bench.register(subparsers, parents)
    run_tasks.testing_cpython.register(subparsers, parents)
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
    # In a CHUMICRO_RAW_OUTPUT child the parent reads our stdout through
    # a pipe, which Python block-buffers.  Plain print() in run_command
    # echoes, the rolled-up summary, and the coverage Hint would then
    # sit in the userspace buffer while grandchild subprocesses (coverage
    # combine/report) write straight to the inherited fd, so the parent's
    # captured transcript shows their output before the command that
    # produced it.  Switch to line buffering so every print flushes at
    # the newline, keeping the transcript in emission order.
    if os.environ.get(_RAW_OUTPUT_ENV_VAR):
        sys.stdout.reconfigure(line_buffering=True)

    # ``add-device`` and ``deploy-example`` are pass-through shims
    # around their workspace counterparts.  Peeled off before argparse
    # so the workspace package's flag sets (which evolve independently
    # of run.py) flow through verbatim.
    if len(argv) >= 2 and argv[1] in ("add-device", "deploy-example"):
        return subprocess.run(
            [PYTHON, "-m", "chumicro_workspace", argv[1], *argv[2:]],
            check=False,
        ).returncode

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
        elevated_packages: set[str] | None = None
        if args.elevated_packages:
            elevated_packages = {
                name.strip()
                for name in args.elevated_packages.split(",")
                if name.strip()
            } or None
        return test_cpython(
            package_dirs,
            filter_expression=args.filter_expression,
            exit_first=args.exit_first,
            verbose=args.verbose,
            no_cov=args.no_cov,
            coverage_threshold=args.coverage_threshold,
            elevated_packages=elevated_packages,
            package_workers=args.package_workers,
            quiet=args.quiet,
            slow_test_threshold_s=args.slow_test_threshold_cpython,
            allow_no_tests=args.allow_no_tests,
        )

    if args.task == "verify-examples":
        return verify_examples(_resolve_scoped_packages(args))

    if args.task == "verify-demos":
        return verify_demos()

    if args.task == "docs":
        return docs(
            _resolve_scoped_packages(args),
            serve=args.serve,
            package_workers=args.package_workers,
            quiet=args.quiet,
        )

    if args.task == "docs-preview":
        return docs_preview(_resolve_scoped_packages(args))

    # --- tasks with specific arguments ---

    if args.task == "new-library":
        return new_library(args.name, workbench=args.workbench)

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
            with_device_unit=args.with_device_unit,
            phase_workers=args.phase_workers,
            package_workers=args.package_workers,
            quiet=args.quiet,
            slow_test_threshold_cpython=args.slow_test_threshold_cpython,
            slow_test_threshold_unix_port=args.slow_test_threshold_unix_port,
        )

    if args.task == "test-micropython":
        package_dirs = _resolve_optional_scope(args)
        return test_micropython(
            args.micropython_binary, package_dirs,
            slow_test_threshold_s=args.slow_test_threshold_unix_port,
        )

    if args.task == "test-circuitpython":
        package_dirs = _resolve_optional_scope(args)
        return test_circuitpython(
            args.circuitpython_binary, package_dirs,
            slow_test_threshold_s=args.slow_test_threshold_unix_port,
        )

    if args.task == "test-all-runtimes":
        package_dirs = _resolve_optional_scope(args)
        return test_all_runtimes(
            args.micropython_binary, args.circuitpython_binary, package_dirs,
            slow_test_threshold_s=args.slow_test_threshold_unix_port,
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

    if args.task == "test-unit-on-device":
        return test_unit_on_device(
            runtime=args.runtime,
            micropython_device=args.micropython_device,
            circuitpython_device=args.circuitpython_device,
            deploy_mode=args.deploy_mode,
            library=args.library,
            per_file=args.per_file,
        )

    if args.task == "sweep-devices":
        return sweep_devices(
            device_ids=args.device_ids,
            demo=args.demo,
            skip_demo=args.skip_demo,
            functional=args.functional,
            skip_workbench=args.skip_workbench,
            library=args.library,
            deploy_mode=args.deploy_mode,
        )

    if args.task == "build":
        return build(package_workers=args.package_workers, quiet=args.quiet)

    if args.task == "check-api":
        return check_api(max_workers=args.max_workers, base=args.base)

    if args.task == "check-version":
        return check_version(base=args.base)

    if args.task == "bench":
        return bench(
            args.micropython_binary,
            args.circuitpython_binary,
            update_baseline=args.update_baseline,
        )

    # --- no-arg tasks ---
    no_arg: dict[str, Callable[[], int]] = {
        "setup": setup,
        "sync-ide": sync_ide,
        "lint": lint,
        "prepare-micropython": prepare_micropython,
        "prepare-circuitpython": prepare_circuitpython,
        "prepare-mpy-cross": prepare_mpy_cross,
        "check-dep-graph": check_dep_graph,
        "check-size": check_size,
    }

    if args.task in no_arg:
        return no_arg[args.task]()

    # Defense in depth: argparse rejects unknown subcommands before
    # reaching here, so this branch is unreachable in normal CLI use.
    print(f"Unknown task: {args.task}")  # pragma: no cover
    return 1  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
