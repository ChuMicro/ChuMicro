# Decision 0057: Workspace-config file shape — `workspace.yml` machinery vs `secrets.toml` device-bound vs per-project `project_config.toml`

Status: `accepted`
Date: `2026-05-04`
Related: Decision 0029 (project workspace — three-zone shape), Decision 0030 (config-and-state — host TOML / device msgpack split), Decision 0035 (runtime-config structure — section-namespaced shape, original `!secret` introduction in §5), Decision 0036 (`chumicro-config` library — flat-key `RuntimeConfig` + `from_config`/`load_section`), Decision 0038 (workspace bootstrap via clone — gitignored files materialised on first setup), Decision 0055 (config pipeline unification).

## Context

Decision 0035 §5 introduced a `!secret <name>` marker pattern + a flat `secrets.yml` key store as the credential mechanism for the runtime-config pipeline.  The marker came from Home Assistant — HA users routinely paste their `configuration.yaml` on community forums for help, so they need a way to commit a config with credentials redacted to a placeholder.

Neither of our two consumer repos has that problem:

- **The mono-repo** (`chumicro/`) workspace's host config is a single contributor's dev config; it isn't shared on forums or committed as a teaching artifact.
- **A workspace-template-derived workspace** lives in *the user's* private project repo.  The starter shape ships from github.com/ChuMicro/ChuMicro-Workspace-Template; the user's filled-in files are theirs.

We imported a pattern designed for a use case that doesn't apply here.  The cost was real: a custom string-prefix syntax, a recursive resolver, an `UnresolvedSecretError`, doctor-level checks, recovery hints, and a flat-key file with vocabulary distinct from the section-namespaced configs that referenced it.

The marker existed precisely to bridge a *committed-shape file* and *uncommitted values*.  When the schema-bearing file is itself gitignored, that bridge has nothing to span — and the mechanism falls away with it.

The shape evolved further during the config-shape-beginner-ergonomics workstream.  The user's audit (2026-05-06) flagged that lumping workspace machinery (`library_sources`, `deploy_targets`, `quality`) and device-bound credentials (wifi password, broker auth) into a single `workspace.yml` made the file's name misleading: a beginner reading "workspace.yml" expected layout / build / package config, not their wifi password.  The decision now describes the post-workstream three-file split.

## Decision

Three files carry the workspace's host-side config; each one's role is self-evident from its filename:

| Layer | Gitignore status | Purpose | Reaches a board? |
|---|---|---|---|
| `workspace.yml` | gitignored at the workspace root; materialised by `setup` from the canonical template (`chumicro_workspace.read_workspace_yml_template`) | **Workspace machinery** — `library_sources` (dev-mode editable overrides), `deploy_targets` (per-project → device mapping), `quality` (lint / coverage knobs), future `environments` block. | **No.**  Host-only. |
| `secrets.toml` | gitignored at the workspace root; materialised on first `setup` from `chumicro_workspace.read_secrets_toml_template`.  Real placeholder values (`replace-with-your-...`) so the parser round-trip preserves them and the additive setup re-apply path can append new keys without losing data | **Workspace-wide credentials + device defaults** — wifi `[wifi] ssid = ...`, MQTT `[mqtt.broker] host = ...`, anything else that should flow into every project's `runtime_config.msgpack`. | **Yes** — flows through `compose_runtime_config` to the device. |
| `<project>/project_config.toml` | Gitignored when scaffolded by `chumicro-workspace new`.  Tracked when shipped with a workspace-template repo (`projects/_template/`, example projects, etc.) — gitignore patterns don't untrack already-tracked files.  `find_project_config` accepts the legacy filename `config.toml` as a fallback so user-edited workspaces from before the rename keep working | **Per-project knobs** that override the secrets defaults at any nesting depth.  Same nested-table TOML shape as `secrets.toml`. | Yes — deep-merges over `secrets.toml`'s defaults. |

Pipeline: `compose_runtime_config(secrets_toml, project_config)` deep-merges the two device-bound layers via the `merge_configs` primitive, **flattens** the nested tables to dotted keys (`{"wifi": {"ssid": "x"}}` → `{"wifi.ssid": "x"}`), and writes the flat dict to the on-device msgpack.  The flat shape gives the device-side reader one hash lookup per access on a 256 KB-RAM target.

