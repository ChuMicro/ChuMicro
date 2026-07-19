"""Tests for project-tree functional-test routing in session / collection.

Covers the ``projects/<name>/functional_tests/`` path predicates
(:func:`session._is_project_functional_test`,
:func:`session._project_functional_test_targeted`,
:func:`session._project_unit_name`), the
:func:`collection.pytest_ignore_collect` gate that keeps untargeted
project functional tests off both the host and the board, the
project-item naming carried by ``DeviceRuntimeItem``, and the
installed-harness fallback a standalone workspace stages from.

All paths run on CPython with tmp_path fixtures and ``SimpleNamespace``
config stand-ins; none reach real hardware.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from chumicro_pytest_device import collection, session
from chumicro_pytest_device import plugin as pytest_device
from chumicro_pytest_device.testing import (
    FakeSession,
    hot_path_device,
    make_test_item,
)


def _project_functional_file(
    tmp_path: Path, project: str = "example_sensor", name: str = "test_x.py",
) -> Path:
    """Create ``projects/<project>/functional_tests/<name>`` under tmp_path."""
    test_file = tmp_path / "projects" / project / "functional_tests" / name
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_one(): pass\n")
    return test_file


def _nested_project_functional_file(tmp_path: Path) -> Path:
    """Create ``projects/garage/heater/functional_tests/test_x.py`` under tmp_path."""
    test_file = (
        tmp_path / "projects" / "garage" / "heater"
        / "functional_tests" / "test_x.py"
    )
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_one(): pass\n")
    return test_file


def _library_functional_file(tmp_path: Path, library: str = "kvstore") -> Path:
    """Create ``libraries/<library>/functional_tests/test_x.py`` under tmp_path."""
    test_file = tmp_path / "libraries" / library / "functional_tests" / "test_x.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_one(): pass\n")
    return test_file


def _fake_config(args: list[str], invocation_dir: Path) -> SimpleNamespace:
    """Return a ``pytest.Config`` stand-in exposing only ``invocation_params``."""
    return SimpleNamespace(
        invocation_params=SimpleNamespace(
            args=tuple(args), dir=invocation_dir,
        ),
    )


class TestIsProjectFunctionalTest:
    """Path-shape classification for project functional tests."""

    def test_accepts_flat_project_path(self, tmp_path: Path) -> None:
        """A ``projects/<name>/functional_tests/test_*.py`` file classifies as project."""
        assert session._is_project_functional_test(
            _project_functional_file(tmp_path),
        )

    def test_accepts_nested_project_path(self, tmp_path: Path) -> None:
        """A nested ``projects/garage/heater/functional_tests`` file classifies too."""
        assert session._is_project_functional_test(
            _nested_project_functional_file(tmp_path),
        )

    def test_rejects_library_under_a_directory_named_projects(self) -> None:
        """A library checkout under a ``projects`` dir stays a library test.

        Walking up from ``functional_tests`` hits ``libraries`` before the
        ancestor ``projects`` directory, so the nearer marker wins.
        """
        path = Path(
            "/home/me/projects/chumicro/libraries/kvstore"
            "/functional_tests/test_kvstore.py",
        )
        assert session._is_project_functional_test(path) is False

    def test_rejects_plain_library_path(self, tmp_path: Path) -> None:
        """A ``libraries/<name>/functional_tests`` file is not a project test."""
        assert (
            session._is_project_functional_test(
                _library_functional_file(tmp_path),
            )
            is False
        )

    def test_rejects_non_test_file(self, tmp_path: Path) -> None:
        """A ``conftest.py`` under a project ``functional_tests`` is not a test file."""
        conftest = _project_functional_file(tmp_path, name="conftest.py")
        assert session._is_project_functional_test(conftest) is False


class TestProjectFunctionalTestsDir:
    """The owning ``functional_tests`` directory for a project test file."""

    def test_flat_owning_dir(self, tmp_path: Path) -> None:
        """The owning dir is the file's own ``functional_tests`` parent."""
        test_file = _project_functional_file(tmp_path)
        assert (
            session._project_functional_tests_dir(test_file) == test_file.parent
        )

    def test_nested_owning_dir(self, tmp_path: Path) -> None:
        """The deepest project-owned ``functional_tests`` component is returned."""
        test_file = _nested_project_functional_file(tmp_path)
        assert (
            session._project_functional_tests_dir(test_file) == test_file.parent
        )


