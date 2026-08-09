"""Tests for ``chumicro_workspace.config_manifest`` (flat dotted-key shape).

Coverage focus:

* The reader returns ``None`` for libraries with no manifest and
  catches every shape malformation with a precise
  ``ConfigManifestError`` message.
* Empty ``required_keys`` / ``optional_keys`` lists are valid
  (forward-compat: a library can declare it reads runtime config
  without pinning any keys).
* The aggregator unions the required + optional sets across libraries
  and promotes any "optional in lib A, required in lib B" key to
  required overall.
* The validator catches missing required keys, tolerates undeclared
  keys for forward-compat, and emits a single multi-line message
  naming every offender so deploy-time errors don't ping-pong.

Real-world end-to-end:

* The mono-repo's ``libraries/wifi/pyproject.toml`` ships a real
  manifest; one test reads it through the live module and asserts
  the keys line up with ``WifiConfig.from_config``'s ``required`` /
  ``optional`` arguments.  Catches drift if either side is renamed
  without updating the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.config_manifest import (
    ConfigManifest,
    ConfigManifestError,
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

    def test_empty_manifest_means_no_keys_pinned(self, tmp_path: Path) -> None:
        # Manifest declares it reads runtime config but doesn't pin
        # keys — forward-compat for a library that wants tooling to
        # know it's a config consumer without committing yet.
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "chumicro-app"\n'
                "[tool.chumicro.config]\n"
            ),
        )
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.library_name == "chumicro-app"
        assert manifest.required_keys == frozenset()
        assert manifest.optional_keys == frozenset()

    def test_required_and_optional_keys_round_trip(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "chumicro-wifi"\n'
                "[tool.chumicro.config]\n"
                'required_keys = ["wifi.ssid", "wifi.password"]\n'
                'optional_keys = ["wifi.hostname"]\n'
            ),
        )
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert manifest.required_keys == frozenset({"wifi.ssid", "wifi.password"})
        assert manifest.optional_keys == frozenset({"wifi.hostname"})
        assert manifest.declared_by.endswith("pyproject.toml")

    def test_falls_back_to_directory_name_when_project_name_missing(
        self, tmp_path: Path,
    ) -> None:
        directory = tmp_path / "chumicro-something"
        directory.mkdir()
        _write_pyproject(
            directory,
            "[tool.chumicro.config]\n",
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

    def test_raises_when_required_value_is_not_list(self, tmp_path: Path) -> None:
        _write_pyproject(
            tmp_path,
            (
                '[project]\nname = "x"\n'
                "[tool.chumicro.config]\n"
                'required_keys = "wifi.ssid"\n'
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
                "[tool.chumicro.config]\n"
                "required_keys = [42]\n"
            ),
        )
        with pytest.raises(ConfigManifestError, match="only strings"):
            read_manifest(tmp_path)


class TestRealMonoRepoManifests:
    """Read the live mono-repo wifi manifest end-to-end."""

    def test_chumicro_wifi_manifest_round_trips(self) -> None:
        manifest = read_manifest(_REPO_ROOT / "libraries" / "wifi")
        assert manifest is not None
        assert manifest.library_name == "chumicro-wifi"
        # Drift on either side surfaces here — keys must match
        # ``WifiConfig.from_config``'s required / optional vocabulary
        # in ``libraries/wifi/src/chumicro_wifi/config.py``.
        assert manifest.required_keys == frozenset({
            "wifi.ssid",
            "wifi.password",
        })
        assert manifest.optional_keys == frozenset({
            "wifi.hostname",
            "wifi.connect_timeout_ms",
            "wifi.first_connect_timeout_ms",
            "wifi.reconnect_backoff_start_ms",
            "wifi.reconnect_backoff_max_ms",
            "wifi.reconnect_max",
            "wifi.power_save",
            "wifi.tx_power_dbm",
        })


class TestAggregateManifests:
    """Union behavior across multiple libraries' manifests."""

    def test_empty_input_returns_none(self) -> None:
        assert aggregate_manifests([]) is None

    def test_drops_none_entries(self) -> None:
        # ``read_manifest`` returns ``None`` for libraries without
        # a manifest — callers can pass the raw list without filtering.
        assert aggregate_manifests([None, None]) is None

    def test_single_manifest_passes_through(self) -> None:
        manifest = ConfigManifest(
            library_name="chumicro-wifi",
            required_keys=frozenset({"wifi.ssid", "wifi.password"}),
            optional_keys=frozenset({"wifi.hostname"}),
            declared_by="libraries/wifi/pyproject.toml",
        )
        result = aggregate_manifests([manifest])
        assert result is not None
        assert result.required_keys == frozenset({"wifi.ssid", "wifi.password"})
        assert result.optional_keys == frozenset({"wifi.hostname"})
        assert result.declared_by == "libraries/wifi/pyproject.toml"

    def test_unions_required_across_libraries(self) -> None:
        # Two hypothetical libraries that read different keys —
        # union is "you need both".
        first = ConfigManifest(
            library_name="lib-a",
            required_keys=frozenset({"wifi.ssid"}),
        )
        second = ConfigManifest(
            library_name="lib-b",
            required_keys=frozenset({"wifi.hostname"}),
        )
        result = aggregate_manifests([first, second])
        assert result is not None
        assert result.required_keys == frozenset({"wifi.ssid", "wifi.hostname"})

    def test_required_promotes_optional_when_libraries_disagree(self) -> None:
        # ``lib-a`` says ``wifi.ssid`` is optional; ``lib-b`` says it's
        # required.  Required must win (otherwise validation would
        # accept configs ``lib-b`` actually fails on).  The aggregated
        # ``optional_keys`` drops the promoted key.
        first = ConfigManifest(
            library_name="lib-a",
            optional_keys=frozenset({"wifi.ssid"}),
        )
        second = ConfigManifest(
            library_name="lib-b",
            required_keys=frozenset({"wifi.ssid"}),
        )
        result = aggregate_manifests([first, second])
        assert result is not None
        assert result.required_keys == frozenset({"wifi.ssid"})
        assert result.optional_keys == frozenset()

    def test_optional_unions_when_no_required_promotion(self) -> None:
        first = ConfigManifest(
            library_name="lib-a",
            optional_keys=frozenset({"wifi.hostname"}),
        )
        second = ConfigManifest(
            library_name="lib-b",
            optional_keys=frozenset({"wifi.power_save"}),
        )
        result = aggregate_manifests([first, second])
        assert result is not None
        assert result.optional_keys == frozenset({
            "wifi.hostname", "wifi.power_save",
        })

    def test_declared_by_concatenates_sources(self) -> None:
        first = ConfigManifest(
            library_name="lib-a",
            required_keys=frozenset({"wifi.ssid"}),
            declared_by="libraries/lib_a/pyproject.toml",
        )
        second = ConfigManifest(
            library_name="lib-b",
            required_keys=frozenset({"wifi.hostname"}),
            declared_by="libraries/lib_b/pyproject.toml",
        )
        result = aggregate_manifests([first, second])
        assert result is not None
        assert "lib_a" in result.declared_by
        assert "lib_b" in result.declared_by


