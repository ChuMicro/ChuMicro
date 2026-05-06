"""Tests for the TransportProtocol / ExtendedTransportProtocol contracts.

Both real transports and the in-memory ``FakeTransport`` should satisfy
the protocols, so the orchestrator can swap them transparently.
"""

from __future__ import annotations

from chumicro_deploy import (
    CircuitpythonTransport,
    DeviceImplementation,
    ExtendedTransportProtocol,
    FakeTransport,
    MicropythonTransport,
    TransportProtocol,
)
from chumicro_deploy.protocol import (
    PROBE_IMPLEMENTATION_SCRIPT,
    parse_probe_output,
)


class TestTransportProtocol:
    """Tests for the minimum transport contract."""

    def test_micropython_transport_satisfies_protocol(self) -> None:
        """MicropythonTransport implements the minimum contract."""
        transport = MicropythonTransport("/dev/null")
        assert isinstance(transport, TransportProtocol)

    def test_circuitpython_transport_satisfies_protocol(self) -> None:
        """CircuitpythonTransport implements the minimum contract."""
        transport = CircuitpythonTransport("/dev/null")
        assert isinstance(transport, TransportProtocol)

    def test_fake_transport_satisfies_protocol(self) -> None:
        """FakeTransport implements the minimum contract."""
        fake = FakeTransport()
        assert isinstance(fake, TransportProtocol)


class TestExtendedTransportProtocol:
    """Tests for the chunked-execution contract (CircuitPython RAM mode)."""

    def test_circuitpython_transport_satisfies_extended(self) -> None:
        """CircuitpythonTransport implements the extended contract."""
        transport = CircuitpythonTransport("/dev/null")
        assert isinstance(transport, ExtendedTransportProtocol)

    def test_fake_transport_satisfies_extended(self) -> None:
        """FakeTransport implements the extended contract."""
        fake = FakeTransport()
        assert isinstance(fake, ExtendedTransportProtocol)

    def test_micropython_transport_does_not_satisfy_extended(self) -> None:
        """MicropythonTransport does not need the chunked helpers."""
        transport = MicropythonTransport("/dev/null")
        assert not isinstance(transport, ExtendedTransportProtocol)


class TestFakeTransportExtended:
    """Tests for the new FakeTransport methods."""

    def test_execute_scripts_records_chunked_call(self) -> None:
        """execute_scripts records the full list and per-script execute entries."""
        fake = FakeTransport(execute_output="stdout-chunk")
        result = fake.execute_scripts(["chunk-1", "chunk-2", "chunk-3"])

        # The configured output is returned (as the last script's output).
        assert result == "stdout-chunk"

        # Top-level execute_scripts call recorded.
        assert ("execute_scripts", (["chunk-1", "chunk-2", "chunk-3"],)) in fake.calls
        # Plus three execute calls — counts that exist for tests asserting
        # on per-call behavior still work.
        execute_calls = [call for call in fake.calls if call[0] == "execute"]
        assert len(execute_calls) == 3
        assert execute_calls[0][1] == ("chunk-1",)
        assert execute_calls[2][1] == ("chunk-3",)

    def test_probe_free_memory_returns_configured_value(self) -> None:
        """probe_free_memory returns the configured free-heap value."""
        fake = FakeTransport(free_memory_bytes=128 * 1024)
        assert fake.probe_free_memory() == 128 * 1024
        assert ("probe_free_memory", ()) in fake.calls

    def test_inline_script_budget_is_half_of_free_memory(self) -> None:
        """inline_script_budget_bytes returns a conservative slice of free memory."""
        fake = FakeTransport(free_memory_bytes=200 * 1024)
        assert fake.inline_script_budget_bytes() == 100 * 1024

    def test_inline_script_budget_has_floor(self) -> None:
        """inline_script_budget_bytes never returns less than its 8 KB floor."""
        fake = FakeTransport(free_memory_bytes=4 * 1024)
        assert fake.inline_script_budget_bytes() == 8 * 1024

    def test_recover_records_call(self) -> None:
        """recover() records a recover call (post-failure hook)."""
        fake = FakeTransport()
        fake.recover()
        assert fake.calls == [("recover", ())]

    def test_probe_implementation_returns_canned_result(self) -> None:
        """probe_implementation returns the configured DeviceImplementation."""
        expected = DeviceImplementation(
            name="micropython", version="1.26.0", machine="Pico W",
        )
        fake = FakeTransport(probe_result=expected)
        assert fake.probe_implementation() is expected
        assert ("probe_implementation", ()) in fake.calls

    def test_probe_implementation_defaults_to_none(self) -> None:
        """Without a canned result, probe_implementation returns None."""
        fake = FakeTransport()
        assert fake.probe_implementation() is None