class TestProjectFunctionalTestTargeted:
    """Targeting semantics: the tree fires only when named directly."""

    def test_targets_functional_tests_dir_itself(self, tmp_path: Path) -> None:
        """Naming the ``functional_tests`` directory targets the tree."""
        test_file = _project_functional_file(tmp_path)
        config = _fake_config([str(test_file.parent)], tmp_path)
        assert session._project_functional_test_targeted(config, test_file)

    def test_targets_a_file_inside_with_nodeid_suffix(self, tmp_path: Path) -> None:
        """Naming a file inside the tree (with a ``::nodeid``) targets it."""
        test_file = _project_functional_file(tmp_path)
        config = _fake_config([f"{test_file}::test_one"], tmp_path)
        assert session._project_functional_test_targeted(config, test_file)

    def test_ancestor_project_dir_does_not_count(self, tmp_path: Path) -> None:
        """Naming the project dir (an ancestor) does not target the tree."""
        test_file = _project_functional_file(tmp_path)
        project_dir = test_file.parent.parent
        config = _fake_config([str(project_dir)], tmp_path)
        assert session._project_functional_test_targeted(config, test_file) is False

    def test_bare_invocation_does_not_target(self, tmp_path: Path) -> None:
        """A no-path invocation (bare sweep) targets nothing."""
        test_file = _project_functional_file(tmp_path)
        config = _fake_config([], tmp_path)
        assert session._project_functional_test_targeted(config, test_file) is False

    def test_option_value_after_flag_is_harmless(self, tmp_path: Path) -> None:
        """A non-path option value (``ram`` after ``--deploy-mode``) never matches."""
        test_file = _project_functional_file(tmp_path)
        config = _fake_config(["--deploy-mode", "ram"], tmp_path)
        assert session._project_functional_test_targeted(config, test_file) is False

    def test_relative_arg_resolves_against_invocation_dir(
        self, tmp_path: Path,
    ) -> None:
        """A relative path resolves against ``invocation_params.dir``."""
        test_file = _project_functional_file(tmp_path)
        relative = "projects/example_sensor/functional_tests"
        config = _fake_config([relative], tmp_path)
        assert session._project_functional_test_targeted(config, test_file)


class TestProjectUnitName:
    """Slash-form project name for display and runtime-config scoping."""

    def test_flat_name(self, tmp_path: Path) -> None:
        """A flat project yields its own directory name."""
        assert (
            session._project_unit_name(_project_functional_file(tmp_path))
            == "example_sensor"
        )

    def test_nested_name(self, tmp_path: Path) -> None:
        """A nested project yields the slash-joined tail after ``projects``."""
        assert (
            session._project_unit_name(_nested_project_functional_file(tmp_path))
            == "garage/heater"
        )


class TestPytestIgnoreCollect:
    """The ignore-collect gate keeps untargeted project tests off every lane."""

    def test_untargeted_project_file_is_ignored(self, tmp_path: Path) -> None:
        """An untargeted project functional test is ignored (returns True)."""
        test_file = _project_functional_file(tmp_path)
        config = _fake_config([], tmp_path)
        assert collection.pytest_ignore_collect(test_file, config) is True

    def test_targeted_project_file_is_not_ignored(self, tmp_path: Path) -> None:
        """A targeted project functional test defers (returns None)."""
        test_file = _project_functional_file(tmp_path)
        config = _fake_config([str(test_file.parent)], tmp_path)
        assert collection.pytest_ignore_collect(test_file, config) is None

    def test_library_file_is_not_ignored(self, tmp_path: Path) -> None:
        """A library functional test is never ignored by this hook (returns None)."""
        test_file = _library_functional_file(tmp_path)
        config = _fake_config([], tmp_path)
        assert collection.pytest_ignore_collect(test_file, config) is None