class TestValidateRuntimeConfig:
    """Validator behavior against a flat config dict."""

    def test_passes_when_required_keys_present(self) -> None:
        manifest = ConfigManifest(
            library_name="<aggregated>",
            required_keys=frozenset({"wifi.ssid", "wifi.password"}),
            optional_keys=frozenset({"wifi.hostname"}),
        )
        validate_runtime_config(
            {"wifi.ssid": "home", "wifi.password": "secret"},
            manifest,
        )

    def test_passes_when_all_optional_present(self) -> None:
        manifest = ConfigManifest(
            library_name="<aggregated>",
            required_keys=frozenset({"wifi.ssid"}),
            optional_keys=frozenset({"wifi.hostname", "wifi.power_save"}),
        )
        validate_runtime_config(
            {"wifi.ssid": "home", "wifi.hostname": "pico", "wifi.power_save": False},
            manifest,
        )

    def test_passes_when_manifest_is_none(self) -> None:
        # No libraries declared anything — validator is a no-op.
        validate_runtime_config({}, None)

    def test_passes_when_manifest_has_no_required_keys(self) -> None:
        # Empty manifest is valid (forward-compat) — no-op validation.
        manifest = ConfigManifest(library_name="x")
        validate_runtime_config({}, manifest)

    def test_raises_on_missing_required_key(self) -> None:
        manifest = ConfigManifest(
            library_name="<aggregated>",
            required_keys=frozenset({"wifi.ssid", "wifi.password"}),
            declared_by="libraries/wifi/pyproject.toml",
        )
        with pytest.raises(
            ConfigManifestError,
            match="wifi.password",
        ):
            validate_runtime_config({"wifi.ssid": "home"}, manifest)

    def test_tolerates_undeclared_keys(self) -> None:
        # Apps can carry app-specific config keys alongside library
        # config — validator ignores anything not in the manifest.
        manifest = ConfigManifest(
            library_name="<aggregated>",
            required_keys=frozenset({"wifi.ssid"}),
        )
        validate_runtime_config(
            {"wifi.ssid": "home", "app.period_ms": 5000, "future.key": "tbd"},
            manifest,
        )

    def test_collects_every_missing_key_in_one_message(self) -> None:
        # Multiple required keys missing — one error names them all
        # so deploy-time failures don't ping-pong (fix one, run again,
        # get the next failure).
        manifest = ConfigManifest(
            library_name="<aggregated>",
            required_keys=frozenset({
                "wifi.ssid", "wifi.password", "mqtt.broker.host",
            }),
            declared_by=(
                "libraries/wifi/pyproject.toml, libraries/mqtt/pyproject.toml"
            ),
        )
        with pytest.raises(ConfigManifestError) as excinfo:
            validate_runtime_config({"wifi.ssid": "home"}, manifest)
        message = str(excinfo.value)
        assert "wifi.password" in message
        assert "mqtt.broker.host" in message
        assert "libraries/wifi" in message
        assert "libraries/mqtt" in message


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
        custom_dir = tmp_path / "custom-lib"
        custom_dir.mkdir()
        _write_pyproject(custom_dir, '[project]\nname = "custom-lib"\n')

        roots = find_library_roots([custom_dir])
        assert roots == (custom_dir,)

    def test_dedupes_roots_seen_via_two_search_paths(
        self, tmp_path: Path,
    ) -> None:
        wifi_dir = tmp_path / "libraries" / "wifi"
        (wifi_dir / "src").mkdir(parents=True)
        _write_pyproject(wifi_dir, '[project]\nname = "chumicro-wifi"\n')

        roots = find_library_roots([wifi_dir / "src", wifi_dir])
        assert roots == (wifi_dir,)

    def test_empty_input_returns_empty_tuple(self) -> None:
        assert find_library_roots([]) == ()
