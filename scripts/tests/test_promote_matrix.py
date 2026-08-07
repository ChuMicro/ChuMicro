"""Tests for promote_matrix.py — the promotion-wave matrix builder.

The per-tag rules live in ``promote_validate`` and are covered by
``test_promote_validate.py``.  What matters here is the wave shape:
which tags reach the matrix, how the kinds split, and that the preflight
gate deduplicates commits so a wave cut from one push gates once.
"""

from __future__ import annotations

import json

import promote_matrix
import promote_validate
import pytest


def _entry(name: str, version: str, kind: str, commit: str, *, docs: bool = True):
    """Build what a validated tag contributes to the matrix."""
    return {
        "library_name": name,
        "version": version,
        "kind": kind,
        "commit": commit,
        "docs": docs,
    }


@pytest.fixture
def stub_validation(monkeypatch: pytest.MonkeyPatch):
    """Drive promote_matrix with scripted per-tag results.

    Returns a callable taking ``{tag: _entry(...)}`` plus the set of
    stable tags that already exist.  Every promote_validate hook the
    matrix builder calls is stubbed, so these tests never touch git,
    the network, or the real workspace tree.
    """
    def install(entries: dict, *, existing_stable: set[str] = frozenset()):
        def fake_parse(tag: str):
            spec = entries[tag]
            return {
                "library_name": spec["library_name"],
                "version": spec["version"],
                "stable_tag": f"chumicro-{spec['library_name']}-v{spec['version']}",
                "source_zip": f"chumicro-{spec['library_name']}-v{spec['version']}-source.zip",
            }

        def fake_locate(library_name: str):
            spec = next(e for e in entries.values() if e["library_name"] == library_name)
            parent = {"library": "libraries", "workbench": "workbench", "support": "support"}
            return {
                "library_dir": f"{parent[spec['kind']]}/{library_name}",
                "package_kind": spec["kind"],
            }

        def fake_gate_commit(tag: str):
            return entries[tag]["commit"]

        def fake_has_docs(library_dir: str, tag: str):
            return entries[tag]["docs"]

        monkeypatch.setattr(promote_validate, "_parse_tag", fake_parse)
        monkeypatch.setattr(promote_validate, "_locate_package", fake_locate)
        monkeypatch.setattr(promote_validate, "_has_docs", fake_has_docs)
        monkeypatch.setattr(
            promote_validate, "_tag_exists", lambda tag: tag in existing_stable,
        )
        monkeypatch.setattr(
            promote_validate, "_check_preconditions",
            lambda *arguments, **keywords: None,
        )
        monkeypatch.setattr(
            promote_validate, "_check_monotonicity",
            lambda *arguments, **keywords: None,
        )
        monkeypatch.setattr(promote_matrix, "_gate_commit", fake_gate_commit)

    return install


def _outputs(payload: str) -> dict[str, str]:
    """Parse the emitted key=value payload into a dict."""
    return dict(line.split("=", 1) for line in payload.splitlines())


class TestSplitTags:
    """Tags arrive as one dispatch string and must survive human formatting."""

    def test_comma_separated(self):
        assert promote_matrix._split_tags("a,b,c") == ["a", "b", "c"]

    def test_tolerates_spaces_and_newlines(self):
        assert promote_matrix._split_tags(" a , b \n c ,") == ["a", "b", "c"]

    def test_empty_yields_nothing(self):
        assert promote_matrix._split_tags("  ,  ") == []