class TestParseProbeOutput:
    """Tests for parse_probe_output — the on-device probe marker parser."""

    def test_parses_marker_line(self) -> None:
        """A well-formed __CHU_IMPL__ line yields a DeviceImplementation."""
        output = "__CHU_IMPL__:micropython|1.26.0|Raspberry Pi Pico W with RP2040\n"
        result = parse_probe_output(output)
        assert result == DeviceImplementation(
            name="micropython",
            version="1.26.0",
            machine="Raspberry Pi Pico W with RP2040",
        )

    def test_ignores_surrounding_output(self) -> None:
        """Boot banners and other lines before/after the marker are ignored."""
        output = (
            "MPY: soft reboot\n"
            "MicroPython v1.26.0 on 2025-08-14\n"
            "__CHU_IMPL__:micropython|1.26.0|rp2\n"
            ">>> \n"
        )
        result = parse_probe_output(output)
        assert result is not None
        assert result.name == "micropython"
        assert result.version == "1.26.0"
        assert result.machine == "rp2"

    def test_missing_marker_returns_none(self) -> None:
        """Output without the marker line returns None (probe unavailable)."""
        assert parse_probe_output("just some boot text\n") is None
        assert parse_probe_output("") is None

    def test_malformed_payload_returns_none(self) -> None:
        """A marker line missing fields returns None rather than partial data."""
        output = "__CHU_IMPL__:only_one_field\n"
        assert parse_probe_output(output) is None

    def test_machine_may_contain_pipe_when_last(self) -> None:
        """Only the first two ``|`` separators are significant — machine keeps its own."""
        # maxsplit=2 means extra pipes belong to the machine field.
        output = "__CHU_IMPL__:circuitpython|10.1.4|Board | variant\n"
        result = parse_probe_output(output)
        assert result is not None
        assert result.machine == "Board | variant"

    def test_uid_marker_populates_implementation_uid(self) -> None:
        """A second ``__CHU_UID__:`` line populates ``DeviceImplementation.uid``."""
        output = (
            "__CHU_IMPL__:circuitpython|10.2.0|Raspberry Pi Pico W\n"
            "__CHU_UID__:E6614103E7174624\n"
        )
        result = parse_probe_output(output)
        assert result is not None
        assert result.uid == "E6614103E7174624"

    def test_uid_marker_is_uppercased(self) -> None:
        """UID probes are normalised to upper-case hex."""
        output = (
            "__CHU_IMPL__:circuitpython|10.2.0|S2Mini\n"
            "__CHU_UID__:487f301f0224\n"
        )
        result = parse_probe_output(output)
        assert result is not None
        assert result.uid == "487F301F0224"

    def test_missing_uid_marker_leaves_uid_empty(self) -> None:
        """Output with no UID line (older firmware) still parses; uid is empty."""
        output = "__CHU_IMPL__:micropython|1.26.0|rp2\n"
        result = parse_probe_output(output)
        assert result is not None
        assert result.uid == ""


class TestProbeImplementationScript:
    """Tests for the PROBE_IMPLEMENTATION_SCRIPT constant."""

    def test_script_is_syntactically_valid_python(self) -> None:
        """The on-device probe script must be executable Python."""
        compile(PROBE_IMPLEMENTATION_SCRIPT, "<probe>", "exec")

    def test_script_emits_chu_impl_marker(self) -> None:
        """The probe's print statement must use the expected marker prefix."""
        assert "__CHU_IMPL__:" in PROBE_IMPLEMENTATION_SCRIPT

    def test_script_does_not_require_staged_files(self) -> None:
        """No imports beyond ``sys`` — probe must work pre-stage."""
        # Only ``sys`` is imported; staged modules (``chumicro_test_harness``
        # etc.) are not referenced.  If this ever changes the probe may
        # run before stage() and fail.
        imported_modules = [
            line.split()[1]
            for line in PROBE_IMPLEMENTATION_SCRIPT.splitlines()
            if line.startswith("import ")
        ]
        assert imported_modules == ["sys"]


