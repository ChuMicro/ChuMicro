"""Tests for ``chumicro_deploy.skip_factories`` and walker integration.

Entrypoint-level ``__chumicro_skip_factories__`` opt-out:

* Family entry (``"sockets_factory"``) — matches every
  ``chumicro_*.sockets_factory`` discovered under the search paths.
* Exact entry (``"chumicro_mqtt.sockets_factory"``) — matches one
  module.
* Typo (no match) — raises ``ValueError`` from
  :class:`ImportGraphSource` construction.
* Direct-import override — entrypoint explicitly imports a skip target
  → it ships with a warning.
* Dead-skip — none of an entry's matched libraries are imported →
  informational warning, no failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import ImportGraphSource
from chumicro_deploy.skip_factories import (
    discover_factory_modules,
    read_skip_factories_marker,
    resolve_skip_targets,
)


class TestReadSkipFactoriesMarker:
    def test_no_marker_returns_none(self, tmp_path: Path) -> None:
        file = tmp_path / "app.py"
        file.write_text("print('hi')\n")
        assert read_skip_factories_marker(file) is None

    def test_tuple_marker(self, tmp_path: Path) -> None:
        file = tmp_path / "app.py"
        file.write_text('__chumicro_skip_factories__ = ("sockets_factory",)\n')
        assert read_skip_factories_marker(file) == ("sockets_factory",)

    def test_list_marker(self, tmp_path: Path) -> None:
        file = tmp_path / "app.py"
        file.write_text(
            '__chumicro_skip_factories__ = ["sockets_factory", "tls_factory"]\n',
        )
        assert read_skip_factories_marker(file) == ("sockets_factory", "tls_factory")

    def test_marker_does_not_execute_file(self, tmp_path: Path) -> None:
        """The reader is AST-only — device-only imports do not crash it."""
        file = tmp_path / "app.py"
        file.write_text(
            '__chumicro_skip_factories__ = ("sockets_factory",)\n'
            "import this_module_does_not_exist\n",
        )
        assert read_skip_factories_marker(file) == ("sockets_factory",)

    def test_unparseable_file_returns_none(self, tmp_path: Path) -> None:
        file = tmp_path / "app.py"
        file.write_text("def : invalid\n")
        assert read_skip_factories_marker(file) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert read_skip_factories_marker(tmp_path / "missing.py") is None

    def test_empty_tuple_returns_empty(self, tmp_path: Path) -> None:
        file = tmp_path / "app.py"
        file.write_text("__chumicro_skip_factories__ = ()\n")
        assert read_skip_factories_marker(file) == ()

    def test_non_string_entries_dropped(self, tmp_path: Path) -> None:
        """Non-string elements in the tuple are silently dropped."""
        file = tmp_path / "app.py"
        file.write_text('__chumicro_skip_factories__ = ("ok", 42, None)\n')
        assert read_skip_factories_marker(file) == ("ok",)

    def test_non_tuple_value_returns_none(self, tmp_path: Path) -> None:
        """A misuse like ``= "string"`` is ignored (treated as no marker)."""
        file = tmp_path / "app.py"
        file.write_text('__chumicro_skip_factories__ = "sockets_factory"\n')
        assert read_skip_factories_marker(file) is None

    def test_other_top_level_assignments_skipped(self, tmp_path: Path) -> None:
        """Unrelated top-level assignments don't confuse the reader."""
        file = tmp_path / "app.py"
        file.write_text(
            "FOO = 1\n"
            'BAR = "hello"\n'
            '__chumicro_runtimes__ = ("circuitpython",)\n'
            '__chumicro_skip_factories__ = ("sockets_factory",)\n',
        )
        assert read_skip_factories_marker(file) == ("sockets_factory",)