class TestWaveShape:
    """The matrices the workflow fans out over."""

    def test_kinds_split_into_library_matrix(self, stub_validation):
        stub_validation({
            "t-mqtt": _entry("mqtt", "1.0.0", "library", "aaa"),
            "t-checks": _entry("checks", "2.0.0", "workbench", "aaa", docs=False),
            "t-harness": _entry("test_harness", "3.0.0", "support", "aaa", docs=False),
        })
        entries = promote_matrix._build_entries(
            ["t-mqtt", "t-checks", "t-harness"],
            allow_downgrade=False, include_tagged=False,
        )
        out = _outputs(promote_matrix._emit_outputs(entries))

        assert out["has_promotions"] == "true"
        assert len(json.loads(out["matrix"])["include"]) == 3
        # Only the library ships to circup / mip (Decisions 0032, 0111).
        library_names = [
            e["library_name"] for e in json.loads(out["library_matrix"])["include"]
        ]
        assert library_names == ["mqtt"]

    def test_docs_libraries_excludes_packages_without_mkdocs(self, stub_validation):
        stub_validation({
            "t-mqtt": _entry("mqtt", "1.0.0", "library", "aaa"),
            "t-checks": _entry("checks", "2.0.0", "workbench", "aaa", docs=False),
        })
        entries = promote_matrix._build_entries(
            ["t-mqtt", "t-checks"], allow_downgrade=False, include_tagged=False,
        )
        out = _outputs(promote_matrix._emit_outputs(entries))

        assert out["docs_libraries"] == "mqtt"
        assert out["has_docs_promotions"] == "true"

    def test_wave_from_one_push_gates_once(self, stub_validation):
        """The whole point: 17 tags off one commit must not gate 17 times."""
        tags = {f"t{i}": _entry(f"lib{i}", "1.0.0", "library", "same-sha")
                for i in range(17)}
        stub_validation(tags)
        entries = promote_matrix._build_entries(
            list(tags), allow_downgrade=False, include_tagged=False,
        )
        out = _outputs(promote_matrix._emit_outputs(entries))

        gate = json.loads(out["gate_commits"])["include"]
        assert gate == [{"commit": "same-sha"}]

    def test_mixed_commits_gate_once_each(self, stub_validation):
        stub_validation({
            "t-a": _entry("a", "1.0.0", "library", "sha1"),
            "t-b": _entry("b", "1.0.0", "library", "sha2"),
            "t-c": _entry("c", "1.0.0", "library", "sha1"),
        })
        entries = promote_matrix._build_entries(
            ["t-a", "t-b", "t-c"], allow_downgrade=False, include_tagged=False,
        )
        out = _outputs(promote_matrix._emit_outputs(entries))

        commits = sorted(e["commit"] for e in json.loads(out["gate_commits"])["include"])
        assert commits == ["sha1", "sha2"]


class TestAlreadyPromoted:
    """Re-dispatching a failed wave's tag list is the resume path."""

    def test_existing_stable_tag_drops_out(self, stub_validation, capsys):
        stub_validation(
            {
                "t-mqtt": _entry("mqtt", "1.0.0", "library", "aaa"),
                "t-ntp": _entry("ntp", "2.0.0", "library", "aaa"),
            },
            existing_stable={"chumicro-mqtt-v1.0.0"},
        )
        entries = promote_matrix._build_entries(
            ["t-mqtt", "t-ntp"], allow_downgrade=False, include_tagged=False,
        )

        assert [e["library_name"] for e in entries] == ["ntp"]
        assert "already exists" in capsys.readouterr().out

    def test_include_tagged_keeps_it(self, stub_validation):
        stub_validation(
            {"t-mqtt": _entry("mqtt", "1.0.0", "library", "aaa")},
            existing_stable={"chumicro-mqtt-v1.0.0"},
        )
        entries = promote_matrix._build_entries(
            ["t-mqtt"], allow_downgrade=False, include_tagged=True,
        )

        assert [e["library_name"] for e in entries] == ["mqtt"]

    def test_fully_promoted_wave_emits_nothing_to_do(self, stub_validation):
        stub_validation(
            {"t-mqtt": _entry("mqtt", "1.0.0", "library", "aaa")},
            existing_stable={"chumicro-mqtt-v1.0.0"},
        )
        entries = promote_matrix._build_entries(
            ["t-mqtt"], allow_downgrade=False, include_tagged=False,
        )
        out = _outputs(promote_matrix._emit_outputs(entries))

        assert out["has_promotions"] == "false"
        assert out["has_library_promotions"] == "false"
        assert out["has_docs_promotions"] == "false"
        assert json.loads(out["gate_commits"])["include"] == []

    def test_duplicate_tag_counted_once(self, stub_validation):
        stub_validation({"t-mqtt": _entry("mqtt", "1.0.0", "library", "aaa")})
        entries = promote_matrix._build_entries(
            ["t-mqtt", "t-mqtt"], allow_downgrade=False, include_tagged=False,
        )

        assert len(entries) == 1


class TestMain:
    """Entry-point behavior the workflow depends on."""

    def test_no_tags_is_an_error(self, capsys):
        assert promote_matrix.main(["--tags", ""]) == 1
        assert "No tags provided" in capsys.readouterr().err

    def test_validation_failure_stops_the_wave(self, stub_validation, monkeypatch, capsys):
        """A malformed tag must not publish the rest of the wave."""
        stub_validation({"t-mqtt": _entry("mqtt", "1.0.0", "library", "aaa")})

        def boom(*_args, **_kwargs):
            raise promote_validate.PromoteValidationError("no source archive")

        monkeypatch.setattr(promote_validate, "_check_preconditions", boom)

        assert promote_matrix.main(["--tags", "t-mqtt"]) == 1
        assert "no source archive" in capsys.readouterr().err
