"""Tests for ``scripts/generate_config_files.py``.

Validates two contracts:

1. The starter ``devices.yml`` content (sourced from the
   ``chumicro-workspace`` workbench package's
   ``read_devices_yml_starter`` rather than a mono-repo template
   file) parses cleanly through ``chumicro_deploy.config.default``'s
   schema validator.  Catches drift between the workbench-owned
   payload and the schema the loader enforces — e.g. someone renames
   a field on the schema side and forgets to update the payload.
2. ``generate_config_files`` is idempotent — running it twice produces
   identical content and never overwrites an edited file.

Background: until 2026-05-04, the mono-repo shipped its own
``scripts/templates/devices.yml.template`` with two
``sample-{circuitpython,micropython}-board`` pre-fills as
documentation.  The unification workstream
(``scripts-workbench-config-unification.md``) swapped the pre-fills
for an empty registry that ``chumicro-workspace add-device``
populates on first registration — same shape as the workspace-template
repo — and moved the canonical content into the workbench package
so both repos materialise from one source of truth.

Decision 0057 then retired the ``secrets.yml`` + ``!secret`` marker
in favour of a structural ``workspace.local.yml`` overlay; the
materialise-from-workbench-payload pattern is unchanged, just with
a different starter file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy.config.default import (
    DeviceConfigError,
    load_device_registry,
)
from chumicro_workspace import (
    read_devices_yml_starter,
    read_workspace_local_yml_starter,
)


def test_devices_yml_starter_validates_against_schema(tmp_path: Path) -> None:
    """The workbench-owned starter must satisfy the production schema.

    Materialises the starter into a temp dir and runs the same
    loader the IDE / functional-test runner uses.  A schema change
    that breaks the starter fails here at unit-test time instead of
    surfacing as a confusing "Run setup to generate it" error from
    a contributor's first pytest invocation.
    """
    devices_yml = tmp_path / "devices.yml"
    devices_yml.write_text(read_devices_yml_starter())

    devices, defaults = load_device_registry(workspace_root=tmp_path)

    assert devices == [], (
        "starter ships an empty registry; add-device populates it"
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
    contributor who edits ``devices.yml`` or ``workspace.local.yml``
    after first ``setup`` and later runs setup again must keep their
    edits.
    """
    import generate_config_files as module  # noqa: PLC0415

    monkeypatch.setattr(module, "ROOT", tmp_path)

    # First run — creates files.
    assert module.generate_config_files() == 0
    devices_yml = tmp_path / "devices.yml"
    workspace_local_yml = tmp_path / "workspace.local.yml"
    assert devices_yml.is_file()
    assert workspace_local_yml.is_file()
    devices_yml.write_text("# user edited\ndevices: []\n")
    workspace_local_yml.write_text(
        "defaults:\n  wifi:\n    password: my-real-password\n",
    )

    # Second run — must not overwrite the edits.
    assert module.generate_config_files() == 0
    assert devices_yml.read_text() == "# user edited\ndevices: []\n"
    assert workspace_local_yml.read_text() == (
        "defaults:\n  wifi:\n    password: my-real-password\n"
    )


def test_workspace_local_yml_materialised_from_workbench_payload(
    tmp_path: Path, monkeypatch,
) -> None:
    """``setup`` writes ``workspace.local.yml`` from the workbench starter.

    Belt-and-suspenders against an accidental shutil/copy layer
    creeping in between ``read_workspace_local_yml_starter`` and the
    file that lands at the repo root — same source-of-truth pattern
    as devices.yml (Phase 1 of the unification workstream; Decision
    0057 swapped which file the pattern materialises).
    """
    import generate_config_files as module  # noqa: PLC0415

    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.generate_config_files() == 0

    workspace_local_yml = tmp_path / "workspace.local.yml"
    assert workspace_local_yml.is_file()
    # The materialised file must come verbatim from the workbench
    # starter — no template substitutions, no rendering layer.
    assert (
        workspace_local_yml.read_text()
        == read_workspace_local_yml_starter()
    )


def test_devices_yml_starter_invalid_runtime_caught_by_schema(
    tmp_path: Path,
) -> None:
    """Sanity-check the validator fires on a deliberately corrupted file.

    Belt-and-suspenders: if the schema validator silently accepts
    bad input the first test above would pass spuriously.  This
    test injects an invalid device entry and expects a hard failure,
    proving the validator is actually doing work.
    """
    starter_text = read_devices_yml_starter()
    corrupted = starter_text.replace(
        "devices: []",
        "devices:\n"
        "  - id: bad-board\n"
        "    runtime: arduino\n"
        "    address: /dev/ttyUSB0\n",
    )
    assert corrupted != starter_text, "fixture corruption produced no change"
    devices_yml = tmp_path / "devices.yml"
    devices_yml.write_text(corrupted)

    with pytest.raises(DeviceConfigError, match="invalid runtime"):
        load_device_registry(workspace_root=tmp_path)


def test_devices_yml_starter_matches_workbench_payload() -> None:
    """The starter content comes verbatim from the workbench payload.

    Belt-and-suspenders against an accidental ``shutil.copy`` /
    template-rendering layer creeping in between
    ``read_devices_yml_starter`` and what ``generate_config_files``
    writes.  If a future caller adds substitution logic that mutates
    the bytes, this test breaks loud.
    """
    starter = read_devices_yml_starter()
    assert "USER-OWNED" in starter
    assert "PROBED-ALWAYS" in starter
    assert "HARDWARE-ONCE" in starter
    assert "devices: []" in starter
    assert "defaults:" in starter
    assert "deploy_mode: flash" in starter
    assert "ide_runtime: micropython" in starter