class TestDiscoverFactoryModules:
    def _scaffold_libs(self, tmp_path: Path) -> Path:
        """Build libs/chumicro_alpha/{sockets,tls}_factory.py + chumicro_beta/sockets_factory.py."""
        libs = tmp_path / "libs"
        libs.mkdir()
        alpha = libs / "chumicro_alpha"
        alpha.mkdir()
        (alpha / "__init__.py").write_text("")
        (alpha / "sockets_factory.py").write_text("def chumicro_sockets_factory(): pass\n")
        (alpha / "tls_factory.py").write_text("def chumicro_tls_factory(): pass\n")
        beta = libs / "chumicro_beta"
        beta.mkdir()
        (beta / "__init__.py").write_text("")
        (beta / "sockets_factory.py").write_text("def chumicro_sockets_factory(): pass\n")
        return libs

    def test_discovers_factory_files(self, tmp_path: Path) -> None:
        libs = self._scaffold_libs(tmp_path)
        discovered = discover_factory_modules([libs])
        assert discovered == {
            "chumicro_alpha.sockets_factory": "sockets_factory",
            "chumicro_alpha.tls_factory": "tls_factory",
            "chumicro_beta.sockets_factory": "sockets_factory",
        }

    def test_ignores_non_chumicro_packages(self, tmp_path: Path) -> None:
        libs = tmp_path / "libs"
        libs.mkdir()
        other = libs / "third_party"
        other.mkdir()
        (other / "sockets_factory.py").write_text("")
        assert discover_factory_modules([libs]) == {}

    def test_ignores_underscore_prefixed_factory_files(self, tmp_path: Path) -> None:
        """Private helpers like ``_thing_factory.py`` are not opt-out targets."""
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "chumicro_foo"
        pkg.mkdir()
        (pkg / "_private_factory.py").write_text("")
        assert discover_factory_modules([libs]) == {}

    def test_does_not_recurse_into_subdirectories(self, tmp_path: Path) -> None:
        """Convention is a flat file at the package root."""
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "chumicro_foo"
        pkg.mkdir()
        sub = pkg / "factories"
        sub.mkdir()
        (sub / "sockets_factory.py").write_text("")
        assert discover_factory_modules([libs]) == {}

    def test_handles_missing_search_paths(self, tmp_path: Path) -> None:
        assert discover_factory_modules([tmp_path / "nope"]) == {}

    def test_first_search_path_wins_on_collision(self, tmp_path: Path) -> None:
        """Mirrors ImportGraphSource._resolve_module's precedence."""
        first = tmp_path / "first"
        second = tmp_path / "second"
        for base in (first, second):
            pkg = base / "chumicro_dup"
            pkg.mkdir(parents=True)
            (pkg / "sockets_factory.py").write_text("# from " + base.name + "\n")
        discovered = discover_factory_modules([first, second])
        # Both contribute the same key; this test just confirms no
        # duplicate-key crash and that the dict has the one expected
        # entry.
        assert discovered == {"chumicro_dup.sockets_factory": "sockets_factory"}


class TestResolveSkipTargets:
    @pytest.fixture
    def discovered(self) -> dict[str, str]:
        return {
            "chumicro_alpha.sockets_factory": "sockets_factory",
            "chumicro_alpha.tls_factory": "tls_factory",
            "chumicro_beta.sockets_factory": "sockets_factory",
        }

    def test_exact_entry_matches_one(self, discovered: dict[str, str]) -> None:
        per_entry, unmatched = resolve_skip_targets(
            ("chumicro_alpha.sockets_factory",), discovered,
        )
        assert per_entry == {
            "chumicro_alpha.sockets_factory": frozenset(
                {"chumicro_alpha.sockets_factory"},
            ),
        }
        assert unmatched == ()

    def test_family_entry_matches_all_with_same_stem(
        self, discovered: dict[str, str],
    ) -> None:
        per_entry, unmatched = resolve_skip_targets(("sockets_factory",), discovered)
        assert per_entry == {
            "sockets_factory": frozenset({
                "chumicro_alpha.sockets_factory",
                "chumicro_beta.sockets_factory",
            }),
        }
        assert unmatched == ()

    def test_unmatched_exact(self, discovered: dict[str, str]) -> None:
        per_entry, unmatched = resolve_skip_targets(
            ("chumicro_nope.sockets_factory",), discovered,
        )
        assert per_entry == {}
        assert unmatched == ("chumicro_nope.sockets_factory",)

    def test_unmatched_family(self, discovered: dict[str, str]) -> None:
        per_entry, unmatched = resolve_skip_targets(("nope_factory",), discovered)
        assert per_entry == {}
        assert unmatched == ("nope_factory",)

    def test_mix_of_matched_and_unmatched_preserves_user_order(
        self, discovered: dict[str, str],
    ) -> None:
        per_entry, unmatched = resolve_skip_targets(
            ("sockets_factory", "nope_factory", "tls_factory"),
            discovered,
        )
        assert set(per_entry.keys()) == {"sockets_factory", "tls_factory"}
        assert unmatched == ("nope_factory",)


