"""Tests for chumicro_workspace.curated_libraries — the libraries: table."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.curated_libraries import (
    CuratedLibrary,
    read_curated_libraries,
    write_curated_libraries,
)
from chumicro_workspace.loaders import WorkspaceConfigError


def _table(*libs: CuratedLibrary) -> dict[str, CuratedLibrary]:
    return {lib.name: lib for lib in libs}


class TestRoundTrip:
    def test_write_then_read(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        table = _table(
            CuratedLibrary("chumicro_mqtt", "stable", "0.10.2"),
            CuratedLibrary("chumicro_sockets", "experimental", "0.4.1.dev3"),
        )
        assert write_curated_libraries(target, table) is True
        loaded = read_curated_libraries(target)
        assert loaded == table

    def test_declined_round_trips_and_only_emitted_when_true(
        self, tmp_path: Path,
    ):
        target = tmp_path / "workspace.yml"
        write_curated_libraries(
            target,
            _table(
                CuratedLibrary("chumicro_mqtt", "stable", "0.10.2"),
                CuratedLibrary(
                    "chumicro_sockets", "stable", "0.4.0", declined=True,
                ),
            ),
        )
        text = target.read_text()
        assert "declined: true" in text
        # Only the declined entry carries the key.
        assert text.count("declined:") == 1
        loaded = read_curated_libraries(target)
        assert loaded["chumicro_sockets"].declined is True
        assert loaded["chumicro_mqtt"].declined is False

    def test_head_version_round_trips(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        write_curated_libraries(
            target,
            _table(CuratedLibrary("chumicro_msgpack", "experimental", "HEAD")),
        )
        assert '    version: "HEAD"' in target.read_text()
        loaded = read_curated_libraries(target)
        assert loaded["chumicro_msgpack"].version == "HEAD"

    def test_idempotent_rerun(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        table = _table(CuratedLibrary("chumicro_mqtt", "stable", "0.10.2"))
        write_curated_libraries(target, table)
        assert write_curated_libraries(target, table) is False

    def test_coexists_with_library_sources_block(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        target.write_text(
            "# workspace.yml\n\n"
            "library_sources:\n"
            "  chumicro_mqtt: ../chumicro/libraries/mqtt/src\n",
        )
        write_curated_libraries(
            target,
            _table(CuratedLibrary("chumicro_mqtt", "stable", "0.10.2")),
        )
        text = target.read_text()
        assert "library_sources:\n  chumicro_mqtt: " in text
        assert "libraries:\n  chumicro_mqtt:\n" in text
        assert read_curated_libraries(target)["chumicro_mqtt"].channel == (
            "stable"
        )


class TestEmptyAndAbsent:
    def test_absent_file_is_empty(self, tmp_path: Path):
        assert read_curated_libraries(tmp_path / "nope.yml") == {}

    def test_absent_libraries_key_is_empty(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        target.write_text("library_sources:\n  chumicro_mqtt: x\n")
        assert read_curated_libraries(target) == {}

    def test_empty_file_is_empty(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        target.write_text("")
        assert read_curated_libraries(target) == {}


class TestValidation:
    def _write(self, tmp_path: Path, body: str) -> Path:
        target = tmp_path / "workspace.yml"
        target.write_text(body)
        return target

    def test_libraries_not_mapping(self, tmp_path: Path):
        target = self._write(tmp_path, "libraries:\n  - chumicro_mqtt\n")
        with pytest.raises(WorkspaceConfigError, match="must be a mapping"):
            read_curated_libraries(target)

    def test_entry_not_mapping(self, tmp_path: Path):
        target = self._write(tmp_path, "libraries:\n  chumicro_mqtt: stable\n")
        with pytest.raises(WorkspaceConfigError, match="must be a mapping"):
            read_curated_libraries(target)

    def test_bad_channel(self, tmp_path: Path):
        target = self._write(
            tmp_path,
            "libraries:\n  chumicro_mqtt:\n"
            "    channel: nightly\n    version: \"1\"\n",
        )
        with pytest.raises(WorkspaceConfigError, match="channel must be"):
            read_curated_libraries(target)

    def test_non_string_version(self, tmp_path: Path):
        target = self._write(
            tmp_path,
            "libraries:\n  chumicro_mqtt:\n"
            "    channel: stable\n    version: 0.10\n",
        )
        with pytest.raises(WorkspaceConfigError, match="version must be"):
            read_curated_libraries(target)

    def test_non_bool_declined(self, tmp_path: Path):
        target = self._write(
            tmp_path,
            "libraries:\n  chumicro_mqtt:\n"
            "    channel: stable\n    version: \"1\"\n"
            "    declined: yes-please\n",
        )
        with pytest.raises(WorkspaceConfigError, match="declined must be"):
            read_curated_libraries(target)
