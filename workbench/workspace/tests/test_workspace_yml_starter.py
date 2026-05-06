"""Tests for ``chumicro_workspace.workspace_yml_starter``.

Pairs with :mod:`test_devices_yml_starter` — same workbench-owned-
content pattern, narrower contract: return the canonical
``workspace.yml`` starter content as a string, identical bytes every
call, sourced from the wheel-bundled
``_payloads/workspace.yml.template``.

Two consumers ride on this:

* The mono-repo's ``scripts/generate_config_files.py`` materialises
  ``<repo>/workspace.yml`` from this content during
  ``python scripts/run.py setup`` (when the repo's
  ``_workspace_template/workspace.yml`` doesn't override it).
* The workspace-template repo's first-clone setup materialises
  ``<workspace>/workspace.yml`` from the same source via
  ``chumicro-workspace setup``.

Tests cover:

* The reader returns a non-empty string.
* The string carries the schema documentation (defaults block +
  example credentials).
* Per Decision 0057: no `!secret` marker; the file is gitignored
  and credentials live here directly.
* The example placeholders appear commented-out so a freshly-
  materialised workspace.yml has no live values.
* Successive calls return identical bytes.
"""

from __future__ import annotations

from chumicro_workspace import read_workspace_yml_starter


class TestReadWorkspaceYmlStarter:
    """Behavioural contract of the canonical workspace.yml starter reader."""

    def test_returns_non_empty_string(self) -> None:
        content = read_workspace_yml_starter()
        assert isinstance(content, str)
        assert content.strip(), "starter must not be blank"

    def test_documents_defaults_shape(self) -> None:
        content = read_workspace_yml_starter()
        # The whole file teaches first-clone contributors how to wire
        # workspace defaults + credentials.  It must show the section-
        # namespaced shape under ``defaults:`` and call out the
        # merge precedence so users understand the per-project
        # config.toml deep-merges on top.
        assert "defaults:" in content
        assert "wifi:" in content
        assert "precedence" in content.lower()

    def test_does_not_reference_secret_marker(self) -> None:
        """Per Decision 0057: no `!secret` indirection in the starter."""
        content = read_workspace_yml_starter()
        assert "!secret" not in content

    def test_carries_commented_placeholder(self) -> None:
        content = read_workspace_yml_starter()
        # Commented example — gitignored file ships with no live
        # values so a fresh-clone workspace has nothing to leak.
        assert "# defaults:" in content
        assert "replace-me" in content

    def test_returns_identical_bytes_across_calls(self) -> None:
        """Two reads must produce the same string."""
        first = read_workspace_yml_starter()
        second = read_workspace_yml_starter()
        assert first == second
