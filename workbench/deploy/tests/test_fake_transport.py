"""Exercise FakeTransport's error-injection hooks and the chunked-execute
+ run_script + clear_entrypoints code paths that other test files don't reach."""

import pytest
from chumicro_deploy.testing import FakeTransport


class TestFakeTransportConnectFailure:
    def test_connect_raises_attribute_propagates(self) -> None:
        boom = RuntimeError("device offline")
        transport = FakeTransport(connect_raises=boom)
        with pytest.raises(RuntimeError, match="device offline"):
            transport.connect()
        assert transport.calls[-1] == ("connect", ())
        assert transport.connected is False


class TestFakeTransportExecuteFailure:
    def test_execute_raises_attribute_propagates(self) -> None:
        boom = ValueError("script error")
        transport = FakeTransport(execute_raises=boom)
        with pytest.raises(ValueError, match="script error"):
            transport.execute("print(1)")
        assert transport.calls[-1] == ("execute", ("print(1)",))

    def test_execute_pops_outputs_head_when_set(self) -> None:
        transport = FakeTransport(outputs=["first", "second"])
        assert transport.execute("a") == "first"
        assert transport.execute("b") == "second"


class TestFakeTransportRunScript:
    def test_run_script_records_call_and_returns_canned_output(self) -> None:
        transport = FakeTransport(execute_output="canned")
        result = transport.run_script("print('hi')", timeout=5.0)
        assert result == "canned"
        assert transport.calls[-1] == ("run_script", ("print('hi')", 5.0))


class TestFakeTransportExecuteScripts:
    def test_execute_scripts_pops_outputs_when_set(self) -> None:
        transport = FakeTransport(outputs=["batch-output"])
        result = transport.execute_scripts(["chunk1", "chunk2"])
        assert result == "batch-output"
        assert transport.calls[-1] == ("execute_scripts", (["chunk1", "chunk2"],))

    def test_execute_scripts_raises_when_configured(self) -> None:
        boom = RuntimeError("batch failed")
        transport = FakeTransport(execute_raises=boom)
        with pytest.raises(RuntimeError, match="batch failed"):
            transport.execute_scripts(["c"])


class TestFakeTransportOnLineDispatch:
    """``on_line`` mirrors the real-transport hook on the fake."""

    def test_execute_dispatches_one_call_per_output_line(self) -> None:
        transport = FakeTransport(execute_output="first\nsecond\nthird\n")
        lines: list[str] = []
        result = transport.execute("ignored", on_line=lines.append)
        assert lines == ["first", "second", "third"]
        assert result == "first\nsecond\nthird\n"

    def test_execute_with_outputs_head_dispatches_lines(self) -> None:
        transport = FakeTransport(outputs=["a\nb\n"])
        lines: list[str] = []
        transport.execute("script", on_line=lines.append)
        assert lines == ["a", "b"]

    def test_execute_without_on_line_omits_dispatch(self) -> None:
        transport = FakeTransport(execute_output="first\nsecond\n")
        # Smoke test: omitting on_line must not raise and the canned
        # return value is unaffected.
        assert transport.execute("script") == "first\nsecond\n"

    def test_execute_scripts_threads_on_line_through_each_call(self) -> None:
        # With outputs empty, execute_scripts calls execute() per chunk
        # — each one dispatches execute_output's lines.
        transport = FakeTransport(execute_output="per-chunk\n")
        lines: list[str] = []
        transport.execute_scripts(
            ["chunk-a", "chunk-b"], on_line=lines.append,
        )
        assert lines == ["per-chunk", "per-chunk"]

    def test_execute_scripts_batched_head_dispatches_lines(self) -> None:
        transport = FakeTransport(outputs=["batch1\nbatch2\n"])
        lines: list[str] = []
        transport.execute_scripts(
            ["chunk-a", "chunk-b"], on_line=lines.append,
        )
        # One batched head pop covers both chunks, dispatched per line.
        assert lines == ["batch1", "batch2"]


class TestFakeTransportRecoverFailure:
    def test_recover_raises_attribute_propagates(self) -> None:
        boom = RuntimeError("unrecoverable")
        transport = FakeTransport(recover_raises=boom)
        with pytest.raises(RuntimeError, match="unrecoverable"):
            transport.recover()


class TestFakeTransportClearEntrypoints:
    def test_clear_entrypoints_removes_candidate_paths(self) -> None:
        transport = FakeTransport(device_files={
            "code.py": b"a",
            "main.py": b"b",
            "/code.py": b"c",
            "/main.py": b"d",
            "lib/keep.py": b"keep",
        })
        transport.clear_entrypoints()
        assert transport.device_files == {"lib/keep.py": b"keep"}
        assert transport.calls[-1] == ("clear_entrypoints", ())
