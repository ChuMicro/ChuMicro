# Workstream: Workspace library curation — chumicro-workspace as library host

Status: `proposed` — surfaced 2026-05-12 during the DI audit (Tier 2 follow-up to [Decision 0062](../decisions/0062-entrypoint-factory-skip.md)).  Not yet started.

## Purpose

Today's chumicro library distribution leans on `mip` (MicroPython) and `circup` (CircuitPython) for on-device installs.  Both install package.json deps recursively with no `--no-deps` flag (bench-verified 2026-05-12 against `mpremote/mip.py` and `circup/commands.py`), and our `scripts/bundle_manager.py` emits chumicro deps into the manifests.  Standalone consumers cannot opt out of installing the chumicro stack on the device — only chumicro-workspace users going through the AST walker get any control.

Layer FAT-stability concerns on top: `mip`/`circup` write files to `CIRCUITPY` through the host filesystem, which has been a recurring source of wedges (Decision 0033) that we now work around in chumicro-workspace via rsync + auto-reload toggling.  Two tools with separate failure modes are harder to support than one tool we control.

Direction: chumicro-workspace becomes the library host for chumicro libraries.  Curated libraries land in the user's workspace `libraries/<name>/` folder (a feature chumicro-workspace already supports for local development).  The deploy walker (Decision 0029) treats them identically to mono-repo libraries — same import-graph rules, same opt-out mechanism via [Decision 0062](../decisions/0062-entrypoint-factory-skip.md), same FAT-safe deploy path.

`mip`/`circup` remain supported for users who prefer them, but the chumicro-workspace happy path uses neither.

## Scope

### Phase 1 — Snapshot distribution channel

Decide the source-of-truth shape for "full library content" (src + tests + examples + docs), then ship the publish pipeline.

Three options surveyed:

- **A. New `ChuMicro/ChuMicro-Library-Snapshots` repo** — per-version archives.  Highest maintenance overhead, cleanest archival semantics.
- **B. Pull from `ChuMicro/ChuMicro` main repo at tag / commit** — zero new infrastructure, agile, GitHub-rate-limit-bound.
- **C. Full subtree alongside `mpy6/` in the existing Bundle repos** — single repo, single publish step; mixes runtime artifacts with development assets but keeps one channel discovery surface.

User leans **C** ("full subtree makes more sense").  Implementation:

- Extend `bundle_manager.py` to stage a `full/<lib>/` tree per library with src + tests + examples + docs.
- Bundle repos gain three top-level dirs per release: `<lib>/` (the existing `.py` source), `mpy6/<lib>/` (existing .mpy), `full/<lib>/` (new — the snapshot).
- Stable channel: `ChuMicro-Bundle`.  Experimental: `ChuMicro-Bundle-Experimental`.  Channel-switch is a chumicro-workspace command, not a repo change.

### Phase 2 — `chumicro-workspace library` CLI surface

```
chumicro-workspace library list                      # available + installed + version + channel
chumicro-workspace library add <name> [--channel main|stable|experimental] [--version <pin>]
chumicro-workspace library update [<name>]           # respects pin if set
chumicro-workspace library remove <name>             # warns if other libs depend on it
chumicro-workspace library switch-channel <name> <channel>
```

Dependency resolution: `library add` reads the target library's `pyproject.toml` and recursively pulls `chumicro-*` deps.  Before pulling the transitive set, prompts the user with the dep tree so they can deselect (e.g. omit `chumicro-sockets` because they're injecting a custom transport — paired with `__chumicro_skip_factories__` in the entrypoint per Decision 0062).

Pin state lives in `workspace.yml` under a new `libraries:` table:

```yaml
libraries:
  chumicro_mqtt:
    channel: stable
    version: "0.8.0"
  chumicro_sockets:
    channel: stable
    version: "0.4.0"
```

`main` channel pins to a commit SHA (reproducibility); `stable` and `experimental` pin to VERSION tags.

### Phase 3 — Non-chumicro upstreams (Adafruit, micropython-lib)

Separate ADR-worthy decision: write a thin `BundleGrabber` that knows the Adafruit-Bundle and micropython-lib shapes, or wrap `mip`/`circup` as subprocesses for non-chumicro libs only.

Recommend deferring this phase until Phase 2 lands and we see whether real workspaces actually need non-chumicro libs delivered through the same channel.  The mono-repo's libraries already cover the common cases (mqtt, ntp, requests, http_server, websockets, sockets, timing, config, kvstore, msgpack, runner, wifi); the typical workspace may never need to reach beyond them.

### Phase 4 — Examples + tests from curated libs

Once `libraries/<name>/` contains examples + tests on the user's disk:

```
chumicro-workspace library run-example <lib> <example-name>
chumicro-workspace library test <lib> [--on-device <id>]
```

Both extend existing chumicro-workspace machinery (`deploy` + `pytest-device`).  Small scope; defer until Phases 1-2 land.

## Open design questions

1. **Snapshot channel: A vs B vs C?** User-confirmed lean: C.  Confirm by sketching the `bundle_manager.py` change and a sample `ChuMicro-Bundle/full/chumicro_mqtt/` tree before committing.
2. **Pin-state location?** Recommend `workspace.yml` `libraries:` table.  Confirm before writing the CLI.  Alternative: separate `libraries.yml` if `workspace.yml` gets crowded.
3. **Default channel for `library add`?** Recommend `stable` for workspace-template users (they're typically beginners); `main` for developers tracking HEAD.  Switch via flag.
4. **Deny-list behavior on transitive deps.** When the user declines a transitive dep at `library add` time, do we (a) refuse the install and tell them what to do, (b) install with the dep marked as "user-declined" in workspace.yml so future updates respect it, or (c) just trust the user and install without the dep, letting runtime errors surface?  Recommendation: (b) — explicit state, no surprises, plays well with Decision 0062's skip mechanism.

## Out of scope

- **`__chumicro_skip_factories__` mechanism itself** — covered by [Decision 0062](../decisions/0062-entrypoint-factory-skip.md).
- **Duck-typed factory contract clarification** — separate ADR (planned 0063).
- **mip/circup deprecation** — both stay supported indefinitely.  This workstream provides an alternative, not a replacement.

## Acceptance

Phase 1: bundle generator emits `full/<lib>/` trees; one end-to-end test pulls from the staged bundle into a workspace `libraries/<lib>/` and the result runs.

Phase 2: `chumicro-workspace library add chumicro_mqtt` works from a fresh workspace, resolves deps, prompts for transitive set, lands all four files (mqtt + sockets + timing + config) in `libraries/`, and `chumicro-workspace deploy` ships the right subset per Decision 0062's skip mechanism.

Phase 3 + 4: deferred.  Trigger conditions:
- Phase 3 fires when a user asks for an Adafruit / mp library through `library add` (real demand, not hypothetical).
- Phase 4 fires when Phase 2 has been used in anger for one release cycle and the "run example from curated lib" workflow has surfaced friction.
