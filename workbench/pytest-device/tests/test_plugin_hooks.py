"""Tests for the chumicro-pytest-device plugin's pytest-hook bodies.

Covers the session-lifecycle and reporting hooks that the IDE-path
tests in ``test_plugin.py`` don't reach: option registration
(``pytest_addoption``), marker wiring (``pytest_configure``), backend +
target resolution (``pytest_sessionstart``), transport teardown plus PR
block emission (``pytest_sessionfinish``), the report-timing /
PR-collector wrapper (``pytest_runtest_makereport``), and the
``_PRSummaryCollector`` accumulator's record / render paths.

These fake pytest's ``Parser`` / ``Config`` / ``Session`` surfaces the
same way the rest of this suite does, rather than spinning up a real
session, so each hook's branches run in isolation.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_deploy.testing import FakeTransport
from chumicro_pytest_device import plugin as pytest_device
from chumicro_pytest_device.backends import UnixPortBackend
from chumicro_pytest_device.device_backend import DeviceBackend
from chumicro_pytest_device.testing import (
    FakeSession,
    hot_path_device,
    make_prepare_item,
    make_run_file_item,
    make_test_item,
    prime_transport_cache,
)
from chumicro_pytest_device.transport_cache import _TransportCache


class _RecordingGroup:
    """Capture every ``addoption(...)`` call as ``(args, kwargs)`` tuples."""

    def __init__(self) -> None:
        self.options: list[tuple[tuple, dict]] = []

    def addoption(self, *args: object, **kwargs: object) -> None:
        self.options.append((args, kwargs))


class _RecordingParser:
    """Stand-in ``pytest.Parser`` that hands back one recording group."""

    def __init__(self) -> None:
        self.group = _RecordingGroup()
        self.group_calls: list[tuple] = []

    def getgroup(self, name: str, description: str | None = None) -> _RecordingGroup:
        self.group_calls.append((name, description))
        return self.group


class _OptionConfig:
    """``pytest.Config`` stand-in whose ``getoption`` reads a fixed map.

    ``rootpath`` is constructor-required so session code that reads
    ``config.rootpath`` resolves to a synthetic dir.  ``getoption``
    returns the value mapped for *name*, falling back to the caller's
    ``default`` for any unmapped option — the same contract real pytest
    options provide.
    """

    def __init__(self, rootpath: Path, options: dict[str, object] | None = None) -> None:
        self.rootpath = rootpath
        self._options = options or {}
        self.stash: dict = {}

    def getoption(self, name: str, default: object = None) -> object:
        return self._options.get(name, default)


class _OptionSession:
    """``pytest.Session`` stand-in carrying an ``_OptionConfig``.

    Holds only ``config``; ``pytest_sessionstart`` writes the transport
    cache, backend, target list, and PR collector as dynamic attributes,
    so tests read those off the instance after the hook runs.
    """

    def __init__(self, config: _OptionConfig) -> None:
        self.config = config


def _option_session(tmp_path: Path, **options: object) -> _OptionSession:
    """Build an ``_OptionSession`` whose config maps the given CLI options."""
    return _OptionSession(_OptionConfig(rootpath=tmp_path, options=options))


class TestPytestAddoption:
    """Tests for pytest_addoption (CLI option registration)."""

    def test_registers_one_chumicro_option_group(self) -> None:
        """All options land in a single ``chumicro`` group with a description."""
        parser = _RecordingParser()
        pytest_device.pytest_addoption(parser)  # type: ignore[arg-type]
        assert parser.group_calls == [("chumicro", "ChuMicro device-test plugin")]

    def test_registers_every_documented_option(self) -> None:
        """The full ``--target`` ... ``--per-file`` option set is registered."""
        parser = _RecordingParser()
        pytest_device.pytest_addoption(parser)  # type: ignore[arg-type]
        registered = {args[0] for args, _kwargs in parser.group.options}
        assert registered == {
            "--target",
            "--runtime",
            "--micropython-device",
            "--circuitpython-device",
            "--micropython-binary",
            "--circuitpython-binary",
            "--unix-port-timeout",
            "--deploy-mode",
            "--pr-summary",
            "--pr-summary-command",
            "--per-file",
        }

    def test_flag_options_are_store_true(self) -> None:
        """``--pr-summary`` and ``--per-file`` register as boolean store_true flags."""
        parser = _RecordingParser()
        pytest_device.pytest_addoption(parser)  # type: ignore[arg-type]
        by_name = {args[0]: kwargs for args, kwargs in parser.group.options}
        assert by_name["--pr-summary"]["action"] == "store_true"
        assert by_name["--pr-summary"]["default"] is False
        assert by_name["--per-file"]["action"] == "store_true"

    def test_target_choices_cover_three_backends(self) -> None:
        """``--target`` constrains to device / device-unit / unix-port, default device."""
        parser = _RecordingParser()
        pytest_device.pytest_addoption(parser)  # type: ignore[arg-type]
        by_name = {args[0]: kwargs for args, kwargs in parser.group.options}
        assert by_name["--target"]["choices"] == (
            "device", "device-unit", "unix-port",
        )
        assert by_name["--target"]["default"] == "device"

    def test_unix_port_timeout_is_a_float_with_generous_default(self) -> None:
        """``--unix-port-timeout`` parses as a float and defaults generously.

        The default matches the backend's own ceiling constant, and it is
        far above the sub-second slowest in-tree unit file so no real file
        trips it.
        """
        from chumicro_pytest_device.backends import (  # noqa: PLC0415
            _DEFAULT_EXECUTE_TIMEOUT_SECONDS,
        )

        parser = _RecordingParser()
        pytest_device.pytest_addoption(parser)  # type: ignore[arg-type]
        by_name = {args[0]: kwargs for args, kwargs in parser.group.options}
        assert by_name["--unix-port-timeout"]["type"] is float
        assert (
            by_name["--unix-port-timeout"]["default"]
            == _DEFAULT_EXECUTE_TIMEOUT_SECONDS
        )
        assert _DEFAULT_EXECUTE_TIMEOUT_SECONDS >= 60


class TestPytestConfigure:
    """Tests for pytest_configure (marker registration)."""

    def test_registers_device_bootstrap_marker(self) -> None:
        """The hook adds a ``device_bootstrap`` markers ini line under markers."""
        recorded: list[tuple[str, str]] = []
        config = SimpleNamespace(
            addinivalue_line=lambda section, line: recorded.append((section, line)),
        )
        pytest_device.pytest_configure(config)  # type: ignore[arg-type]
        assert len(recorded) == 1
        section, line = recorded[0]
        assert section == "markers"
        assert line.startswith("device_bootstrap(board_file):")


class TestPytestSessionstartDeviceTarget:
    """Tests for pytest_sessionstart on the default --target device path."""

    def test_installs_cache_and_device_backend(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """Default target installs a fresh cache plus a DeviceBackend."""
        empty_defaults = SimpleNamespace(
            micropython=None,
            circuitpython=None,
            deploy_mode="flash",
            ide_runtime="both",
        )
        monkeypatch.setattr(
            pytest_device,
            "load_device_registry",
            lambda *, workspace_root: ([], empty_defaults),
        )
        monkeypatch.setattr(
            pytest_device, "resolve_ide_devices", lambda devices, defaults: [],
        )
        session = _option_session(tmp_path)
        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]
        assert isinstance(session._device_transport_cache, _TransportCache)
        assert isinstance(session._backend, DeviceBackend)

    def test_overrides_layer_on_top_of_devices_yml_defaults(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """CLI per-runtime / runtime / deploy-mode overrides win over devices.yml defaults."""
        loaded_defaults = SimpleNamespace(
            micropython="yml-mp",
            circuitpython="yml-cp",
            deploy_mode="flash",
            ide_runtime="both",
        )
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            pytest_device,
            "load_device_registry",
            lambda *, workspace_root: (["dev"], loaded_defaults),
        )

        def _capture_resolve(devices, effective_defaults):
            captured["defaults"] = effective_defaults
            return ["resolved"]

        monkeypatch.setattr(pytest_device, "resolve_ide_devices", _capture_resolve)
        session = _option_session(
            tmp_path,
            **{
                "--runtime": "micropython",
                "--micropython-device": "cli-mp",
                "--circuitpython-device": "cli-cp",
                "--deploy-mode": "ram",
            },
        )

        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]

        effective = captured["defaults"]
        assert effective.micropython == "cli-mp"
        assert effective.circuitpython == "cli-cp"
        assert effective.deploy_mode == "ram"
        assert effective.ide_runtime == "micropython"
        assert session._device_targets == ["resolved"]

    def test_omitted_overrides_preserve_devices_yml_defaults(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """With no CLI flags, the resolved defaults come straight from devices.yml."""
        loaded_defaults = SimpleNamespace(
            micropython="yml-mp",
            circuitpython="yml-cp",
            deploy_mode="flash",
            ide_runtime="circuitpython",
        )
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            pytest_device,
            "load_device_registry",
            lambda *, workspace_root: (["dev"], loaded_defaults),
        )
        monkeypatch.setattr(
            pytest_device,
            "resolve_ide_devices",
            lambda devices, defaults: captured.setdefault("defaults", defaults) or ["x"],
        )
        session = _option_session(tmp_path)

        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]

        effective = captured["defaults"]
        assert effective.micropython == "yml-mp"
        assert effective.circuitpython == "yml-cp"
        assert effective.deploy_mode == "flash"
        assert effective.ide_runtime == "circuitpython"

    def test_missing_devices_yml_sets_targets_none(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """A DeviceConfigError leaves targets None so collection still finishes."""
        from chumicro_deploy import DeviceConfigError

        def _raise(*, workspace_root):
            raise DeviceConfigError("devices.yml not found")

        monkeypatch.setattr(pytest_device, "load_device_registry", _raise)
        session = _option_session(tmp_path)

        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]

        assert session._device_targets is None
        assert isinstance(session._backend, DeviceBackend)


class TestPytestSessionstartUnixPort:
    """Tests for pytest_sessionstart on the --target unix-port path."""

    def test_installs_unix_port_backend_and_synthetic_targets(
        self, tmp_path: Path,
    ) -> None:
        """unix-port target installs UnixPortBackend and synthesizes both runtimes by default."""
        session = _option_session(tmp_path, **{"--target": "unix-port"})
        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]
        assert isinstance(session._backend, UnixPortBackend)
        identifiers = [entry.identifier for entry in session._device_targets]
        assert identifiers == ["micropython-unix-port", "circuitpython-unix-port"]

    def test_runtime_override_narrows_synthetic_targets(
        self, tmp_path: Path,
    ) -> None:
        """``--runtime micropython`` under unix-port yields one synthetic entry."""
        session = _option_session(
            tmp_path, **{"--target": "unix-port", "--runtime": "micropython"},
        )
        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]
        identifiers = [entry.identifier for entry in session._device_targets]
        assert identifiers == ["micropython-unix-port"]

    def test_binary_overrides_passed_to_backend(self, tmp_path: Path) -> None:
        """Per-runtime binary overrides are threaded into the UnixPortBackend."""
        session = _option_session(
            tmp_path,
            **{
                "--target": "unix-port",
                "--micropython-binary": "/opt/mp",
                "--circuitpython-binary": "/opt/cp",
            },
        )
        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]
        backend = session._backend
        assert backend._binary_overrides["micropython"] == "/opt/mp"
        assert backend._binary_overrides["circuitpython"] == "/opt/cp"


class TestPytestSessionstartPrSummary:
    """Tests for the --pr-summary opt-in collector wiring at sessionstart."""

    def test_pr_summary_flag_installs_collector(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """``--pr-summary`` installs a _PRSummaryCollector on the session."""
        session = _option_session(
            tmp_path, **{"--target": "unix-port", "--pr-summary": True},
        )
        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]
        assert isinstance(session._pr_summary, pytest_device._PRSummaryCollector)

    def test_no_pr_summary_flag_leaves_collector_unset(
        self, tmp_path: Path,
    ) -> None:
        """Without the flag, no collector attribute is set (default IDE quiet path)."""
        session = _option_session(tmp_path, **{"--target": "unix-port"})
        pytest_device.pytest_sessionstart(session)  # type: ignore[arg-type]
        assert getattr(session, "_pr_summary", None) is None


class TestPytestSessionfinish:
    """Tests for pytest_sessionfinish (transport teardown + PR block emit)."""

    def test_disconnects_all_transports(self, tmp_path: Path) -> None:
        """The hook calls disconnect_all on the session transport cache."""
        calls: list[str] = []
        cache = SimpleNamespace(disconnect_all=lambda: calls.append("disconnected"))
        session = SimpleNamespace(
            _device_transport_cache=cache,
            _pr_summary=None,
            config=_OptionConfig(rootpath=tmp_path),
        )
        pytest_device.pytest_sessionfinish(session, 0)  # type: ignore[arg-type]
        assert calls == ["disconnected"]

    def test_no_cache_is_a_no_op(self, tmp_path: Path) -> None:
        """A session with no cache attribute finishes without error."""
        session = SimpleNamespace(
            _pr_summary=None, config=_OptionConfig(rootpath=tmp_path),
        )
        pytest_device.pytest_sessionfinish(session, 0)  # type: ignore[arg-type]

    def test_collector_with_no_results_emits_nothing(
        self, tmp_path: Path, capsys,
    ) -> None:
        """An installed collector with zero recorded devices prints no PR block."""
        session = SimpleNamespace(
            _device_transport_cache=SimpleNamespace(disconnect_all=lambda: None),
            _pr_summary=pytest_device._PRSummaryCollector(),
            config=_OptionConfig(rootpath=tmp_path),
        )
        pytest_device.pytest_sessionfinish(session, 0)  # type: ignore[arg-type]
        assert "PR summary" not in capsys.readouterr().out

    def test_collector_with_results_prints_summary_and_block(
        self, tmp_path: Path, capsys,
    ) -> None:
        """A collector with one recorded device prints the summary line and PR block."""
        collector = pytest_device._PRSummaryCollector()
        cache = _TransportCache()
        session = FakeSession(cache, rootpath=tmp_path)
        device = hot_path_device("micropython")
        test_file = (
            tmp_path / "alpha" / "functional_tests" / "test_x.py"
        )
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_one(): pass\n")
        item = make_test_item(session, device, test_file, "test_one")
        report = SimpleNamespace(passed=True, skipped=False, failed=False, duration=0.1)
        collector.record(item, report)  # type: ignore[arg-type]

        finish_session = SimpleNamespace(
            _device_transport_cache=SimpleNamespace(disconnect_all=lambda: None),
            _pr_summary=collector,
            config=_OptionConfig(rootpath=tmp_path),
        )
        pytest_device.pytest_sessionfinish(finish_session, 0)  # type: ignore[arg-type]

        out = capsys.readouterr().out
        assert "Device test summary:" in out
        assert "PR summary" in out

    def test_pr_summary_command_override_is_read(
        self, tmp_path: Path, capsys,
    ) -> None:
        """``--pr-summary-command`` text is rendered into the PR block's command line."""
        collector = pytest_device._PRSummaryCollector()
        cache = _TransportCache()
        session = FakeSession(cache, rootpath=tmp_path)
        device = hot_path_device("circuitpython")
        test_file = tmp_path / "beta" / "functional_tests" / "test_y.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_one(): pass\n")
        item = make_test_item(session, device, test_file, "test_one")
        report = SimpleNamespace(passed=True, skipped=False, failed=False, duration=0.1)
        collector.record(item, report)  # type: ignore[arg-type]

        finish_session = SimpleNamespace(
            _device_transport_cache=SimpleNamespace(disconnect_all=lambda: None),
            _pr_summary=collector,
            config=_OptionConfig(
                rootpath=tmp_path,
                options={"--pr-summary-command": "make test-functional"},
            ),
        )
        pytest_device.pytest_sessionfinish(finish_session, 0)  # type: ignore[arg-type]

        assert "make test-functional" in capsys.readouterr().out


