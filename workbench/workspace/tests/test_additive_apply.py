"""Tests for ``chumicro_workspace.additive_apply``.

When the upstream template gains a new key the user doesn't have,
append it in place — comments preserved, existing values untouched.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from chumicro_workspace.additive_apply import additive_reapply


def _patch_workspace_yml_template(
    monkeypatch: pytest.MonkeyPatch, content: str,
) -> None:
    """Make the workspace.yml template return *content* for the test."""
    monkeypatch.setattr(
        "chumicro_workspace.template_drift.read_workspace_yml_template",
        lambda: content,
    )


def _patch_secrets_toml_template(
    monkeypatch: pytest.MonkeyPatch, content: str,
) -> None:
    """Make the secrets.toml template return *content* for the test."""
    monkeypatch.setattr(
        "chumicro_workspace.template_drift.read_secrets_toml_template",
        lambda: content,
    )


class TestAdditiveReapplyToml:
    """secrets.toml — the primary user-facing target."""

    def test_no_op_when_user_file_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pre-materialization: nothing to drift against.
        _patch_secrets_toml_template(monkeypatch, '[wifi]\nssid = "x"\n')
        result = additive_reapply(tmp_path)
        assert "secrets.toml" not in result

    def test_no_op_when_user_already_has_everything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        template = '[wifi]\nssid = "x"\n'
        _patch_secrets_toml_template(monkeypatch, template)
        (tmp_path / "secrets.toml").write_text(template)
        result = additive_reapply(tmp_path)
        assert "secrets.toml" not in result

    def test_appends_missing_top_level_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Template has [wifi] + [mqtt.broker]; user only had [wifi].
        template = (
            '[wifi]\nssid = "starter-default"\n'
            '\n[mqtt.broker]\nhost = "test.mosquitto.org"\nport = 1883\n'
        )
        user = '[wifi]\nssid = "my-network"\n'
        _patch_secrets_toml_template(monkeypatch, template)
        (tmp_path / "secrets.toml").write_text(user)

        result = additive_reapply(tmp_path)
        assert result.get("secrets.toml") == ["mqtt"]

        new_text = (tmp_path / "secrets.toml").read_text()
        # Original wifi stays — value untouched.
        parsed = tomllib.loads(new_text)
        assert parsed["wifi"]["ssid"] == "my-network"
        # New mqtt block landed.
        assert parsed["mqtt"]["broker"]["host"] == "test.mosquitto.org"
        assert parsed["mqtt"]["broker"]["port"] == 1883

    def test_appends_missing_nested_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Both have [wifi]; template adds wifi.hostname.
        template = '[wifi]\nssid = "x"\nhostname = "default-host"\n'
        user = '[wifi]\nssid = "my-network"\n'
        _patch_secrets_toml_template(monkeypatch, template)
        (tmp_path / "secrets.toml").write_text(user)

        result = additive_reapply(tmp_path)
        assert result.get("secrets.toml") == ["wifi.hostname"]

        parsed = tomllib.loads((tmp_path / "secrets.toml").read_text())
        # User's edit preserved.
        assert parsed["wifi"]["ssid"] == "my-network"
        # Template's hostname appended.
        assert parsed["wifi"]["hostname"] == "default-host"

    def test_preserves_user_comments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        template = (
            '[wifi]\nssid = "x"\n'
            '\n[mqtt.broker]\nhost = "test.mosquitto.org"\n'
        )
        user = (
            "# My personal wifi notes — do not delete!\n"
            "[wifi]\n"
            "# Real SSID for the office network.\n"
            'ssid = "OfficeNet"\n'
        )
        _patch_secrets_toml_template(monkeypatch, template)
        (tmp_path / "secrets.toml").write_text(user)

        additive_reapply(tmp_path)

        new_text = (tmp_path / "secrets.toml").read_text()
        # Both user comments survived.
        assert "My personal wifi notes" in new_text
        assert "Real SSID for the office network" in new_text
        # User's value survived.
        assert "OfficeNet" in new_text

    def test_does_not_overwrite_user_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Template and user both have wifi.ssid with different values —
        # additive re-apply must leave the user's value alone.
        template = '[wifi]\nssid = "template-default"\n'
        user = '[wifi]\nssid = "user-set-this"\n'
        _patch_secrets_toml_template(monkeypatch, template)
        (tmp_path / "secrets.toml").write_text(user)

        additive_reapply(tmp_path)

        parsed = tomllib.loads((tmp_path / "secrets.toml").read_text())
        assert parsed["wifi"]["ssid"] == "user-set-this"


class TestAdditiveReapplyYaml:
    """workspace.yml — the host-only machinery file."""

    def test_appends_missing_top_level_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Template has library_sources + deploy_targets; user has only
        # library_sources.
        template = (
            "library_sources:\n  some-lib: ./path\n"
            "deploy_targets:\n  my-project: my-board\n"
        )
        user = "library_sources:\n  some-lib: ./path\n"
        _patch_workspace_yml_template(monkeypatch, template)
        (tmp_path / "workspace.yml").write_text(user)

        result = additive_reapply(tmp_path)
        assert result.get("workspace.yml") == ["deploy_targets"]

        new_text = (tmp_path / "workspace.yml").read_text()
        # Original library_sources preserved.
        assert "library_sources:" in new_text
        # New deploy_targets block landed.
        assert "deploy_targets:" in new_text
        assert "my-project: my-board" in new_text

    def test_preserves_user_comments_in_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        template = (
            "library_sources:\n  some-lib: ./path\n"
            "deploy_targets:\n  my-project: my-board\n"
        )
        user = (
            "# These are my dev-mode editable installs.\n"
            "library_sources:\n"
            "  # Pinned to my work-in-progress branch.\n"
            "  some-lib: /Users/me/checkout/src\n"
        )
        _patch_workspace_yml_template(monkeypatch, template)
        (tmp_path / "workspace.yml").write_text(user)

        additive_reapply(tmp_path)

        new_text = (tmp_path / "workspace.yml").read_text()
        assert "These are my dev-mode editable installs" in new_text
        assert "Pinned to my work-in-progress branch" in new_text
        assert "/Users/me/checkout/src" in new_text


class TestPrivateHelpers:
    """Direct coverage of internal helpers — the writer's defensive
    branches (path missing from template, intermediate-table creation)
    can't be reached via the public driver because
    ``collect_missing_template_paths`` only returns paths known to
    exist in the template, so test them in isolation."""

    def test_toml_writer_skips_paths_missing_from_template(
        self, tmp_path: Path,
    ) -> None:
        from chumicro_workspace.additive_apply import _append_missing_toml  # noqa: PLC0415

        # Path "nope.gone" doesn't exist in template — writer skips it.
        result = _append_missing_toml(
            user_text="[wifi]\nssid = 'x'\n",
            template_text="[wifi]\nssid = 'x'\n",
            missing_paths=["nope.gone"],
        )
        # Round-trip leaves the user file effectively unchanged
        # (tomlkit may normalize whitespace; just confirm content stable).
        import tomllib  # noqa: PLC0415
        assert tomllib.loads(result) == {"wifi": {"ssid": "x"}}

    def test_toml_writer_creates_intermediate_tables(self) -> None:
        from chumicro_workspace.additive_apply import _append_missing_toml  # noqa: PLC0415

        # Pretend the diff returned a deep dotted path whose intermediate
        # table doesn't exist in the user yet.  The writer must create it.
        result = _append_missing_toml(
            user_text="",
            template_text='[a.b.c]\nd = "from-starter"\n',
            missing_paths=["a.b.c.d"],
        )
        import tomllib  # noqa: PLC0415
        assert tomllib.loads(result) == {"a": {"b": {"c": {"d": "from-starter"}}}}

    def test_yaml_writer_skips_paths_missing_from_template(self) -> None:
        from chumicro_workspace.additive_apply import _append_missing_yaml  # noqa: PLC0415
        from ruamel.yaml import YAML  # noqa: PLC0415

        result = _append_missing_yaml(
            user_text="library_sources:\n  some-lib: ./path\n",
            template_text="library_sources:\n  some-lib: ./path\n",
            missing_paths=["nonexistent.path"],
        )
        assert YAML(typ="safe").load(result) == {"library_sources": {"some-lib": "./path"}}

    def test_yaml_writer_creates_intermediate_mappings(self) -> None:
        from chumicro_workspace.additive_apply import _append_missing_yaml  # noqa: PLC0415
        from ruamel.yaml import YAML  # noqa: PLC0415

        result = _append_missing_yaml(
            user_text="",
            template_text="a:\n  b:\n    c: value\n",
            missing_paths=["a.b.c"],
        )
        assert YAML(typ="safe").load(result) == {"a": {"b": {"c": "value"}}}


class TestAdditiveReapplyMixed:
    """Both files together — the realistic ``setup`` flow."""

    def test_walks_both_targets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_workspace_yml_template(
            monkeypatch, "deploy_targets:\n  proj: board\n",
        )
        _patch_secrets_toml_template(
            monkeypatch, '[wifi]\nssid = "x"\n',
        )
        (tmp_path / "workspace.yml").write_text("# empty\n")
        (tmp_path / "secrets.toml").write_text("# empty\n")

        result = additive_reapply(tmp_path)
        assert "workspace.yml" in result
        assert "secrets.toml" in result

    def test_skips_files_with_no_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_workspace_yml_template(monkeypatch, "deploy_targets:\n  p: b\n")
        _patch_secrets_toml_template(monkeypatch, '[wifi]\nssid = "x"\n')
        # User's workspace.yml is missing the template block; secrets
        # already has it.
        (tmp_path / "workspace.yml").write_text("# empty\n")
        (tmp_path / "secrets.toml").write_text('[wifi]\nssid = "x"\n')

        result = additive_reapply(tmp_path)
        assert "workspace.yml" in result
        assert "secrets.toml" not in result
