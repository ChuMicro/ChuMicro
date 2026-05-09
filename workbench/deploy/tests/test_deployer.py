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
    RsyncMissingError,
    WindowsNotSupportedError,
    host_platform,
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
        files_arg, entrypoint_arg, _follow = deploy_call[1]
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


class TestWindowsGuard:
    """Deployer.__init__ refuses to run on native Windows."""

    def test_init_raises_on_windows(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "win32")
        with pytest.raises(WindowsNotSupportedError, match="WSL2"):
            Deployer(Device(transport="micropython", address="/dev/fake"))

    def test_init_passes_on_linux(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        deployer = Deployer(Device(transport="micropython", address="/dev/fake"))
        assert isinstance(deployer, Deployer)


class TestFlashModeRsyncGuard:
    """Deployer.deploy() pre-checks rsync for CP flash deploys."""

    def test_flash_mode_circuitpython_raises_when_rsync_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeTransport()

        class CpFlashDevice(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = CpFlashDevice(
            transport="circuitpython",
            address="/dev/fake",
            deploy_mode="flash",
        )
        deployer = Deployer(device)
        # Block rsync globally for this test.
        monkeypatch.setattr(host_platform.shutil, "which", lambda _name: None)
        source = FileMapSource({"/code.py": "pass"}, entrypoint="/code.py")

        with pytest.raises(RsyncMissingError):
            deployer.deploy(source)
        # Transport must not have been opened — no connect/disconnect dance
        # before the rsync gate fires.
        assert fake.calls == []

    def test_ram_mode_circuitpython_skips_rsync_check(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeTransport(execute_output="ok\n")

        class CpRamDevice(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = CpRamDevice(
            transport="circuitpython",
            address="/dev/fake",
            deploy_mode="ram",
        )
        deployer = Deployer(device)
        monkeypatch.setattr(host_platform.shutil, "which", lambda _name: None)
        source = FileMapSource({"/code.py": "pass"}, entrypoint="/code.py")

        # Must complete normally — RAM mode never touches rsync.
        result = deployer.deploy(source)
        assert result.success is True

    def test_micropython_flash_skips_rsync_check(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeTransport(execute_output="ok\n")

        class MpFlashDevice(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = MpFlashDevice(
            transport="micropython",
            address="/dev/fake",
            deploy_mode="flash",
        )
        deployer = Deployer(device)
        monkeypatch.setattr(host_platform.shutil, "which", lambda _name: None)
        source = FileMapSource({"/main.py": "pass"}, entrypoint="/main.py")

        # mpremote handles flash on MP — no rsync needed, no gate.
        result = deployer.deploy(source)
        assert result.success is True


class TestDeployerFollowKwargRouting:
    """Deployer routes ``follow="soft_reboot"`` for MP+flash+main.py only.

    See Decision 0028 §MicroPython flash transport for the rule.  Other
    paths (CP, MP RAM, MP flash with non-main.py entrypoints) keep
    transport defaults — CP doesn't accept ``follow`` at all, and MP
    RAM/test-harness deploys want ``follow="exec"``.
    """

    def _make_deployer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        runtime: str,
        deploy_mode: str,
    ) -> tuple[Deployer, FakeTransport]:
        fake = FakeTransport(execute_output="ok\n", mode=deploy_mode)

        class _Device(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = _Device(
            transport=runtime,
            address="/dev/fake",
            deploy_mode=deploy_mode,
        )
        monkeypatch.setattr(host_platform.shutil, "which", lambda _name: None)
        return Deployer(device), fake

    def test_micropython_flash_main_py_passes_soft_reboot(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        deployer, fake = self._make_deployer(
            monkeypatch, runtime="micropython", deploy_mode="flash",
        )
        deployer.deploy(FileMapSource({"/main.py": "pass"}, entrypoint="/main.py"))
        deploy_call = next(call for call in fake.calls if call[0] == "deploy_files")
        _files, _entrypoint, follow = deploy_call[1]
        assert follow == "soft_reboot"

    def test_micropython_flash_non_main_py_keeps_exec_follow_mode(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        deployer, fake = self._make_deployer(
            monkeypatch, runtime="micropython", deploy_mode="flash",
        )
        deployer.deploy(FileMapSource({"/code.py": "pass"}, entrypoint="/code.py"))
        deploy_call = next(call for call in fake.calls if call[0] == "deploy_files")
        _files, _entrypoint, follow = deploy_call[1]
        assert follow == "exec"

    def test_micropython_ram_keeps_exec_follow_mode(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        deployer, fake = self._make_deployer(
            monkeypatch, runtime="micropython", deploy_mode="ram",
        )
        deployer.deploy(FileMapSource({"/main.py": "pass"}, entrypoint="/main.py"))
        deploy_call = next(call for call in fake.calls if call[0] == "deploy_files")
        _files, _entrypoint, follow = deploy_call[1]
        assert follow == "exec"

    def test_circuitpython_omits_follow_kwarg(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CP transport doesn't accept ``follow`` — the Deployer must not pass it.

        Uses RAM mode to sidestep the CP-flash rsync gate (orthogonal
        to the kwarg-routing behaviour under test).  The branch the
        Deployer takes here is the same for CP RAM and CP flash —
        ``follow`` is suppressed for any non-MP transport.
        """
        deployer, fake = self._make_deployer(
            monkeypatch, runtime="circuitpython", deploy_mode="ram",
        )
        deployer.deploy(FileMapSource({"/code.py": "pass"}, entrypoint="/code.py"))
        deploy_call = next(call for call in fake.calls if call[0] == "deploy_files")
        # FakeTransport's default ``follow="exec"`` is recorded — i.e.
        # the kwarg was not passed by the Deployer.  The discriminator
        # is the live MP transport, which would raise if a kwarg it
        # doesn't accept were splatted in.
        _files, _entrypoint, follow = deploy_call[1]
        assert follow == "exec"


class TestPreflightAutoSwitch:
    """Decision 0047 — RAM-mode deploys auto-switch to flash when the deploy
    graph contains a library declaring ``[tool.chumicro] requires_flash = true``.
    """

    def _stage_library(
        self,
        tmp_path,
        *,
        name: str,
        project_name: str,
        requires_flash: bool,
    ):
        """Write a minimal ``libraries/<name>/`` tree with a pyproject + a single
        importable module under ``src/<name>/``.
        """
        from pathlib import Path

        lib = tmp_path / name
        source_dir = lib / "src" / name
        source_dir.mkdir(parents=True)
        (source_dir / "__init__.py").write_text("VALUE = 1\n")
        pyproject_lines = [
            "[project]",
            f'name = "{project_name}"',
            'version = "0.0.0"',
        ]
        if requires_flash:
            pyproject_lines.extend(
                [
                    "",
                    "[tool.chumicro]",
                    "requires_flash = true",
                ],
            )
        (lib / "pyproject.toml").write_text("\n".join(pyproject_lines) + "\n")
        return lib, Path(source_dir)

    def _stage_entrypoint(self, tmp_path, import_targets: list[str]):
        """Write a `main.py` entrypoint that imports the listed module names."""
        entry = tmp_path / "main.py"
        body = "\n".join(f"import {target}" for target in import_targets) + "\n"
        entry.write_text(body)
        return entry

    def test_auto_switch_when_flagged_library_in_graph(self, tmp_path):
        """RAM-mode deploy + flagged library => effective deploy proceeds in flash mode."""
        from chumicro_deploy import ImportGraphSource

        _, src_dir = self._stage_library(
            tmp_path,
            name="mylib",
            project_name="chumicro-mylib",
            requires_flash=True,
        )
        entry = self._stage_entrypoint(tmp_path, ["mylib"])
        source = ImportGraphSource(entry, search_paths=[src_dir.parent])

        deployer, fake = _make_deployer_with_fake(execute_output="ok\n")
        # Set the device into RAM mode by re-binding through the dataclass.
        ram_device = deployer.device.__class__(
            transport=deployer.device.transport,
            address=deployer.device.address,
            deploy_mode="ram",
        )
        # The fake transport-creation closure captures `fake`; rebind a fresh
        # Deployer over it.
        ram_device.create_transport = lambda: fake  # type: ignore[method-assign]
        deployer = Deployer(ram_device)

        messages: list[str] = []
        result = deployer.deploy(
            source,
            on_preflight_message=messages.append,
        )

        assert result.success is True
        # The pre-flight message names the flagged library.
        assert len(messages) == 1
        assert "chumicro-mylib" in messages[0]
        assert "switching to flash mode" in messages[0]

    def test_no_switch_when_no_flagged_library(self, tmp_path):
        """RAM-mode deploy + no flagged library => stays in RAM mode silently."""
        from chumicro_deploy import ImportGraphSource

        _, src_dir = self._stage_library(
            tmp_path,
            name="lightlib",
            project_name="chumicro-lightlib",
            requires_flash=False,
        )
        entry = self._stage_entrypoint(tmp_path, ["lightlib"])
        source = ImportGraphSource(entry, search_paths=[src_dir.parent])

        fake = FakeTransport(execute_output="ok\n")

        class RamDevice(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = RamDevice(
            transport="micropython",
            address="/dev/fake",
            deploy_mode="ram",
        )
        deployer = Deployer(device)
        messages: list[str] = []
        result = deployer.deploy(source, on_preflight_message=messages.append)

        assert result.success is True
        assert messages == []  # silent when nothing to switch

    def test_force_deploy_mode_bypasses_preflight(self, tmp_path):
        """Even with a flagged library in the graph, ``force_deploy_mode='ram'``
        skips the auto-switch.
        """
        from chumicro_deploy import ImportGraphSource

        _, src_dir = self._stage_library(
            tmp_path,
            name="heavy",
            project_name="chumicro-heavy",
            requires_flash=True,
        )
        entry = self._stage_entrypoint(tmp_path, ["heavy"])
        source = ImportGraphSource(entry, search_paths=[src_dir.parent])

        fake = FakeTransport(execute_output="ok\n")

        class RamDevice(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = RamDevice(
            transport="micropython",
            address="/dev/fake",
            deploy_mode="ram",
        )
        deployer = Deployer(device)
        messages: list[str] = []
        # Force RAM mode despite the flagged library — caller's choice.
        result = deployer.deploy(
            source,
            force_deploy_mode="ram",
            on_preflight_message=messages.append,
        )

        assert result.success is True
        assert messages == []  # force-flag silences the pre-flight message

    def test_preflight_message_defaults_to_stderr(self, tmp_path, capsys):
        """When no callback supplied, the explanation goes to stderr."""
        from chumicro_deploy import ImportGraphSource

        _, src_dir = self._stage_library(
            tmp_path,
            name="mylib",
            project_name="chumicro-mylib",
            requires_flash=True,
        )
        entry = self._stage_entrypoint(tmp_path, ["mylib"])
        source = ImportGraphSource(entry, search_paths=[src_dir.parent])

        fake = FakeTransport(execute_output="ok\n")

        class RamDevice(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = RamDevice(
            transport="micropython",
            address="/dev/fake",
            deploy_mode="ram",
        )
        deployer = Deployer(device)
        deployer.deploy(source)

        captured = capsys.readouterr()
        assert "switching to flash mode" in captured.err
        assert "chumicro-mylib" in captured.err


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
