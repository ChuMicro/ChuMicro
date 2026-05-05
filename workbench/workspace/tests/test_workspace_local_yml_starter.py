"""Tests for ``chumicro_workspace.workspace_local_yml_starter``.

Pairs with :mod:`test_devices_yml_starter` — same workbench-owned-
content pattern, narrower contract: return the canonical
``workspace.local.yml`` starter content as a string, identical bytes
every call, sourced from the wheel-bundled
``_payloads/workspace_local_yml/starter.yml.template``.

Two consumers ride on this:

* The mono-repo's ``scripts/generate_config_files.py`` materialises
  ``<repo>/workspace.local.yml`` from this content during
  ``python scripts/run.py setup``.
* The workspace-template repo's first-clone setup materialises
  ``<workspace>/workspace.local.yml`` from the same source via
  ``chumicro-workspace setup``.

Tests cover:

* The reader returns a non-empty string.
* The string explains the structural-overlay design (no `!secret`
  marker mentioned — Decision 0057 retired that indirection).
* The example placeholder appears commented-out so a freshly-
  materialised workspace.local.yml has no live values.
* Successive calls return identical bytes.
"""

from __future__ import annotations

from chumicro_workspace import read_workspace_local_yml_starter


class TestReadWorkspaceLocalYmlStarter:
    """Behavioural contract of the canonical overlay starter reader."""

    def test_returns_non_empty_string(self) -> None:
        content = read_workspace_local_yml_starter()
        assert isinstance(content, str)
        assert content.strip(), "starter must not be blank"

    def test_documents_overlay_shape(self) -> None:
        content = read_workspace_local_yml_starter()
        # The whole file teaches first-clone contributors how to wire
        # credentials.  It must show the section-namespaced shape
        # (matches workspace.yml exactly) and the merge precedence
        # so users understand workspace.local.yml is just another
        # deep-merge layer.
        assert "defaults:" in content
        assert "wifi:" in content
        # Must spell out the merge precedence explicitly so users
        # understand which layer wins.
        assert "precedence" in content.lower()

    def test_does_not_reference_secret_marker(self) -> None:
        """Decision 0057: the `!secret` indirection is gone — no resurrection."""
        content = read_workspace_local_yml_starter()
        assert "!secret" not in content

    def test_carries_commented_placeholder(self) -> None:
        content = read_workspace_local_yml_starter()
        # Commented example — gitignored file ships with no live
        # values so a fresh-clone workspace has nothing to leak.
        assert "# defaults:" in content
        assert "replace-me" in content

    def test_returns_identical_bytes_across_calls(self) -> None:
        """Two reads must produce the same string.

        Pure side-effect-free reader; protects against a future
        change that adds e.g. a "fill in current date" template
        substitution that would make two consecutive calls differ.
        """
        first = read_workspace_local_yml_starter()
        second = read_workspace_local_yml_starter()
        assert first == second