class TestDeviceRuntimeItemProjectNaming:
    """A project item scopes by slash-form name; a library item by dir name."""

    def test_project_item_uses_slash_form_name(self, tmp_path: Path) -> None:
        """A nested-project item carries the slash-form project name."""
        session_stub = FakeSession(
            pytest_device._TransportCache(), rootpath=tmp_path,
        )
        test_file = _nested_project_functional_file(tmp_path)
        item = make_test_item(
            session_stub, hot_path_device(), test_file, "test_one",
        )
        assert item.library_name == "garage/heater"

    def test_library_item_uses_directory_name(self, tmp_path: Path) -> None:
        """A library item keeps the library directory name as its scope."""
        session_stub = FakeSession(
            pytest_device._TransportCache(), rootpath=tmp_path,
        )
        test_file = _library_functional_file(tmp_path, library="kvstore")
        item = make_test_item(
            session_stub, hot_path_device(), test_file, "test_one",
        )
        assert item.library_name == "kvstore"


class TestInstalledHarnessSourceDir:
    """The pip-installed harness fallback resolves both install layouts."""

    def test_src_layout_returns_the_src_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A source-checkout layout returns the ``src`` dir that holds only the package."""
        source_dir = tmp_path / "src"
        package_dir = source_dir / "chumicro_test_harness"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").touch()
        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name: SimpleNamespace(
                origin=str(package_dir / "__init__.py"),
            ),
        )
        config = SimpleNamespace(
            cache=SimpleNamespace(mkdir=lambda name: tmp_path / "cache"),
        )
        assert session._installed_harness_source_dir(config) == source_dir

    def test_wheel_layout_stages_only_the_harness_package(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A site-packages layout copies only the harness into a private staging dir."""
        site_packages = tmp_path / "site-packages"
        package_dir = site_packages / "chumicro_test_harness"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# init\n")
        (package_dir / "runner.py").write_text("# runner\n")
        (package_dir / "__pycache__").mkdir()
        (package_dir / "__pycache__" / "runner.pyc").write_text("junk\n")
        # A sibling distribution that staging the whole dir would sweep in.
        (site_packages / "some_other_package").mkdir()
        (site_packages / "some_other_package" / "__init__.py").touch()

        staging_root = tmp_path / "cache-staging"
        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name: SimpleNamespace(
                origin=str(package_dir / "__init__.py"),
            ),
        )
        config = SimpleNamespace(
            cache=SimpleNamespace(mkdir=lambda name: staging_root),
        )

        result = session._installed_harness_source_dir(config)

        assert result == staging_root
        assert [child.name for child in sorted(result.iterdir())] == [
            "chumicro_test_harness",
        ]
        staged_package = result / "chumicro_test_harness"
        assert (staged_package / "runner.py").is_file()
        assert not (staged_package / "__pycache__").exists()

    def test_wheel_layout_replaces_a_stale_staged_package(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A stale ``chumicro_test_harness`` in the staging dir is removed first."""
        site_packages = tmp_path / "site-packages"
        package_dir = site_packages / "chumicro_test_harness"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("# fresh\n")

        staging_root = tmp_path / "cache-staging"
        stale = staging_root / "chumicro_test_harness"
        stale.mkdir(parents=True)
        (stale / "stale_module.py").write_text("# stale\n")

        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name: SimpleNamespace(
                origin=str(package_dir / "__init__.py"),
            ),
        )
        config = SimpleNamespace(
            cache=SimpleNamespace(mkdir=lambda name: staging_root),
        )

        result = session._installed_harness_source_dir(config)

        staged_package = result / "chumicro_test_harness"
        assert not (staged_package / "stale_module.py").exists()
        assert (staged_package / "__init__.py").read_text() == "# fresh\n"

    def test_missing_harness_raises_usage_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No importable harness raises a coached ``pytest.UsageError``."""
        monkeypatch.setattr(
            importlib.util, "find_spec", lambda name: None,
        )
        with pytest.raises(
            pytest.UsageError, match="pip install chumicro-test-harness",
        ):
            session._installed_harness_source_dir(SimpleNamespace())
