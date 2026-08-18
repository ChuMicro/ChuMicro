"""Tests for docs_deploy.py — the mike invocation and its URL layout.

Every test drives the real ``docs_deploy`` against recorded fakes: the
mike calls are captured instead of run, discovery returns synthetic
package dirs, and the landing-page injection is stubbed out.  What the
tests assert is the shape of the command line, because that shape is
what decides the published URLs.
"""

from __future__ import annotations

import json
from pathlib import Path

import docs_deploy
import pytest


@pytest.fixture
def synthetic_library(tmp_path: Path, monkeypatch) -> Path:
    """One synthetic library with a VERSION file, wired into discovery."""
    library_dir = tmp_path / "libraries" / "lib_a"
    library_dir.mkdir(parents=True)
    (library_dir / "mkdocs.yml").write_text("site_name: chumicro-lib_a\n")
    (library_dir / "VERSION").write_text("1.2.3\n")

    monkeypatch.setattr(docs_deploy, "discover_doc_dirs", lambda: [library_dir])
    monkeypatch.setattr(docs_deploy, "copy_shared_docs_assets", lambda _dirs: None)
    monkeypatch.setattr(docs_deploy, "inject_landing_page", lambda _branch: None)
    return library_dir


@pytest.fixture
def recorded_commands(monkeypatch) -> list[list[str]]:
    """Record every mike command instead of running it."""
    commands: list[list[str]] = []

    def fake_run_command(command: list[str]) -> int:
        commands.append(command)
        return 0

    monkeypatch.setattr(docs_deploy, "run_command", fake_run_command)
    return commands


def _fake_mike_list(monkeypatch, deployed: list[dict]) -> None:
    """Make ``mike list -j`` report *deployed*."""
    class Completed:
        returncode = 0
        stdout = json.dumps(deployed).encode()

    monkeypatch.setattr(
        docs_deploy.subprocess, "run", lambda *args, **kwargs: Completed(),
    )


def _deploy_command(commands: list[list[str]]) -> list[str]:
    return next(command for command in commands if command[1] == "deploy")


