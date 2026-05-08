"""Workspace-template readers — canonical content shipped from the wheel.

Three workspace-root files have their canonical first-write content
embedded inside a workbench wheel and materialised on first ``setup``:
``devices.yml`` (board registry — schema owned by ``chumicro-deploy``,
re-exported here for symmetry), ``workspace.yml`` (host-only workspace
machinery), and ``secrets.toml`` (workspace-wide credentials + device
defaults).

Every reader returns the file's full text — callers decide where to
write it.  The bytes travel with the wheel inside ``_payloads/``
(``chumicro-workspace``'s for ``workspace.yml`` / ``secrets.toml``,
``chumicro-deploy``'s for ``devices.yml``) so reads work in both
editable installs and pip-installed wheels.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_deploy.config.devices_yaml import read_devices_yml_template

_PAYLOADS_DIR = Path(__file__).resolve().parent / "_payloads"


def read_workspace_yml_template() -> str:
    """Return the canonical ``workspace.yml`` template content.

    Complete commented-example file with schema for
    ``library_sources:`` / ``deploy_targets:`` / ``quality:`` /
    ``environments:`` blocks.
    """
    return (_PAYLOADS_DIR / "workspace.yml.template").read_text(encoding="utf-8")


def read_secrets_toml_template() -> str:
    """Return the canonical ``secrets.toml`` template content.

    Complete TOML file carrying ``[wifi]`` and ``[mqtt.broker]``
    sections with placeholder values that fail sanity at deploy time
    but parse cleanly.  Real placeholders (not commented examples) so
    the parser round-trip preserves them and the additive re-apply
    path can append new keys without clobbering user edits.
    """
    return (_PAYLOADS_DIR / "secrets.toml.template").read_text(encoding="utf-8")


__all__ = [
    "read_devices_yml_template",
    "read_secrets_toml_template",
    "read_workspace_yml_template",
]
