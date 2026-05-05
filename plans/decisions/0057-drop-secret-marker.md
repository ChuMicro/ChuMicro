# Decision 0057: Drop `!secret` marker; gitignored credentials live in `workspace.local.yml` as a structural overlay

Status: `accepted`
Date: `2026-05-04`
Related: Decision 0029 (project workspace — three-zone shape), Decision 0030 (config-and-state — host TOML / device msgpack split), Decision 0035 (runtime-config structure — section-namespaced shape, original `!secret` introduction in §5), Decision 0036 (`chumicro-config` library — `load_runtime_config` + `load_section`), Decision 0038 (workspace bootstrap via clone — gitignored secrets file materialised on first setup), Decision 0055 (config pipeline unification — Phase 4.5a follow-up flagged this work explicitly).

## Context

Decision 0035 §5 introduced the `!secret <name>` marker pattern and the gitignored `secrets.yml` flat key store as the credential-management mechanism for the runtime-config pipeline.  The marker was a string prefix in any TOML / YAML config file; `chumicro_workspace.secrets.resolve_secrets` walked the merged config dict and substituted any matching strings against `secrets.yml`'s flat `key: value` map before writing the on-device `runtime_config.msgpack`.

The pattern came from Home Assistant, where it earned its keep: HA users routinely paste their `configuration.yaml` on community forums for help, so they needed a way to share / commit configs with credentials redacted to a placeholder.  The marker tells the resolver "the value lives elsewhere; here's the lookup name."

Neither of our two consumer repos has that problem:

- **The mono-repo** (`chumicro/`) workspace.yml is a single contributor's dev config; it isn't shared on forums or committed as a teaching artifact.
- **A workspace-template-derived workspace** lives in *the user's* private (or rarely-public-and-curated) project repo.  The `_workspace_template/` carrying the *shape* is what ships on github.com/ChuMicro/ChuMicro-Workspace-Template; the user's filled-in workspace.yml is theirs.

We imported a pattern designed for a use case that doesn't apply to either consumer.  The cost was real: a custom string-prefix syntax, a recursive resolver module, an `UnresolvedSecretError` exception, doctor-level checks for unresolved references, recovery-hint patterns matched against runtime tracebacks of unresolved markers, plus a flat-key secrets file with vocabulary distinct from the section-namespaced config files it's referenced from.  Decision 0055's Phase 4.5a follow-up flagged the over-engineering directly: *"the user has flagged that the `!secret <name>` indirection may be over-engineered for the mono-repo's contributor wifi creds for functional tests use case."*

## Decision

The `!secret` marker is retired.  Gitignored credentials and per-developer overrides live in a `workspace.local.yml` file with the same section-namespaced shape as `workspace.yml`, deep-merged on top as one more layer in the runtime-config pipeline.

### 1. Merge precedence (lowest → highest)

The deployer reads four sources and deep-merges them in this order:

