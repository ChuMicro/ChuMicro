# chumicro-workspace-runtime

Host-side runtime for ChuMicro project workspaces. Implements the deploy-time config-merge pipeline (workspace defaults + per-thing config + secrets → `/runtime_config.msgpack`) per [Decision 0035](../../plans/decisions/0035-runtime-config-structure.md), the per-library template collection per [Decision 0036 §5](../../plans/decisions/0036-chumicro-config-library.md), and the workspace command dispatch ([Decision 0029](../../plans/decisions/0029-project-workspace.md)).

> **Workbench package** — runs on CPython only; never lands on a microcontroller. Consumed by the `run.py` shim a workspace ships.

## Status

Phase 4a in flight. Slice 0 (this commit) ships the config-merge core (`merge_configs`, `resolve_secrets`, file IO for workspace.yml + thing config + secrets.yml + msgpack output). Subsequent slices add command dispatch, three-zone yaml writer, onboarding flows, firmware URL derivation, and the import-graph resolver per [`plans/workstreams/project-workspace.md`](../../plans/workstreams/project-workspace.md) Phase 4a.

## Public API (Slice 0)

```python
from chumicro_workspace_runtime import (
    merge_configs,           # workspace_dict + thing_dict + secrets_dict -> merged_dict
    resolve_secrets,         # walk a value, replace !secret <name> refs from a secrets dict
    read_workspace_yaml,     # parse workspace.yml -> dict
    read_thing_config,       # parse things/<name>/config.{toml,yml} -> dict
    read_secrets_yaml,       # parse secrets.yml -> dict
    write_runtime_config,    # write merged dict to /runtime_config.msgpack-shaped file
    build_runtime_config,    # convenience: read all four sources + write
)
```

## Developing this library

```bash
python scripts/run.py test --libraries workspace-runtime
python scripts/run.py lint
```
