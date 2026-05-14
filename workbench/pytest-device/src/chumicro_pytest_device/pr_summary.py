"""Markdown PR-summary rendering for device test runs.

The ``--pr-summary`` hook of the chumicro-pytest-device
plugin consumes per-test reports and feeds
:func:`format_pr_summary_block` a :class:`DeviceRunResult` list
to render the final Markdown block users paste into PRs.

Keep the output stable — it lands in PR bodies and reviewers skim
it at-a-glance.  Any behaviour change here should be paired with a
baseline update on the ``test-libraries-functional`` smoke runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chumicro_deploy import DeviceEntry, DeviceImplementation

from .result_parser import TestResult


@dataclass
class FileRunResult:
    """Results captured for a single test file run on a single device.

    Populated once per ``(device, test_file)`` pair by whichever layer
    drives the run (plugin or CLI).  Used by the PR summary to build
    per-file sub-bullets (or per-test sub-bullets when only one file
    ran on a device).

    Attributes:
        library: Library directory name (e.g. ``"timing"``).
        file_name: Test file name without its path (e.g.
            ``"test_heartbeat.py"``).
        passed: ``summary.total - summary.failed`` from the harness.
        failed: ``summary.failed`` from the harness.
        errors: 1 if the harness produced no summary line, else 0.
        tests: Per-test results emitted by the harness — available so
            single-file runs can show method-level pass/fail.
        duration_seconds: Wall-clock time spent running this file.
    """

    library: str
    file_name: str
    passed: int
    failed: int
    errors: int
    tests: list[TestResult] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    duration_seconds: float = 0.0


@dataclass
class DeviceRunResult:
    """Aggregate results for one device across its whole test plan.

    Returned by whichever layer drives the device tests (plugin or
    CLI).  ``files`` is empty when the device never reached the per-
    file loop (transport creation failure, connect failure, or
    bulk-stage failure).

    Attributes:
        device: The originating :class:`DeviceEntry`.
        passed: Total passing tests across all files.
        failed: Total failing tests across all files.
        errors: Total errors (per-file raises + missing summary lines +
            bulk-stage failures).
        implementation: Probe result, or ``None`` if the probe
            couldn't complete.
        deploy_mode: User-facing deploy mode (``"ram"`` or
            ``"flash"``).
        duration_seconds: Wall-clock time spent on this device,
            measured from transport creation through disconnect.
        files: Per-file results in test-plan order.
    """

    device: DeviceEntry
    passed: int
    failed: int
    errors: int
    implementation: DeviceImplementation | None
    deploy_mode: str
    duration_seconds: float = 0.0
    files: list[FileRunResult] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]


def format_duration(seconds: float) -> str:
    """Format a wall-clock duration for PR summary output.

    Uses ``ms`` for sub-second values so per-test rows stay compact,
    ``s`` otherwise.  Keeps two-digit precision on seconds so readers
    can tell ``0.12s`` apart from ``1.20s``.

    Args:
        seconds: Elapsed seconds (non-negative).

    Returns:
        Short human label (e.g. ``"124ms"``, ``"3.42s"``).
    """
    if seconds < 1.0:
        return f"{int(round(seconds * 1000))}ms"
    return f"{seconds:.2f}s"


def _format_markdown_table(
    headers: list[str],
    rows: list[list[str]],
    alignments: list[str] | None = None,
) -> str:
    """Render a padded markdown table.

    Pads each cell with trailing (or leading, for right-aligned
    columns) spaces so columns align in monospace CLI output; the
    result still parses as a valid GitHub-flavored markdown table.
    The separator row gets a trailing ``:`` for right-aligned
    columns and a leading-plus-trailing ``:`` for centered ones, so
    GitHub renders the intended alignment.

    Args:
        headers: Column headers, one per column.
        rows: Data rows, each a list of strings aligned to *headers*.
        alignments: Per-column ``"left"`` / ``"right"`` / ``"center"``.
            Defaults to all-left.

    Returns:
        Multi-line markdown table string (no trailing newline).
    """
    if alignments is None:
        alignments = ["left"] * len(headers)

    # Column widths: max content width, bumped to a 3-char minimum
    # so the separator row can always render ``---``.
    widths: list[int] = []
    for column in range(len(headers)):
        cell_widths = [len(headers[column])]
        cell_widths.extend(len(row[column]) for row in rows)
        widths.append(max(max(cell_widths), 3))

    def pad(text: str, width: int, alignment: str) -> str:
        if alignment == "right":
            return text.rjust(width)
        if alignment == "center":
            return text.center(width)
        return text.ljust(width)

    def separator(width: int, alignment: str) -> str:
        if alignment == "right":
            return "-" * (width - 1) + ":"
        if alignment == "center":
            return ":" + "-" * (width - 2) + ":"
        return "-" * width

    lines: list[str] = []
    header_cells = [
        pad(headers[column], widths[column], alignments[column])
        for column in range(len(headers))
    ]
    lines.append("| " + " | ".join(header_cells) + " |")
    separator_cells = [
        separator(widths[column], alignments[column])
        for column in range(len(headers))
    ]
    lines.append("| " + " | ".join(separator_cells) + " |")
    for row in rows:
        cells = [
            pad(row[column], widths[column], alignments[column])
            for column in range(len(row))
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


#: Summary table column headers, in render order.
_SUMMARY_HEADERS = [
    "Device", "Runtime", "Board", "Mode",
    "Passed", "Failed", "Errors", "Duration",
]
#: Per-column alignment for the summary table.
_SUMMARY_ALIGNMENTS = [
    "left", "left", "left", "left",
    "right", "right", "right", "right",
]
#: Per-file detail table headers.
_FILE_HEADERS = ["File", "Passed", "Failed", "Errors", "Duration"]
_FILE_ALIGNMENTS = ["left", "right", "right", "right", "right"]
#: Per-test detail table headers.
_TEST_HEADERS = ["Test", "Status", "Duration", "Notes"]
_TEST_ALIGNMENTS = ["left", "left", "right", "left"]


def format_pr_summary_block(
    command: str,
    per_device_results: list[DeviceRunResult],
    total_duration_seconds: float | None = None,
) -> str:
    """Render a markdown block for the PR template's Device testing section.

    Layout::

        - Command: `...`
        - Duration: 12.34s

        | Device | Runtime | Board | Mode | Passed | Failed | Errors | Duration |
        | ... one row per device ...                                           |

        **Total: P passed, F failed, E errors**

        #### `<device>` — per-file breakdown (`<address>`)
        | File | Passed | Failed | Errors | Duration |
        | ... one row per file ...                    |

    Table rows are padded so the block is equally readable in a
    terminal (monospace) and on GitHub (rendered markdown).  A device
    with exactly one file gets a per-test table instead of per-file —
    the PASS / FAIL / SKIP status and duration of each method show so
    single-file runs surface method-level detail.  A device that
    crashed before running anything gets no detail section; its
    summary row is enough.

    Args:
        command: Reconstructed ``test-libraries-functional`` invocation string.
        per_device_results: Per-device :class:`DeviceRunResult`
            instances in the order they ran.
        total_duration_seconds: Total wall-clock time for the whole
            invocation.  ``None`` omits the ``Duration:`` line — used
            by tests that render blocks without timing.

    Returns:
        Multi-line markdown body (no trailing newline).
    """
    lines = [f"- Command: `{command}`"]
    if total_duration_seconds is not None:
        lines.append(f"- Duration: {format_duration(total_duration_seconds)}")

    if per_device_results:
        lines.append("")
        lines.append(_format_markdown_table(
            _SUMMARY_HEADERS,
            [_device_summary_row(device) for device in per_device_results],
            _SUMMARY_ALIGNMENTS,
        ))

    total_passed = sum(device.passed for device in per_device_results)
    total_failed = sum(device.failed for device in per_device_results)
    total_errors = sum(device.errors for device in per_device_results)
    lines.append("")
    lines.append(
        f"**Total: {total_passed} passed, {total_failed} failed, "
        f"{total_errors} errors**"
    )

    for device in per_device_results:
        detail = _format_device_detail_section(device)
        if detail:
            lines.append("")
            lines.append(detail)

    return "\n".join(lines)


def _device_summary_row(device: DeviceRunResult) -> list[str]:
    """Build one row of the device summary table."""
    entry = device.device
    runtime_label = runtime_display_name(entry.runtime)
    implementation = device.implementation
    if implementation is not None and implementation.version:
        runtime_cell = f"{runtime_label} {implementation.version}"
    else:
        runtime_cell = runtime_label
    board_cell = implementation.machine if implementation is not None else ""
    return [
        f"`{entry.identifier}`",
        runtime_cell,
        board_cell,
        device.deploy_mode,
        str(device.passed),
        str(device.failed),
        str(device.errors),
        format_duration(device.duration_seconds),
    ]


def _format_device_detail_section(device: DeviceRunResult) -> str:
    """Render the per-file or per-test detail section for one device.

    Layout rule:

    - 0 files → no detail (device failed before running anything).
    - 1 file with test detail → per-test table.
    - 1 file without test detail (bulk-stage failure, unparsable
      output) → per-file table with the single row so readers see a
      placeholder instead of a missing section.
    - 2+ files → per-file table.
    """
    if not device.files:
        return ""
    heading = _detail_section_heading(device)
    if len(device.files) == 1 and device.files[0].tests:
        return (
            f"{heading}\n"
            + _format_markdown_table(
                _TEST_HEADERS,
                [_test_row(test) for test in device.files[0].tests],
                _TEST_ALIGNMENTS,
            )
        )
    return (
        f"{heading}\n"
        + _format_markdown_table(
            _FILE_HEADERS,
            [_file_row(file_result) for file_result in device.files],
            _FILE_ALIGNMENTS,
        )
    )


def _detail_section_heading(device: DeviceRunResult) -> str:
    """Return the ``#### ...`` heading line for a device's detail section."""
    entry = device.device
    subject = "per-test breakdown" if (
        len(device.files) == 1 and device.files[0].tests
    ) else "per-file breakdown"
    return f"#### `{entry.identifier}` — {subject} (`{entry.address}`)"


def _file_row(file_result: FileRunResult) -> list[str]:
    """One row of the per-file detail table."""
    return [
        f"`{file_result.library}/{file_result.file_name}`",
        str(file_result.passed),
        str(file_result.failed),
        str(file_result.errors),
        format_duration(file_result.duration_seconds),
    ]


def _test_row(test_result: TestResult) -> list[str]:
    """One row of the per-test detail table."""
    duration_cell = (
        format_duration(test_result.duration)
        if test_result.duration is not None else ""
    )
    return [
        f"`{test_result.name}`",
        test_result.status,
        duration_cell,
        test_result.message or "",
    ]


def runtime_display_name(runtime_name: str) -> str:
    """Return a human-friendly runtime label for the PR summary."""
    return {
        "micropython": "MicroPython",
        "circuitpython": "CircuitPython",
    }.get(runtime_name, runtime_name)
