"""Tests for ``chumicro_workspace.config_manifest``.

Coverage focus:

* The reader returns ``None`` for libraries with no manifest and
  catches every shape malformation with a precise
  ``ConfigManifestError`` message.
* Empty section tables are valid (forward-compat: a library can
  declare it reads a section without pinning keys yet).
* The aggregator unions correctly when two libraries declare the
  same section, including the "one library marks a key required,
  another marks it optional → required wins" promotion.
* The validator catches missing sections, wrong-type sections, and
  missing required keys; tolerates unknown sections + unknown keys
  for forward-compat (matches ``chumicro_config.load_section``'s
  contract).

Real-world end-to-end:

* The mono-repo's ``libraries/wifi/pyproject.toml`` ships a real
  manifest; one test reads it through the live module and asserts
  the section shape lines up with ``WifiConfig.from_dict``'s
  ``required`` / ``optional`` arguments.  Catches drift if either
  side is renamed without updating the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.config_manifest import (
    ConfigManifest,
    ConfigManifestError,
    SectionManifest,
    aggregate_manifests,
    find_library_roots,
    read_manifest,
    validate_runtime_config,
)

#: Mono-repo root — used to point read_manifest at real libraries.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_pyproject(directory: Path, body: str) -> Path:
    pyproject = directory / "pyproject.toml"
    pyproject.write_text(body)
    return pyproject


class TestReadManifest:
    """Exercise the per-library reader against synthesized pyprojects."""

    def test_returns_none_when_no_tool_chumicro_config_table(
        self, tmp_path: Path,
    ) -> None:
        _write_pyproject(
            tmp_path,
            '[project]\nname = "chumicro-bare"\n',
        )
        assert read_manifest(tmp_path) is None

    def test_empty_section_table_means_no_keys_pinned(
        self, tmp_path: Path,
    ) -> None:
        # Manifest declares it reads ``app`` but doesn't pin keys —
        # forward-compat for a library that wants tooling to know
        # it's a config consumer without committing to a schema yet.
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "chumicro-app"\n'
                "[tool.chumicro.config.sections.app]\n"
            ),
        )
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.library_name == "chumicro-app"
        assert len(manifest.sections) == 1
        assert manifest.sections[0].name == "app"
        assert manifest.sections[0].required == frozenset()
        assert manifest.sections[0].optional == frozenset()

    def test_section_table_with_required_and_optional(
        self, tmp_path: Path,
    ) -> None:
        # The shape libraries actually ship — one table per
        # section, listing required + optional keys.
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "chumicro-wifi"\n'
                "[tool.chumicro.config.sections.wifi]\n"
                'required = ["ssid", "password"]\n'
                'optional = ["hostname"]\n'
            ),
        )
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert len(manifest.sections) == 1
        section = manifest.sections[0]
        assert section.name == "wifi"
        assert section.required == frozenset({"ssid", "password"})
        assert section.optional == frozenset({"hostname"})
        assert section.declared_by.endswith("pyproject.toml")

    def test_multiple_sections_round_trip(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "chumicro-multi"\n'
                "[tool.chumicro.config.sections.wifi]\n"
                'required = ["ssid"]\n'
                "[tool.chumicro.config.sections.mqtt]\n"
                'required = ["broker"]\n'
                'optional = ["port"]\n'
            ),
        )
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        sections_by_name = {
            section.name: section for section in manifest.sections
        }
        assert sections_by_name["wifi"].required == frozenset({"ssid"})
        assert sections_by_name["mqtt"].required == frozenset({"broker"})
        assert sections_by_name["mqtt"].optional == frozenset({"port"})

    def test_falls_back_to_directory_name_when_project_name_missing(
        self, tmp_path: Path,
    ) -> None:
        directory = tmp_path / "chumicro-something"
        directory.mkdir()
        _write_pyproject(
            directory,
            "[tool.chumicro.config.sections.something]\n",
        )
        manifest = read_manifest(directory)
        assert manifest is not None
        assert manifest.library_name == "chumicro-something"

    def test_raises_when_config_table_is_not_a_table(
        self, tmp_path: Path,
    ) -> None:
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "x"\n'
                '[tool.chumicro]\nconfig = "wrong-shape"\n'
            ),
        )
        with pytest.raises(ConfigManifestError, match="must be a table"):
            read_manifest(tmp_path)

    def test_raises_when_required_value_is_not_list(
        self, tmp_path: Path,
    ) -> None:
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "x"\n'
                "[tool.chumicro.config.sections.wifi]\n"
                'required = "ssid"\n'
            ),
        )
        with pytest.raises(ConfigManifestError, match="must be a list"):
            read_manifest(tmp_path)

    def test_raises_when_required_list_has_non_string(
        self, tmp_path: Path,
    ) -> None:
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "x"\n'
                "[tool.chumicro.config.sections.wifi]\n"
                "required = [42]\n"
            ),
        )
        with pytest.raises(ConfigManifestError, match="only strings"):
            read_manifest(tmp_path)

    def test_raises_when_sections_table_has_wrong_type(
        self, tmp_path: Path,
    ) -> None:
        # ``sections`` = a string is the canonical malformed shape —
        # reader rejects with a clear message.
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "x"\n'
                '[tool.chumicro.config]\nsections = "wifi"\n'
            ),
        )
        with pytest.raises(ConfigManifestError, match="sections must be"):
            read_manifest(tmp_path)


class TestRealMonoRepoManifests:
    """Read the live mono-repo wifi manifest end-to-end."""

    def test_chumicro_wifi_manifest_round_trips(self) -> None:
        manifest = read_manifest(_REPO_ROOT / "libraries" / "wifi")
        assert manifest is not None
        assert manifest.library_name == "chumicro-wifi"
        assert len(manifest.sections) == 1
        wifi = manifest.sections[0]
        assert wifi.name == "wifi"
        # Lines up with ``WifiConfig.from_dict``'s ``required``
        # tuple in ``libraries/wifi/src/chumicro_wifi/config.py``.
        # Drift on either side surfaces here.
        assert wifi.required == frozenset({"ssid", "password"})
        # Lines up with the ``WifiConfig.from_dict`` ``optional``
        # mapping.  Defaults aren't echoed in the manifest by
        # design (see the schema comment in
        # ``libraries/wifi/pyproject.toml``).
        assert wifi.optional == frozenset({
            "hostname",
            "connect_timeout_ms",
            "reconnect_backoff_start_ms",
            "reconnect_backoff_max_ms",
            "reconnect_max",
            "power_save",
        })


class TestAggregateManifests:
    """Union behaviour across multiple libraries' manifests."""

    def test_empty_input_returns_empty_dict(self) -> None:
        assert aggregate_manifests([]) == {}

    def test_drops_none_entries(self) -> None:
        # ``read_manifest`` returns ``None`` for libraries without
        # a manifest — callers can pass the raw list without
        # filtering.
        result = aggregate_manifests([None, None])
        assert result == {}

    def test_single_manifest_passes_through(self) -> None:
        manifest = ConfigManifest(
            library_name="chumicro-wifi",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset({"ssid", "password"}),
                optional=frozenset({"hostname"}),
                declared_by="libraries/wifi/pyproject.toml",
            ),),
        )
        result = aggregate_manifests([manifest])
        assert set(result.keys()) == {"wifi"}
        assert result["wifi"].required == frozenset({"ssid", "password"})
        assert result["wifi"].optional == frozenset({"hostname"})

    def test_unions_required_when_two_libraries_declare_same_section(
        self,
    ) -> None:
        # Two hypothetical libraries that both read ``wifi`` —
        # one needs ``ssid``, the other needs ``hostname``.  Union
        # is "you need both".
        first = ConfigManifest(
            library_name="lib-a",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset(),
            ),),
        )
        second = ConfigManifest(
            library_name="lib-b",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset({"hostname"}),
                optional=frozenset(),
            ),),
        )
        result = aggregate_manifests([first, second])
        assert result["wifi"].required == frozenset({"ssid", "hostname"})

    def test_required_promotes_optional_when_libraries_disagree(
        self,
    ) -> None:
        # ``lib-a`` says ``ssid`` is optional; ``lib-b`` says it's
        # required.  Required must win (otherwise validation would
        # accept configs ``lib-b`` actually fails on).  The
        # aggregated section's ``optional`` set drops the promoted
        # key so validation isn't ambiguous.
        first = ConfigManifest(
            library_name="lib-a",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset(),
                optional=frozenset({"ssid"}),
            ),),
        )
        second = ConfigManifest(
            library_name="lib-b",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset(),
            ),),
        )
        result = aggregate_manifests([first, second])
        assert result["wifi"].required == frozenset({"ssid"})
        assert result["wifi"].optional == frozenset()

    def test_optional_unions_when_no_required_promotion(self) -> None:
        first = ConfigManifest(
            library_name="lib-a",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset(),
                optional=frozenset({"hostname"}),
            ),),
        )
        second = ConfigManifest(
            library_name="lib-b",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset(),
                optional=frozenset({"power_save"}),
            ),),
        )
        result = aggregate_manifests([first, second])
        assert result["wifi"].optional == frozenset({"hostname", "power_save"})

    def test_distinct_sections_coexist(self) -> None:
        first = ConfigManifest(
            library_name="lib-a",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset(),
            ),),
        )
        second = ConfigManifest(
            library_name="lib-b",
            sections=(SectionManifest(
                name="mqtt",
                required=frozenset({"broker"}),
                optional=frozenset(),
            ),),
        )
        result = aggregate_manifests([first, second])
        assert set(result.keys()) == {"wifi", "mqtt"}

    def test_declared_by_concatenates_sources(self) -> None:
        first = ConfigManifest(
            library_name="lib-a",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset(),
                declared_by="libraries/lib_a/pyproject.toml",
            ),),
        )
        second = ConfigManifest(
            library_name="lib-b",
            sections=(SectionManifest(
                name="wifi",
                required=frozenset({"hostname"}),
                optional=frozenset(),
                declared_by="libraries/lib_b/pyproject.toml",
            ),),
        )
        result = aggregate_manifests([first, second])
        assert "lib_a" in result["wifi"].declared_by
        assert "lib_b" in result["wifi"].declared_by