class TestProbeVersionStringification:
    """Verify the probe's leading-int-run version stringification.

    F3 of the 2026-05-06 verification pass — the original probe
    joined every element of ``sys.implementation.version`` with
    dots, producing ``"10.2.0."`` (trailing dot) on CircuitPython
    RC builds where ``version`` is ``(10, 2, 0, '')``.

    These tests exec the probe script under simulated
    ``sys.implementation.version`` shapes and assert the joined
    string is clean dotted-ints with no trailing dot or non-int
    components.
    """

    def _run_probe_with_version(
        self, version_tuple: tuple[object, ...], name: str = "circuitpython",
    ) -> str:
        """Exec the probe under a simulated implementation version.

        Patches ``sys.implementation`` with a fake ``version`` and
        ``name``, captures stdout, returns the version segment of the
        emitted ``__CHU_IMPL__:`` marker line.
        """
        import io  # noqa: PLC0415
        import sys  # noqa: PLC0415
        import types  # noqa: PLC0415
        from contextlib import redirect_stdout  # noqa: PLC0415

        fake_implementation = types.SimpleNamespace(
            version=version_tuple,
            name=name,
            _machine="fake-machine",
        )
        original_implementation = sys.implementation
        sys.implementation = fake_implementation  # type: ignore[assignment]
        try:
            buffer = io.StringIO()
            namespace: dict[str, object] = {}
            with redirect_stdout(buffer):
                # The probe script does `import microcontroller` /
                # `import machine` inside try/except for UID — those
                # fail cleanly on host CPython.
                exec(  # noqa: S102 — probe script under controlled namespace
                    compile(PROBE_IMPLEMENTATION_SCRIPT, "<probe>", "exec"),
                    namespace,
                )
            captured = buffer.getvalue()
        finally:
            sys.implementation = original_implementation  # type: ignore[assignment]

        for line in captured.splitlines():
            if line.startswith("__CHU_IMPL__:"):
                payload = line[len("__CHU_IMPL__:"):]
                _name, version_str, _machine = payload.split("|", 2)
                return version_str
        raise AssertionError(
            f"probe did not emit __CHU_IMPL__ marker (output: {captured!r})",
        )

    def test_cp_rc_four_tuple_with_empty_string_strips_trailing_dot(
        self,
    ) -> None:
        """``(10, 2, 0, '')`` (CP 10.2.0-rc.0 shape) → ``"10.2.0"``."""
        assert self._run_probe_with_version((10, 2, 0, "")) == "10.2.0"

    def test_cp_final_three_tuple(self) -> None:
        """``(10, 1, 4)`` (CP 10.1.4 final shape) → ``"10.1.4"``."""
        assert self._run_probe_with_version((10, 1, 4)) == "10.1.4"

    def test_mp_three_tuple(self) -> None:
        """``(1, 28, 0)`` (MicroPython 1.28.0 shape) → ``"1.28.0"``."""
        assert self._run_probe_with_version(
            (1, 28, 0), name="micropython",
        ) == "1.28.0"

    def test_cpython_five_tuple_stops_at_releaselevel(self) -> None:
        """``(3, 12, 0, 'final', 0)`` (CPython shape) → ``"3.12.0"``.

        Stops at the first non-int component — does NOT continue
        through to the trailing serial int.
        """
        assert self._run_probe_with_version(
            (3, 12, 0, "final", 0),
        ) == "3.12.0"

    def test_first_element_non_int_yields_empty(self) -> None:
        """Defensive: a runtime that returns a string-first version
        produces an empty version string (caller treats as
        ``UNPARSEABLE``).
        """
        assert self._run_probe_with_version(("v", 1, 0)) == ""
