"""Library scaffolding — thin wrapper over `chumicro_workspace.scaffold`.

`python scripts/run.py new-library <name>` calls
:func:`new_library` here, which composes the workbench
scaffolder with mono-repo-only follow-ups: editable-install
of the new package + IDE config sync.

External users developing their own chumicro-style libraries
get the same scaffolder via
``python run.py new --library <name>`` (the workspace CLI's
library mode); they don't need this script's editable-install
+ IDE sync because their workspace's `setup` already handles
those.
"""

from __future__ import annotations

from chumicro_workspace.scaffold import (
    LibraryAlreadyExistsError,
    scaffold_library,
)
from ide_sync import sync_ide
from repo_layout import ROOT
from shared import install_editable


def _scaffold_library(name: str) -> int:
    """Create the directory structure and template files for a new library.

    Delegates to :func:`chumicro_workspace.scaffold.scaffold_library`
    with the mono-repo's ``libraries/`` parent.  Returns 0 on
    success, 1 when the target already exists.
    """
    target_dir = ROOT / "libraries"
    try:
        created = scaffold_library(target_dir, name)
    except LibraryAlreadyExistsError as exception:
        print(f"Directory already exists: {exception}")
        return 1
    print(f"Created {created.relative_to(ROOT)}/")
    return 0


def new_library(name: str) -> int:
    """Scaffold a new library under libraries/ and regenerate IDE configs.

    Args:
        name: Library short name (e.g. ``"gpio"``).
    """
    result = _scaffold_library(name)
    if result != 0:
        return result

    result = install_editable()
    if result != 0:
        return result

    return sync_ide()