class TestImportGraphSourceSkipFactories:
    """End-to-end walker behavior under ``__chumicro_skip_factories__``."""

    def _scaffold(self, tmp_path: Path) -> tuple[Path, Path]:
        """Build a mqtt-shaped fixture:

        - libs/chumicro_mqtt/{__init__,client,sockets_factory}.py
        - libs/chumicro_sockets/__init__.py
        - chumicro_mqtt.client lazily imports chumicro_mqtt.sockets_factory
          (mirroring the real from_config lazy import — discovered by the walker).
        - chumicro_mqtt.sockets_factory imports chumicro_sockets.
        - libs/chumicro_other/sockets_factory.py exists so family-form skips
          have something to validate against.

        Returns (entrypoint_dir, search_path).
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        mqtt = libs / "chumicro_mqtt"
        mqtt.mkdir()
        (mqtt / "__init__.py").write_text(
            "from chumicro_mqtt.client import MQTTClient\n",
        )
        (mqtt / "client.py").write_text(
            "class MQTTClient:\n"
            "    def from_config(self):\n"
            "        from chumicro_mqtt.sockets_factory import chumicro_sockets_factory\n"
            "        return chumicro_sockets_factory\n",
        )
        (mqtt / "sockets_factory.py").write_text(
            "import chumicro_sockets\n"
            "def chumicro_sockets_factory(): return chumicro_sockets\n",
        )
        sockets = libs / "chumicro_sockets"
        sockets.mkdir()
        (sockets / "__init__.py").write_text("# transport\n")
        other = libs / "chumicro_other"
        other.mkdir()
        (other / "__init__.py").write_text("")
        (other / "sockets_factory.py").write_text("# unused\n")
        return tmp_path, libs

    def test_no_marker_is_legacy_behavior(self, tmp_path: Path) -> None:
        """A user without the marker gets the everything-ships baseline."""
        root, libs = self._scaffold(tmp_path)
        entrypoint = root / "app.py"
        entrypoint.write_text("from chumicro_mqtt import MQTTClient\n")
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        assert "/lib/chumicro_mqtt/sockets_factory.py" in files
        assert "/lib/chumicro_sockets/__init__.py" in files
        assert source.skip_factories_warnings() == ()

    def test_family_form_skips_all_matching_factories(
        self, tmp_path: Path,
    ) -> None:
        """``"sockets_factory"`` drops every chumicro_*.sockets_factory."""
        root, libs = self._scaffold(tmp_path)
        entrypoint = root / "app.py"
        entrypoint.write_text(
            'from chumicro_mqtt import MQTTClient\n'
            '__chumicro_skip_factories__ = ("sockets_factory",)\n',
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        assert "/lib/chumicro_mqtt/__init__.py" in files
        assert "/lib/chumicro_mqtt/client.py" in files
        assert "/lib/chumicro_mqtt/sockets_factory.py" not in files
        # chumicro_sockets is only reachable through the factory — falls
        # out of the graph naturally.
        assert "/lib/chumicro_sockets/__init__.py" not in files

    def test_exact_form_skips_one_module(self, tmp_path: Path) -> None:
        root, libs = self._scaffold(tmp_path)
        entrypoint = root / "app.py"
        entrypoint.write_text(
            "from chumicro_mqtt import MQTTClient\n"
            '__chumicro_skip_factories__ = ("chumicro_mqtt.sockets_factory",)\n',
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        assert "/lib/chumicro_mqtt/sockets_factory.py" not in files
        assert "/lib/chumicro_sockets/__init__.py" not in files

    def test_unmatched_entry_raises_typo_guard(self, tmp_path: Path) -> None:
        root, libs = self._scaffold(tmp_path)
        entrypoint = root / "app.py"
        entrypoint.write_text(
            "from chumicro_mqtt import MQTTClient\n"
            '__chumicro_skip_factories__ = ("socets_factory",)\n',  # typo
        )
        with pytest.raises(ValueError, match="socets_factory"):
            ImportGraphSource(entrypoint, search_paths=[libs])

    def test_direct_import_override_keeps_module_and_warns(
        self, tmp_path: Path,
    ) -> None:
        """User imports a skip target directly → it ships, warning emitted."""
        root, libs = self._scaffold(tmp_path)
        entrypoint = root / "app.py"
        entrypoint.write_text(
            "from chumicro_mqtt import MQTTClient\n"
            "import chumicro_mqtt.sockets_factory\n"
            '__chumicro_skip_factories__ = ("sockets_factory",)\n',
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        assert "/lib/chumicro_mqtt/sockets_factory.py" in files
        assert "/lib/chumicro_sockets/__init__.py" in files  # closure ships too
        warnings = source.skip_factories_warnings()
        assert any(
            "chumicro_mqtt.sockets_factory" in warning
            and "imports it directly" in warning
            for warning in warnings
        )

    def test_dead_skip_emits_info_warning(self, tmp_path: Path) -> None:
        """Skip entry whose parent library is never imported → info warning."""
        root, libs = self._scaffold(tmp_path)
        entrypoint = root / "app.py"
        entrypoint.write_text(
            "from chumicro_mqtt import MQTTClient\n"
            '__chumicro_skip_factories__ = ("chumicro_other.sockets_factory",)\n',
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        warnings = source.skip_factories_warnings()
        assert any(
            "chumicro_other.sockets_factory" in warning
            and "no effect" in warning
            for warning in warnings
        )
        # The mqtt deploy still works — dead-skip is informational only.
        files = source.files()
        assert "/lib/chumicro_mqtt/__init__.py" in files

    def test_family_skip_is_not_dead_when_one_library_uses_it(
        self, tmp_path: Path,
    ) -> None:
        """A family entry that matches 2 libs and at least one is used → no warning."""
        root, libs = self._scaffold(tmp_path)
        entrypoint = root / "app.py"
        entrypoint.write_text(
            "from chumicro_mqtt import MQTTClient\n"
            '__chumicro_skip_factories__ = ("sockets_factory",)\n',
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        warnings = source.skip_factories_warnings()
        assert warnings == ()
