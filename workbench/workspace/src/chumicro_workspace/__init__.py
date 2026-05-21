"""Host-side runtime for ChuMicro project workspaces.

Combines:

* **Config merge**: ``secrets.toml`` (workspace-wide credentials and
  device defaults) and per-project ``project_config.toml`` deep-merge
  into ``/runtime_config.msgpack``.  Both inputs are gitignored and
  share a ``[section]``-keyed TOML layout.
* **Deploy integration**: :class:`~chumicro_workspace.deploy_source.WithRuntimeConfig`
  and the ``project_*_source`` helpers compose with ``chumicro-deploy``'s
  ``FileSource``\\ s so a single ``Deployer.deploy_diff(...)`` call ships
  app code, the merged config, and an optional boot shim in one shot.
* **``devices.yml`` round-trip**: three-zone writer (USER_OWNED /
  HARDWARE_ONCE / PROBED_ALWAYS), owned by ``chumicro-deploy``.
* **Onboarding**: board-state detection, firmware URL derivation
  (CP S3 listing plus MP curated machine-to-BOARD map).
* **Init / update**: clone the workspace template repo and re-flow
  tool-owned files.
* **CLI dispatch**: :func:`chumicro_workspace.cli.main` powers the
  ``chumicro-workspace`` entry-point and the workspace ``run.py`` shim.

Package-root surface (``__all__`` below) is intentionally narrow.
It exposes the :class:`WorkspaceLayout` type and the few helpers
sibling packages reach for through the root::

    from chumicro_workspace import (
        WorkspaceLayout,             # workspace path resolution + project tree
        compose_runtime_config,      # functional-test config merge
        read_workspace_yml_template, # workspace.yml template content
        read_devices_yml_template,   # devices.yml template content
        verify_examples,             # AST-based example verifier
    )

Everything else lives in submodules (``chumicro_workspace.deploy_source``,
``chumicro_workspace.pipeline``, ``chumicro_workspace.config_manifest``,
``chumicro_workspace.workspace`` for :data:`ENTRY_POINT_FILENAMES` /
:class:`ProjectClassification`, etc.) and stays reachable via explicit
submodule imports.

Workbench-only: runs on CPython, never lands on a
microcontroller.  Workbench tools and the workspace's ``run.py``
shim consume this package.  The on-device counterpart is
``chumicro-config``.
"""

from chumicro_workspace.example_verify import verify_examples
from chumicro_workspace.pipeline import compose_runtime_config
from chumicro_workspace.templates import (
    read_devices_yml_template,
    read_workspace_yml_template,
)
from chumicro_workspace.workspace import (
    ProjectClassification,
    WorkspaceLayout,
    WorkspaceNotFoundError,
)

#: Re-exported sibling-package surface.
__all__ = [
    "ProjectClassification",
    "WorkspaceLayout",
    "WorkspaceNotFoundError",
    "compose_runtime_config",
    "read_devices_yml_template",
    "read_workspace_yml_template",
    "verify_examples",
]