class TestPRSummaryCollectorRecord:
    """Tests for _PRSummaryCollector.record across the item-type branches."""

    @pytest.fixture
    def collector(self) -> pytest_device._PRSummaryCollector:
        return pytest_device._PRSummaryCollector()

    @pytest.fixture
    def session(self, tmp_path: Path) -> FakeSession:
        return FakeSession(_TransportCache(), rootpath=tmp_path)

    def _functional_file(self, tmp_path: Path, library: str = "alpha") -> Path:
        test_file = tmp_path / library / "functional_tests" / "test_x.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_one(): pass\n")
        return test_file

    def test_record_with_no_target_device_is_ignored(
        self, collector, session, tmp_path,
    ) -> None:
        """An item whose target_device is None contributes nothing to the rollup."""
        test_file = self._functional_file(tmp_path)
        item = make_test_item(session, hot_path_device(), test_file, "test_one")
        item.target_device = None
        report = SimpleNamespace(passed=True, skipped=False, failed=False, duration=0.1)
        collector.record(item, report)
        assert collector.render() == []

    def test_record_passing_test_increments_passed(
        self, collector, session, tmp_path,
    ) -> None:
        """A passing DeviceTestItem rolls into the file's passed tally."""
        test_file = self._functional_file(tmp_path)
        item = make_test_item(session, hot_path_device(), test_file, "test_one")
        report = SimpleNamespace(passed=True, skipped=False, failed=False, duration=0.05)
        collector.record(item, report)
        results = collector.render()
        assert len(results) == 1
        assert results[0].passed == 1
        assert results[0].failed == 0

    def test_record_failing_test_increments_failed(
        self, collector, session, tmp_path,
    ) -> None:
        """A failing DeviceTestItem rolls into the file's failed tally."""
        test_file = self._functional_file(tmp_path)
        item = make_test_item(session, hot_path_device(), test_file, "test_one")
        report = SimpleNamespace(passed=False, skipped=False, failed=True, duration=0.05)
        collector.record(item, report)
        results = collector.render()
        assert results[0].failed == 1
        assert results[0].passed == 0

    def test_record_skipped_test_counts_in_neither_total(
        self, collector, session, tmp_path,
    ) -> None:
        """A skipped DeviceTestItem leaves both passed and failed at zero."""
        test_file = self._functional_file(tmp_path)
        item = make_test_item(session, hot_path_device(), test_file, "test_one")
        report = SimpleNamespace(passed=False, skipped=True, failed=False, duration=0.0)
        collector.record(item, report)
        results = collector.render()
        assert results[0].passed == 0
        assert results[0].failed == 0

    def test_record_reported_duration_accumulates_into_file(
        self, collector, session, tmp_path,
    ) -> None:
        """A test's parsed device duration sums into the file's duration_seconds."""
        test_file = self._functional_file(tmp_path)
        item = make_test_item(session, hot_path_device(), test_file, "test_one")
        item.reported_duration = 0.25
        report = SimpleNamespace(passed=True, skipped=False, failed=False, duration=0.05)
        collector.record(item, report)
        rendered = collector.render()
        assert rendered[0].files[0].duration_seconds == pytest.approx(0.25)

    def test_record_failing_prepare_item_counts_bulk_stage_error(
        self, collector, session, tmp_path,
    ) -> None:
        """A failed DevicePrepareItem report counts one bulk-stage error for the device."""
        test_file = self._functional_file(tmp_path)
        item = make_prepare_item(session, hot_path_device(), test_file)
        report = SimpleNamespace(passed=False, skipped=False, failed=True, duration=0.0)
        collector.record(item, report)
        # A prepare error alone produces a device with no files but a
        # nonzero error count once a test item also lands.
        test_item = make_test_item(session, hot_path_device(), test_file, "test_one")
        passing = SimpleNamespace(
            passed=True, skipped=False, failed=False, duration=0.0,
        )
        collector.record(test_item, passing)
        results = collector.render()
        assert results[0].errors == 1

    def test_record_failing_run_file_item_counts_file_error(
        self, collector, session, tmp_path,
    ) -> None:
        """A failed DeviceRunFileItem report sets the file's error count to one."""
        test_file = self._functional_file(tmp_path)
        item = make_run_file_item(session, hot_path_device(), test_file)
        report = SimpleNamespace(passed=False, skipped=False, failed=True, duration=0.0)
        collector.record(item, report)
        results = collector.render()
        assert results[0].errors == 1

    def test_record_probes_implementation_when_transport_present(
        self, collector, session, tmp_path,
    ) -> None:
        """When a transport is cached, record probes its implementation once."""
        device = hot_path_device("micropython")
        transport = FakeTransport(mode="flash", probe_result="micropython")
        prime_transport_cache(session._device_transport_cache, device, transport)
        test_file = self._functional_file(tmp_path)
        item = make_test_item(session, device, test_file, "test_one")
        report = SimpleNamespace(passed=True, skipped=False, failed=False, duration=0.0)
        collector.record(item, report)
        results = collector.render()
        # The canned probe_result flows through record()'s lazy probe
        # onto the rendered device result, and the probe ran exactly once.
        assert results[0].implementation == "micropython"
        probe_calls = [call for call in transport.calls if call[0] == "probe_implementation"]
        assert len(probe_calls) == 1


