"""Tests for ``scripts/generate_config_files.py``.

Validates two contracts:

1. The mono-repo's ``devices.yml.template`` (a contributor-facing
   starter shaped like the workspace-template repo's empty-registry-
   plus-three-zone-comments file) parses cleanly through
   ``chumicro_deploy.config.default``'s schema validator.  Catches
   drift between the template payload and the schema the loader
   enforces — e.g. someone renames a field on the schema side and
   forgets to update the template.
2. ``generate_config_files`` is idempotent — running it twice produces
   identical content and never overwrites an edited file.

Background: until 2026-05-04, the mono-repo template shipped two
``sample-{circuitpython,micropython}-board`` pre-fills as documentation.
That made the test suite assert ``len(devices) >= 2`` after parse.
The unification workstream (``scripts-workbench-config-unification.md``)
swapped the pre-fills for an empty registry that ``chumicro-workspace
add-device`` populates on first registration — same shape as the
template repo.  These tests now verify the empty-registry contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy.config.default import (
    DeviceConfigError,
    load_device_registry,
)


def test_devices_yml_template_validates_against_schema(tmp_path: Path) -> None:
    """The starter ``devices.yml.template`` must satisfy the production schema.

    Materialises the template into a temp dir and runs the same
    loader the IDE / functional-test runner uses.  A schema change
    that breaks the template fails here at unit-test time instead of
    surfacing as a confusing "Run setup to generate it" error from
    a contributor's first pytest invocation.
    """
    from generate_config_files import _CONFIGS  # noqa: PLC0415
    from shared import TEMPLATES_DIR  # noqa: PLC0415

    devices_template_name = next(
        template
        for relative, template in _CONFIGS
        if relative == "devices.yml"
    )
    template_text = (TEMPLATES_DIR / devices_template_name).read_text()
    devices_yml = tmp_path / "devices.yml"
    devices_yml.write_text(template_text)

    # ``load_device_registry`` raises ``DeviceConfigError`` on any
    # schema violation — wrong runtime values, malformed defaults, etc.
    # An empty ``devices: []`` is a valid state (workspace-template
    # repo ships this shape; mono-repo does too as of the unification
    # workstream), so the loader returns ``([], defaults)`` cleanly.
    devices, defaults = load_device_registry(workspace_root=tmp_path)

    # The starter ships empty — ``chumicro-workspace add-device``
    # populates the list on first registration.
    assert devices == [], (
        "starter template ships an empty registry; add-device populates it"
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
    contributor who edits ``devices.yml`` after first ``setup`` and
    later runs setup again must keep their edits.
    """
    import generate_config_files as module  # noqa: PLC0415

    monkeypatch.setattr(module, "ROOT", tmp_path)

    # First run — creates files.
    assert module.generate_config_files() == 0
    devices_yml = tmp_path / "devices.yml"
    assert devices_yml.is_file()
    devices_yml.write_text("# user edited\ndevices: []\n")

    # Second run — must not overwrite the edit.
    assert module.generate_config_files() == 0
    assert devices_yml.read_text() == "# user edited\ndevices: []\n"


def test_devices_yml_template_invalid_runtime_caught_by_schema(
    tmp_path: Path,
) -> None:
    """Sanity-check the validator fires on a deliberately corrupted file.

    Belt-and-suspenders: if the schema validator silently accepts
    bad input the first test above would pass spuriously.  This
    test injects an invalid device entry and expects a hard failure,
    proving the validator is actually doing work.

    The template itself ships empty (no device entries) so we
    materialize it, then append a malformed entry — covering the
    same ground as the previous "corrupt the sample entry" approach
    without relying on hardcoded sample IDs.
    """
    from generate_config_files import _CONFIGS  # noqa: PLC0415
    from shared import TEMPLATES_DIR  # noqa: PLC0415

    devices_template_name = next(
        template
        for relative, template in _CONFIGS
        if relative == "devices.yml"
    )
    template_text = (TEMPLATES_DIR / devices_template_name).read_text()
    # Replace the empty list with a single entry carrying a bad runtime.
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
