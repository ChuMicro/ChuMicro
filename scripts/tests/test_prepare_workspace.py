"""Tests for prepare_workspace.py — environment detection, venv resolution, summary."""

import subprocess
import sys
from pathlib import Path

import prepare_workspace
import pytest
from prepare_workspace import (
    MIN_PYTHON,
    _check_python_version,
    _describe_environment,
    _has_uv,
    _in_virtual_environment,
    _missing_unix_port_tools,
    _reexec_into_venv_if_needed,
    _venv_python,
    install_dependencies,
    print_summary,
    resolve_python,
    verify_workspace,
)


class TestVenvPython:
    """Tests for _venv_python path resolution."""

    def test_returns_path(self):
        """_venv_python returns a Path under the repository .venv."""
        result = _venv_python()
        assert isinstance(result, Path)
        assert result.parent.name in {"bin", "Scripts"}

    def test_uses_scripts_on_windows(self, monkeypatch):
        """Windows uses Scripts/python.exe, POSIX uses bin/python."""
        monkeypatch.setattr(prepare_workspace.os, "name", "nt")
        result = _venv_python()
        assert result.name == "python.exe"
        assert result.parent.name == "Scripts"

    def test_uses_bin_on_posix(self, monkeypatch):
        """POSIX uses bin/python."""
        monkeypatch.setattr(prepare_workspace.os, "name", "posix")
        result = _venv_python()
        assert result.name == "python"
        assert result.parent.name == "bin"


class TestInVirtualEnvironment:
    """Tests for _in_virtual_environment detection."""

    def test_returns_bool(self):
        """Returns a boolean (real-environment-dependent value)."""
        result = _in_virtual_environment()
        assert isinstance(result, bool)

    def test_detects_venv(self, monkeypatch):
        """sys.prefix != sys.base_prefix indicates a virtual environment."""
        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/fake/venv")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        assert _in_virtual_environment() is True

    def test_detects_system_python(self, monkeypatch):
        """sys.prefix == sys.base_prefix indicates the system interpreter."""
        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        assert _in_virtual_environment() is False


class TestDescribeEnvironment:
    """Tests for _describe_environment string formatting."""

    def test_describes_virtualenv(self, monkeypatch):
        """Reports the virtual environment prefix."""
        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/proj/.venv")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        result = _describe_environment()
        assert "virtual environment" in result
        assert "/proj/.venv" in result

    def test_describes_conda(self, monkeypatch):
        """Reports the conda prefix when CONDA_PREFIX is set and not in a venv."""
        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        monkeypatch.setenv("CONDA_PREFIX", "/opt/conda")
        result = _describe_environment()
        assert "conda" in result
        assert "/opt/conda" in result

    def test_describes_system(self, monkeypatch):
        """Reports the system Python path when no env is active."""
        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        monkeypatch.setattr(prepare_workspace.sys, "executable", "/usr/local/bin/python3")
        result = _describe_environment()
        assert "system Python" in result
        assert "/usr/local/bin/python3" in result


class TestMissingUnixPortTools:
    """Tests for _missing_unix_port_tools."""

    def test_returns_list(self):
        """Returns a list (possibly empty) of tool names."""
        result = _missing_unix_port_tools()
        assert isinstance(result, list)
        for tool in result:
            assert tool in {"git", "make", "cc"}

    def test_all_present(self, monkeypatch):
        """No missing tools when all three resolve."""
        monkeypatch.setattr(prepare_workspace.shutil, "which", lambda _: "/usr/bin/anything")
        assert _missing_unix_port_tools() == []

    def test_all_missing(self, monkeypatch):
        """All three missing when shutil.which returns None."""
        monkeypatch.setattr(prepare_workspace.shutil, "which", lambda _: None)
        assert _missing_unix_port_tools() == ["git", "make", "cc"]


class TestHasUv:
    """Tests for _has_uv detection."""

    def test_present(self, monkeypatch):
        monkeypatch.setattr(prepare_workspace.shutil, "which", lambda _: "/usr/local/bin/uv")
        assert _has_uv() is True

    def test_absent(self, monkeypatch):
        monkeypatch.setattr(prepare_workspace.shutil, "which", lambda _: None)
        assert _has_uv() is False


