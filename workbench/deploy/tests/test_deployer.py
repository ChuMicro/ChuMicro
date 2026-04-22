"""Tests for the Deployer orchestrator."""

from __future__ import annotations

from typing import Any

import pytest
from chumicro_deploy import (
    Deployer,
    DeployResult,
    Device,
    FakeTransport,
    FileMapSource,
)


class _DeviceWithFake(Device):
    """Device subclass that returns a configured FakeTransport.

    Frozen dataclass doesn't allow attribute injection, so we subclass
    and override create_transport with a method on the subclass.
    """


def _make_deployer_with_fake(**fake_kwargs: Any) -> tuple[Deployer, FakeTransport]:
    fake = FakeTransport(**fake_kwargs)

    class DeviceForTest(Device):
        def create_transport(self):  # type: ignore[override]
            return fake

    device = DeviceForTest(transport="micropython", address="/dev/fake")
    return Deployer(device), fake


class TestDeployerBasic:
    def test_deploy_returns_success_on_clean_run(self):
        deployer, fake = _make_deployer_with_fake(execute_output="hello\n")
        source = FileMapSource({"/code.py": "print('hello')"}, entrypoint="/code.py")
        result = deployer.deploy(source)
        assert isinstance(result, DeployResult)
        assert result.success is True
        assert result.execute_output == "hello\n"
        assert result.traceback is None
        assert result.staged_files == ["/code.py"]

    def test_deploy_returns_failure_when_traceback_present(self):
        traceback_output = (
            "Traceback (most recent call last):\n"
            '  File "<stdin>", line 1, in <module>\n'
            "ZeroDivisionError: division by zero\n"
        )
        deployer, _ = _make_deployer_with_fake(execute_output=traceback_output)
        source = FileMapSource({"/code.py": "1/0"}, entrypoint="/code.py")
        result = deployer.deploy(source)
        assert result.success is False
        assert result.traceback is not None
        assert "ZeroDivisionError" in result.traceback

    def test_deploy_lifecycle_calls(self):
        deployer, fake = _make_deployer_with_fake()
        source = FileMapSource({"/code.py": "pass"}, entrypoint="/code.py")
        deployer.deploy(source)
        method_order = [call[0] for call in fake.calls]
        assert method_order == ["connect", "deploy_files", "disconnect"]

    def test_disconnect_called_even_on_transport_error(self):
        class BoomTransport(FakeTransport):
            def deploy_files(self, *_args, **_kwargs):  # type: ignore[override]
                self.calls.append(("deploy_files", ()))
                raise RuntimeError("kaboom")

        fake = BoomTransport()

        class DeviceForTest(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        deployer = Deployer(DeviceForTest(transport="micropython", address="/dev/x"))
        source = FileMapSource({"/code.py": "pass"}, entrypoint="/code.py")
        with pytest.raises(RuntimeError, match="kaboom"):
            deployer.deploy(source)
        assert ("disconnect", ()) in fake.calls

    def test_deploy_passes_files_and_entrypoint_to_transport(self):
        deployer, fake = _make_deployer_with_fake()
        source = FileMapSource(
            {"/code.py": "pass", "/lib/helper.py": "X = 1"},
            entrypoint="/code.py",
        )
        deployer.deploy(source)
        deploy_call = [call for call in fake.calls if call[0] == "deploy_files"][0]
        files_arg, entrypoint_arg = deploy_call[1]
        assert entrypoint_arg == "/code.py"
        assert files_arg == {"/code.py": b"pass", "/lib/helper.py": b"X = 1"}

    def test_device_property_returns_constructor_device(self):
        deployer, _ = _make_deployer_with_fake()
        assert isinstance(deployer.device, Device)


class TestDeployerCallbacks:
    def test_on_progress_invoked_with_known_milestones(self):
        deployer, _ = _make_deployer_with_fake()
        progress_events: list[tuple[float, str]] = []
        source = FileMapSource({"/code.py": "pass"}, entrypoint="/code.py")
        def record(fraction: float, message: str) -> None:
            progress_events.append((fraction, message))

        deployer.deploy(source, on_progress=record)
        fractions = [event[0] for event in progress_events]
        messages = [event[1] for event in progress_events]
        assert fractions == [0.0, 0.1, 0.2, 0.9, 1.0]
        assert "connecting" in messages[0]
        assert "done" in messages[-1]

    def test_on_file_staged_forwarded_to_transport(self):
        deployer, _ = _make_deployer_with_fake()
        source = FileMapSource(
            {"/code.py": "pass", "/lib/helper.py": "X = 1"},
            entrypoint="/code.py",
        )
        staged: list[str] = []
        deployer.deploy(source, on_file_staged=staged.append)
        # FakeTransport emits sorted, so we should see both in order.
        assert staged == ["/code.py", "/lib/helper.py"]

    def test_on_execute_line_forwarded_to_transport(self):
        deployer, _ = _make_deployer_with_fake(execute_output="alpha\nbeta\ngamma\n")
        source = FileMapSource({"/code.py": "pass"}, entrypoint="/code.py")
        lines: list[str] = []
        deployer.deploy(source, on_execute_line=lines.append)
        assert lines == ["alpha", "beta", "gamma"]

    def test_callbacks_default_to_none_without_error(self):
        deployer, _ = _make_deployer_with_fake(execute_output="hi\n")
        source = FileMapSource({"/code.py": "pass"}, entrypoint="/code.py")
        # No callbacks — should run without raising.
        result = deployer.deploy(source)
        assert result.success is True


class TestTracebackExtraction:
    def test_extract_takes_last_traceback(self):
        output = (
            "before first\n"
            "Traceback (most recent call last):\n"
            "  File x\n"
            "ValueError: first\n"
            "\n"
            "after first\n"
            "Traceback (most recent call last):\n"
            "  File y\n"
            "KeyError: second\n"
        )
        deployer, _ = _make_deployer_with_fake(execute_output=output)
        source = FileMapSource({"/code.py": "pass"}, entrypoint="/code.py")
        result = deployer.deploy(source)
        assert result.traceback is not None
        assert "KeyError: second" in result.traceback
        assert "ValueError: first" not in result.traceback
