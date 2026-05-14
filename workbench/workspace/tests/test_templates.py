"""Tests for ``chumicro_workspace.templates`` — the canonical first-write
content shipped from the workbench wheel for ``workspace.yml`` /
``secrets.toml``, plus the re-exported ``devices.yml`` reader from
``chumicro_deploy``.

Each reader returns a string sourced from a ``.template`` file inside
the owning package's ``_payloads/`` so reads work in editable installs
and pip-installed wheels alike.
"""

from __future__ import annotations

from chumicro_workspace.templates import (
    read_devices_yml_template,
    read_secrets_toml_template,
    read_workspace_yml_template,
)


class TestReadWorkspaceYmlTemplate:
    """``workspace.yml`` — host-only workspace machinery."""

    def test_returns_non_empty_string(self) -> None:
        content = read_workspace_yml_template()
        assert isinstance(content, str)
        assert content.strip(), "template must not be blank"

    def test_lists_top_level_blocks(self) -> None:
        # The template documents the four optional blocks the workspace
        # machinery understands.
        content = read_workspace_yml_template()
        assert "library_sources" in content
        assert "deploy_targets" in content
        assert "quality" in content
        assert "environments" in content

    def test_blocks_ship_commented_out(self) -> None:
        # workspace.yml is gitignored.  A fresh-materialized workspace
        # has no live values so contributors opt in deliberately.
        content = read_workspace_yml_template()
        for marker in ("# library_sources:", "# deploy_targets:", "# quality:"):
            assert marker in content

    def test_points_credentials_at_secrets_toml(self) -> None:
        # Two-file split: machinery in workspace.yml, credentials in
        # secrets.toml.  The workspace.yml header tells the reader
        # where credentials go.
        content = read_workspace_yml_template()
        assert "secrets.toml" in content

    def test_returns_identical_bytes_across_calls(self) -> None:
        assert read_workspace_yml_template() == read_workspace_yml_template()


class TestReadSecretsTomlTemplate:
    """``secrets.toml`` — workspace-wide credentials + device defaults."""

    def test_returns_non_empty_string(self) -> None:
        content = read_secrets_toml_template()
        assert isinstance(content, str)
        assert content.strip()

    def test_carries_real_placeholder_keys(self) -> None:
        # Real placeholders (not commented examples) so the additive
        # re-apply path can append new keys without round-trip data
        # loss.
        content = read_secrets_toml_template()
        assert "[wifi]" in content
        assert "ssid" in content
        assert "[mqtt.broker]" in content

    def test_returns_identical_bytes_across_calls(self) -> None:
        assert read_secrets_toml_template() == read_secrets_toml_template()


class TestReadDevicesYmlTemplate:
    """``devices.yml`` — board registry; schema + content owned by
    ``chumicro-deploy``, re-exported here for symmetry."""

    def test_returns_non_empty_string(self) -> None:
        content = read_devices_yml_template()
        assert isinstance(content, str)
        assert content.strip()

    def test_three_zone_shape(self) -> None:
        # The template embeds the ownership-zone vocabulary so a
        # contributor reading the file understands which fields they
        # own vs. which the tool refreshes.
        content = read_devices_yml_template()
        assert "USER-OWNED" in content
        assert "HARDWARE-ONCE" in content
        assert "PROBED-ALWAYS" in content

    def test_empty_devices_registry(self) -> None:
        # Fresh-materialized registry must parse to an empty list so
        # ``add-device`` can append without a hand-edit.
        content = read_devices_yml_template()
        assert "devices: []" in content

    def test_defaults_block_unset(self) -> None:
        # ``defaults.{micropython,circuitpython}`` are filled by
        # ``add-device`` on first registration.
        content = read_devices_yml_template()
        assert "micropython: null" in content
        assert "circuitpython: null" in content

    def test_returns_identical_bytes_across_calls(self) -> None:
        assert read_devices_yml_template() == read_devices_yml_template()
