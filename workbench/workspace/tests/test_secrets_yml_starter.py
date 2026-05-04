"""Tests for ``chumicro_workspace.secrets_yml_starter``.

Pairs with :mod:`test_devices_yml_starter` — same workbench-owned-
content pattern, narrower contract: return the canonical
``secrets.yml`` starter content as a string, identical bytes every
call, sourced from the wheel-bundled
``_payloads/secrets_yml/starter.yml.template``.

Two consumers ride on this:

* The mono-repo's ``scripts/generate_config_files.py`` materialises
  ``<repo>/secrets.yml`` from this content during
  ``python scripts/run.py setup`` (Phase 3 of the unification
  workstream).
* The workspace-template repo's first-clone setup will materialise
  ``<workspace>/secrets.yml`` from the same source — currently the
  template repo carries its own static
  ``_workspace_template/secrets.yml``; a planned follow-up replaces
  that with a call to this reader.

Tests cover:

* The reader returns a non-empty string.
* The string includes the documented schema header (``!secret <name>``,
  flat ``key: value`` pairs).
* The example placeholders (``wifi_password``, ``api_token``) appear
  commented-out so a fresh-clone secrets.yml has no live values.
* Successive calls return identical bytes.
"""

from __future__ import annotations

from chumicro_workspace import read_secrets_yml_starter


class TestReadSecretsYmlStarter:
    """Behavioural contract of the canonical secrets-store starter reader."""

    def test_returns_non_empty_string(self) -> None:
        content = read_secrets_yml_starter()
        assert isinstance(content, str)
        assert content.strip(), "starter must not be blank"

    def test_documents_secret_marker_syntax(self) -> None:
        content = read_secrets_yml_starter()
        # The whole file is a teaching artifact for first-clone
        # contributors — it must explain the ``!secret <name>``
        # indirection or new users won't know how to wire creds.
        assert "!secret" in content
        # And it must show the resolution order so users understand
        # workspace.yml + project config get merged before secrets
        # land.
        assert "deploy-time merge" in content.lower() or (
            "deploy time" in content.lower()
        )

    def test_carries_commented_placeholders(self) -> None:
        content = read_secrets_yml_starter()
        # Two canonical example credential names.  Both commented
        # so a freshly-materialised secrets.yml has no live values
        # (the file is gitignored, but we still don't want to ship
        # accidental live placeholders).
        assert "# wifi_password:" in content
        assert "# api_token:" in content

    def test_returns_identical_bytes_across_calls(self) -> None:
        """Two reads must produce the same string.

        Pure side-effect-free reader; protects against a future
        change that adds e.g. a "fill in current date" template
        substitution that would make two consecutive calls differ.
        """
        first = read_secrets_yml_starter()
        second = read_secrets_yml_starter()
        assert first == second
