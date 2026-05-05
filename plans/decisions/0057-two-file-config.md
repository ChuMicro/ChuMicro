# Decision 0057: Two-file workspace config — drop `!secret` marker; gitignored `workspace.yml` + per-project `config.toml`

Status: `accepted`
Date: `2026-05-04`
Related: Decision 0029 (project workspace — three-zone shape), Decision 0030 (config-and-state — host TOML / device msgpack split), Decision 0035 (runtime-config structure — section-namespaced shape, original `!secret` introduction in §5), Decision 0036 (`chumicro-config` library — `load_runtime_config` + `load_section`), Decision 0038 (workspace bootstrap via clone — gitignored files materialised on first setup), Decision 0055 (config pipeline unification).

## Context

Decision 0035 §5 introduced a `!secret <name>` marker pattern + a flat `secrets.yml` key store as the credential mechanism for the runtime-config pipeline.  The marker came from Home Assistant — HA users routinely paste their `configuration.yaml` on community forums for help, so they need a way to commit a config with credentials redacted to a placeholder.

Neither of our two consumer repos has that problem:

- **The mono-repo** (`chumicro/`) workspace.yml is a single contributor's dev config; it isn't shared on forums or committed as a teaching artifact.
- **A workspace-template-derived workspace** lives in *the user's* private project repo.  The `_workspace_template/` carrying the *shape* ships from github.com/ChuMicro/ChuMicro-Workspace-Template; the user's filled-in `workspace.yml` is theirs.

We imported a pattern designed for a use case that doesn't apply here.  The cost was real: a custom string-prefix syntax, a recursive resolver, an `UnresolvedSecretError`, doctor-level checks, recovery hints, and a flat-key file with vocabulary distinct from the section-namespaced configs that referenced it.

The marker existed precisely to bridge a *committed-shape file* and *uncommitted values*.  When the schema-bearing file is itself gitignored, that bridge has nothing to span — and the mechanism falls away with it.

## Decision

The runtime-config pipeline is two gitignored layers, deep-merged, sharing the same section-namespaced shape:

| Layer | Gitignore status | Purpose |
|---|---|---|
| `workspace.yml` | gitignored; materialised by `setup` from a workbench-owned starter (`chumicro_workspace.read_workspace_yml_starter`), or from a repo-specific `_workspace_template/workspace.yml` override when one exists | Workspace-wide defaults *and* credentials in one place.  Contributor / user fills in real values; never committed. |
| `projects/<name>/config.toml` | gitignored when scaffolded by `chumicro-workspace new`.  Tracked when shipped with a workspace-template repo (`projects/_template/`, example projects, etc.) — gitignore patterns don't untrack already-tracked files. | Per-project knobs.  User-authored projects keep their config.toml private; example/scaffold copies that ship with the template stay tracked. |

Pipeline: `compose_runtime_config(workspace_yaml, project_config)` deep-merges the two layers via the same `merge_configs` primitive every other layer uses.  No `!secret` marker, no resolver, no `UnresolvedSecretError`, no flat-key `secrets.yml`.

Schema-as-documentation is delivered by the starter, not a tracked file: a fresh clone runs `setup`, gets a materialised `workspace.yml` with commented schema inline, and edits it.  Same documentation benefit without paying the file-split cost the marker / overlay approaches forced.

## Rejected alternatives

- **Keep `!secret` markers in the workspace template.**  Loses the symmetry of one shape across both repos; forces the workspace-template's documentation surface to keep teaching the marker for a use case its actual users don't have either.
- **Tracked `workspace.yml` + a gitignored overlay file (`workspace.local.yml`) for credentials.**  Re-pays the marker's cost in a different shape: a contributor still edits two files for one logical thing (their wifi network — SSID committed, password gitignored).  The split exists only to preserve "schema as documentation," which the starter already delivers.
- **Environment variables (`${WIFI_PASSWORD}` interpolation).**  Microcontroller-deploying users typically don't run from a shell with persistent env vars; they'd need a `.env` file, which is `secrets.yml` reinvented under a different name with the same custom-interpolation cost.
- **Per-project credential override file (`projects/<name>/config.local.<suffix>`).**  YAGNI — solves a hypothetical "user with two wifi networks across projects" that hasn't surfaced.  Re-introduce if it does.
- **Tracked `workspace.yml` + a per-machine override outside the workspace** (e.g. `~/.config/chumicro/workspace.local.yml`).  Adds a "where does my config live" question across the workspace boundary; doesn't compose with multiple workspaces under one user account.

## Consequences

- **One file for one logical thing.**  Wifi credentials live in `workspace.yml`; one place to set, one place to update.
- **Same gitignored guarantee.**  `workspace.yml` is gitignored; credentials never reach git.  The on-device `runtime_config.msgpack` carries only the resolved values.
- **Same DRY-across-projects benefit.**  A wifi password set once under `defaults.wifi.password` flows to every project that consumes the `wifi` section.  This was the load-bearing benefit Decision 0035 §5 cited and it's preserved unchanged; the workspace-defaults layer has always been the mechanism, not the marker.
- **Per-repo customisation hook.**  A repo's `_workspace_template/workspace.yml` (when present) overrides the workbench's minimal starter — the mono-repo uses this to ship its specific opinions (`mqtt.broker.host = test.mosquitto.org`, `wifi.ssid` placeholder) while a fresh workspace-template-derived workspace gets the workbench starter as-is.
- **Hard breaking change; no compat shim.**  Any pre-existing workspace must drop every `!secret` reference and move values from the old `secrets.yml` into the gitignored `workspace.yml` under section-namespaced paths (`wifi_password: foo` → `defaults: { wifi: { password: foo } }`).  Both repos are sole-developer at the time of this change; the no-shim trade-off is acceptable for that audience.
