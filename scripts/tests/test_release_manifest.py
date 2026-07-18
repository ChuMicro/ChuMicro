"""Tests for scripts/release_manifest.py — the releases.json correlation index."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from release_manifest import build_entry, main, update_index  # noqa: E402

_MATRIX = {
    "include": [
        {"library_name": "http_server", "version": "0.18.1"},
        {"library_name": "wifi", "version": "0.8.0"},
    ],
}


class TestBuildEntry:
    def test_projects_matrix_and_tags(self):
        entry = build_entry(
            _MATRIX, "experimental", "20260718", "20260718.153658",
            "2026-07-18T15:38:00Z",
        )
        assert entry == {
            "channel": "experimental",
            "bundle_tag": "20260718",
            "libraries_tag": "20260718.153658",
            "published_at": "2026-07-18T15:38:00Z",
            "packages": {"http_server": "0.18.1", "wifi": "0.8.0"},
        }

    def test_empty_matrix_yields_no_packages(self):
        entry = build_entry({"include": []}, "stable", "20260101", "t", "ts")
        assert entry["packages"] == {}


class TestUpdateIndex:
    def test_fresh_index(self):
        entry = build_entry(_MATRIX, "experimental", "20260718", "t", "ts")
        assert update_index(None, entry) == {"releases": [entry]}

    def test_appends_newest_first(self):
        older = build_entry(_MATRIX, "experimental", "20260101", "a",
                            "2026-01-01T00:00:00Z")
        newer = build_entry(_MATRIX, "experimental", "20260718", "b",
                            "2026-07-18T00:00:00Z")
        index = update_index({"releases": [older]}, newer)
        assert [r["bundle_tag"] for r in index["releases"]] == [
            "20260718", "20260101",
        ]

    def test_same_bundle_tag_replaces_in_place(self):
        """A re-run of the same release rewrites its row, not a duplicate."""
        first = build_entry(_MATRIX, "experimental", "20260718", "t1", "ts1")
        rerun = build_entry(
            {"include": [{"library_name": "wifi", "version": "0.8.1"}]},
            "experimental", "20260718", "t2", "ts2",
        )
        index = update_index({"releases": [first]}, rerun)
        assert len(index["releases"]) == 1
        assert index["releases"][0]["libraries_tag"] == "t2"
        assert index["releases"][0]["packages"] == {"wifi": "0.8.1"}

    def test_same_bundle_tag_different_channel_kept_separate(self):
        exp = build_entry(_MATRIX, "experimental", "20260718", "t", "ts1")
        stable = build_entry(_MATRIX, "stable", "20260718", "t", "ts2")
        index = update_index({"releases": [exp]}, stable)
        assert len(index["releases"]) == 2


class TestMain:
    def test_writes_and_reloads(self, tmp_path: Path, capsys):
        index_path = tmp_path / "releases.json"
        code = main([
            "--index", str(index_path),
            "--channel", "experimental",
            "--matrix", json.dumps(_MATRIX),
            "--bundle-tag", "20260718",
            "--libraries-tag", "20260718.153658",
            "--published-at", "2026-07-18T15:38:00Z",
        ])
        assert code == 0
        data = json.loads(index_path.read_text())
        assert data["releases"][0]["bundle_tag"] == "20260718"
        assert data["releases"][0]["packages"]["http_server"] == "0.18.1"
        assert "recorded experimental 20260718" in capsys.readouterr().out
        # Committed file ends in a single newline.
        assert index_path.read_text().endswith("}\n")

    def test_second_run_accumulates(self, tmp_path: Path):
        index_path = tmp_path / "releases.json"
        common = [
            "--index", str(index_path), "--channel", "experimental",
            "--matrix", json.dumps(_MATRIX), "--libraries-tag", "t",
        ]
        main([*common, "--bundle-tag", "20260101",
              "--published-at", "2026-01-01T00:00:00Z"])
        main([*common, "--bundle-tag", "20260718",
              "--published-at", "2026-07-18T00:00:00Z"])
        data = json.loads(index_path.read_text())
        assert [r["bundle_tag"] for r in data["releases"]] == [
            "20260718", "20260101",
        ]

    def test_rejects_unknown_channel(self, tmp_path: Path):
        with pytest.raises(SystemExit):
            main([
                "--index", str(tmp_path / "r.json"), "--channel", "nightly",
                "--matrix", json.dumps(_MATRIX), "--bundle-tag", "t",
                "--libraries-tag", "t", "--published-at", "ts",
            ])