No `!secret` marker, no resolver, no `UnresolvedSecretError`, no flat-key `secrets.yml`.

Schema-as-documentation is delivered by the template, not a tracked file: a fresh clone runs `setup`, gets a materialised `secrets.toml` with real placeholder keys (`[wifi] ssid = "replace-with-your-ap-ssid"`), and edits them in place.  Same documentation benefit without paying the file-split cost the marker / overlay approaches forced.  `chumicro-workspace setup` runs an additive re-apply pass after materialisation: when the upstream template gains a new key the user doesn't have, it's appended to the user's file in place — comments preserved, existing values untouched (Strategy C of `setup-schema-reconciliation.md`).

## Rejected alternatives

- **Keep `!secret` markers in the workspace template.**  Loses the symmetry of one shape across both repos; forces the workspace-template's documentation surface to keep teaching the marker for a use case its actual users don't have either.
- **Tracked `workspace.yml` + a gitignored overlay file (`workspace.local.yml`) for credentials.**  Re-pays the marker's cost in a different shape: a contributor still edits two files for one logical thing (their wifi network — SSID committed, password gitignored).  The split exists only to preserve "schema as documentation," which the starter already delivers.
- **Environment variables (`${WIFI_PASSWORD}` interpolation).**  Microcontroller-deploying users typically don't run from a shell with persistent env vars; they'd need a `.env` file, which is `secrets.toml` reinvented under a different name with the same custom-interpolation cost.
- **One file for everything (the original Decision 0057 shape — `workspace.yml` carrying both machinery and credentials).**  Reads correctly: every field in it is either a credential or a workspace-wide default, none of it actually "workspacey" — a beginner sees their wifi password under a name that suggests build / package config.  The split makes each filename match its file's actual role.
- **Per-project credential override file (`projects/<name>/config.local.<suffix>`).**  YAGNI — solves a hypothetical "user with two wifi networks across projects" that hasn't surfaced.  Re-introduce if it does.
- **Tracked `workspace.yml` + a per-machine override outside the workspace** (e.g. `~/.config/chumicro/workspace.local.yml`).  Adds a "where does my config live" question across the workspace boundary; doesn't compose with multiple workspaces under one user account.
- **CircuitPython `settings.toml` integration.**  CP's own `settings.toml` lives at `/settings.toml` on the device and is read by `os.getenv()`.  Bridging it (e.g. falling back from `chumicro-config` to `os.getenv` when a key is missing from the msgpack) was considered and rejected: a user setting `CIRCUITPY_WIFI_SSID` there gets CP's auto-connect supervisor competing with `chumicro-wifi`, which is exactly the conflict `chumicro-wifi`'s sole-supervisor model rules out.  Surface that conflict explicitly rather than absorb it.

## Consequences

- **One filename per role.**  `workspace.yml` is host-only machinery, `secrets.toml` is device-bound credentials and defaults, `project_config.toml` is per-project knobs.  Each filename matches its file's actual role; no beginner has to read docs to know where their wifi password belongs.
- **Same gitignored guarantee.**  Both `workspace.yml` and `secrets.toml` at the workspace root are gitignored; credentials never reach git.  The on-device `runtime_config.msgpack` carries only the resolved values (and even those land via the gitignored `_generated/` output dir).
- **DRY-across-projects benefit preserved.**  A wifi password set once under `[wifi] password = ...` in `secrets.toml` flows to every project that consumes the wifi keys.  This was the load-bearing benefit Decision 0035 §5 cited and it's preserved unchanged; the workspace-defaults layer has always been the mechanism, not the marker.
- **Setup re-apply is additive-only.**  When the upstream starter gains a new key, `setup` appends it to the user file in place — comments preserved, existing values untouched.  Strategy C of `setup-schema-reconciliation.md` is the canonical contract per the user's Q10 direction in the config-shape workstream.
- **Hard breaking change; no compat shim.**  Any pre-existing workspace must move credentials from `workspace.yml`'s `defaults:` block into a new `secrets.toml` (nested TOML tables instead of nested YAML mappings), and rename per-project `config.toml` to `project_config.toml` (or leave as `config.toml` — `find_project_config` accepts both).  Both repos are sole-developer at the time of this change; the no-shim trade-off is acceptable for that audience.
