"""Tests for pr_summary — markdown rendering for the Device testing PR block."""

from __future__ import annotations

from chumicro_deploy import DeviceEntry
from chumicro_pytest_device import pr_summary


def _make_device_result(
    identifier: str = "mp-one",
    runtime: str = "micropython",
    address: str = "/dev/cu.usbmodem1",
    *,
    passed: int = 0,
    failed: int = 0,
    errors: int = 0,
    implementation=None,
    deploy_mode: str = "ram",
    duration_seconds: float = 0.0,
    files=None,
):
    """Build a DeviceRunResult with a synthetic DeviceEntry for tests."""
    device = DeviceEntry(
        identifier=identifier, runtime=runtime, address=address,
    )
    return pr_summary.DeviceRunResult(
        device=device,
        passed=passed, failed=failed, errors=errors,
        implementation=implementation, deploy_mode=deploy_mode,
        duration_seconds=duration_seconds,
        files=list(files) if files is not None else [],
    )


class TestFormatPrSummaryBlock:
    """Tests for _format_pr_summary_block — paste-ready PR markdown."""

    def test_empty_results_still_renders_command_and_zero_total(self) -> None:
        """No devices run → block shows just the command and a bold zero total."""
        block = pr_summary.format_pr_summary_block(
            command="chumicro-workspace test --functional",
            per_device_results=[],
        )
        lines = block.splitlines()
        assert lines[0] == "- Command: `chumicro-workspace test --functional`"
        assert "**Total: 0 passed, 0 failed, 0 errors**" in block
        # No table when there are no devices.
        assert "| Device" not in block

    def test_duration_line_included_when_provided(self) -> None:
        """``Duration:`` line appears right after the Command when passed."""
        block = pr_summary.format_pr_summary_block(
            command="cmd",
            per_device_results=[],
            total_duration_seconds=12.345,
        )
        lines = block.splitlines()
        assert lines[0].startswith("- Command:")
        assert lines[1] == "- Duration: 12.35s"

    def test_single_device_renders_table_row(self) -> None:
        """A device appears as a padded markdown table row with its duration."""
        result = _make_device_result(
            identifier="pico-w", passed=5, duration_seconds=1.5,
        )
        block = pr_summary.format_pr_summary_block(
            command="chumicro-workspace test --functional --runtime micropython",
            per_device_results=[result],
        )
        # Header + separator + data row present.
        assert "| Device" in block
        assert "| Runtime" in block
        assert "| Duration" in block
        assert "---" in block
        # The data row contains the identifier, runtime, mode, counts,
        # and duration.
        data_rows = [
            line for line in block.splitlines()
            if line.startswith("| `pico-w`")
        ]
        assert len(data_rows) == 1
        data_row = data_rows[0]
        assert "MicroPython" in data_row
        assert "ram" in data_row
        assert " 5 " in data_row
        assert "1.50s" in data_row
        # Total follows the table, not embedded in it.
        assert "**Total: 5 passed, 0 failed, 0 errors**" in block

    def test_multiple_devices_sum_into_bold_total(self) -> None:
        """Per-device counts accumulate into the bolded final line."""
        mp_result = _make_device_result(
            identifier="pico-w", passed=4, failed=1,
        )
        cp_result = _make_device_result(
            identifier="s2-mini", runtime="circuitpython",
            address="/dev/cu.usbmodem2",
            passed=3, errors=2, deploy_mode="flash",
        )
        block = pr_summary.format_pr_summary_block(
            command="chumicro-workspace test --functional --runtime both",
            per_device_results=[mp_result, cp_result],
        )
        # Both devices appear as table rows.
        data_rows = [
            line for line in block.splitlines()
            if line.startswith("| `") and ("pico-w" in line or "s2-mini" in line)
        ]
        assert len(data_rows) == 2
        assert "**Total: 7 passed, 1 failed, 2 errors**" in block

    def test_uses_human_friendly_runtime_labels(self) -> None:
        """Internal runtime names render as human labels in the block."""
        block = pr_summary.format_pr_summary_block(
            command="cmd",
            per_device_results=[
                _make_device_result(identifier="x", address="/dev/a"),
                _make_device_result(
                    identifier="y", runtime="circuitpython", address="/dev/b",
                ),
            ],
        )
        assert "MicroPython" in block
        assert "CircuitPython" in block
        # Internal identifiers should NOT leak into the rendered block.
        assert "| micropython " not in block
        assert "| circuitpython " not in block

    def test_probe_result_surfaces_version_and_board(self) -> None:
        """When the probe succeeded, version and machine fill their table columns."""
        from chumicro_deploy import DeviceImplementation

        result = _make_device_result(
            identifier="pico-w", passed=5,
            implementation=DeviceImplementation(
                name="micropython",
                version="1.26.0",
                machine="Raspberry Pi Pico W with RP2040",
            ),
        )
        block = pr_summary.format_pr_summary_block(
            command="chumicro-workspace test --functional",
            per_device_results=[result],
        )
        # Version lives in the Runtime column, machine in the Board column.
        assert "MicroPython 1.26.0" in block
        assert "Raspberry Pi Pico W with RP2040" in block

    def test_probe_result_without_machine_keeps_board_cell_empty(self) -> None:
        """Empty ``machine`` leaves the Board cell blank (not missing)."""
        from chumicro_deploy import DeviceImplementation

        result = _make_device_result(
            identifier="cp", runtime="circuitpython",
            address="/dev/cu.usbmodem2",
            implementation=DeviceImplementation(
                name="circuitpython",
                version="10.1.4",
                machine="",
            ),
        )
        block = pr_summary.format_pr_summary_block(
            command="cmd",
            per_device_results=[result],
        )
        assert "CircuitPython 10.1.4" in block
        # Still a well-formed table row: | `cp` | CircuitPython 10.1.4 |  | ...
        data_row = next(
            line for line in block.splitlines()
            if line.startswith("| `cp`")
        )
        # Exactly 8 data columns + 2 outer borders → 9 pipes.
        assert data_row.count("|") == 9

    def test_deploy_mode_surfaces_even_without_probe(self) -> None:
        """Bare ``test-libraries-functional`` (no probe result) still shows the deploy mode."""
        result = _make_device_result(
            identifier="cp", runtime="circuitpython",
            address="/dev/cu.usbmodem2",
            passed=1, deploy_mode="flash",
        )
        block = pr_summary.format_pr_summary_block(
            command="chumicro-workspace test --functional",
            per_device_results=[result],
        )
        data_row = next(
            line for line in block.splitlines()
            if line.startswith("| `cp`")
        )
        assert " flash " in data_row

    def test_different_devices_can_show_different_modes(self) -> None:
        """Per-device modes render independently so mixed runs are legible."""
        block = pr_summary.format_pr_summary_block(
            command="cmd",
            per_device_results=[
                _make_device_result(identifier="mp", address="/dev/a"),
                _make_device_result(
                    identifier="cp", runtime="circuitpython",
                    address="/dev/b", deploy_mode="flash",
                ),
            ],
        )
        mp_row = next(
            line for line in block.splitlines()
            if line.startswith("| `mp`")
        )
        cp_row = next(
            line for line in block.splitlines()
            if line.startswith("| `cp`")
        )
        assert " ram " in mp_row
        assert " flash " in cp_row

    def test_single_file_run_renders_per_test_table(self) -> None:
        """One file → per-test detail table with status + duration per method."""
        from chumicro_pytest_device.result_parser import TestResult

        files = [pr_summary.FileRunResult(
            library="timing",
            file_name="test_heartbeat.py",
            passed=2,
            failed=1,
            errors=0,
            tests=[
                TestResult(
                    name="test_heartbeat_fires",
                    status="PASS",
                    duration=0.012,
                ),
                TestResult(
                    name="test_heartbeat_resets",
                    status="FAIL",
                    duration=0.008,
                    message="",
                ),
                TestResult(
                    name="test_heartbeat_period",
                    status="PASS",
                    duration=0.002,
                ),
            ],
            duration_seconds=0.045,
        )]
        result = _make_device_result(
            passed=2, failed=1, duration_seconds=1.2, files=files,
        )
        block = pr_summary.format_pr_summary_block(
            command="cmd",
            per_device_results=[result],
        )
        assert "per-test breakdown" in block
        assert "| Test" in block
        assert "| Status" in block
        assert "`test_heartbeat_fires`" in block
        assert "PASS" in block
        assert "FAIL" in block
        assert "12ms" in block
        # Per-file table should NOT appear when only one file ran
        # (the device row + per-test table are enough).
        assert "per-file breakdown" not in block

    def test_multi_file_run_renders_per_file_table(self) -> None:
        """Multiple files → per-file detail table with counts + duration."""
        files = [
            pr_summary.FileRunResult(
                library="timing", file_name="test_heartbeat.py",
                passed=3, failed=0, errors=0, duration_seconds=0.120,
            ),
            pr_summary.FileRunResult(
                library="timing", file_name="test_ticks.py",
                passed=2, failed=0, errors=0, duration_seconds=0.080,
            ),
        ]
        result = _make_device_result(
            passed=5, duration_seconds=0.5, files=files,
        )
        block = pr_summary.format_pr_summary_block(
            command="cmd",
            per_device_results=[result],
        )
        assert "per-file breakdown" in block
        assert "| File" in block
        assert "`timing/test_heartbeat.py`" in block
        assert "`timing/test_ticks.py`" in block
        assert "120ms" in block
        assert "80ms" in block
        # Test-level detail must be suppressed when multiple files run.
        assert "per-test breakdown" not in block

    def test_device_without_files_has_no_detail_section(self) -> None:
        """A device that never ran any file gets no detail section."""
        result = _make_device_result(errors=1, duration_seconds=0.05)
        block = pr_summary.format_pr_summary_block(
            command="cmd",
            per_device_results=[result],
        )
        assert "per-file breakdown" not in block
        assert "per-test breakdown" not in block
        # Summary row still there.
        assert "| `mp-one`" in block


