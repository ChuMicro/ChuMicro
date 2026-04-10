"""Tests for check_version.py — VERSION enforcement logic."""

from check_version import _check


class TestCheck:
    """Tests for the _check function."""

    def test_no_changed_files(self, monkeypatch, capsys):
        """No changes produces a clean exit."""
        monkeypatch.setattr("check_version.changed_files", lambda _base: [])
        result = _check("origin/main")
        assert result == 0
        assert "No changed files detected" in capsys.readouterr().out

    def test_non_library_changes_only(self, monkeypatch, capsys):
        """Changes outside libraries/ are not release-relevant."""
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["scripts/run.py", "README.md"],
        )
        result = _check("origin/main")
        assert result == 0
        assert "No release-relevant library changes" in capsys.readouterr().out

    def test_src_change_with_version_bump(self, monkeypatch, capsys):
        """src/ change with VERSION bump passes."""
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: [
                "libraries/timing/src/chumicro_timing/core.py",
                "libraries/timing/VERSION",
            ],
        )
        monkeypatch.setattr("check_version.release_tags", lambda _name: [])
        result = _check("origin/main")
        assert result == 0
        assert "OK:" in capsys.readouterr().out

    def test_src_change_without_version_bump_fails(self, monkeypatch, capsys):
        """src/ change without VERSION bump fails."""
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/timing/src/chumicro_timing/core.py"],
        )
        result = _check("origin/main")
        assert result == 1
        assert "FAIL:" in capsys.readouterr().out

    def test_pyproject_change_requires_bump(self, monkeypatch, capsys):
        """pyproject.toml change without VERSION bump fails."""
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/runner/pyproject.toml"],
        )
        result = _check("origin/main")
        assert result == 1
        assert "FAIL:" in capsys.readouterr().out

    def test_test_change_does_not_require_bump(self, monkeypatch, capsys):
        """tests/ change is not release-relevant and doesn't need a bump."""
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/timing/tests/test_ticks.py"],
        )
        result = _check("origin/main")
        assert result == 0
        assert "No release-relevant" in capsys.readouterr().out

    def test_version_only_change(self, monkeypatch, capsys):
        """Bumping VERSION without src/ changes is fine (unusual but valid)."""
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/timing/VERSION"],
        )
        monkeypatch.setattr("check_version.release_tags", lambda _name: [])
        result = _check("origin/main")
        assert result == 0

    def test_multiple_libraries_one_missing(self, monkeypatch, capsys):
        """When two libraries change, failing one causes overall failure."""
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: [
                "libraries/timing/src/chumicro_timing/core.py",
                "libraries/timing/VERSION",
                "libraries/runner/src/chumicro_runner/core.py",
                # runner VERSION not bumped
            ],
        )
        monkeypatch.setattr("check_version.release_tags", lambda _name: [])
        result = _check("origin/main")
        assert result == 1
        captured = capsys.readouterr().out
        # _check returns 1 immediately after printing FAIL lines —
        # the OK messages for compliant libraries are never reached.
        assert "FAIL: libraries/runner/" in captured

    def test_git_failure_returns_2(self, monkeypatch):
        """Git failure propagates as exit code 2."""
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: (_ for _ in ()).throw(RuntimeError("git diff failed")),
        )
        result = _check("origin/main")
        assert result == 2

