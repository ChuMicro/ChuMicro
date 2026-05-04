"""Tests for ``chumicro_workspace.devices_yml_starter``.

The module is a single-function payload reader — the contract is
narrow: return the canonical ``devices.yml`` starter content as a
string, identical bytes every call, sourced from the wheel-bundled
``_payloads/devices_yml/starter.yml.template``.

Two consumers in the ChuMicro ecosystem ride on this:

* The mono-repo's ``scripts/generate_config_files.py`` materialises
  ``<repo>/devices.yml`` from this content during
  ``python scripts/run.py setup``.
* The workspace-template repo's first-clone setup (``chumicro-workspace
  setup`` materialising ``<workspace>/devices.yml``).  The template
  repo currently carries its own static ``_workspace_template/
  devices.yml`` — a planned follow-up replaces that with a call to
  this reader so both repos share one source of truth.

Tests cover:

* The reader returns a non-empty string.
* The string contains the three-zone shape, empty-registry sentinel,
  and the unified-defaults block (``deploy_mode``, ``ide_runtime``,
  ``micropython``, ``circuitpython``).
* The content parses as valid YAML through the canonical schema
  reader (``chumicro_deploy.config.default.load_device_registry``).
* Successive calls return identical bytes.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_deploy.config.default import load_device_registry
from chumicro_workspace import read_devices_yml_starter


class TestReadDevicesYmlStarter:
    """Behavioural contract of the canonical starter reader."""

    def test_returns_non_empty_string(self) -> None:
        content = read_devices_yml_starter()
        assert isinstance(content, str)
        assert content.strip(), "starter must not be blank"

    def test_carries_three_zone_header(self) -> None:
        content = read_devices_yml_starter()
        # Each zone label appears in the unified header comment so
        # users grep'ing the file (or scrolling on first ``setup``)
        # find the documentation in place.
        assert "USER-OWNED" in content
        assert "HARDWARE-ONCE" in content
        assert "PROBED-ALWAYS" in content

    def test_ships_empty_registry(self) -> None:
        content = read_devices_yml_starter()
        # The sentinel ``add-device`` replaces on first registration.
        assert "devices: []" in content

    def test_carries_unified_defaults_block(self) -> None:
        content = read_devices_yml_starter()
        assert "defaults:" in content
        assert "micropython: null" in content
        assert "circuitpython: null" in content
        assert "deploy_mode: flash" in content
        # ``ide_runtime`` is part of the unified shape — both the
        # mono-repo and the workspace-template carry it so library
        # authors in either repo get IDE play-button targeting.
        assert "ide_runtime: micropython" in content

    def test_parses_through_canonical_schema_reader(
        self, tmp_path: Path,
    ) -> None:
        """The starter validates as a real ``devices.yml``.

        Catches drift between the payload and the schema reader —
        if someone renames a field on the schema side and forgets
        to update the starter, the schema check fires here at
        unit-test time.
        """
        devices_yml = tmp_path / "devices.yml"
        devices_yml.write_text(read_devices_yml_starter())

        devices, defaults = load_device_registry(workspace_root=tmp_path)
        assert devices == []
        assert defaults.deploy_mode == "flash"
        assert defaults.ide_runtime == "micropython"
        assert defaults.micropython is None
        assert defaults.circuitpython is None

    def test_returns_identical_bytes_across_calls(self) -> None:
        """Two reads must produce the same string.

        Pure side-effect-free reader; protects against a future
        change that adds e.g. a "fill in current date" template
        substitution that would make two consecutive calls differ.
        """
        first = read_devices_yml_starter()
        second = read_devices_yml_starter()
        assert first == second
