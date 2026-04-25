"""Host-side runtime for ChuMicro project workspaces.

Phase 4a Slice 0 surface — the deploy-time config-merge pipeline
per Decision 0035 (workspace defaults + per-thing config + secrets
→ ``/runtime_config.msgpack``).  Subsequent slices add command
dispatch, three-zone YAML writer, onboarding flows, firmware URL
derivation, import-graph resolver per
``plans/workstreams/project-workspace.md`` Phase 4a.

Public API::

    from chumicro_workspace_runtime import (
        build_runtime_config,    # end-to-end: read all sources, merge, write msgpack
        merge_configs,           # deep per-key merge of two or more dicts
        resolve_secrets,         # walk a value, replace !secret <name> refs
        read_workspace_yaml,     # parse workspace.yml -> defaults dict
        read_thing_config,       # parse things/<name>/config.{toml,yml,yaml} -> dict
        read_secrets_yaml,       # parse secrets.yml -> dict (empty when absent)
        write_runtime_config,    # write merged dict to msgpack at given path
        UnresolvedSecretError,   # !secret <name> resolved against missing key
        WorkspaceConfigError,    # YAML/TOML top-level shape malformed
    )

Workbench-only — runs on CPython only; never lands on a
microcontroller.  Workbench tools and scripts (the workspace's
``run.py`` shim) consume this package; the on-device side is
``chumicro-config`` (Decision 0036).
"""

from chumicro_workspace_runtime.loaders import (
    WorkspaceConfigError,
    read_secrets_yaml,
    read_thing_config,
    read_workspace_yaml,
)
from chumicro_workspace_runtime.merge import merge_configs
from chumicro_workspace_runtime.pipeline import build_runtime_config
from chumicro_workspace_runtime.secrets import UnresolvedSecretError, resolve_secrets
from chumicro_workspace_runtime.writer import write_runtime_config

__all__ = [
    "UnresolvedSecretError",
    "WorkspaceConfigError",
    "build_runtime_config",
    "merge_configs",
    "read_secrets_yaml",
    "read_thing_config",
    "read_workspace_yaml",
    "resolve_secrets",
    "write_runtime_config",
]
