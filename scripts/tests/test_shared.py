"""Tests for shared.py — subprocess helpers, binary resolution, and build helpers."""

import os
import shutil
from pathlib import Path

import pytest
from shared import (
    _read_prepared_binary,
    build_environment,
    build_jobs,
    install_command,
    resolve_circuitpython_binary,
    resolve_cp_mpy_cross,
    resolve_micropython_binary,
    resolve_mp_mpy_cross,
    run_command,
    running_on_native_windows,
)


class TestRunCommand:
    """Tests for run_command."""

    def test_successful_command(self, capsys):
        """Successful command returns 0."""
        result = run_command(["python", "-c", "print('ok')"])
        assert result == 0
        # Prints the command with + prefix.
        assert "+" in capsys.readouterr().out

    def test_failing_command(self):
        """Failing command returns non-zero exit code."""
        result = run_command(["python", "-c", "raise SystemExit(42)"])
        assert result == 42

    def test_prints_command(self, capsys):
        """Command is printed before execution."""
        run_command(["python", "-c", "pass"])
        captured = capsys.readouterr().out
        assert "+ python -c pass" in captured


class TestInstallCommand:
    """Tests for install_command."""

    def test_returns_list(self):
        """Returns a list of strings."""
        result = install_command()
        assert isinstance(result, list)
        assert all(isinstance(part, str) for part in result)

    def test_ends_with_install(self):
        """Command ends with 'install'."""
        result = install_command()
        assert result[-1] == "install"

    def test_uses_uv_when_available(self, monkeypatch):
        """Uses uv pip install when uv is on PATH."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
        result = install_command()
        assert result[0] == "uv"
        assert "pip" in result

    def test_falls_back_to_pip(self, monkeypatch):
        """Falls back to pip install when uv is not available."""
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        result = install_command()
        assert "-m" in result
        assert "pip" in result

    def test_custom_python(self, monkeypatch):
        """Custom python argument is passed through."""
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        result = install_command(python="/custom/python")
        assert result[0] == "/custom/python"

    def test_uv_with_custom_python(self, monkeypatch):
        """uv install with custom python uses --python flag."""
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
        result = install_command(python="/custom/python")
        assert "--python" in result
        assert "/custom/python" in result


class TestRunningOnNativeWindows:
    """Tests for running_on_native_windows."""

    def test_returns_bool(self):
        """Returns a boolean value."""
        result = running_on_native_windows()
        assert isinstance(result, bool)

    def test_matches_os_name(self):
        """Result matches whether os.name is 'nt'."""
        assert running_on_native_windows() == (os.name == "nt")


class TestBuildJobs:
    """Tests for build_jobs."""

    def test_returns_string(self):
        """Returns a string suitable for make -j."""
        result = build_jobs()
        assert isinstance(result, str)
        assert int(result) >= 1

    def test_capped_at_4(self):
        """Parallelism is capped at 4."""
        assert int(build_jobs()) <= 4


class TestBuildEnvironment:
    """Tests for build_environment."""

    def test_copies_environ(self):
        """Returns a copy of os.environ (not the same object)."""
        environment = build_environment()
        assert environment is not os.environ
        assert "PATH" in environment

    def test_adds_cflags(self):
        """Extra CFLAGS are appended."""
        environment = build_environment("-Wno-error")
        assert "-Wno-error" in environment.get("CFLAGS_EXTRA", "")

    def test_no_duplicate_flags(self):
        """Same flag passed twice is not duplicated."""
        environment = build_environment("-Wno-error", "-Wno-error")
        cflags = environment.get("CFLAGS_EXTRA", "")
        assert cflags.count("-Wno-error") == 1

    def test_preserves_existing_cflags(self, monkeypatch):
        """Existing CFLAGS_EXTRA values are preserved."""
        monkeypatch.setenv("CFLAGS_EXTRA", "-Wexisting")
        environment = build_environment("-Wnew")
        cflags = environment["CFLAGS_EXTRA"]
        assert "-Wexisting" in cflags
        assert "-Wnew" in cflags


class TestReadPreparedBinary:
    """Tests for _read_prepared_binary."""

    def test_missing_marker_returns_none(self, monkeypatch, tmp_path: Path):
        """Missing marker file returns None."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        assert _read_prepared_binary("micropython.path") is None

    def test_marker_with_nonexistent_path(self, monkeypatch, tmp_path: Path):
        """Marker pointing to nonexistent binary returns None."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        (tmp_path / "micropython.path").write_text("/nonexistent/binary")
        assert _read_prepared_binary("micropython.path") is None

    def test_marker_with_existing_path(self, monkeypatch, tmp_path: Path):
        """Marker pointing to existing binary returns the path."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        binary_path = tmp_path / "micropython"
        binary_path.touch()
        (tmp_path / "micropython.path").write_text(str(binary_path))
        result = _read_prepared_binary("micropython.path")
        assert result == str(binary_path)


