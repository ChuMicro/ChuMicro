"""Scaffold + update tool for ChuMicro project workspaces.

Public API::

    from chumicro_workspace_template import (
        init,                     # lay down a fresh workspace
        update,                   # refresh the tool-owned slice
        default_template_root,    # path to the built-in template payload
        ApplyReport,              # per-file action log returned by init/update
        Zone,                     # three-zone classification enum
        classify,                 # path -> Zone
    )

Workbench-only — runs on CPython only.  See Decision 0029 §4 (Phase 4b)
for the workstream context and Decision 0032 for the workbench-package
pattern.
"""

from chumicro_workspace_template.apply import (
    ApplyAction,
    ApplyReport,
    default_template_root,
    init,
    update,
)
from chumicro_workspace_template.manifest import Zone, classify

__all__ = [
    "ApplyAction",
    "ApplyReport",
    "Zone",
    "classify",
    "default_template_root",
    "init",
    "update",
]