class TestPRSummaryCollectorRenderAndDuration:
    """Tests for _PRSummaryCollector.render ordering and session_duration."""

    def test_render_orders_files_by_first_encounter(self, tmp_path: Path) -> None:
        """Files appear in the order their first test was recorded."""
        collector = pytest_device._PRSummaryCollector()
        session = FakeSession(_TransportCache(), rootpath=tmp_path)
        device = hot_path_device()

        first = tmp_path / "alpha" / "functional_tests" / "test_a.py"
        first.parent.mkdir(parents=True)
        first.write_text("def test_one(): pass\n")
        second = tmp_path / "alpha" / "functional_tests" / "test_b.py"
        second.write_text("def test_one(): pass\n")

        passing = SimpleNamespace(
            passed=True, skipped=False, failed=False, duration=0.0,
        )
        collector.record(make_test_item(session, device, first, "test_one"), passing)
        collector.record(make_test_item(session, device, second, "test_one"), passing)

        file_names = [file_result.file_name for file_result in collector.render()[0].files]
        assert file_names == ["test_a.py", "test_b.py"]

    def test_session_duration_never_negative(self) -> None:
        """session_duration clamps to zero when end precedes start."""
        collector = pytest_device._PRSummaryCollector()
        collector._session_end = collector._session_start - 5.0
        assert collector.session_duration() == 0.0