class TestValidateRuntimeConfig:
    """Validator behaviour against a config dict."""

    def test_passes_when_required_keys_present(self) -> None:
        manifest = {
            "wifi": SectionManifest(
                name="wifi",
                required=frozenset({"ssid", "password"}),
                optional=frozenset({"hostname"}),
            ),
        }
        validate_runtime_config(
            {"wifi": {"ssid": "home", "password": "secret"}},
            manifest,
        )

    def test_passes_when_all_optional_present(self) -> None:
        manifest = {
            "wifi": SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset({"hostname", "power_save"}),
            ),
        }
        validate_runtime_config(
            {"wifi": {"ssid": "home", "hostname": "pico", "power_save": False}},
            manifest,
        )

    def test_raises_on_missing_section(self) -> None:
        manifest = {
            "wifi": SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset(),
                declared_by="libraries/wifi/pyproject.toml",
            ),
        }
        with pytest.raises(
            ConfigManifestError, match=r"\[wifi\] section missing",
        ):
            validate_runtime_config({}, manifest)

    def test_raises_on_missing_required_key(self) -> None:
        manifest = {
            "wifi": SectionManifest(
                name="wifi",
                required=frozenset({"ssid", "password"}),
                optional=frozenset(),
                declared_by="libraries/wifi/pyproject.toml",
            ),
        }
        with pytest.raises(
            ConfigManifestError,
            match=r"\[wifi\] missing required keys: password",
        ):
            validate_runtime_config({"wifi": {"ssid": "home"}}, manifest)

    def test_raises_on_wrong_section_type(self) -> None:
        manifest = {
            "wifi": SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset(),
            ),
        }
        with pytest.raises(
            ConfigManifestError, match=r"\[wifi\] section must be a table",
        ):
            validate_runtime_config({"wifi": "not-a-table"}, manifest)

    def test_tolerates_unknown_section(self) -> None:
        # App-specific config sections that no library imports must
        # not raise — Decision 0035 §section key convention reserves
        # ``app`` for thing-specific config and forward-compat
        # demands "section a library hasn't claimed yet" stays valid.
        manifest = {
            "wifi": SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset(),
            ),
        }
        validate_runtime_config(
            {"wifi": {"ssid": "home"}, "app": {"period": 5000}},
            manifest,
        )

    def test_tolerates_unknown_keys_in_known_section(self) -> None:
        # Same forward-compat as ``chumicro_config.load_section`` —
        # unknown keys ride through unchallenged so authors can
        # add config keys without coordinating with the validator.
        manifest = {
            "wifi": SectionManifest(
                name="wifi",
                required=frozenset({"ssid"}),
                optional=frozenset(),
            ),
        }
        validate_runtime_config(
            {"wifi": {"ssid": "home", "future_extension": "tbd"}},
            manifest,
        )

    def test_collects_every_problem_in_one_message(self) -> None:
        # The validator names every offending section + key in one
        # multi-line string so deploy-time errors don't ping-pong
        # the user (fix one, run again, get the next failure).
        manifest = {
            "wifi": SectionManifest(
                name="wifi",
                required=frozenset({"ssid", "password"}),
                optional=frozenset(),
                declared_by="libraries/wifi/pyproject.toml",
            ),
            "mqtt": SectionManifest(
                name="mqtt",
                required=frozenset({"broker"}),
                optional=frozenset(),
                declared_by="libraries/mqtt/pyproject.toml",
            ),
        }
        with pytest.raises(ConfigManifestError) as excinfo:
            validate_runtime_config({"wifi": {}}, manifest)
        message = str(excinfo.value)
        # Both problem rows present — ``wifi`` missing required
        # keys, ``mqtt`` section missing entirely.
        assert "[wifi]" in message
        assert "[mqtt]" in message
        assert "ssid" in message
        assert "password" in message
        assert "broker" in message