class TestResolveMicropythonBinary:
    """Tests for resolve_micropython_binary."""

    def test_explicit_path_exists(self, tmp_path: Path):
        """Explicit path to existing binary is returned."""
        binary = tmp_path / "micropython"
        binary.touch()
        result = resolve_micropython_binary(str(binary))
        assert result == str(binary)

    def test_explicit_path_missing_exits(self):
        """Explicit path to nonexistent binary raises SystemExit."""
        with pytest.raises(SystemExit):
            resolve_micropython_binary("/nonexistent/micropython")

    def test_no_binary_returns_none(self, monkeypatch, tmp_path: Path):
        """When no binary is found anywhere, returns None."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        monkeypatch.setattr("shared.shutil.which", lambda _name: None)
        result = resolve_micropython_binary()
        assert result is None


class TestResolveCircuitpythonBinary:
    """Tests for resolve_circuitpython_binary."""

    def test_explicit_path_exists(self, tmp_path: Path):
        """Explicit path to existing binary is returned."""
        binary = tmp_path / "circuitpython"
        binary.touch()
        result = resolve_circuitpython_binary(str(binary))
        assert result == str(binary)

    def test_explicit_path_missing_exits(self):
        """Explicit path to nonexistent binary raises SystemExit."""
        with pytest.raises(SystemExit):
            resolve_circuitpython_binary("/nonexistent/circuitpython")

    def test_no_binary_returns_none(self, monkeypatch, tmp_path: Path):
        """When no binary is found anywhere, returns None."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        monkeypatch.setattr("shared.shutil.which", lambda _name: None)
        result = resolve_circuitpython_binary()
        assert result is None


class TestResolveCpMpyCross:
    """Tests for resolve_cp_mpy_cross."""

    def test_explicit_path_exists(self, tmp_path: Path):
        """Explicit path to existing binary is returned."""
        binary = tmp_path / "mpy-cross"
        binary.touch()
        result = resolve_cp_mpy_cross(str(binary))
        assert result == str(binary)

    def test_explicit_path_missing_exits(self):
        """Explicit path to nonexistent binary raises SystemExit."""
        with pytest.raises(SystemExit):
            resolve_cp_mpy_cross("/nonexistent/mpy-cross")

    def test_discovers_from_tools(self, monkeypatch, tmp_path: Path):
        """Finds mpy-cross in the prepared CircuitPython source tree."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        monkeypatch.setattr(
            "shared.runtime_versions",
            lambda: {"circuitpython": {"version": "10.1.4"}},
        )
        binary = tmp_path / "circuitpython-10.1.4" / "mpy-cross" / "build" / "mpy-cross"
        binary.parent.mkdir(parents=True)
        binary.touch()
        result = resolve_cp_mpy_cross()
        assert result == str(binary)

    def test_no_binary_returns_none(self, monkeypatch, tmp_path: Path):
        """When no binary is found, returns None (no PATH fallback)."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        monkeypatch.setattr(
            "shared.runtime_versions",
            lambda: {"circuitpython": {"version": "10.1.4"}},
        )
        result = resolve_cp_mpy_cross()
        assert result is None

    def test_no_circuitpython_config(self, monkeypatch, tmp_path: Path):
        """Missing circuitpython key in config returns None."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        monkeypatch.setattr("shared.runtime_versions", lambda: {})
        result = resolve_cp_mpy_cross()
        assert result is None


class TestResolveMpMpyCross:
    """Tests for resolve_mp_mpy_cross."""

    def test_explicit_path_exists(self, tmp_path: Path):
        """Explicit path to existing binary is returned."""
        binary = tmp_path / "mpy-cross"
        binary.touch()
        result = resolve_mp_mpy_cross(str(binary))
        assert result == str(binary)

    def test_explicit_path_missing_exits(self):
        """Explicit path to nonexistent binary raises SystemExit."""
        with pytest.raises(SystemExit):
            resolve_mp_mpy_cross("/nonexistent/mpy-cross")

    def test_discovers_from_tools(self, monkeypatch, tmp_path: Path):
        """Finds mpy-cross in the prepared MicroPython source tree."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        monkeypatch.setattr(
            "shared.runtime_versions",
            lambda: {"micropython": {"version": "v1.26.0"}},
        )
        binary = tmp_path / "micropython-v1.26.0" / "mpy-cross" / "build" / "mpy-cross"
        binary.parent.mkdir(parents=True)
        binary.touch()
        result = resolve_mp_mpy_cross()
        assert result == str(binary)

    def test_falls_back_to_path(self, monkeypatch, tmp_path: Path):
        """Falls back to PATH-installed mpy-cross when tree not prepared."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        monkeypatch.setattr(
            "shared.runtime_versions",
            lambda: {"micropython": {"version": "v1.26.0"}},
        )
        monkeypatch.setattr(
            "shared.shutil.which",
            lambda name: "/usr/bin/mpy-cross" if name == "mpy-cross" else None,
        )
        result = resolve_mp_mpy_cross()
        assert result == "/usr/bin/mpy-cross"

    def test_no_binary_returns_none(self, monkeypatch, tmp_path: Path):
        """When no binary is found anywhere, returns None."""
        monkeypatch.setattr("shared.TOOLS", tmp_path)
        monkeypatch.setattr(
            "shared.runtime_versions",
            lambda: {"micropython": {"version": "v1.26.0"}},
        )
        monkeypatch.setattr("shared.shutil.which", lambda _name: None)
        result = resolve_mp_mpy_cross()
        assert result is None