class TestPytestRuntestMakereport:
    """Tests for the pytest_runtest_makereport hookwrapper body."""

    def _drive_hookwrapper(self, item, report) -> None:
        """Run the hookwrapper generator the way pytest's hook machinery does."""
        generator = pytest_device.pytest_runtest_makereport(item, None)
        next(generator)
        outcome = SimpleNamespace(get_result=lambda: report)
        try:
            generator.send(outcome)
        except StopIteration:
            pass

    def test_non_device_item_is_left_untouched(self, tmp_path: Path) -> None:
        """A plain pytest item bypasses device timing and the collector."""
        plain_item = SimpleNamespace()
        report = SimpleNamespace(when="call", duration=1.0)
        # No DeviceRuntimeItem attributes, so the body's isinstance gate
        # short-circuits and the report is returned unmodified.
        self._drive_hookwrapper(plain_item, report)
        assert report.duration == 1.0

    def test_device_item_call_report_applies_duration_and_records(
        self, tmp_path: Path,
    ) -> None:
        """A device item's call report gets device timing and feeds the collector."""
        collector = pytest_device._PRSummaryCollector()
        cache = _TransportCache()
        session = FakeSession(cache, rootpath=tmp_path)
        session._pr_summary = collector  # type: ignore[attr-defined]
        device = hot_path_device()
        test_file = tmp_path / "alpha" / "functional_tests" / "test_x.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_one(): pass\n")
        item = make_test_item(session, device, test_file, "test_one")
        item.reported_duration = 0.42
        report = SimpleNamespace(
            when="call", duration=9.9, passed=True, skipped=False, failed=False,
        )

        self._drive_hookwrapper(item, report)

        assert report.duration == pytest.approx(0.42)
        assert collector.render()[0].passed == 1

    def test_device_item_with_no_parsed_timing_keeps_pytest_duration(
        self, tmp_path: Path,
    ) -> None:
        """A device item carrying neither parsed duration leaves the report timing as-is."""
        cache = _TransportCache()
        session = FakeSession(cache, rootpath=tmp_path)
        device = hot_path_device()
        test_file = tmp_path / "alpha" / "functional_tests" / "test_x.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_one(): pass\n")
        item = make_test_item(session, device, test_file, "test_one")
        # make_test_item leaves both reported_duration and
        # reported_test_total_duration None, the "device gave us no
        # timing" branch.
        report = SimpleNamespace(
            when="call", duration=3.3, passed=True, skipped=False, failed=False,
        )

        self._drive_hookwrapper(item, report)

        assert report.duration == pytest.approx(3.3)

    def test_device_item_non_call_phase_does_not_record(
        self, tmp_path: Path,
    ) -> None:
        """A setup-phase report adjusts timing only, never reaching the collector."""
        collector = pytest_device._PRSummaryCollector()
        cache = _TransportCache()
        session = FakeSession(cache, rootpath=tmp_path)
        session._pr_summary = collector  # type: ignore[attr-defined]
        device = hot_path_device()
        test_file = tmp_path / "alpha" / "functional_tests" / "test_x.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_one(): pass\n")
        item = make_test_item(session, device, test_file, "test_one")
        report = SimpleNamespace(when="setup", duration=2.0)

        self._drive_hookwrapper(item, report)

        assert collector.render() == []


class TestSynthesizeUnixPortTargetEntries:
    """Tests for the synthetic DeviceEntry shape on the unix-port path."""

    def test_synthetic_entries_carry_unix_port_sentinel_address(self) -> None:
        """Each synthesized DeviceEntry uses 'unix-port' as its address sentinel."""
        targets = pytest_device._synthesize_unix_port_targets("both")
        assert all(isinstance(entry, DeviceEntry) for entry in targets)
        assert {entry.address for entry in targets} == {"unix-port"}
