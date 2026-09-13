"""Library scaffolding: thin wrapper over `chumicro_workspace.scaffold`.

`python scripts/run.py new-library <name>` calls
:func:`new_library` here, which composes the workbench
scaffolder with mono-repo-only follow-ups: editable-install
of the new package + IDE config sync.

External users developing their own chumicro-style libraries
get the same scaffolder via
``python run.py new --library <name>`` (the workspace CLI's
library mode).  They don't need this script's editable-install
plus IDE sync because their workspace's `setup` already handles
those.
"""

from __future__ import annotations

from chumicro_workspace.scaffold import (
    CHUMICRO_BRANDING,
    LibraryAlreadyExistsError,
    scaffold_library,
)
from ide_sync import sync_ide
from repo_layout import ROOT
from shared import install_editable


def _scaffold_library(name: str, *, workbench: bool = False) -> int:
    """Create the directory structure and template files for a new package.

    Delegates to :func:`chumicro_workspace.scaffold.scaffold_library`.
    A device library lands under the mono-repo's ``libraries/`` parent;
    *workbench=True* scaffolds a host-only CPython tool under
    ``workbench/`` instead (workbench-flavored pyproject + docs, no
    Runner pattern).  Same parent/kind split the workspace CLI's
    ``new --library`` / ``new --workbench`` uses.  Passes
    ``CHUMICRO_BRANDING`` so the emitted package points at the ChuMicro
    repos, bundle, and docs site where these libraries actually live
    (the workspace CLI leaves the neutral, self-owned default for
    downstream users).  Returns 0 on success, 1 when the target already
    exists.
    """
    package_kind = "workbench" if workbench else "library"
    target_dir = ROOT / ("workbench" if workbench else "libraries")
    try:
        created = scaffold_library(
            target_dir, name, package_kind=package_kind,
            branding=CHUMICRO_BRANDING,
        )
    except LibraryAlreadyExistsError as exception:
        print(f"Directory already exists: {exception}")
        return 1
    # The sdist gate requires every package to carry the canonical
    # license text; the shared scaffolder can't do this because a
    # downstream workspace has no ChuMicro root LICENSE to copy.
    (created / "LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
    print(f"Created {created.relative_to(ROOT)}/")
    return 0


def new_library(name: str, *, workbench: bool = False) -> int:
    """Scaffold a new package and regenerate IDE configs.

    Args:
        name: Package short name (e.g. ``"gpio"``).
        workbench: Scaffold a host-only workbench tool under
            ``workbench/`` instead of a device library under
            ``libraries/``.
    """
    result = _scaffold_library(name, workbench=workbench)
    if result != 0:
        return result

    result = install_editable()
    if result != 0:
        return result

    return sync_ide()