class TestCheckPythonVersion:
    """Tests for _check_python_version."""

    def test_running_interpreter_passes(self, capsys):
        """The running interpreter is by definition new enough."""
        # Will not raise because the test runner is itself >= MIN_PYTHON.
        _check_python_version()
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_running_interpreter_too_old(self, monkeypatch, capsys):
        """A too-old running interpreter raises SystemExit with a friendly message."""
        old_version = (3, 7, 0)
        monkeypatch.setattr(prepare_workspace.sys, "version_info", old_version + (0, 0))
        with pytest.raises(SystemExit) as excinfo:
            _check_python_version()
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "required" in captured.out.lower()

    def test_target_interpreter_too_old(self, monkeypatch, capsys, tmp_path):
        """A too-old target interpreter raises SystemExit."""
        too_old = "3.7.0"
        fake_run_calls = []

        def fake_run(*args, **kwargs):
            fake_run_calls.append(args)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=too_old + "\n")

        monkeypatch.setattr(prepare_workspace.subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as excinfo:
            _check_python_version(tmp_path / "python")
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert too_old in captured.out

    def test_target_interpreter_subprocess_failure(self, monkeypatch, capsys, tmp_path):
        """If the target interpreter cannot be queried, raise with a clear message."""

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="")

        monkeypatch.setattr(prepare_workspace.subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as excinfo:
            _check_python_version(tmp_path / "python")
        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Cannot determine" in captured.out


class TestResolvePython:
    """Tests for resolve_python — venv selection logic."""

    def test_uses_active_venv(self, monkeypatch, capsys):
        """An already-active virtual environment is used as-is."""
        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/fake/venv")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "executable", "/fake/venv/bin/python")
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        result = resolve_python()
        assert result == Path("/fake/venv/bin/python")
        assert "virtual environment" in capsys.readouterr().out

    def test_uses_conda(self, monkeypatch, capsys):
        """A conda environment is used when no venv is active."""
        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "executable", "/opt/conda/bin/python")
        monkeypatch.setenv("CONDA_PREFIX", "/opt/conda")
        result = resolve_python()
        assert result == Path("/opt/conda/bin/python")
        assert "conda" in capsys.readouterr().out

    def test_finds_existing_venv_dir(self, monkeypatch, tmp_path, capsys):
        """An existing .venv directory is reused even without activation."""
        venv_python = tmp_path / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()

        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        monkeypatch.setattr(prepare_workspace, "_venv_python", lambda: venv_python)

        result = resolve_python()
        assert result == venv_python
        assert "Found existing" in capsys.readouterr().out

    def test_creates_venv_when_missing(self, monkeypatch, tmp_path, capsys):
        """No active env + no .venv triggers automatic venv creation."""
        venv_python = tmp_path / "bin" / "python"
        venv_calls: list[tuple] = []

        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        monkeypatch.setattr(prepare_workspace, "_venv_python", lambda: venv_python)
        monkeypatch.setattr(prepare_workspace, "_has_uv", lambda: False)
        monkeypatch.setattr(prepare_workspace, "_check_python_version", lambda python=None: None)

        def fake_create(path, with_pip):
            venv_calls.append((path, with_pip))

        monkeypatch.setattr(prepare_workspace.venv, "create", fake_create)

        result = resolve_python()
        assert result == venv_python
        assert venv_calls == [(str(prepare_workspace.VENV_DIR), True)]
        assert "Creating virtual environment" in capsys.readouterr().out


class TestInstallDependencies:
    """Tests for install_dependencies — delegation to install_workspace."""

    def test_delegates_to_install_workspace(self, monkeypatch, capsys, tmp_path):
        """install_dependencies forwards the python path and prints a banner."""
        captured_python: list[Path] = []

        def fake_install(python=None):
            captured_python.append(python)
            return 0

        monkeypatch.setattr(prepare_workspace, "install_workspace", fake_install)

        install_dependencies(tmp_path / "python")

        assert captured_python == [tmp_path / "python"]
        out = capsys.readouterr().out
        assert "Installing workspace" in out
        assert "Target interpreter" in out

    def test_propagates_failure(self, monkeypatch, capsys, tmp_path):
        """A non-zero return from install_workspace raises SystemExit."""

        def fake_install(python=None):
            return 7

        monkeypatch.setattr(prepare_workspace, "install_workspace", fake_install)

        with pytest.raises(SystemExit) as excinfo:
            install_dependencies(tmp_path / "python")
        assert excinfo.value.code == 7
        assert "Failed: Installing workspace" in capsys.readouterr().out


class TestVerifyWorkspace:
    """Tests for verify_workspace — opt-in lint + test."""

    def test_runs_lint_then_test(self, monkeypatch, tmp_path):
        """verify_workspace runs lint then test in order, both via run.py."""
        invocations: list[list[str]] = []

        def fake_run(command, label):
            invocations.append([str(arg) for arg in command])

        monkeypatch.setattr(prepare_workspace, "_run", fake_run)

        verify_workspace(tmp_path / "python")

        assert len(invocations) == 2
        assert invocations[0][1:] == ["scripts/run.py", "lint"]
        assert invocations[1][1:] == ["scripts/run.py", "test"]


