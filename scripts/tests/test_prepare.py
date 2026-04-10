"""Tests for prepare.py — binary resolution and build helpers."""

import os
from pathlib import Path

import pytest
from prepare import (
    _read_prepared_binary,
    build_environment,
    build_jobs,
    resolve_circuitpython_binary,
    resolve_micropython_binary,
    running_on_native_windows,
)


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
        monkeypatch.setattr("prepare.TOOLS", tmp_path)
        assert _read_prepared_binary("micropython.path") is None

    def test_marker_with_nonexistent_path(self, monkeypatch, tmp_path: Path):
        """Marker pointing to nonexistent binary returns None."""
        monkeypatch.setattr("prepare.TOOLS", tmp_path)
        (tmp_path / "micropython.path").write_text("/nonexistent/binary")
        assert _read_prepared_binary("micropython.path") is None

    def test_marker_with_existing_path(self, monkeypatch, tmp_path: Path):
        """Marker pointing to existing binary returns the path."""
        monkeypatch.setattr("prepare.TOOLS", tmp_path)
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
        monkeypatch.setattr("prepare.TOOLS", tmp_path)
        monkeypatch.setattr("prepare.shutil.which", lambda _name: None)
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
        monkeypatch.setattr("prepare.TOOLS", tmp_path)
        monkeypatch.setattr("prepare.shutil.which", lambda _name: None)
        result = resolve_circuitpython_binary()
        assert result is None

