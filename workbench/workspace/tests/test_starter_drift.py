"""Tests for ``chumicro_workspace.starter_drift``.

Strategy B from the setup-schema-reconciliation workstream — surface
fields the upstream starter has gained since the user materialised
their ``workspace.yml`` / ``secrets.toml``.  No auto-application;
pure print.

Coverage focuses on the diff semantics (what counts as "missing")
and the source-resolution logic (repo-specific override vs
workbench-owned starter), since those are the parts a future
contributor would extend when picking up Strategy C / D.
"""

from __future__ import annotations

import io
from pathlib import Path

from chumicro_workspace import (
    collect_missing_starter_paths,
    print_starter_drift_report,
    read_secrets_toml_starter,
)


def _write_workspace_yml(workspace_root: Path, content: str) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "workspace.yml").write_text(content, encoding="utf-8")


def _write_secrets_toml(workspace_root: Path, content: str) -> None:
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "secrets.toml").write_text(content, encoding="utf-8")


def _write_repo_override(workspace_root: Path, content: str) -> None:
    override_dir = workspace_root / "_workspace_template"
    override_dir.mkdir(parents=True, exist_ok=True)
    (override_dir / "workspace.yml").write_text(content, encoding="utf-8")


def _write_secrets_override(workspace_root: Path, content: str) -> None:
    override_dir = workspace_root / "_workspace_template"
    override_dir.mkdir(parents=True, exist_ok=True)
    (override_dir / "secrets.toml").write_text(content, encoding="utf-8")


class TestCollectMissingStarterPaths:
    """``collect_missing_starter_paths`` — pure diff semantics."""

    def test_no_user_file_returns_empty(self, tmp_path: Path) -> None:
        # Pre-materialisation: the user hasn't run setup yet, so there's
        # nothing to drift against.  Empty list is the silent path.
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []

    def test_user_matches_starter_returns_empty(self, tmp_path: Path) -> None:
        starter = "defaults:\n  wifi:\n    ssid: ap\n"
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, starter)
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []

    def test_top_level_addition_surfaces(self, tmp_path: Path) -> None:
        # Starter gained a whole new top-level section since the user
        # materialised — that's the canonical case Strategy B catches.
        starter = (
            "defaults:\n  wifi:\n    ssid: ap\n"
            "quality:\n  coverage_threshold: 85\n"
        )
        user = "defaults:\n  wifi:\n    ssid: ap\n"
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_starter_paths(workspace_root=tmp_path) == [
            "quality",
        ]

    def test_nested_addition_surfaces_with_dotted_path(
        self, tmp_path: Path,
    ) -> None:
        # Starter gained a new field inside an existing section — the
        # user's section-level branch is preserved, only the missing
        # leaf shows up, dotted.
        starter = (
            "defaults:\n"
            "  wifi:\n"
            "    ssid: ap\n"
            "    power_save: true\n"
        )
        user = "defaults:\n  wifi:\n    ssid: ap\n"
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_starter_paths(workspace_root=tmp_path) == [
            "defaults.wifi.power_save",
        ]

    def test_multiple_missing_keys_listed_in_starter_order(
        self, tmp_path: Path,
    ) -> None:
        starter = (
            "defaults:\n"
            "  wifi:\n"
            "    ssid: ap\n"
            "    power_save: true\n"
            "  mqtt:\n"
            "    broker:\n"
            "      host: example.com\n"
        )
        user = "defaults:\n  wifi:\n    ssid: ap\n"
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_starter_paths(workspace_root=tmp_path) == [
            "defaults.wifi.power_save",
            "defaults.mqtt",
        ]

    def test_user_extras_are_not_flagged(self, tmp_path: Path) -> None:
        # Diff is starter→user.  Anything the user has that the starter
        # doesn't (their own custom fields, credentials, etc.) is fine.
        starter = "defaults:\n  wifi:\n    ssid: ap\n"
        user = (
            "defaults:\n"
            "  wifi:\n"
            "    ssid: ap\n"
            "    password: super-secret\n"
            "  custom_block:\n"
            "    field: value\n"
        )
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []

    def test_scalar_in_user_blocks_subtree_recursion(
        self, tmp_path: Path,
    ) -> None:
        # The user replaced a section the starter offers as a dict with
        # a scalar.  That's their territory — don't recurse, don't
        # flag the starter's child keys as missing.
        starter = (
            "defaults:\n"
            "  wifi:\n"
            "    ssid: ap\n"
            "    password: replace-me\n"
        )
        user = "defaults:\n  wifi: my-ap-string\n"
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, user)
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []

    def test_empty_starter_returns_empty(self, tmp_path: Path) -> None:
        # Edge: a starter with nothing but comments parses to None.
        # That's "schema knows nothing"; nothing the user could be
        # missing.  Return empty list (silent).
        _write_repo_override(tmp_path, "# comment-only\n")
        _write_workspace_yml(tmp_path, "defaults:\n  wifi:\n    ssid: ap\n")
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []

    def test_non_mapping_user_returns_empty(self, tmp_path: Path) -> None:
        # Defensive: the user's file isn't a mapping at the top level.
        # The loaders module raises on this; this module is fail-soft
        # so a bad file doesn't break setup output.
        _write_repo_override(tmp_path, "defaults:\n  wifi:\n    ssid: ap\n")
        _write_workspace_yml(tmp_path, "- list\n- form\n")
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []

    def test_unparseable_user_returns_empty(self, tmp_path: Path) -> None:
        # Defensive: malformed YAML.  Same fail-soft path — surface
        # parse problems through the loaders, not through drift output.
        _write_repo_override(tmp_path, "defaults:\n  wifi:\n    ssid: ap\n")
        _write_workspace_yml(tmp_path, "defaults:\n  wifi: [unclosed\n")
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []

    def test_falls_back_to_workbench_starter_when_no_override(
        self, tmp_path: Path,
    ) -> None:
        # No `_workspace_template/workspace.yml` — the diff source is
        # the workbench-owned starter (whose entire `defaults:` block
        # ships commented-out, so a user file with any uncommented
        # `defaults:` is a strict superset).
        _write_workspace_yml(
            tmp_path,
            "defaults:\n  wifi:\n    ssid: ap\n",
        )
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []


class TestPrintStarterDriftReport:
    """``print_starter_drift_report`` — output shape + return value."""

    def test_no_drift_prints_nothing(self, tmp_path: Path) -> None:
        starter = "defaults:\n  wifi:\n    ssid: ap\n"
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, starter)
        stream = io.StringIO()
        count = print_starter_drift_report(tmp_path, stream=stream)
        assert count == 0
        assert stream.getvalue() == ""

    def test_drift_lists_each_path_and_names_source(
        self, tmp_path: Path,
    ) -> None:
        starter = (
            "defaults:\n  wifi:\n    ssid: ap\n"
            "quality:\n  coverage_threshold: 85\n"
        )
        user = "defaults:\n  wifi:\n    ssid: ap\n"
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, user)
        stream = io.StringIO()
        count = print_starter_drift_report(tmp_path, stream=stream)
        output = stream.getvalue()
        assert count == 1
        assert "missing 1 field" in output
        assert "- quality" in output
        # Source label points at the repo-specific override when it
        # exists — that's the file the user copies from.
        assert "_workspace_template/workspace.yml" in output

    def test_pluralisation_matches_count(self, tmp_path: Path) -> None:
        starter = (
            "defaults:\n  wifi:\n    ssid: ap\n"
            "quality:\n  coverage_threshold: 85\n"
            "library_sources:\n  chumicro-deploy: ./local\n"
        )
        user = "defaults:\n  wifi:\n    ssid: ap\n"
        _write_repo_override(tmp_path, starter)
        _write_workspace_yml(tmp_path, user)
        stream = io.StringIO()
        print_starter_drift_report(tmp_path, stream=stream)
        assert "missing 2 fields" in stream.getvalue()

    def test_falls_back_to_workbench_label_when_no_override(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        # The workbench-owned starter today ships with everything
        # commented out — no drift surface naturally hits this branch.
        # Stub the reader so the no-override path actually fires and
        # we can assert the source label points at the workbench
        # starter, not at the (non-existent) repo override.
        monkeypatch.setattr(
            "chumicro_workspace.starter_drift.read_workspace_yml_starter",
            lambda: "defaults:\n  wifi:\n    ssid: starter-default\n",
        )
        _write_workspace_yml(tmp_path, "library_sources: {}\n")
        stream = io.StringIO()
        count = print_starter_drift_report(tmp_path, stream=stream)
        output = stream.getvalue()
        assert count == 1
        assert "- defaults" in output
        assert "workbench-owned starter" in output
        # The repo-override hint must not leak through when there's
        # no override to copy from.
        assert "_workspace_template/workspace.yml" not in output

    def test_workbench_workspace_yml_starter_has_no_live_keys(
        self, tmp_path: Path,
    ) -> None:
        # The workbench-owned workspace.yml starter has no live
        # uncommented top-level keys (it's purely commented-out
        # examples for library_sources / deploy_targets / quality /
        # environments) — a user file with any uncommented top-level
        # key shows zero drift against it.
        _write_workspace_yml(
            tmp_path,
            "library_sources:\n  some-lib: ./path\n",
        )
        assert collect_missing_starter_paths(workspace_root=tmp_path) == []


class TestSecretsTomlDrift:
    """Same drift semantics as workspace.yml, against secrets.toml."""

    def test_no_user_file_returns_empty(self, tmp_path: Path) -> None:
        assert (
            collect_missing_starter_paths(
                workspace_root=tmp_path, filename="secrets.toml",
            )
            == []
        )

    def test_top_level_addition_surfaces(self, tmp_path: Path) -> None:
        # Starter gained a [mqtt] table; user only had [wifi].  The
        # diff convention reports the missing TOP-LEVEL key (``mqtt``)
        # rather than every leaf under it — same shape as the
        # workspace.yml diff.
        _write_secrets_override(
            tmp_path,
            '[wifi]\nssid = "x"\n[mqtt.broker]\nhost = "test.mosquitto.org"\n',
        )
        _write_secrets_toml(tmp_path, '[wifi]\nssid = "x"\n')
        missing = collect_missing_starter_paths(
            workspace_root=tmp_path, filename="secrets.toml",
        )
        assert missing == ["mqtt"]

    def test_nested_addition_surfaces_with_dotted_path(
        self, tmp_path: Path,
    ) -> None:
        # When the user already has the parent table, an addition
        # within it surfaces with the full dotted path.
        _write_secrets_override(
            tmp_path,
            '[wifi]\nssid = "x"\npassword = "y"\nhostname = "name"\n',
        )
        _write_secrets_toml(
            tmp_path, '[wifi]\nssid = "x"\npassword = "y"\n',
        )
        missing = collect_missing_starter_paths(
            workspace_root=tmp_path, filename="secrets.toml",
        )
        assert missing == ["wifi.hostname"]

    def test_user_matches_starter_returns_empty(self, tmp_path: Path) -> None:
        _write_secrets_override(tmp_path, '[wifi]\nssid = "x"\n')
        _write_secrets_toml(tmp_path, '[wifi]\nssid = "x"\n')
        assert (
            collect_missing_starter_paths(
                workspace_root=tmp_path, filename="secrets.toml",
            )
            == []
        )

    def test_workbench_starter_ships_real_placeholder_keys(
        self, tmp_path: Path,
    ) -> None:
        # The workbench-owned secrets.toml starter ships with real
        # ``wifi.ssid`` / ``wifi.password`` placeholder keys (not
        # commented examples) so the additive setup re-apply path
        # (Strategy C, future) can append new starter keys to a
        # user file without round-trip data loss.
        starter_text = read_secrets_toml_starter()
        assert "[wifi]" in starter_text
        assert "ssid" in starter_text

    def test_unparseable_user_file_returns_empty(
        self, tmp_path: Path,
    ) -> None:
        # Malformed TOML — fail-soft so a bad file never breaks setup.
        _write_secrets_override(tmp_path, '[wifi]\nssid = "x"\n')
        _write_secrets_toml(tmp_path, "not [valid] = toml-anywhere\n[")
        assert (
            collect_missing_starter_paths(
                workspace_root=tmp_path, filename="secrets.toml",
            )
            == []
        )

    def test_print_drift_report_includes_secrets_toml(
        self, tmp_path: Path,
    ) -> None:
        # Drift in secrets.toml shows up under its own header in the
        # combined drift report.
        _write_secrets_override(
            tmp_path,
            '[mqtt.broker]\nhost = "test.mosquitto.org"\n',
        )
        _write_secrets_toml(tmp_path, "")
        stream = io.StringIO()
        count = print_starter_drift_report(tmp_path, stream=stream)
        assert count >= 1
        output = stream.getvalue()
        assert "secrets.toml" in output
        assert "mqtt" in output