class TestFormatMarkdownTable:
    """Tests for the padded-table helper used by the PR summary."""

    def test_left_alignment_default_pads_right(self) -> None:
        """With no alignments argument, every column pads on the right."""
        table = pr_summary.format_markdown_table(
            headers=["Name", "Value"],
            rows=[["alpha", "1"], ["bravo", "22"]],
        )
        lines = table.splitlines()
        # Header row and two data rows, all the same width → padded.
        row_widths = [len(line) for line in lines]
        assert len(set(row_widths)) == 1
        # Separator is ``|  ---- |`` style — all dashes, no colons.
        separator = lines[1]
        assert ":" not in separator

    def test_right_alignment_adds_trailing_colon_to_separator(self) -> None:
        """``"right"`` alignment marks the separator with a trailing colon."""
        table = pr_summary.format_markdown_table(
            headers=["N"],
            rows=[["1"], ["10"]],
            alignments=["right"],
        )
        # With the 3-char minimum column width, the separator is ``--:``.
        separator = table.splitlines()[1]
        assert " --: " in separator
        # Right-aligned data rows pad on the left (numbers right-justified).
        data_rows = table.splitlines()[2:]
        assert "|   1 |" in data_rows[0]
        assert "|  10 |" in data_rows[1]

    def test_center_alignment_marks_both_ends_of_separator(self) -> None:
        """``"center"`` alignment marks the separator with colons on both ends."""
        table = pr_summary.format_markdown_table(
            headers=["Mode"],
            rows=[["ram"]],
            alignments=["center"],
        )
        separator = table.splitlines()[1]
        # Strip the outer "| " / " |" then check the payload.
        inner = separator[2:-2]
        assert inner.startswith(":")
        assert inner.endswith(":")

    def test_column_widths_respect_max_content(self) -> None:
        """Each column widens to fit its widest cell (header or data)."""
        table = pr_summary.format_markdown_table(
            headers=["Short", "Wider header"],
            rows=[["loooooong value", "x"]],
        )
        # Long data cell in column 0 forces the header to pad:
        # ``| Short           | Wider header |``
        header_row = table.splitlines()[0]
        assert "Short           " in header_row
