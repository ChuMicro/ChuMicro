"""Tests for ``chumicro_workspace.template_drift``.

Surfaces fields the canonical workbench-owned template has gained
since the user materialised their ``workspace.yml`` / ``secrets.toml``.
The result feeds :func:`chumicro_workspace.additive_apply.additive_reapply`,
which lands the missing keys in place.

Tests inject synthetic templates by monkeypatching the canonical reader
so each case can exercise a tailored diff scenario.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace import (
    collect_missing_template_paths,
    read_secrets_toml_template,
)


def _write_workspace_yml(workspace_root: Path, content: str) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "workspace.yml").write_text(content, encoding="utf-8")


def _write_secrets_toml(workspace_root: Path, content: str) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "secrets.toml").write_text(content, encoding="utf-8")


def _patch_workspace_yml_template(
    monkeypatch: pytest.MonkeyPatch, content: str,
) -> None:
    """Make :func:`read_workspace_yml_template` return *content* for the test."""
    monkeypatch.setattr(
        "chumicro_workspace.template_drift.read_workspace_yml_template",
        lambda: content,
    )


def _patch_secrets_toml_template(
    monkeypatch: pytest.MonkeyPatch, content: str,
) -> None:
    """Make :func:`read_secrets_toml_template` return *content* for the test."""
    monkeypatch.setattr(
        "chumicro_workspace.template_drift.read_secrets_toml_template",
        lambda: content,
    )


class TestCollectMissingTemplatePaths:
    """Pure diff semantics, against ``workspace.yml``."""

    def test_no_user_file_returns_empty(self, tmp_path: Path) -> None:
        # Pre-materialisation: the user hasn't run setup yet, so there's
        # nothing to drift against.  Empty list is the silent path.
        assert collect_missing_template_paths(workspace_root=tmp_path) == []

    def test_user_matches_template_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        template = "defaults:\n  wifi:\n    ssid: ap\n"
        _patch_workspace_yml_template(monkeypatch, template)
        _write_workspace_yml(tmp_path, template)
        assert collect_missing_template_paths(workspace_root=tmp_path) == []

    def test_top_level_addition_surfaces(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Template gained a whole new top-level section since the user
        # materialised — that's the canonical case the diff catches.
        template = (
            "defaults:\n  wifi:\n    ssid: ap\n"
            "quality:\n  coverage_threshold: 85\n"
        )
        user = "defaults:\n  wifi:\n    ssid: ap\n"
        _patch_workspace_yml_template(monkeypatch, template)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_template_paths(workspace_root=tmp_path) == [
            "quality",
        ]

    def test_nested_addition_surfaces_with_dotted_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Template gained a new field inside an existing section — the
        # user's section-level branch is preserved, only the missing
        # leaf shows up, dotted.
        template = (
            "defaults:\n"
            "  wifi:\n"
            "    ssid: ap\n"
            "    power_save: true\n"
        )
        user = "defaults:\n  wifi:\n    ssid: ap\n"
        _patch_workspace_yml_template(monkeypatch, template)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_template_paths(workspace_root=tmp_path) == [
            "defaults.wifi.power_save",
        ]

    def test_multiple_missing_keys_listed_in_template_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        template = (
            "defaults:\n"
            "  wifi:\n"
            "    ssid: ap\n"
            "    power_save: true\n"
            "  mqtt:\n"
            "    broker:\n"
            "      host: example.com\n"
        )
        user = "defaults:\n  wifi:\n    ssid: ap\n"
        _patch_workspace_yml_template(monkeypatch, template)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_template_paths(workspace_root=tmp_path) == [
            "defaults.wifi.power_save",
            "defaults.mqtt",
        ]

    def test_user_extras_are_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Diff is template→user.  Anything the user has that the template
        # doesn't (their own custom fields, credentials, etc.) is fine.
        template = "defaults:\n  wifi:\n    ssid: ap\n"
        user = (
            "defaults:\n"
            "  wifi:\n"
            "    ssid: ap\n"
            "    password: super-secret\n"
            "  custom_block:\n"
            "    field: value\n"
        )
        _patch_workspace_yml_template(monkeypatch, template)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_template_paths(workspace_root=tmp_path) == []

    def test_scalar_in_user_blocks_subtree_recursion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The user replaced a section the template offers as a dict with
        # a scalar.  That's their territory — don't recurse, don't
        # flag the template's child keys as missing.
        template = (
            "defaults:\n"
            "  wifi:\n"
            "    ssid: ap\n"
            "    password: replace-me\n"
        )
        user = "defaults:\n  wifi: my-ap-string\n"
        _patch_workspace_yml_template(monkeypatch, template)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_template_paths(workspace_root=tmp_path) == []

    def test_empty_template_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Edge: a template with nothing but comments parses to None.
        # That's "schema knows nothing"; nothing the user could be
        # missing.  Return empty list (silent).
        _patch_workspace_yml_template(monkeypatch, "# comment-only\n")
        _write_workspace_yml(tmp_path, "defaults:\n  wifi:\n    ssid: ap\n")
        assert collect_missing_template_paths(workspace_root=tmp_path) == []

    def test_non_mapping_user_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Defensive: the user's file isn't a mapping at the top level.
        # The loaders module raises on this; this module is fail-soft
        # so a bad file doesn't break setup output.
        _patch_workspace_yml_template(
            monkeypatch, "defaults:\n  wifi:\n    ssid: ap\n",
        )
        _write_workspace_yml(tmp_path, "- list\n- form\n")
        assert collect_missing_template_paths(workspace_root=tmp_path) == []

    def test_unparseable_user_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Defensive: malformed YAML.  Same fail-soft path — surface
        # parse problems through the loaders, not through drift output.
        _patch_workspace_yml_template(
            monkeypatch, "defaults:\n  wifi:\n    ssid: ap\n",
        )
        _write_workspace_yml(tmp_path, "defaults:\n  wifi: [unclosed\n")
        assert collect_missing_template_paths(workspace_root=tmp_path) == []

    def test_uses_canonical_template_when_unpatched(
        self, tmp_path: Path,
    ) -> None:
        # The canonical workspace.yml template ships with everything
        # commented out — so any uncommented user file is a strict
        # superset and produces no drift.
        _write_workspace_yml(
            tmp_path,
            "defaults:\n  wifi:\n    ssid: ap\n",
        )
        assert collect_missing_template_paths(workspace_root=tmp_path) == []


class TestSecretsTomlDrift:
    """Same diff semantics as workspace.yml, against secrets.toml."""

    def test_no_user_file_returns_empty(self, tmp_path: Path) -> None:
        assert (
            collect_missing_template_paths(
                workspace_root=tmp_path, filename="secrets.toml",
            )
            == []
        )

    def test_top_level_addition_surfaces(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Template gained a [mqtt] table; user only had [wifi].  The
        # diff convention reports the missing TOP-LEVEL key (``mqtt``)
        # rather than every leaf under it — same shape as the
        # workspace.yml diff.
        _patch_secrets_toml_template(
            monkeypatch,
            '[wifi]\nssid = "x"\n[mqtt.broker]\nhost = "test.mosquitto.org"\n',
        )
        _write_secrets_toml(tmp_path, '[wifi]\nssid = "x"\n')
        missing = collect_missing_template_paths(
            workspace_root=tmp_path, filename="secrets.toml",
        )
        assert missing == ["mqtt"]

    def test_nested_addition_surfaces_with_dotted_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # When the user already has the parent table, an addition
        # within it surfaces with the full dotted path.
        _patch_secrets_toml_template(
            monkeypatch,
            '[wifi]\nssid = "x"\npassword = "y"\nhostname = "name"\n',
        )
        _write_secrets_toml(
            tmp_path, '[wifi]\nssid = "x"\npassword = "y"\n',
        )
        missing = collect_missing_template_paths(
            workspace_root=tmp_path, filename="secrets.toml",
        )
        assert missing == ["wifi.hostname"]

    def test_user_matches_template_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_secrets_toml_template(monkeypatch, '[wifi]\nssid = "x"\n')
        _write_secrets_toml(tmp_path, '[wifi]\nssid = "x"\n')
        assert (
            collect_missing_template_paths(
                workspace_root=tmp_path, filename="secrets.toml",
            )
            == []
        )

    def test_template_ships_real_placeholder_keys(self) -> None:
        # The canonical secrets.toml template ships with real
        # ``wifi.ssid`` / ``wifi.password`` placeholder keys (not
        # commented examples) so the additive setup re-apply path
        # can append new template keys to a user file without
        # round-trip data loss.
        template_text = read_secrets_toml_template()
        assert "[wifi]" in template_text
        assert "ssid" in template_text

    def test_unparseable_user_file_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Malformed TOML — fail-soft so a bad file never breaks setup.
        _patch_secrets_toml_template(monkeypatch, '[wifi]\nssid = "x"\n')
        _write_secrets_toml(tmp_path, "not [valid] = toml-anywhere\n[")
        assert (
            collect_missing_template_paths(
                workspace_root=tmp_path, filename="secrets.toml",
            )
            == []
        )
