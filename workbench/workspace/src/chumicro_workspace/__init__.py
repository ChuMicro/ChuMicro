"""Host-side runtime for ChuMicro project workspaces.

Combines:

* **Config merge** — gitignored ``workspace.yml`` (defaults +
  credentials in one place) + per-project ``config.{toml,yml,yaml}``
  → ``/runtime_config.msgpack``.  Pure structural deep-merge; both
  layers are gitignored and share the section-namespaced shape.
* **Deploy integration** — :class:`~chumicro_workspace.deploy_source.WithRuntimeConfig`
  + the ``project_*_source`` helpers compose with ``chumicro-deploy``'s
  ``FileSource``\\ s so a single ``Deployer.deploy(...)`` call ships
  app code + the merged config + (optional) boot shim in one shot.
* **``devices.yml`` round-trip** — three-zone writer (USER_OWNED /
  HARDWARE_ONCE / PROBED_ALWAYS), owned by ``chumicro-deploy``.
* **Onboarding** — board-state detection, firmware URL derivation
  (CP S3 listing + MP curated machine→BOARD map).
* **Init / update** — clone the canonical workspace template repo
  and re-flow tool-owned files.
* **CLI dispatch** — :func:`chumicro_workspace.cli.main` powers the
  ``chumicro-workspace`` entry-point and the workspace ``run.py`` shim.

Package-root surface (``__all__`` below) is intentionally narrow —
just the central :class:`WorkspaceLayout` type and the few helpers
sibling packages reach for through the root::

    from chumicro_workspace import (
        WorkspaceLayout,             # workspace path resolution + project tree
        compose_runtime_config,      # functional-test config merge
        read_workspace_yml_template, # canonical workspace.yml content
        read_devices_yml_template,   # canonical devices.yml content
        verify_examples,             # AST-based example verifier
    )

Everything else lives in submodules (``chumicro_workspace.deploy_source``,
``chumicro_workspace.pipeline``, ``chumicro_workspace.config_manifest``,
etc.) and stays reachable via explicit submodule imports.

Workbench-only — runs on CPython only; never lands on a
microcontroller.  Workbench tools and the workspace's ``run.py``
shim consume this package; the on-device counterpart is
``chumicro-config``.
"""

from chumicro_workspace.example_verify import verify_examples
from chumicro_workspace.pipeline import compose_runtime_config
from chumicro_workspace.templates import (
    read_devices_yml_template,
    read_workspace_yml_template,
)
from chumicro_workspace.workspace import (
    ENTRY_POINT_FILENAMES,
    ProjectClassification,
    WorkspaceLayout,
    WorkspaceNotFoundError,
)

#: Narrow front-door surface — symbols sibling packages
#: (``libraries/*/functional_tests/conftest.py``, ``scripts/*``) reach for
#: via ``from chumicro_workspace import ...``.  Everything else is a
#: submodule reach; ``from chumicro_workspace.deploy_source import
#: WithRuntimeConfig`` etc. still works.
__all__ = [
    "ENTRY_POINT_FILENAMES",
    "ProjectClassification",
    "WorkspaceLayout",
    "WorkspaceNotFoundError",
    "compose_runtime_config",
    "read_devices_yml_template",
    "read_workspace_yml_template",
    "verify_examples",
]
