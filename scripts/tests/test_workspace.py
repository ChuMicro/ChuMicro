"""Tests for workspace.py — subprocess helpers and package installation."""

import shutil

from workspace import install_command


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

