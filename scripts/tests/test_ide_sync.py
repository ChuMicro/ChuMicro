"""Tests for ide.py — IDE configuration generation."""

import json

from ide_sync import _config_filename, sync_ide


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
        assert _config_filename("CircuitPython Compatibility") == "CircuitPython_Compatibility.xml"


class TestSyncIde:
    """Tests for sync_ide — integration with real workspace."""

    def test_idempotent(self):
        """Running sync_ide twice produces the same result."""
        result1 = sync_ide()
        assert result1 == 0
        result2 = sync_ide()
        assert result2 == 0

    def test_creates_pyrightconfig(self):
        """pyrightconfig.json exists after sync."""
        from workspace import ROOT

        sync_ide()
        config_file = ROOT / "pyrightconfig.json"
        assert config_file.exists()
        config = json.loads(config_file.read_text())
        assert "extraPaths" in config
        assert len(config["extraPaths"]) > 0

    def test_creates_vscode_tasks(self):
        """VS Code tasks.json exists after sync."""
        from workspace import ROOT

        sync_ide()
        tasks_file = ROOT / ".vscode" / "tasks.json"
        assert tasks_file.exists()
        tasks = json.loads(tasks_file.read_text())
        assert tasks["version"] == "2.0.0"
        assert len(tasks["tasks"]) > 0

    def test_creates_pycharm_configs(self):
        """PyCharm run configurations are created."""
        from workspace import ROOT

        sync_ide()
        config_dir = ROOT / ".idea" / "runConfigurations"
        assert config_dir.is_dir()
        xml_files = list(config_dir.glob("*.xml"))
        assert len(xml_files) > 0