1. `workspace.yml` (committed; workspace-wide defaults)
2. `workspace.local.yml` (gitignored; per-developer credential / config overlay)
3. `projects/<name>/config.toml` (committed; per-project config — for the mono-repo, "project" = a library's `functional_tests/` directory)
4. `projects/<name>/config.local.toml` (gitignored, optional; per-project credential override for the rare case where one project needs different creds)

All four layers carry the same shape (section-namespaced dict).  The merge is the existing `chumicro_workspace.merge.merge_configs` deep-merge — no new primitive, no marker resolution step.  Any key set in a higher-precedence layer wins at any nesting depth.

### 2. `secrets.yml`, `!secret`, `chumicro_workspace.secrets`, and `UnresolvedSecretError` are removed

The retired surface:

- `chumicro_workspace.secrets` module (resolver function, exception class) — deleted.
- `chumicro_workspace.secrets_yml_starter` module (canonical `secrets.yml` starter content reader) — deleted; replaced by `workspace_local_yml_starter` carrying the new structural-overlay starter.
- `_payloads/secrets_yml/starter.yml.template` — deleted; replaced by `_payloads/workspace_local_yml/starter.yml.template`.
- `read_secrets_yaml`, `resolve_secrets`, `read_secrets_yml_starter`, `UnresolvedSecretError` exports — removed from `chumicro_workspace`'s public API.
- `WorkspaceLayout.secrets_yaml` property — renamed to `workspace_local_yaml`.
- `health.check_secrets_yaml` and `health.check_secret_references` — replaced by `check_workspace_local_yaml` (a lighter check: parses cleanly, reports section count).  `SECRET_PLACEHOLDER` constant — gone.
- `recovery._HINT_TABLE` — `unresolved-secret` pattern removed; `missing-config-key` hint now mentions `workspace.local.yml` as a place to check.
- `WithRuntimeConfig` / `project_directory_source` / `project_boot_source` / `project_boot_with_import_graph_source` / `project_import_graph_source` — `secrets_yaml=` keyword renamed to `workspace_local_yaml=`.
- `compose_runtime_config` / `build_runtime_config` — same kwarg rename.

### 3. Workspace-template tooling

`chumicro_workspace.template_apply._WORKBENCH_STARTERS` ships `workspace.local.yml` (from the workbench-owned starter) instead of `secrets.yml`.  `chumicro_workspace.template_zones` lists `workspace.local.yml` as a user-owned path (init writes if missing; update never touches).  Mono-repo's `scripts/generate_config_files.py` materialises `workspace.local.yml` from `chumicro_workspace.read_workspace_local_yml_starter`.

### 4. Mono-repo `.gitignore` carries one cycle of legacy guard

The retired `secrets.yml` filename stays in `.gitignore` for one cycle so contributors with a left-over copy from the pre-0057 era don't accidentally commit it.  Same defensive pattern Decision 0055 applied to `chumicro-dev-config.toml`.  New entries: `workspace.local.yml`, plus `**/config.local.{toml,yml,yaml}` patterns under `projects/` and per-library `functional_tests/`.

## Rejected alternatives

### A. Drop `!secret` only in the mono-repo; keep it in the workspace-template

Walks back §5 of Decision 0035 only partially.  Loses the symmetry of one shape across both repos and forces the workspace-template's documentation surface to keep teaching the marker — including the `chumicro_workspace.secrets` module, `UnresolvedSecretError`, doctor checks, recovery-hint patterns, and the dedicated flat-key file format — for a use case that doesn't apply to its actual users either.

### B. Just gitignore `workspace.yml` itself (no overlay file)

Materialise `workspace.yml` from a committed `workspace.yml.template` on first setup; users edit the gitignored file freely.  Rejected because it loses the *committed schema as documentation* benefit: anyone reading the repo today sees `workspace.yml` and knows what shape the workspace-wide defaults take.  An overlay preserves that benefit at the cost of one more file.

### C. Use environment variables (`${WIFI_PASSWORD}` interpolation)

The 12-factor pattern.  Rejected because microcontroller-deploying users typically don't run their dev workflows from a shell with persistent env vars; they'd need a `.env` file, which is just `secrets.yml` reinvented under a different name with the same custom interpolation syntax to maintain.

## Consequences

- **Smaller surface to learn.** One vocabulary (deep-merged section-namespaced dicts) covers every config layer.  No `!secret` marker syntax, no resolver, no `UnresolvedSecretError`, no flat-key file.
- **Same gitignored-credentials guarantee.** Credentials live in `workspace.local.yml` and never reach git.  The on-device `runtime_config.msgpack` carries only the resolved values, same as before.
- **Same DRY-across-projects benefit.** A wifi password set once under `defaults.wifi.password` in `workspace.local.yml` flows to every project that consumes the `wifi` section — one place to update, multiple consumers.  This was the load-bearing benefit Decision 0035 §5 cited and it's preserved unchanged; the workspace-defaults layer has always been the mechanism, not the marker.
- **Per-project credential override stays available** via `projects/<name>/config.local.<suffix>` (gitignored sibling of `config.toml`).  Same shape, same merge.  Rare in practice; documented for the case where one project needs different creds.
- **No migration code shipped.** Pre-0057 contributors with a populated `secrets.yml` need to manually re-shape their entries: `wifi_password: foo` becomes `defaults: { wifi: { password: foo } }` in the new `workspace.local.yml`.  Both repos are sole-developer at the time of this change; the migration is one paste per workspace.
- **Library `_templates/config.toml`** (the file `chumicro-workspace new` copies into a new project) drops the `password = "!secret wifi_password"` line and gains a comment pointing the user at `workspace.local.yml` for the credential-overlay flow.
- **Workspace-template-derived workspaces** that already shipped a `secrets.yml` keep working until a new `setup` cycle materialises `workspace.local.yml`; users with credentials in both files get the structural-overlay value (the new merge layer) winning.  The legacy `secrets.yml` is silently ignored (no longer read) — gitignored, so no commit risk, and the user can delete it once they've migrated.
- **Net code change:** ~250 LOC deleted (resolver module, secrets-yml starter module + payload, two health-check functions, one recovery-hint pattern, two test files, dozens of `secrets_yaml=` kwargs across boot_shim / deploy_source / import_graph / cli) vs ~150 LOC added (workspace_local_yml starter module + payload, one health-check function, updated tests for the structural overlay including a `config.local` round-trip test).
