"""Tests for ``[tool.chumicro-checks]`` config loading + CLI integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_checks import Finding, Rule
from chumicro_checks._config import Config, load_config
from chumicro_checks.cli import main


def _write_pyproject(repo_root: Path, body: str) -> None:
    (repo_root / "pyproject.toml").write_text(body, encoding="utf-8")


class _AlwaysFires(Rule):
    """Test fixture: rule that emits one finding per check."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.description = f"test rule {code}"

    def check(self, repo_root: Path) -> list[Finding]:
        return [
            Finding(
                path=repo_root / "fake.py",
                line=1,
                code=self.code,
                message="example",
            )
        ]


class TestLoadConfig:
    def test_no_pyproject_yields_empty_config(self, tmp_path: Path) -> None:
        assert load_config(tmp_path) == Config()

    def test_no_section_yields_empty_config(self, tmp_path: Path) -> None:
        _write_pyproject(tmp_path, "[project]\nname = 'x'\n")
        assert load_config(tmp_path).ignore == frozenset()

    def test_ignore_list_loaded(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.chumicro-checks]\nignore = ['CHU012', 'CHU011']\n",
        )
        cfg = load_config(tmp_path)
        assert cfg.ignore == frozenset({"CHU011", "CHU012"})

    def test_ignore_codes_normalised_uppercase(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.chumicro-checks]\nignore = ['chu012', 'cHu011']\n",
        )
        assert load_config(tmp_path).ignore == frozenset({"CHU011", "CHU012"})

    def test_ignore_blank_entries_dropped(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.chumicro-checks]\nignore = ['CHU012', '', '  ']\n",
        )
        assert load_config(tmp_path).ignore == frozenset({"CHU012"})

    def test_non_list_ignore_treated_as_empty(self, tmp_path: Path) -> None:
        # Defensive: if a user typo-types `ignore = "CHU012"` (string
        # instead of list), don't crash. Just yield empty.
        _write_pyproject(
            tmp_path,
            "[tool.chumicro-checks]\nignore = 'CHU012'\n",
        )
        assert load_config(tmp_path).ignore == frozenset()

    def test_malformed_toml_raises(self, tmp_path: Path) -> None:
        import tomllib
        _write_pyproject(tmp_path, "[invalid")
        with pytest.raises(tomllib.TOMLDecodeError):
            load_config(tmp_path)


class TestCLIIntegration:
    def test_config_ignore_skips_rule(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.chumicro-checks]\nignore = ['CHU999']\n",
        )
        monkeypatch.setattr(
            "chumicro_checks.cli.registered_rules",
            lambda: {"CHU999": _AlwaysFires("CHU999")},
        )
        # CHU999 fires once normally, but config ignores it.
        assert main(["--root", str(tmp_path)]) == 0

    def test_cli_select_overrides_config_ignore(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.chumicro-checks]\nignore = ['CHU999']\n",
        )
        monkeypatch.setattr(
            "chumicro_checks.cli.registered_rules",
            lambda: {"CHU999": _AlwaysFires("CHU999")},
        )
        # --select bypasses config's ignore.
        assert main(["--root", str(tmp_path), "--select", "CHU999"]) == 1
        assert "CHU999" in capsys.readouterr().out

    def test_cli_ignore_extends_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_pyproject(
            tmp_path,
            "[tool.chumicro-checks]\nignore = ['CHU998']\n",
        )
        monkeypatch.setattr(
            "chumicro_checks.cli.registered_rules",
            lambda: {
                "CHU998": _AlwaysFires("CHU998"),
                "CHU999": _AlwaysFires("CHU999"),
            },
        )
        # Config ignores 998 and CLI ignores 999, so both are ignored.
        assert main(["--root", str(tmp_path), "--ignore", "CHU999"]) == 0

    def test_no_config_runs_all_rules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No pyproject.toml in tmp_path. Config is empty.
        monkeypatch.setattr(
            "chumicro_checks.cli.registered_rules",
            lambda: {"CHU999": _AlwaysFires("CHU999")},
        )
        assert main(["--root", str(tmp_path)]) == 1
