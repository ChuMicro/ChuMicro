"""Tests for ide.py — IDE configuration generation.

Every test that drives ``sync_ide`` (or one of its ``_sync_*`` helpers)
runs against a synthetic workspace materialized under ``tmp_path`` and
pins both ``ide_sync.ROOT`` and the workspace-discovery callables to
that synthetic tree.  This keeps the test suite from mutating the real
``.vscode/`` and ``.idea/`` directories on the contributor's working
copy and decouples assertions from whichever real packages happen to
sit on disk.
"""

import json
from pathlib import Path
from xml.etree import ElementTree

import ide_sync
import pytest
from ide_sync import _config_filename, sync_ide


@pytest.fixture
def synthetic_workspace(tmp_path: Path, monkeypatch):
    """Build a minimal synthetic workspace and pin ``ide_sync.ROOT`` to it.

    Materializes one fake library (``libraries/synth``) with an
    importable package under ``src/`` and pre-creates ``scripts/tests/``
    so ``_sync_pycharm_iml`` finds the test source root.  Patches
    ``ide_sync.discover_package_dirs`` and ``ide_sync.discover_source_roots``
    so they return paths relative to the synthetic tree (the real
    discovery functions read ``workspace.ROOT``, not ``ide_sync.ROOT``,
    and would otherwise hand back real-workspace paths that
    ``relative_to(ROOT)`` would reject).
    """
    library_dir = tmp_path / "libraries" / "synth"
    package_source_dir = library_dir / "src" / "chumicro_synth"
    package_source_dir.mkdir(parents=True)
    (package_source_dir / "__init__.py").touch()
    (library_dir / "pyproject.toml").write_text(
        '[project]\nname = "chumicro-synth"\n',
    )

    # _sync_pycharm_iml conditionally adds scripts/tests as a source root.
    (tmp_path / "scripts" / "tests").mkdir(parents=True)

    monkeypatch.setattr(ide_sync, "ROOT", tmp_path)
    monkeypatch.setattr(
        ide_sync, "discover_package_dirs", lambda: [library_dir],
    )
    monkeypatch.setattr(
        ide_sync,
        "discover_source_roots",
        lambda: [library_dir / "src"],
    )

    return tmp_path


class TestConfigFilename:
    """Tests for _config_filename."""

    def test_simple_name(self):
        """Simple name is converted to XML filename."""
        assert _config_filename("Lint") == "Lint.xml"

    def test_spaces_become_underscores(self):
        """Spaces in names are replaced with underscores."""
        assert _config_filename("Check API") == "Check_API.xml"

    def test_multi_word(self):
        """Multi-word names are fully converted."""
        assert _config_filename("Test Libraries Functional") == "Test_Libraries_Functional.xml"


class TestSyncIde:
    """Tests for sync_ide — runs against a synthetic workspace."""

    def test_idempotent(self, synthetic_workspace):
        """Running sync_ide twice produces the same result."""
        result1 = sync_ide()
        assert result1 == 0
        result2 = sync_ide()
        assert result2 == 0

    def test_creates_pyrightconfig(self, synthetic_workspace):
        """pyrightconfig.json exists after sync."""
        sync_ide()
        config_file = synthetic_workspace / "pyrightconfig.json"
        assert config_file.exists()
        config = json.loads(config_file.read_text())
        assert "extraPaths" in config
        assert len(config["extraPaths"]) > 0

    def test_creates_vscode_tasks(self, synthetic_workspace):
        """VS Code tasks.json exists after sync."""
        sync_ide()
        tasks_file = synthetic_workspace / ".vscode" / "tasks.json"
        assert tasks_file.exists()
        tasks = json.loads(tasks_file.read_text())
        assert tasks["version"] == "2.0.0"
        assert len(tasks["tasks"]) > 0

    def test_tasks_use_python_extension_interpreter_variable(
        self, synthetic_workspace,
    ):
        """Tasks must invoke the Python extension's selected interpreter
        rather than a bare ``python`` — many systems only ship ``python3``
        on PATH (and Windows venvs live under Scripts/), so a literal
        ``python`` fails to launch."""
        sync_ide()
        tasks = json.loads(
            (synthetic_workspace / ".vscode" / "tasks.json").read_text(),
        )["tasks"]
        for task in tasks:
            assert task["command"] == "${command:python.interpreterPath}", (
                f"Task {task['label']!r} uses {task['command']!r} — must "
                "use ${command:python.interpreterPath} for cross-platform "
                "compatibility."
            )

    def test_creates_vscode_extensions(self, synthetic_workspace):
        """VS Code extensions.json exists after sync with the recommended set."""
        sync_ide()
        extensions_file = synthetic_workspace / ".vscode" / "extensions.json"
        assert extensions_file.exists()
        extensions = json.loads(extensions_file.read_text())
        assert "ms-python.python" in extensions["recommendations"]
        assert "ms-python.vscode-pylance" in extensions["recommendations"]

    def test_creates_pycharm_configs(self, synthetic_workspace):
        """PyCharm run configurations are created."""
        sync_ide()
        config_dir = synthetic_workspace / ".idea" / "runConfigurations"
        assert config_dir.is_dir()
        xml_files = list(config_dir.glob("*.xml"))
        assert len(xml_files) > 0

    def test_generated_iml_includes_reset_guidance(self, synthetic_workspace):
        """The generated .iml should explain how to reset local PyCharm rewrites."""
        sync_ide()
        iml_file = synthetic_workspace / ".idea" / "chumicro.iml"
        assert iml_file.exists()
        content = iml_file.read_text()
        ElementTree.fromstring(content)
        assert "Generated by scripts/run.py sync-ide." in content
        assert "PyCharm may rewrite this file" in content
        assert "python scripts/run.py sync-ide" in content

    def test_preserves_existing_misc_xml(self, tmp_path, monkeypatch):
        """sync_ide should never overwrite an existing .idea/misc.xml."""
        fake_root = tmp_path
        (fake_root / ".idea").mkdir()
        misc_file = fake_root / ".idea" / "misc.xml"
        original = "<project version=\"4\"><!-- user content --></project>\n"
        misc_file.write_text(original)

        monkeypatch.setattr(ide_sync, "ROOT", fake_root)
        ide_sync._sync_pycharm_misc_xml()

        assert misc_file.read_text() == original

    def test_creates_misc_xml_when_missing(self, tmp_path, monkeypatch):
        """sync_ide should seed misc.xml with a PyCharm-convention SDK name."""
        fake_root = tmp_path / "chumicro"
        fake_root.mkdir()
        (fake_root / ".idea").mkdir()

        monkeypatch.setattr(ide_sync, "ROOT", fake_root)
        ide_sync._sync_pycharm_misc_xml()

        misc_file = fake_root / ".idea" / "misc.xml"
        assert misc_file.exists()
        content = misc_file.read_text()
        ElementTree.fromstring(content)
        # Name follows PyCharm's convention: Python X.Y (<project folder>)
        assert "(chumicro)" in content
        assert "project-jdk-name=" in content
