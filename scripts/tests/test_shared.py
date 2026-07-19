"""Tests for shared.py — subprocess helpers, binary resolution, and build helpers."""

import os
import shutil
import sys
from pathlib import Path

import pytest
import shared
from shared import (
    _read_prepared_binary,
    build_environment,
    build_jobs,
    ensure_build_tools,
    install_command,
    install_editable,
    resolve_circuitpython_binary,
    resolve_cp_mpy_cross,
    resolve_micropython_binary,
    resolve_mp_mpy_cross,
    run_command,
    running_on_native_windows,
    stream_subprocess,
)


class TestRunCommand:
    """Tests for run_command."""

    def test_successful_command(self, capsys):
        """Successful command returns 0."""
        # Use sys.executable so the test works on systems where the
        # bare ``python`` symlink isn't on PATH (Homebrew installs only
        # python3 / python3.14).
        result = run_command([sys.executable, "-c", "print('ok')"])
        assert result == 0
        # Prints the command with + prefix.
        assert "+" in capsys.readouterr().out

    def test_failing_command(self):
        """Failing command returns non-zero exit code."""
        result = run_command([sys.executable, "-c", "raise SystemExit(42)"])
        assert result == 42

    def test_prints_command(self, capsys):
        """Command is printed before execution."""
        run_command([sys.executable, "-c", "pass"])
        captured = capsys.readouterr().out
        assert f"+ {sys.executable} -c pass" in captured


class TestStreamSubprocess:
    """Tests for stream_subprocess — the live line-streaming helper."""

    def test_returns_exit_code_and_captured_text(self):
        """Both the exit code and the joined captured transcript come back."""
        exit_code, captured = stream_subprocess(
            [sys.executable, "-c", "print('hello'); print('world')"],
        )
        assert exit_code == 0
        assert "hello" in captured
        assert "world" in captured
        assert captured.endswith("\n")

    def test_failing_command_returns_nonzero(self):
        """Non-zero exit code propagates."""
        exit_code, _ = stream_subprocess(
            [sys.executable, "-c", "raise SystemExit(7)"],
        )
        assert exit_code == 7

    def test_on_line_callback_fires_per_line(self):
        """Each line read from the child invokes ``on_line`` once."""
        lines: list[str] = []
        stream_subprocess(
            [
                sys.executable, "-c",
                "import sys; print('one'); print('two'); print('three')",
            ],
            on_line=lines.append,
        )
        assert lines == ["one", "two", "three"]

    def test_stderr_merged_into_stdout_stream(self):
        """Stderr lines arrive on the same line stream as stdout."""
        lines: list[str] = []
        stream_subprocess(
            [
                sys.executable, "-c",
                "import sys; print('out'); print('err', file=sys.stderr)",
            ],
            on_line=lines.append,
        )
        assert "out" in lines
        assert "err" in lines


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


class TestInstallEditable:
    """Tests for install_editable."""

    def test_includes_parked_libraries(self, monkeypatch):
        """Editable install passes ``include_parked=True`` so parked
        libraries (Decision 0107) stay importable — parking holds a
        library out of the publish set, not out of the workspace."""
        recorded: dict[str, object] = {}

        def _fake_publishable(*, include_parked: bool = False):
            recorded["include_parked"] = include_parked
            return ["libraries/logging"] if include_parked else []

        monkeypatch.setattr(shared, "find_publishable_packages", _fake_publishable)
        monkeypatch.setattr(shared, "find_support_packages", list)
        monkeypatch.setattr(shared, "run_command", lambda command: 0)

        assert install_editable() == 0
        assert recorded["include_parked"] is True

    def test_dedupes_support_package_in_both_lists(self, monkeypatch):
        """A VERSION'd support package appears in both find_publishable_packages
        and find_support_packages (Decision 0111); install_editable installs
        it once, not twice."""
        recorded: dict[str, list[str]] = {}

        def _capture(command):
            recorded["cmd"] = command
            return 0

        monkeypatch.setattr(
            shared,
            "find_publishable_packages",
            lambda *, include_parked=False: ["libraries/timing", "support/test_harness"],
        )
        monkeypatch.setattr(
            shared, "find_support_packages", lambda: ["support/test_harness"],
        )
        monkeypatch.setattr(shared, "run_command", _capture)
        monkeypatch.setattr(shared, "install_command", lambda python: ["pip", "install"])

        assert install_editable() == 0
        assert recorded["cmd"].count("support/test_harness") == 1


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
        assert "-Wno-error" in environment.get("CFLAGS", "")

    def test_no_duplicate_flags(self):
        """Same flag passed twice is not duplicated."""
        environment = build_environment("-Wno-error", "-Wno-error")
        cflags = environment.get("CFLAGS", "")
        assert cflags.count("-Wno-error") == 1

    def test_preserves_existing_cflags(self, monkeypatch):
        """Existing CFLAGS values are preserved."""
        monkeypatch.setenv("CFLAGS", "-Wexisting")
        environment = build_environment("-Wnew")
        cflags = environment["CFLAGS"]
        assert "-Wexisting" in cflags
        assert "-Wnew" in cflags


class TestEnsureBuildTools:
    """Tests for ensure_build_tools."""

    def test_passes_when_tools_exist(self, monkeypatch):
        """Does not raise when git, make, and cc are all on PATH."""
        monkeypatch.setattr("shared.shutil.which", lambda _name: "/usr/bin/tool")
        ensure_build_tools()  # Should not raise.

    def test_raises_when_tool_missing(self, monkeypatch):
        """Raises RuntimeError when a required tool is missing."""
        monkeypatch.setattr("shared.shutil.which", lambda _name: None)
        with pytest.raises(RuntimeError, match="Required tool not found"):
            ensure_build_tools()

    def test_checks_all_three_tools(self, monkeypatch):
        """Checks for git, make, and cc specifically."""
        checked_tools: list[str] = []

        def track_which(name):
            checked_tools.append(name)
            return f"/usr/bin/{name}"

        monkeypatch.setattr("shared.shutil.which", track_which)
        ensure_build_tools()
        assert set(checked_tools) == {"git", "make", "cc"}


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