class TestChannelNamedVersions:
    """The published URL carries the channel, not the release number."""

    def test_stable_deploys_the_channel_with_the_release_as_alias(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        _fake_mike_list(monkeypatch, [])
        assert docs_deploy.docs_deploy("stable", branch="gh-pages") == 0

        command = _deploy_command(recorded_commands)
        assert command[-2:] == ["stable", "1.2.3"]
        assert "--alias-type" in command
        assert command[command.index("--alias-type") + 1] == "redirect"

    def test_stable_title_carries_the_release_number(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        _fake_mike_list(monkeypatch, [])
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        command = _deploy_command(recorded_commands)
        assert command[command.index("-t") + 1] == "stable (1.2.3)"

    def test_experimental_deploys_the_channel_with_dev_as_alias(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        _fake_mike_list(monkeypatch, [])
        docs_deploy.docs_deploy("experimental", branch="gh-pages")

        command = _deploy_command(recorded_commands)
        assert command[-2:] == ["experimental", "dev"]

    def test_library_without_a_version_file_deploys_experimental(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        (synthetic_library / "VERSION").unlink()
        _fake_mike_list(monkeypatch, [])
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        command = _deploy_command(recorded_commands)
        assert command[-2:] == ["experimental", "dev"]


class TestRetireConflictingNames:
    """Docs deployed under the old layout are cleared before deploying."""

    def test_release_numbered_version_is_retired(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        """The old layout put 1.2.3 in the version slot; the new one
        wants it as an alias, which mike refuses until it's gone."""
        _fake_mike_list(
            monkeypatch, [{"version": "1.2.3", "aliases": ["stable"]}],
        )
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        deletes = [c for c in recorded_commands if c[1] == "delete"]
        assert "1.2.3" in deletes[0]

    def test_channel_name_held_as_an_alias_is_retired(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        _fake_mike_list(
            monkeypatch, [{"version": "0.9.0", "aliases": ["stable"]}],
        )
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        deletes = [c for c in recorded_commands if c[1] == "delete"]
        assert deletes[0][-1] == "0.9.0"

    def test_current_layout_needs_no_retirement(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        _fake_mike_list(
            monkeypatch, [{"version": "stable", "aliases": ["1.2.2"]}],
        )
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        assert [c for c in recorded_commands if c[1] == "delete"] == []

    def test_empty_branch_needs_no_retirement(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        class Failed:
            returncode = 1
            stdout = b""

        monkeypatch.setattr(
            docs_deploy.subprocess, "run", lambda *args, **kwargs: Failed(),
        )
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        assert [c for c in recorded_commands if c[1] == "delete"] == []


class TestFoldReleaseUrlsIntoRedirects:
    """Release-numbered URLs point at the docs that ship today."""

    def test_retired_release_url_comes_back_as_a_redirect(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        """The number the old layout used as a version does not 404:
        it is re-added as an alias of the stable docs."""
        _fake_mike_list(
            monkeypatch, [{"version": "1.2.2", "aliases": ["stable"]}],
        )
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        aliases = [c for c in recorded_commands if c[1] == "alias"]
        assert aliases, "expected a mike alias call"
        assert aliases[0][-2:] == ["stable", "1.2.2"]
        assert aliases[0][aliases[0].index("--alias-type") + 1] == "redirect"

    def test_archived_release_directories_become_redirects(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        """Older release directories still holding a frozen copy are
        deleted and handed back as redirects to the living docs."""
        _fake_mike_list(monkeypatch, [
            {"version": "stable", "aliases": ["1.2.3"]},
            {"version": "1.1.0", "aliases": []},
            {"version": "1.0.0", "aliases": []},
        ])
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        deletes = [c for c in recorded_commands if c[1] == "delete"]
        assert "1.1.0" in deletes[-1] and "1.0.0" in deletes[-1]
        aliases = [c for c in recorded_commands if c[1] == "alias"]
        assert aliases[0][-2:] == ["1.0.0", "1.1.0"] or set(aliases[0][-2:]) == {
            "1.0.0", "1.1.0",
        }

    def test_existing_alias_is_left_alone(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        """A release number already aliased needs no second pass."""
        _fake_mike_list(monkeypatch, [
            {"version": "stable", "aliases": ["1.2.3"]},
        ])
        docs_deploy.docs_deploy("stable", branch="gh-pages")

        assert [c for c in recorded_commands if c[1] == "alias"] == []

    def test_experimental_deploy_leaves_release_urls_alone(
        self, synthetic_library, recorded_commands, monkeypatch,
    ):
        """Release numbers belong to stable; an experimental deploy is
        not entitled to repoint them."""
        _fake_mike_list(monkeypatch, [
            {"version": "stable", "aliases": ["1.2.3"]},
            {"version": "1.1.0", "aliases": []},
        ])
        docs_deploy.docs_deploy("experimental", branch="gh-pages")

        assert [c for c in recorded_commands if c[1] == "alias"] == []
        assert [c for c in recorded_commands if c[1] == "delete"] == []


class TestVerificationFiles:
    """File-based proofs and the IndexNow key publish at the docs root."""

    def test_html_proof_publishes_at_the_root(self, tmp_path, monkeypatch):
        """Search Console's file method uses google<hash>.html."""
        verification = tmp_path / "site-verification"
        verification.mkdir()
        (verification / "google123.html").write_text("google-site-verification\n")
        monkeypatch.setattr(docs_deploy, "VERIFICATION_DIR", verification)
        monkeypatch.setattr(docs_deploy.index_now, "read_key", lambda: "")
        monkeypatch.setattr(docs_deploy, "_hash_file", lambda path: "blob-sha")

        assert docs_deploy._verification_file_blobs() == [("blob-sha", "google123.html")]

    def test_xml_proof_publishes_too(self, tmp_path, monkeypatch):
        """Bing's file method uses BingSiteAuth.xml."""
        verification = tmp_path / "site-verification"
        verification.mkdir()
        (verification / "BingSiteAuth.xml").write_text("<users/>\n")
        monkeypatch.setattr(docs_deploy, "VERIFICATION_DIR", verification)
        monkeypatch.setattr(docs_deploy.index_now, "read_key", lambda: "")
        monkeypatch.setattr(docs_deploy, "_hash_file", lambda path: "blob-sha")

        assert docs_deploy._verification_file_blobs() == [
            ("blob-sha", "BingSiteAuth.xml"),
        ]

    def test_indexnow_key_publishes_under_its_own_name(self, tmp_path, monkeypatch):
        """A crawler checks the ping against <key>.txt at the root."""
        monkeypatch.setattr(docs_deploy, "VERIFICATION_DIR", tmp_path / "absent")
        monkeypatch.setattr(docs_deploy.index_now, "read_key", lambda: "abc123")
        monkeypatch.setattr(docs_deploy, "_hash_blob", lambda content: "blob-sha")

        assert docs_deploy._verification_file_blobs() == [("blob-sha", "abc123.txt")]

    def test_nothing_configured_publishes_nothing_extra(self, tmp_path, monkeypatch):
        monkeypatch.setattr(docs_deploy, "VERIFICATION_DIR", tmp_path / "absent")
        monkeypatch.setattr(docs_deploy.index_now, "read_key", lambda: "")

        assert docs_deploy._verification_file_blobs() == []
