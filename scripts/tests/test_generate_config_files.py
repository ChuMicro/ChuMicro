"""Tests for ``scripts/generate_config_files.py``.

Validates two contracts:

1. The canonical ``devices.yml`` template (sourced from
   ``chumicro_deploy.read_devices_yml_template``) parses cleanly
   through ``chumicro_deploy.config.default``'s schema validator.
   Catches drift between the bundled payload and the schema the
   loader enforces — e.g. someone renames a field on the schema side
   and forgets to update the payload.
2. ``generate_config_files`` is idempotent — running it twice produces
   identical content and never overwrites an edited file.

``generate_config_files`` materializes any missing config files from
the canonical templates: ``devices.yml`` from ``chumicro_deploy``
(co-located with the schema) and ``workspace.yml`` / ``secrets.toml``
from ``chumicro_workspace.templates``.  Existing files are never
overwritten.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import read_devices_yml_template
from chumicro_deploy.config.default import (
    DeviceConfigError,
    load_device_registry,
)
from chumicro_workspace import read_workspace_yml_template


def test_devices_yml_template_validates_against_schema(tmp_path: Path) -> None:
    """The canonical template must satisfy the production schema.

    Materializes the template into a temp dir and runs the same
    loader the IDE / functional-test runner uses.  A schema change
    that breaks the template fails here at unit-test time instead of
    surfacing as a confusing "Run setup to generate it" error from
    a contributor's first pytest invocation.
    """
    devices_yml = tmp_path / "devices.yml"
    devices_yml.write_text(read_devices_yml_template())

    devices, defaults = load_device_registry(workspace_root=tmp_path)

    assert devices == [], (
        "template ships an empty registry; add-device populates it"
    )
    assert defaults.deploy_mode in ("ram", "flash"), (
        f"defaults.deploy_mode must be valid, got {defaults.deploy_mode}"
    )
    assert defaults.ide_runtime in ("micropython", "circuitpython", "both"), (
        f"defaults.ide_runtime must be valid, got {defaults.ide_runtime}"
    )
    assert defaults.micropython is None
    assert defaults.circuitpython is None


def test_generate_config_files_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Running ``generate_config_files`` twice doesn't overwrite existing files.

    The function's contract: write-if-missing, never clobber.  A
    contributor who edits ``devices.yml`` or ``workspace.yml`` after
    first ``setup`` and later runs setup again must keep their edits.
    """
    import generate_config_files as module  # noqa: PLC0415

    monkeypatch.setattr(module, "ROOT", tmp_path)

    # First run — creates files.
    assert module.generate_config_files() == 0
    devices_yml = tmp_path / "devices.yml"
    workspace_yml = tmp_path / "workspace.yml"
    assert devices_yml.is_file()
    assert workspace_yml.is_file()
    devices_yml.write_text("# user edited\ndevices: []\n")
    workspace_yml.write_text(
        "defaults:\n  wifi:\n    password: my-real-password\n",
    )

    # Second run — must not overwrite the edits.
    assert module.generate_config_files() == 0
    assert devices_yml.read_text() == "# user edited\ndevices: []\n"
    assert workspace_yml.read_text() == (
        "defaults:\n  wifi:\n    password: my-real-password\n"
    )


def test_workspace_yml_materialized_from_template_verbatim(
    tmp_path: Path, monkeypatch,
) -> None:
    """``setup`` writes ``workspace.yml`` from the canonical template.

    Belt-and-suspenders against an accidental shutil/copy layer
    creeping in between ``read_workspace_yml_template`` and the file
    that lands at the repo root.
    """
    import generate_config_files as module  # noqa: PLC0415

    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.generate_config_files() == 0

    workspace_yml = tmp_path / "workspace.yml"
    assert workspace_yml.is_file()
    # The materialized file comes verbatim from the template.
    assert workspace_yml.read_text() == read_workspace_yml_template()


def test_devices_yml_template_invalid_runtime_caught_by_schema(
    tmp_path: Path,
) -> None:
    """Sanity-check the validator fires on a deliberately corrupted file.

    Belt-and-suspenders: if the schema validator silently accepts
    bad input the first test above would pass spuriously.  This test
    injects an invalid device entry and expects a hard failure,
    proving the validator is actually doing work.
    """
    template_text = read_devices_yml_template()
    corrupted = template_text.replace(
        "devices: []",
        "devices:\n"
        "  - id: bad-board\n"
        "    runtime: arduino\n"
        "    address: /dev/ttyUSB0\n",
    )
    assert corrupted != template_text, "fixture corruption produced no change"
    devices_yml = tmp_path / "devices.yml"
    devices_yml.write_text(corrupted)

    with pytest.raises(DeviceConfigError, match="invalid runtime"):
        load_device_registry(workspace_root=tmp_path)


def test_devices_yml_template_matches_payload_verbatim() -> None:
    """The template content comes verbatim from the wheel payload.

    Belt-and-suspenders against an accidental ``shutil.copy`` /
    template-rendering layer creeping in between
    ``read_devices_yml_template`` and what ``generate_config_files``
    writes.  If a future caller adds substitution logic that mutates
    the bytes, this test breaks loud.
    """
    template = read_devices_yml_template()
    assert "USER-OWNED" in template
    assert "PROBED-ALWAYS" in template
    assert "HARDWARE-ONCE" in template
    assert "devices: []" in template
    assert "defaults:" in template
    assert "deploy_mode: flash" in template
    assert "ide_runtime: micropython" in template