class TestPrintSummary:
    """Tests for print_summary — friendly post-install hints."""

    def test_prints_common_tasks(self, monkeypatch, capsys, tmp_path):
        """The summary lists at least preflight as a follow-up task."""
        monkeypatch.setattr(prepare_workspace, "running_on_native_windows", lambda: False)
        monkeypatch.setattr(prepare_workspace, "_missing_unix_port_tools", lambda: [])
        monkeypatch.setattr(prepare_workspace, "_in_virtual_environment", lambda: True)

        print_summary(tmp_path / "python")
        out = capsys.readouterr().out
        assert "preflight" in out
        assert "Workspace is ready" in out

    def test_windows_hides_unix_port_hint(self, monkeypatch, capsys, tmp_path):
        """Windows summary mentions WSL2 and skips unix-port tool hints."""
        monkeypatch.setattr(prepare_workspace, "running_on_native_windows", lambda: True)
        monkeypatch.setattr(prepare_workspace, "_in_virtual_environment", lambda: True)

        print_summary(tmp_path / "python")
        out = capsys.readouterr().out
        assert "WSL2" in out
        # Should not show the unix-port tools hint on Windows.
        assert "install" not in out.lower() or "wsl2" in out.lower()

    def test_missing_unix_port_tools_hinted(self, monkeypatch, capsys, tmp_path):
        """Missing git/make/cc surfaces an optional install hint."""
        monkeypatch.setattr(prepare_workspace, "running_on_native_windows", lambda: False)
        monkeypatch.setattr(prepare_workspace, "_missing_unix_port_tools", lambda: ["git"])
        monkeypatch.setattr(prepare_workspace, "_in_virtual_environment", lambda: True)

        print_summary(tmp_path / "python")
        out = capsys.readouterr().out
        assert "Optional" in out
        assert "git" in out

    def test_activation_hint_when_venv_unactivated(self, monkeypatch, capsys, tmp_path):
        """When .venv was created but not activated, prompt the user to activate."""
        venv_python = tmp_path / "bin" / "python"

        monkeypatch.setattr(prepare_workspace, "_venv_python", lambda: venv_python)
        monkeypatch.setattr(prepare_workspace, "_in_virtual_environment", lambda: False)
        monkeypatch.setattr(prepare_workspace, "running_on_native_windows", lambda: False)
        monkeypatch.setattr(prepare_workspace, "_missing_unix_port_tools", lambda: [])

        print_summary(venv_python)
        out = capsys.readouterr().out
        assert "Activate" in out
        assert ".venv" in out


class TestMinPythonConstant:
    """Sanity check the minimum-Python constant."""

    def test_min_python_format(self):
        """MIN_PYTHON is a (major, minor) tuple of ints."""
        assert isinstance(MIN_PYTHON, tuple)
        assert len(MIN_PYTHON) == 2
        assert all(isinstance(part, int) for part in MIN_PYTHON)
        # Must be at least 3.x.
        assert MIN_PYTHON[0] >= 3


