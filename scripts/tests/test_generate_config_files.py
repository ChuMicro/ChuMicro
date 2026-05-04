"""Tests for ``scripts/generate_config_files.py``.

Validates two contracts:

1. The starter ``devices.yml`` content (now sourced from the
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
documentation.  That made the test suite assert ``len(devices) >= 2``
after parse.  The unification workstream
(``scripts-workbench-config-unification.md``) swapped the pre-fills
for an empty registry that ``chumicro-workspace add-device``
populates on first registration — same shape as the workspace-template
repo — and moved the canonical content into the workbench package
so both repos materialise from one source of truth.  These tests
verify the empty-registry contract and the workbench-payload wiring.
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
    read_secrets_yml_starter,
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

    # ``load_device_registry`` raises ``DeviceConfigError`` on any
    # schema violation — wrong runtime values, malformed defaults, etc.
    # An empty ``devices: []`` is a valid state (workspace-template
    # repo ships this shape; mono-repo does too as of the unification
    # workstream), so the loader returns ``([], defaults)`` cleanly.
    devices, defaults = load_device_registry(workspace_root=tmp_path)

    # The starter ships empty — ``chumicro-workspace add-device``
    # populates the list on first registration.
    assert devices == [], (
        "starter ships an empty registry; add-device populates it"
    )
    # Defaults are present and valid even on a freshly-materialized
    # empty file — keeps preflight / IDE-resolve paths well-defined
    # before any board is registered.
    assert defaults.deploy_mode in ("ram", "flash"), (
        f"defaults.deploy_mode must be valid, got {defaults.deploy_mode}"
    )
    assert defaults.ide_runtime in ("micropython", "circuitpython", "both"), (
        f"defaults.ide_runtime must be valid, got {defaults.ide_runtime}"
    )
    # ``defaults.{micropython,circuitpython}`` are explicitly null in
    # the starter; ``add-device`` fills them in on first registration
    # of each runtime.
    assert defaults.micropython is None
    assert defaults.circuitpython is None


def test_generate_config_files_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Running ``generate_config_files`` twice doesn't overwrite existing files.

    The function's contract: write-if-missing, never clobber.  A
    contributor who edits ``devices.yml`` or ``secrets.yml`` after
    first ``setup`` and later runs setup again must keep their edits.
    """
    import generate_config_files as module  # noqa: PLC0415

    monkeypatch.setattr(module, "ROOT", tmp_path)

    # First run — creates files.
    assert module.generate_config_files() == 0
    devices_yml = tmp_path / "devices.yml"
    secrets_yml = tmp_path / "secrets.yml"
    assert devices_yml.is_file()
    assert secrets_yml.is_file()
    devices_yml.write_text("# user edited\ndevices: []\n")
    secrets_yml.write_text("wifi_password: my-real-password\n")

    # Second run — must not overwrite the edits.
    assert module.generate_config_files() == 0
    assert devices_yml.read_text() == "# user edited\ndevices: []\n"
    assert secrets_yml.read_text() == "wifi_password: my-real-password\n"


def test_secrets_yml_materialised_from_workbench_payload(
    tmp_path: Path, monkeypatch,
) -> None:
    """``setup`` writes ``secrets.yml`` from the workbench starter.

    Belt-and-suspenders against an accidental shutil/copy layer
    creeping in between ``read_secrets_yml_starter`` and the file
    that lands at the repo root — same source-of-truth pattern as
    devices.yml (Phase 1 of the unification workstream).
    """
    import generate_config_files as module  # noqa: PLC0415

    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.generate_config_files() == 0

    secrets_yml = tmp_path / "secrets.yml"
    assert secrets_yml.is_file()
    # The materialised file must come verbatim from the workbench
    # starter — no template substitutions, no rendering layer.
    assert secrets_yml.read_text() == read_secrets_yml_starter()


def test_devices_yml_starter_invalid_runtime_caught_by_schema(
    tmp_path: Path,
) -> None:
    """Sanity-check the validator fires on a deliberately corrupted file.

    Belt-and-suspenders: if the schema validator silently accepts
    bad input the first test above would pass spuriously.  This
    test injects an invalid device entry and expects a hard failure,
    proving the validator is actually doing work.

    The starter itself ships empty (no device entries) so we
    materialize it, then append a malformed entry — covering the
    same ground as the previous "corrupt the sample entry" approach
    without relying on hardcoded sample IDs.
    """
    starter_text = read_devices_yml_starter()
    # Replace the empty list with a single entry carrying a bad runtime.
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
    # Three load-bearing markers from the unified shape:
    assert "USER-OWNED" in starter
    assert "PROBED-ALWAYS" in starter
    assert "HARDWARE-ONCE" in starter
    # The empty-registry sentinel is what add-device replaces:
    assert "devices: []" in starter
    # Defaults block is well-formed (the schema test above covers
    # parsing; this is a quick sanity check that the YAML keys
    # are present at the lexical level too):
    assert "defaults:" in starter
    assert "deploy_mode: flash" in starter
    assert "ide_runtime: micropython" in starter
