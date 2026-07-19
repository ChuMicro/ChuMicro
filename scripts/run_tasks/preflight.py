"""The ``preflight`` gate: fan out every CI phase as a subprocess, then run
the hardware tail serially in-process."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from repo_layout import detect_changed_packages, is_ref_reachable

from run_tasks._dispatch import (
    _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    _DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
    _DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
    _PhaseResult,
    _pick_dispatcher,
    _preflight_run_parallel_phases,
    _Sink,
    _subcommand_phase_factory,
    _tally_pytest_counts,
)
from run_tasks.functional import (
    test_libraries_functional,
    test_unit_on_device,
    test_workbench_functional,
)

#: Number of trailing transcript lines the failure recap re-prints.
_FAILURE_RECAP_LINES = 40


def _format_preflight_phase_table(
    parallel_specs: Sequence[tuple[str, list[str] | None]],
    phase_results: Sequence[_PhaseResult],
) -> list[str]:
    """Build the per-phase status table in submission order.

    One row per spec: label, ``PASS`` / ``FAIL`` / ``SKIP``, and wall
    seconds.  A spec whose args are ``None`` was skipped (origin/main
    unreachable) and has no :class:`_PhaseResult`; everything else maps
    by label to its result.  Submission order matches the spec list so
    the table reads "lint first, test-circuitpython last" regardless of
    finish order.
    """
    by_label = {result.label: result for result in phase_results}
    label_width = max((len(label) for label, _ in parallel_specs), default=0)
    lines = ["", "Phase summary:"]
    for label, args in parallel_specs:
        if args is None:
            lines.append(f"  {label:<{label_width}}  SKIP")
            continue
        result = by_label.get(label)
        if result is None:
            # Phase never recorded a result (cancelled mid-interrupt).
            lines.append(f"  {label:<{label_width}}  ----")
            continue
        status = "PASS" if result.exit_code == 0 else "FAIL"
        lines.append(
            f"  {label:<{label_width}}  {status}  {result.elapsed_s:6.1f}s",
        )
    return lines


def _format_preflight_failure_recap(
    failing_label: str | None,
    phase_results: Sequence[_PhaseResult],
) -> list[str]:
    """Re-print the failing phase's last lines under a clear header.

    The live interleave stream leaves the root cause hundreds of lines
    above EOF (every later-finishing phase's output piles on top).  This
    pulls the failing phase's last :data:`_FAILURE_RECAP_LINES` captured
    lines back to the tail so a log reader lands on the error.
    """
    if failing_label is None:
        return []
    result = next(
        (phase for phase in phase_results if phase.label == failing_label),
        None,
    )
    if result is None or not result.captured:
        return []
    tail = result.captured.splitlines()[-_FAILURE_RECAP_LINES:]
    return [
        "",
        f"== {failing_label} (failed) — last {len(tail)} lines ==",
        *tail,
    ]


def preflight(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    coverage_threshold: int | None = None,
    with_functional: bool = False,
    with_device_unit: bool = False,
    phase_workers: int | None = None,
    package_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    quiet: bool = False,
    slow_test_threshold_cpython: float = _DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
    slow_test_threshold_unix_port: float = _DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
) -> int:
    """Run the full check suite that CI requires on every pull request.

    Mirrors the CI matrix as closely as possible on the local machine:
    lint, build, docs (with griffe warning detection), CPython tests,
    scripts infrastructure tests, example verification, size-budget
    check, version-check, api-check, MicroPython and CircuitPython
    cross-runtime unit tests.

    The 13 phases run **in parallel** as independent subprocess
    re-invocations of ``python scripts/run.py <subcommand>`` (two of the
    13 — check-version and check-api — skip when ``origin/main`` is
    unreachable).  See Decision 0048 for the design.  Output routing
    depends on the context (Decision 0054): a TTY gets the status
    dispatcher (per-phase events live, failing-phase transcript dumped
    at the end); ``--quiet`` / ``CHUMICRO_OUTPUT_MODE=quiet`` buffers
    and replays each phase under a ``== <label> ==`` header in
    submission order; a redirected / non-TTY stdout (CI, ``preflight >
    out.log``) gets live ``[label]``-prefixed interleave.  After the
    parallel block, every mode prints a per-phase status table and, on
    failure, a recap of the failing phase's last lines so the root
    cause sits at the tail.  The ``--with-functional`` tail stays serial
    because both phases drive the same physical hardware.

    Pass *coverage_threshold* to override the ``pyproject.toml`` default
    (85 %).  Agents should pass ``--coverage-threshold 94`` (Decision 0025).

    Tests run once with the current Python interpreter (CI runs 3.11,
    3.12, and 3.13 separately).  Version-check and api-check require
    ``origin/main`` to be reachable; they skip gracefully if it is not.

    Functional tests on real hardware are skipped by default: they
    require a connected board.  Pass *with_functional* to append
    ``test-libraries-functional`` and ``test-workbench-functional``
    (running with ``devices.yml`` defaults) to the end of the sweep.
    Pass *with_device_unit* to also append ``test-unit-on-device``
    (the cross-runtime unit suite on connected boards) after that,
    likewise serial, since it drives the same hardware.
    """
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

    # When --coverage-threshold is set, only apply the elevated threshold
    # to libraries the caller actually changed.  Libraries the caller
    # didn't touch keep the pyproject.toml default (85 %).  This prevents
    # agents from failing on pre-existing coverage in human-authored code.
    elevated_package_names: list[str] | None = None
    if coverage_threshold is not None:
        changed = detect_changed_packages()
        if changed is not None:
            elevated_package_names = sorted(
                package_dir.name for package_dir in changed
            )
        # When changed is None (infrastructure change or no diff), all
        # packages are considered "changed".  Leave elevated_package_names
        # as None so the threshold applies everywhere.

    # version-check and api-check need a base ref to diff against.
    # If origin/main isn't reachable (detached HEAD, no remote, etc.),
    # skip them with a warning rather than crashing preflight.  We
    # decide reachability here in the parent so the parallel block
    # never sees an unreachable phase.  The skip line prints in the
    # per-phase ordering below.
    base_reference = "origin/main"
    can_diff = is_ref_reachable(base_reference)

    # Build the parallel-phase list.  Order matters for the per-phase
    # status table and the quiet-mode replay, both of which render in
    # submission order, so the log keeps the documented "lint first,
    # test-circuitpython last" shape regardless of which phase finishes
    # first.
    # Forward --package-workers to subcommands whose internal fan-out
    # honors the cap (test, build, docs, check-api).  Phases that don't
    # fan out per-package (lint, test-scripts, verify-examples,
    # check-dep-graph, check-size, check-version, test-micropython,
    # test-circuitpython) ignore it.
    package_workers_args = ["--package-workers", str(package_workers)]
    check_api_workers_args = ["--max-workers", str(package_workers)]

    test_args = [
        "test", "--all", *package_workers_args,
        "--slow-test-threshold-cpython", str(slow_test_threshold_cpython),
    ]
    if coverage_threshold is not None:
        test_args.extend(["--coverage-threshold", str(coverage_threshold)])
    if elevated_package_names is not None:
        test_args.extend(
            ["--elevated-packages", ",".join(elevated_package_names)],
        )

    unix_port_shared_args = [
        "--slow-test-threshold-unix-port", str(slow_test_threshold_unix_port),
    ]

    test_micropython_args = ["test-micropython", *unix_port_shared_args]
    if micropython_binary is not None:
        test_micropython_args.extend(["--micropython-binary", micropython_binary])

    test_circuitpython_args = ["test-circuitpython", *unix_port_shared_args]
    if circuitpython_binary is not None:
        test_circuitpython_args.extend(
            ["--circuitpython-binary", circuitpython_binary],
        )

    parallel_specs: list[tuple[str, list[str] | None]] = [
        ("lint", ["lint"]),
        ("build", ["build", *package_workers_args]),
        ("docs", ["docs", "--all", *package_workers_args]),
        (f"test (python {python_version})", test_args),
        ("test-scripts", ["test-scripts"]),
        ("verify-examples", ["verify-examples", "--all"]),
        ("verify-demos", ["verify-demos"]),
        ("check-dep-graph", ["check-dep-graph"]),
        ("check-size", ["check-size"]),
        ("check-version", ["check-version"] if can_diff else None),
        (
            "check-api",
            ["check-api", *check_api_workers_args] if can_diff else None,
        ),
        ("test-micropython", test_micropython_args),
        ("test-circuitpython", test_circuitpython_args),
    ]

    parallel_phases: list[tuple[str, Callable[[_Sink], int]]] = []
    skipped_phases: list[str] = []
    for label, args in parallel_specs:
        if args is None:
            skipped_phases.append(label)
            continue
        parallel_phases.append(
            (label, _subcommand_phase_factory(label, args)),
        )

    # Print skip notices up-front so the user sees them before the
    # parallel block.  Order: same as in the spec list above.
    for label in skipped_phases:
        print(f"== {label} ==")
        print(f"  SKIP: {base_reference} not reachable (fetch or set --base).")

    dispatcher = _pick_dispatcher(quiet=quiet)
    parallel_result, failing_label, phase_results = _preflight_run_parallel_phases(
        parallel_phases,
        max_workers=phase_workers,
        dispatcher=dispatcher,
    )

    # Print a per-phase status table in submission order so the run's
    # shape is legible at a glance regardless of which dispatcher routed
    # the live stream.  On failure, follow it with a recap of the
    # failing phase's last lines so the root cause sits at EOF instead
    # of buried hundreds of interleaved lines above.
    for line in _format_preflight_phase_table(
        parallel_specs, phase_results,
    ):
        print(line)

    if parallel_result != 0:
        for line in _format_preflight_failure_recap(failing_label, phase_results):
            print(line)
        # Final labeled banner so the failing phase survives
        # interleaved-output schedulers where its [FAIL] line scrolls
        # past the visible tail.
        if failing_label is not None:
            print(f"Preflight failed at: {failing_label}")
        else:
            print("Preflight failed.")  # pragma: no cover - defensive
        return parallel_result

    # Functional tests on real hardware run **after** the parallel
    # block and **serially** between themselves: both phases drive
    # the same boards via devices.yml defaults, so concurrent access
    # would deadlock.  See Decision 0048.
    if with_functional:
        functional_steps: list[tuple[str, Callable[[], int]]] = [
            ("test-libraries-functional", test_libraries_functional),
            ("test-workbench-functional", test_workbench_functional),
        ]
        for step_name, step in functional_steps:
            print(f"== {step_name} ==")
            result = step()
            if result != 0:
                print(f"Preflight failed at: {step_name}")
                return result

    # The on-device unit sweep also drives the boards, so it runs
    # serially here too, after functional, never concurrently.
    if with_device_unit:
        print("== test-unit-on-device ==")
        result = test_unit_on_device()
        if result != 0:
            print("Preflight failed at: test-unit-on-device")
            return result

    total_tests = _tally_pytest_counts(dispatcher.captured_outputs())
    if total_tests > 0:
        print(
            f"Preflight passed.  Required CI checks should pass.  "
            f"{total_tests} tests ran across all phases.",
        )
    else:
        print("Preflight passed.  Required CI checks should pass.")
    return 0


def register(subparsers, parents):
    """Register the preflight subcommand."""
    binary = parents["binary"]
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
    preflight_parser.add_argument(
        "--with-device-unit", action="store_true",
        help=(
            "also run test-unit-on-device (the cross-runtime unit "
            "suite on connected boards) after the functional tail "
            "(requires connected hardware)"
        ),
    )
    preflight_parser.add_argument(
        "--phase-workers", type=int, metavar="N",
        default=None,
        help=(
            "cap on concurrent preflight phases "
            "(default: run every phase at once — the cap controls no real "
            "resource since each phase is a thread streaming a subprocess)"
        ),
    )
    preflight_parser.add_argument(
        "--package-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent per-package subprocesses inside each "
            f"phase that fans out by package "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS} for this host)"
        ),
    )
    preflight_parser.add_argument(
        "--slow-test-threshold-cpython", type=float, metavar="SECONDS",
        default=_DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON,
        help=(
            f"warn-only threshold for surfacing slow CPython unit tests "
            f"(default: {_DEFAULT_SLOW_TEST_THRESHOLD_CPYTHON:.1f}s)"
        ),
    )
    preflight_parser.add_argument(
        "--slow-test-threshold-unix-port", type=float, metavar="SECONDS",
        default=_DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT,
        help=(
            f"warn-only threshold for surfacing slow unix-port tests "
            f"(default: {_DEFAULT_SLOW_TEST_THRESHOLD_UNIX_PORT:.1f}s)"
        ),
    )
    preflight_parser.add_argument(
        "--quiet", action="store_true",
        help=(
            "buffer per-phase output; replay full transcript under "
            "== <phase> == headers in submission order at end "
            "(useful for log capture and agent runs)"
        ),
    )
