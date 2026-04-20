"""Tests for the TransportProtocol / ExtendedTransportProtocol contracts.

Both real transports and the in-memory ``FakeTransport`` should satisfy
the protocols, so the orchestrator can swap them transparently.
"""

from __future__ import annotations

from chumicro_device_transport import (
    CircuitpythonTransport,
    ExtendedTransportProtocol,
    FakeTransport,
    MicropythonTransport,
    TransportProtocol,
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