class TestRunHelper:
    """Tests for prepare_workspace._run subprocess wrapper."""

    def test_succeeds(self, monkeypatch, capsys):
        """Successful subprocess returns silently and prints the command."""
        captured: list[list[str]] = []

        def fake_run(command, cwd):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        monkeypatch.setattr(prepare_workspace.subprocess, "run", fake_run)
        prepare_workspace._run([sys.executable, "-c", "pass"], "Smoke test")

        assert captured == [[sys.executable, "-c", "pass"]]
        out = capsys.readouterr().out
        assert "Smoke test" in out
        assert "+ " in out

    def test_aborts_on_failure(self, monkeypatch, capsys):
        """Non-zero subprocess raises SystemExit with the command's exit code."""

        def fake_run(command, cwd):
            return subprocess.CompletedProcess(args=command, returncode=42)

        monkeypatch.setattr(prepare_workspace.subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as excinfo:
            prepare_workspace._run([sys.executable, "-c", "pass"], "Smoke test")
        assert excinfo.value.code == 42
        out = capsys.readouterr().out
        assert "Failed: Smoke test" in out


class TestReexecIntoVenvIfNeeded:
    """Tests for the re-exec-into-venv handoff."""

    def test_no_op_inside_venv(self, monkeypatch, tmp_path):
        """When already inside a venv, the helper returns without subprocessing."""
        called: list = []
        monkeypatch.setattr(prepare_workspace, "_in_virtual_environment", lambda: True)
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        monkeypatch.setattr(
            prepare_workspace.subprocess, "run",
            lambda *_args, **_kwargs: called.append("subprocess") or None,
        )

        _reexec_into_venv_if_needed(tmp_path / "python")

        assert called == []

    def test_no_op_inside_conda(self, monkeypatch, tmp_path):
        """When inside a conda env (no venv), the helper returns without subprocessing."""
        called: list = []
        monkeypatch.setattr(prepare_workspace, "_in_virtual_environment", lambda: False)
        monkeypatch.setenv("CONDA_PREFIX", "/opt/conda")
        monkeypatch.setattr(
            prepare_workspace.subprocess, "run",
            lambda *_args, **_kwargs: called.append("subprocess") or None,
        )

        _reexec_into_venv_if_needed(tmp_path / "python")

        assert called == []

    def test_reexecs_from_system_python(self, monkeypatch, capsys, tmp_path):
        """Outside any venv/conda, the helper subprocesses into *python* and exits with the rc."""
        captured_command: list[list[str]] = []
        target = tmp_path / "bin" / "python"

        monkeypatch.setattr(prepare_workspace, "_in_virtual_environment", lambda: False)
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        monkeypatch.setattr(prepare_workspace.sys, "argv", ["prepare_workspace.py", "--flag"])

        def fake_run(command, cwd):
            captured_command.append(command)
            return subprocess.CompletedProcess(args=command, returncode=4)

        monkeypatch.setattr(prepare_workspace.subprocess, "run", fake_run)

        with pytest.raises(SystemExit) as excinfo:
            _reexec_into_venv_if_needed(target)
        assert excinfo.value.code == 4

        assert len(captured_command) == 1
        assert captured_command[0][0] == str(target)
        # The script path should come second so the re-execed interpreter
        # re-runs *this* module from scratch.
        assert captured_command[0][1].endswith("prepare_workspace.py")
        # CLI args after the script path are forwarded verbatim.
        assert captured_command[0][2:] == ["--flag"]
        assert "Re-executing inside" in capsys.readouterr().out


class TestMain:
    """Tests for prepare_workspace.main entry point."""

    def test_main_invokes_steps_in_order(self, monkeypatch, capsys, tmp_path):
        """main() runs resolve -> check -> reexec -> install -> verify -> summary."""
        called: list[str] = []
        fake_python = tmp_path / "python"

        monkeypatch.setattr(prepare_workspace.sys, "argv", ["prepare_workspace.py"])
        monkeypatch.setattr(
            prepare_workspace, "resolve_python",
            lambda: (called.append("resolve"), fake_python)[1],
        )
        monkeypatch.setattr(
            prepare_workspace, "_check_python_version",
            lambda python: called.append(f"check({python})"),
        )
        monkeypatch.setattr(
            prepare_workspace, "_reexec_into_venv_if_needed",
            lambda python: called.append(f"reexec({python})"),
        )
        monkeypatch.setattr(
            prepare_workspace, "install_dependencies",
            lambda python: called.append(f"install({python})"),
        )
        monkeypatch.setattr(
            prepare_workspace, "verify_workspace",
            lambda python: called.append(f"verify({python})"),
        )
        monkeypatch.setattr(
            prepare_workspace, "print_summary",
            lambda python: called.append(f"summary({python})"),
        )

        prepare_workspace.main()

        # Verify always runs now — no flag.
        assert called == [
            "resolve",
            f"check({fake_python})",
            f"reexec({fake_python})",
            f"install({fake_python})",
            f"verify({fake_python})",
            f"summary({fake_python})",
        ]

    def test_main_rejects_unknown_flag(self, monkeypatch, capsys):
        """argparse still rejects unknown flags so old --verify / --create-venv fail loudly."""
        monkeypatch.setattr(
            prepare_workspace.sys, "argv", ["prepare_workspace.py", "--create-venv"],
        )
        with pytest.raises(SystemExit):
            prepare_workspace.main()


class TestResolvePythonCreatesVenvWithUv:
    """Automatic .venv creation uses uv when available."""

    def test_uses_uv_when_available(self, monkeypatch, tmp_path, capsys):
        """No env anywhere + uv on PATH → resolve_python calls uv venv."""
        venv_python = tmp_path / "bin" / "python"
        captured: list[list[str]] = []

        monkeypatch.setattr(prepare_workspace.sys, "prefix", "/usr/local")
        monkeypatch.setattr(prepare_workspace.sys, "base_prefix", "/usr/local")
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        monkeypatch.setattr(prepare_workspace, "_venv_python", lambda: venv_python)
        monkeypatch.setattr(prepare_workspace, "_has_uv", lambda: True)

        def fake_run(command, cwd, check):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        monkeypatch.setattr(prepare_workspace.subprocess, "run", fake_run)

        result = resolve_python()
        assert result == venv_python
        assert any(
            "uv" in part and "venv" in command for command in captured for part in command
        )
