"""Hardware-gated functional lanes and the multi-board device sweep."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from repo_layout import (
    ROOT,
    discover_library_dirs,
    discover_workbench_dirs,
    pythonpath_environment,
)
from shared import run_command, stream_subprocess

from run_tasks._dispatch import PYTHON


def test_functional(
    *,
    verbose: bool = False,
    exit_first: bool = False,
) -> int:
    """Run every hardware-gated functional suite end-to-end.

    Composes :func:`test_libraries_functional` (library code on
    connected MCUs) and :func:`test_workbench_functional` (host-side
    CPython tests that drive a board).  Both phases use ``devices.yml``
    defaults.  For narrower runs, call the individual commands directly.
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
    with the ``--chumicro-*`` flags the ``chumicro-pytest-device``
    plugin exposes.  The plugin owns collection, routing, transport
    caching, and the PR-summary block.  The IDE play-button path
    uses exactly the same hooks, so CLI and IDE runs are byte-for-byte
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
        The pytest exit code: ``0`` on all-pass, ``1`` on failures,
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
        command.extend(["--runtime", runtime])
    if micropython_device is not None:
        command.extend(["--micropython-device", micropython_device])
    if circuitpython_device is not None:
        command.extend(["--circuitpython-device", circuitpython_device])
    if deploy_mode is not None:
        command.extend(["--deploy-mode", deploy_mode])
    command.extend([
        "--pr-summary",
        "--pr-summary-command",
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


#: Console marker a wifi demo prints once its first association lands
#: (``WIFI_OK ip=...``).  A freshly-erased ESP32-family board runs RF
#: calibration on its very first wifi association, which can push that
#: one join past the demo driver's WIFI_OK budget; the radio is warm on
#: the immediately-following attempt.  The sweep keys its single
#: first-association retry on a timeout waiting for THIS marker — cold
#: start is a property of the ESP32 family generally, not of any one
#: board or vendor, so no board-quirk table is involved.
_FIRST_ASSOCIATION_MARKER = "WIFI_OK"


def _demo_output_shows_first_association_timeout(output: str) -> bool:
    """True when *output* shows the demo timed out awaiting first association.

    The wifi demo drivers wait on the board's ``WIFI_OK`` marker with a
    fixed budget; a miss raises ``MarkerTimeoutError`` whose message the
    driver prints as ``... waiting for marker 'WIFI_OK'``.  That
    signature is the only cold-start candidate the sweep grants a retry
    — a *later* marker timing out (e.g. ``DEMO_COMPLETE``) is a genuine
    failure and is not retried, so the "cold-start grace" the summary
    reports stays honest.
    """
    return f"waiting for marker '{_FIRST_ASSOCIATION_MARKER}'" in output


def _run_demo_cell(driver: Path, device_id: str) -> tuple[str, str | None]:
    """Run one demo driver against *device_id*, granting one cold-start retry.

    Returns ``(cell, note)``.  ``cell`` is ``"PASS"``, ``"FAIL"``, or
    ``"PASS*"`` (passed only on the cold-start retry); ``note`` is a
    one-line summary footnote when a retry was granted, else ``None``.

    A first attempt that fails specifically on the first-association
    marker timeout (see
    :func:`_demo_output_shows_first_association_timeout`) is retried
    exactly once — the documented "run the sweep twice" bench remedy for
    ESP32-family cold-start RF calibration, automated.  Any other
    failure, and any second failure, is a plain ``FAIL``.  The retry is
    never silent: it announces itself before re-running and is called
    out under the summary table (no-silent-caps).
    """
    command = [PYTHON, str(driver), "--device", device_id]
    environment = pythonpath_environment()
    print(f"+ {' '.join(command)}", flush=True)
    code, output = stream_subprocess(
        command,
        environment=environment,
        on_line=lambda line: print(line, flush=True),
    )
    if code == 0:
        return "PASS", None
    if not _demo_output_shows_first_association_timeout(output):
        return "FAIL", None

    print(
        f"== sweep {device_id} :: demo first-association grace — "
        f"{_FIRST_ASSOCIATION_MARKER} marker timed out on a cold start; "
        f"retrying once against the now-warm radio ==",
        flush=True,
    )
    print(f"+ {' '.join(command)}", flush=True)
    retry_code, _ = stream_subprocess(
        command,
        environment=environment,
        on_line=lambda line: print(line, flush=True),
    )
    if retry_code == 0:
        return "PASS*", f"{device_id}: demo passed on retry (cold-start grace)"
    return "FAIL", (
        f"{device_id}: demo retried once on cold-start grace, still FAIL"
    )


def sweep_devices(
    *,
    device_ids: list[str] | None = None,
    demo: str = "sockets_runner_connector",
    skip_demo: bool = False,
    functional: bool = False,
    skip_workbench: bool = False,
    library: str | None = None,
    deploy_mode: str | None = None,
) -> int:
    """Run the bench-board sweep across every registered device.

    Formalizes the previously ad-hoc four-board pass: for each device
    in ``devices.yml`` (registry order), deploy and run a demo as the
    smoke layer, plus that board's library functional suite when
    ``functional`` is set.  Boards run strictly serially — the bench
    shares serial ports and host-side demo endpoints, so concurrent
    access deadlocks (Decision 0048).  Adding a board to the sweep is
    a ``devices.yml`` entry, not a code change.

    After every per-board cell completes, unless ``skip_workbench`` is
    set, the sweep closes with the workbench functional suites
    (``test_workbench_functional``) against the ``devices.yml`` default
    boards.  That host-side suite is not per-board and had no routine
    caller; folding it into the sweep keeps it from rotting.  It runs
    last so it never contends with the per-board cells for the boards.

    Args:
        device_ids: Limit the sweep to these device IDs (registry
            order is replaced by the given order).  ``None`` sweeps
            every registered device.
        demo: Demo directory name under ``demos/`` whose ``driver.py``
            is the smoke layer.
        skip_demo: Skip the demo layer (requires ``functional`` or the
            workbench phase).
        functional: Also run each board's library functional suite.
        skip_workbench: Skip the closing workbench functional suites.
        library: Limit the functional layer to one library.
        deploy_mode: Deploy-mode override for the functional layer.

    Returns:
        ``0`` when every cell passes, ``1`` on any failure, ``2`` for
        configuration problems (bad device ID, unknown demo, nothing
        to run).
    """
    from chumicro_deploy.config.default import (  # noqa: PLC0415 - deferred heavy import
        DeviceConfigError,
        load_device_registry,
    )

    run_demo = not skip_demo
    if not run_demo and not functional and skip_workbench:
        print(
            "sweep-devices: --skip-demo with --skip-workbench and no "
            "--functional leaves nothing to run."
        )
        return 2

    try:
        devices, _ = load_device_registry(workspace_root=ROOT)
    except DeviceConfigError as error:
        print(f"sweep-devices: {error}")
        return 2

    if device_ids:
        by_id = {entry.identifier: entry for entry in devices}
        unknown = [device_id for device_id in device_ids if device_id not in by_id]
        if unknown:
            print(
                f"sweep-devices: unknown device id(s): {', '.join(unknown)} "
                f"(registered: {', '.join(sorted(by_id))})"
            )
            return 2
        devices = [by_id[device_id] for device_id in device_ids]

    if not devices:
        print("sweep-devices: no devices registered in devices.yml.")
        return 2

    driver = ROOT / "demos" / demo / "driver.py"
    if run_demo and not driver.is_file():
        available = sorted(
            path.parent.name for path in (ROOT / "demos").glob("*/driver.py")
        )
        print(
            f"sweep-devices: no demo named {demo!r} "
            f"(available: {', '.join(available)})"
        )
        return 2

    failed = False
    rows: list[tuple[str, str, str, str, float]] = []
    cold_start_notes: list[str] = []
    for entry in devices:
        demo_cell = "-"
        functional_cell = "-"
        started = time.monotonic()
        # flush=True on the cell headers: with stdout redirected to a
        # file the parent's prints are block-buffered while the child
        # writes the inherited fd directly, so an unflushed header
        # would land *after* the child output it introduces.
        if run_demo:
            print(f"== sweep {entry.identifier} :: demo {demo} ==", flush=True)
            demo_cell, cold_start_note = _run_demo_cell(driver, entry.identifier)
            failed = failed or demo_cell == "FAIL"
            if cold_start_note is not None:
                cold_start_notes.append(cold_start_note)
        if functional:
            print(f"== sweep {entry.identifier} :: functional ==", flush=True)
            device_kwargs = {f"{entry.runtime}_device": entry.identifier}
            code = test_libraries_functional(
                runtime=entry.runtime,
                library=library,
                deploy_mode=deploy_mode,
                **device_kwargs,
            )
            functional_cell = "PASS" if code == 0 else "FAIL"
            failed = failed or code != 0
        rows.append((
            entry.identifier,
            entry.runtime,
            demo_cell,
            functional_cell,
            time.monotonic() - started,
        ))

    if not skip_workbench:
        # Runs only after every per-board cell above: the workbench
        # suites drive the same boards, so strict serial discipline
        # keeps them from contending for the shared serial ports.
        # flush=True for the same block-buffering reason as the cell
        # headers above — the header must precede the child output.
        print(
            "== sweep workbench-functional (devices.yml defaults) ==",
            flush=True,
        )
        started = time.monotonic()
        code = test_workbench_functional()
        rows.append((
            "workbench-functional",
            "defaults",
            "-",
            "PASS" if code == 0 else "FAIL",
            time.monotonic() - started,
        ))
        failed = failed or code != 0

    print("== sweep summary ==")
    width = max(len("device"), *(len(identifier) for identifier, *_ in rows))
    print(f"{'device':<{width}}  {'runtime':<13} {'demo':<5} {'functional':<10} elapsed")
    for identifier, runtime, demo_cell, functional_cell, elapsed in rows:
        print(
            f"{identifier:<{width}}  {runtime:<13} {demo_cell:<5} "
            f"{functional_cell:<10} {elapsed:.0f}s"
        )
    # A ``PASS*`` cell above means the demo timed out on its first
    # association and passed on the automatic retry; spell that out so
    # the grace is never a silent cap on the reported result.
    for note in cold_start_notes:
        print(f"* {note}")
    return 1 if failed else 0


def _library_has_cross_runtime_unit_suite(library_dir: Path) -> bool:
    """True when ``library_dir/tests`` holds a device-unit-eligible file.

    A file is eligible for the on-device sweep when its in-file
    markers put it in the device lane: not CPython-only
    (``__chumicro_runtimes__ = ("cpython",)``) and not host-only
    (``__chumicro_host_only__ = True``).  The lane is read via the
    shared ``chumicro_deploy`` marker predicate, the same one the
    pytest-device collector uses, so this orchestration pre-filter
    and the collector never disagree (no duplicated filename rule).
    """
    from chumicro_deploy import (  # noqa: PLC0415 - deferred heavy import
        is_host_only_test,
        read_runtime_marker,
    )

    tests_dir = library_dir / "tests"
    if not tests_dir.is_dir():
        return False
    for path in tests_dir.glob("test_*.py"):
        if is_host_only_test(path):
            continue
        marker = read_runtime_marker(path)
        if marker is not None and not any(
            name == "circuitpython" or name.startswith("micropython")
            for name in marker
        ):
            # CPython-only (no device runtime in the marker), not swept.
            continue
        return True
    return False


def _library_pip_name(library_dir: Path) -> str:
    """Return the library's ``[project].name`` (the requires_flash key).

    Falls back to the ``chumicro-<dir>`` convention if the pyproject is
    unreadable.  Only used to decide whether the resolution unit is
    itself in the flagged set, so the convention is a safe default.
    """
    import tomllib  # noqa: PLC0415 - deferred; this task is rarely run

    pyproject = library_dir / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            name = tomllib.load(handle).get("project", {}).get("name")
    except (OSError, tomllib.TOMLDecodeError):
        name = None
    return name or f"chumicro-{library_dir.name.replace('_', '-')}"


def test_unit_on_device(
    runtime: str | None = None,
    micropython_device: str | None = None,
    circuitpython_device: str | None = None,
    deploy_mode: str | None = None,
    library: str | None = None,
    per_file: bool = False,
) -> int:
    """Run the cross-runtime *unit* suite on real boards (the sweep).

    For each library, resolves the deploy mode through the one shared
    policy with **own-src** ``staged_files`` scoping (a dependency's
    data file must not poison a light dependent's suite) and the full
    transitive ``requires_flash`` closure, then groups libraries by
    resolved mode and runs each group as one single-mode
    ``--target device-unit`` pytest session per runtime.  A light
    library stays in the fast RAM session.  A ``requires_flash`` or
    data-file library lands in a flash session, where only that
    library's suite switches, not the whole sweep.

    The sweep's last-resort mode preference is **RAM** (its purpose is
    RAM-capable on-device validation; Decision 0047's flash-default
    footgun does not apply to a deliberate dev sweep).  ``--deploy-mode``
    overrides that preference.  Unlike the functional path the sweep
    does not inherit ``devices.yml``'s ``deploy_mode`` (that is tuned
    for app-shaped functional deploys).  Behavioral pass/fail only,
    no coverage gating (``coverage.py`` cannot trace MP / CP bytecode).

    Args:
        runtime: ``micropython`` / ``circuitpython`` / ``both``
            (default: both).
        micropython_device: Override the MicroPython target device ID.
        circuitpython_device: Override the CircuitPython target ID.
        deploy_mode: Override the RAM preference for every library
            (``ram`` / ``flash``).  The per-library rule still applies.
        library: Limit the sweep to one library's unit suite.
        per_file: Soft-reset before each test *file* (not just each
            library) in flash/copy sessions, so a large class-organized
            module runs on a fresh interpreter.  Opt-in, slower, for
            large suites on a 256 KB board.  No-op for RAM sessions
            (they already reset per file).

    Returns:
        ``0`` all-pass, ``1`` test failures, ``2`` configuration
        problems.  Cleanly returns ``0`` when no board is configured
        for a target runtime (matches the functional path).
    """
    from chumicro_deploy import (  # noqa: PLC0415 - deferred heavy import
        DeviceCaps,
        DeviceConfigError,
        find_libraries_requiring_flash,
        load_device_registry,
        resolve_deploy_mode,
    )
    from chumicro_workspace.device_orchestration import (  # noqa: PLC0415
        resolve_library_source_dirs,
    )

    libraries_root = ROOT / "libraries"
    if library is not None:
        candidate = libraries_root / library
        if not _library_has_cross_runtime_unit_suite(candidate):
            print(f"No cross-runtime unit suite for --library {library!r}.")
            return 2
        library_dirs = [candidate]
    else:
        library_dirs = [
            directory
            for directory in discover_library_dirs()
            if _library_has_cross_runtime_unit_suite(directory)
        ]
    if not library_dirs:
        print("No on-device unit suites to run.")
        return 0

    try:
        devices, defaults = load_device_registry(workspace_root=ROOT)
    except DeviceConfigError as error:
        print(f"Skipping on-device unit sweep: {error}")
        return 0
    devices_by_id = {entry.identifier: entry for entry in devices}

    if runtime in (None, "both"):
        target_runtimes = ["micropython", "circuitpython"]
    else:
        target_runtimes = [runtime]
    device_override = {
        "micropython": micropython_device,
        "circuitpython": circuitpython_device,
    }

    configured = deploy_mode or "ram"
    worst_exit = 0
    ran_anything = False

    for target_runtime in target_runtimes:
        device_id = device_override[target_runtime] or getattr(
            defaults, target_runtime,
        )
        device_entry = devices_by_id.get(device_id) if device_id else None
        if device_entry is None:
            print(
                f"No {target_runtime} device configured "
                f"(devices.yml defaults.{target_runtime}); "
                f"skipping its unit sweep.",
            )
            continue

        device_capabilities = DeviceCaps(
            supports_ram_mode=device_entry.supports_ram_mode,
        )
        libraries_by_mode: dict[str, list[Path]] = {}
        for library_dir in library_dirs:
            own_source = library_dir / "src"
            own_files = [
                path.name
                for path in own_source.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            ]
            closure_dirs = resolve_library_source_dirs(
                library_dir, libraries_root=libraries_root,
            )
            mode, message = resolve_deploy_mode(
                configured,
                staged_files=own_files,
                device_caps=device_capabilities,
                requires_flash_libs=find_libraries_requiring_flash(
                    closure_dirs,
                ),
                resolution_unit=_library_pip_name(library_dir),
                force=None,
            )
            if message is not None:
                print(f"[{library_dir.name} → {target_runtime}] {message}")
            libraries_by_mode.setdefault(mode, []).append(library_dir)

        # Flash group before RAM so the slower, wear-incurring session
        # runs first and a RAM-group failure isn't masked by flash I/O.
        for session_mode in ("flash", "ram"):
            group = libraries_by_mode.get(session_mode)
            if not group:
                continue
            ran_anything = True
            command = [
                PYTHON, "-m", "pytest",
                *[str(directory / "tests") for directory in group],
                "--target", "device-unit",
                "--runtime", target_runtime,
                f"--{target_runtime}-device", device_entry.identifier,
                "--deploy-mode", session_mode,
                "--pr-summary",
                "--pr-summary-command",
                (
                    f"python scripts/run.py test-unit-on-device "
                    f"--runtime {target_runtime} "
                    f"--deploy-mode {session_mode}"
                    + (" --per-file" if per_file else "")
                ),
            ]
            if per_file:
                command.append("--per-file")
            print(
                f"== on-device unit sweep: {target_runtime} / "
                f"{session_mode} ({len(group)} libraries) ==",
            )
            exit_code = run_command(
                command, environment=pythonpath_environment(),
            )
            worst_exit = worst_exit or exit_code

    if not ran_anything:
        print("No on-device unit sweep ran (no target devices).")
        return 0
    return worst_exit


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
    public ``chumicro_deploy`` API (or each workbench's own entrypoint).
    No test-harness plugin routes these, since workbench code is
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

    # Unlike host-only ``test``, this task does not pass ``-W error``.
    # Hardware-interacting tests routinely surface warnings from
    # upstream libraries (mpremote's mount/unmount leaves a file
    # finalizer, pyserial's cleanup) that are out of our control.
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


def register(subparsers, parents):
    """Register the functional / device-sweep subcommands."""
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
        help="deploy mode: flash (default, persistent) or ram (no flash wear). "
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
    test_unit_on_device_parser = subparsers.add_parser(
        "test-unit-on-device",
        description=(
            "Run the cross-runtime libraries/<name>/tests suite on real "
            "boards.  Resolves each library's deploy mode (own-src "
            "scoping, RAM-preferred), groups libraries by mode, and "
            "runs one single-mode session per runtime: light libraries "
            "ride a fast RAM session, requires_flash / data-file "
            "libraries land in a flash session.  Behavioral pass/fail "
            "only — no coverage gating."
        ),
        help=(
            "run the cross-runtime unit suite on connected boards "
            "(RAM-preferred, mode-grouped; the on-device unit sweep)"
        ),
    )
    test_unit_on_device_parser.add_argument(
        "--runtime",
        choices=["micropython", "circuitpython", "both"],
        help="runtime set to sweep (default: both)",
    )
    test_unit_on_device_parser.add_argument(
        "--micropython-device",
        help="override the MicroPython target device ID",
    )
    test_unit_on_device_parser.add_argument(
        "--circuitpython-device",
        help="override the CircuitPython target device ID",
    )
    test_unit_on_device_parser.add_argument(
        "--deploy-mode",
        dest="deploy_mode",
        choices=["ram", "flash"],
        default=None,
        help=(
            "override the RAM mode preference for every library "
            "(the per-library requires_flash / data-file rule still "
            "applies); default preference is ram"
        ),
    )
    test_unit_on_device_parser.add_argument(
        "--library",
        help="limit the sweep to one library's unit suite",
    )
    test_unit_on_device_parser.add_argument(
        "--per-file",
        dest="per_file",
        action="store_true",
        help=(
            "soft-reset before each test file (not just each library) "
            "in flash/copy sessions, so a large class-organized module "
            "runs on a fresh interpreter; opt-in, slower, for large "
            "suites on a 256 KB board (no-op for RAM sessions)"
        ),
    )
    sweep_devices_parser = subparsers.add_parser(
        "sweep-devices",
        description=(
            "Run the bench-board sweep across every device registered in "
            "devices.yml, in sequence: a demo deploy+run as the smoke "
            "layer, plus each board's library functional suite with "
            "--functional.  Formalizes the routine multi-board bench pass."
        ),
        help=(
            "run the demo smoke sweep (+ optional functional suite) on "
            "every board in devices.yml"
        ),
    )
    sweep_devices_parser.add_argument(
        "--device",
        action="append",
        dest="device_ids",
        metavar="DEVICE_ID",
        help="limit the sweep to this device id (repeatable)",
    )
    sweep_devices_parser.add_argument(
        "--demo",
        default="sockets_runner_connector",
        help=(
            "demo under demos/ whose driver.py is the smoke layer "
            "(default: sockets_runner_connector)"
        ),
    )
    sweep_devices_parser.add_argument(
        "--skip-demo",
        action="store_true",
        help="skip the demo smoke layer (requires --functional)",
    )
    sweep_devices_parser.add_argument(
        "--functional",
        action="store_true",
        help="also run each board's library functional suite",
    )
    sweep_devices_parser.add_argument(
        "--skip-workbench",
        action="store_true",
        help=(
            "skip the workbench functional suites (deploy/repl/workspace) "
            "that close the sweep"
        ),
    )
    sweep_devices_parser.add_argument(
        "--library",
        help="limit the functional layer to one library",
    )
    sweep_devices_parser.add_argument(
        "--deploy-mode",
        dest="deploy_mode",
        choices=["ram", "flash"],
        default=None,
        help="deploy-mode override for the functional layer",
    )