class TestFindLibraryRoots:
    """Filter import-graph search paths down to the ones with a pyproject.toml."""

    def test_filters_libraries_src_subdirectories(
        self, tmp_path: Path,
    ) -> None:
        # Standard ``libraries/<name>/src/`` layout — pyproject lives
        # at the parent.  Library root returned is the parent.
        wifi_dir = tmp_path / "libraries" / "wifi"
        (wifi_dir / "src").mkdir(parents=True)
        _write_pyproject(wifi_dir, '[project]\nname = "chumicro-wifi"\n')

        roots = find_library_roots([wifi_dir / "src"])
        assert roots == (wifi_dir,)

    def test_skips_search_paths_without_pyproject(
        self, tmp_path: Path,
    ) -> None:
        # ``shared/`` and ``packages/`` are valid search paths but
        # don't carry pyprojects — silently dropped.
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        packages_dir = tmp_path / "packages"
        packages_dir.mkdir()
        wifi_dir = tmp_path / "libraries" / "wifi"
        (wifi_dir / "src").mkdir(parents=True)
        _write_pyproject(wifi_dir, '[project]\nname = "chumicro-wifi"\n')

        roots = find_library_roots([
            shared_dir, packages_dir, wifi_dir / "src",
        ])
        assert roots == (wifi_dir,)

    def test_handles_search_path_pointing_directly_at_pyproject_dir(
        self, tmp_path: Path,
    ) -> None:
        # Some ``library_sources:`` overrides point a search path
        # directly at the directory carrying the pyproject (rather
        # than at a ``src/`` subdir).  Recogniser still finds it.
        custom_dir = tmp_path / "custom-lib"
        custom_dir.mkdir()
        _write_pyproject(custom_dir, '[project]\nname = "custom-lib"\n')

        roots = find_library_roots([custom_dir])
        assert roots == (custom_dir,)

    def test_dedupes_roots_seen_via_two_search_paths(
        self, tmp_path: Path,
    ) -> None:
        # Override + default-scan can resolve to the same root —
        # don't return it twice.
        wifi_dir = tmp_path / "libraries" / "wifi"
        (wifi_dir / "src").mkdir(parents=True)
        _write_pyproject(wifi_dir, '[project]\nname = "chumicro-wifi"\n')

        roots = find_library_roots([wifi_dir / "src", wifi_dir])
        assert roots == (wifi_dir,)

    def test_empty_input_returns_empty_tuple(self) -> None:
        assert find_library_roots([]) == ()
