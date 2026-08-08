# Workstream: Workspace library curation — chumicro-workspace as library host

Status: `accepted` — Phases 1 + 2 **complete and validated** 2026-05-17 (sdist-content + build guard + PyPI fetch backend; then the `library` CLI: managed-block writer, `libraries:` table, dep resolver, six verbs incl. per-dep deselect + the Q4 remove/forget machine).  Acceptance met modulo one CI-gated residual (live-PyPI end-to-end — see Acceptance).  Phases 3 (non-chumicro upstreams) + 4 (`run-example`/`test`) stay **demand-gated by design** with explicit trigger conditions — not built, not blocking; this workstream is closed for active work and reopens only when a trigger fires.  Surfaced 2026-05-12 during the DI audit (Tier 2 follow-up to [Decision 0062](../../decisions/0062-entrypoint-factory-skip.md)); design fully resolved 2026-05-12.

## Purpose

Today's chumicro library distribution leans on `mip` (MicroPython) and `circup` (CircuitPython) for on-device installs.  Both install package.json deps recursively with no `--no-deps` flag (bench-verified 2026-05-12 against `mpremote/mip.py` and `circup/commands.py`), and our `scripts/bundle_manager.py` emits chumicro deps into the manifests.  Standalone consumers cannot opt out of installing the chumicro stack on the device — only chumicro-workspace users going through the AST walker get any control.

Layer FAT-stability concerns on top: `mip`/`circup` write files to `CIRCUITPY` through the host filesystem, which has been a recurring source of wedges (Decision 0033) that we now work around in chumicro-workspace via rsync + auto-reload toggling.  Two tools with separate failure modes are harder to support than one tool we control.

Direction: chumicro-workspace becomes the library host for chumicro libraries.  Curated libraries land in the user's workspace `libraries/<name>/` folder (a feature chumicro-workspace already supports for local development).  The deploy walker (Decision 0029) treats them identically to mono-repo libraries — same import-graph rules, same opt-out mechanism via [Decision 0062](../../decisions/0062-entrypoint-factory-skip.md), same FAT-safe deploy path.

`mip`/`circup` remain supported for users who prefer them, but the chumicro-workspace happy path uses neither.

## Scope

### Phase 1 — PyPI sdist as the source channel

Make the existing PyPI sdists carry full library content, then ship a fetch path that pulls one into `libraries/<name>/` and walks the dep graph.

Implementation:

- **Each library's `pyproject.toml`** — *landed*: `[tool.hatch.build.targets.sdist].only-include` set to `["src/", "VERSION", "README.md", "tests/", "examples/", "docs/"]` across all 15 libraries, each with a lockstep patch VERSION bump (sdist content is publish-affecting; `release.yml` auto-publishes each to `chumicro-<lib>-experimental`). (Started as `include`; switched to `only-include` to keep hatchling's sdist walker out of `site/`, `dist/`, `.cache/` and stop the parallel-preflight race with the `docs` phase.)
- **Build-time regression test** — *landed*: `scripts/sdist_content.py` runs inside `scripts/run.py build` and fails the build if any library sdist is missing `tests/`/`examples/`/`docs/` *or* if its `pyproject.toml` dropped the `[test]` extra (a curated consumer needs `chumicro-<lib>[test]` to run the shipped tests — shipping the files is necessary but not sufficient).
- **`chumicro_workspace.library` module** — *landed*: PyPI fetch backend (`fetch_library` + `channel_distribution` + `classify_pip_failure`).  `pip download --no-deps --no-binary :all:` (injected `subprocess_runner`), safe-extract the sdist (manual `..`/absolute-member rejection — `tarfile`'s `data` filter is 3.12+ and this package targets 3.11), validate the four required trees + metadata files, replace `libraries/<package>/`.  `version: HEAD` → unpinned download (PyPI has no "HEAD"; the channel's latest already tracks main).  Closed-set `LibraryFetchFailureKind` + classifier; the per-kind user prose + retry coaching loop land with the Phase 2 CLI.
- **No `bundle_manager.py` change**, no new bundle-repo subtree.  Bundle repos stay focused on deployment artifacts (circup zips + `mpy6/` for the `mip`/`circup` happy path).

### Phase 2 — `chumicro-workspace library` CLI surface — *landed 2026-05-17*

```
chumicro-workspace library list                               # available + installed + version + channel
chumicro-workspace library add <name> [--channel stable|experimental] [--version <pin>] [--floating]
chumicro-workspace library update [<name>]                    # respects pin if set
chumicro-workspace library remove <name>                      # warns if other libs depend on it
chumicro-workspace library switch-channel <name> <channel>
```

Built across four modules: `managed_block.py` (generalized regex block writer extracted from `chumicro_dev.sync_library_sources`), `curated_libraries.py` (the `libraries:` table model + reader + writer), `dep_resolver.py` (`chumicro_dependencies` + cycle-safe `transitive_closure`), and `cli/library.py` (the six verbs).  `library.py` gained `fetch_closure` (BFS fetch + dep walk), `read_installed_version`, `remove_library`.

Dependency resolution: `library add` BFS-fetches the root then every chumicro lib in its `[project].dependencies` closure.  The interactive transitive prompt is **per-dep** — it lists the closure then asks `pull <dep>? [Y/n]` for each, so a user injecting a custom transport can decline just `chumicro_sockets` and keep the rest (the Q4 motivating case).  Declined deps are recorded `declined: true` and removed from disk; the fetched-then-removed cost is accepted to avoid a separate metadata-only resolver (PyPI deps are only knowable post-download in this design).  Non-interactive keeps the full set (Decision 0066 default).  Interactivity = `sys.stdin.isatty()` and not `--non-interactive`.

The Q4 remove/forget state machine is implemented: `add` → row present, `declined: false`; `remove` → uninstall the tree but keep the row as `declined: true` (so `update` skips it and the decision is auditable); a later `add` flips `declined` back off; `forget` → drop the row entirely (and uninstall if still present).  Both `remove` and `forget` warn (and, when interactive, confirm) if other curated libraries still depend on the target.

**Deferred (cross-repo; tracked elsewhere):** the workspace-template repo's regular-mode README (gap #4b) gaining a `library add` section now that this path exists — that lives in the separate workspace-template repo and is owned by the "Workspace-template gaps" item, not this workstream.

Pin state lives in `workspace.yml` under a new `libraries:` table — see Q2 below for the schema.

**Landing location** — `chumicro_workspace`'s CLI is now a package (`workbench/workspace/src/chumicro_workspace/cli/` with `__init__.py` + `_common.py` + `setup.py` + `devices.py`).  The `library` subcommand surface lands as a new `cli/library.py` module following the same shape as `cli/setup.py` and `cli/devices.py` — subparser builder + `_cmd_<verb>` functions + thin handoff into a `chumicro_workspace.library` core module.  Subparser registration in `cli/__init__.py`'s `build_parser`.

**Agent-runnable surface** — the transitive-deps prompt is an interactive seam, so per [Decision 0066](../../decisions/0066-agent-runnable-clis.md) the subcommand needs `--non-interactive` behavior.  When non-interactive: `library add` must not prompt; it either installs the full transitive set (recommended default) or fails with a distinct exit code naming the unresolved choice.  The decline-all-transitive option (`--decline-transitive` or similar) can be added later if a real workflow needs it.  Interactivity defaults to `sys.stdin.isatty()` with `--non-interactive` as the explicit override (Decision 0066 §1–2) — `cli/examples.py` (`non_interactive = not sys.stdin.isatty()`) and `cli/devices.py` (`args.non_interactive` + exit-2 on missing required arg) are the two precedents to mirror.

#### `switch-channel <name> <channel>` semantics

Flip an already-curated library between `stable` and `experimental` and re-fetch from the new channel's PyPI distribution.  Defined precisely (it is the verb most likely to be implemented loosely):

1. `<name>` not in the `libraries:` table → exit 2, "not curated; use `library add`".  `<channel>` ∉ {stable, experimental} → exit 2.  Already on `<channel>` → idempotent no-op, exit 0.
2. **Re-resolve the version — do not carry the pin across channels.**  A stable pin (`0.10.2`) is not a valid version of the `-experimental` distribution (dev-tagged `0.10.3.dev4`).  Default: resolve the new channel's latest and re-pin.  A `--floating` entry (`version: HEAD`) stays `HEAD`.
3. `fetch_library(name, channel=<new>, version=<resolved|HEAD>, …)` replaces `libraries/<name>/` in place; update the entry's `channel:`/`version:`.  `declined: true` entries have nothing on disk — update the recorded channel only, no fetch, exit 0 with a note.
4. **Blast radius is the named library only** — switch-channel does not cascade to transitive deps (mirrors the Q3 rule that `--channel` on `add` does not leak to deps).  If the new channel's `pyproject.toml` changed the chumicro dep set, warn and point at `library update`; do not silently auto-pull.
5. Implementation economy: switch-channel ≈ `add` with the channel flipped, version re-resolution forced, and the transitive prompt skipped — it can be a thin wrapper over the shared `add` core, not a parallel code path.

#### Phase 2 readiness (validated against code 2026-05-17)

- **`workspace.yml` writer strategy — decided.** `chumicro_dev.sync_library_sources` deliberately does *not* round-trip through ruamel (ruamel drops the file's leading comment header when no key anchors it); it does marker-comment + single-regex *block* replacement, preserving every other byte.  The `libraries:` table follows the same pattern: a CLI-managed marked block, read-modify-rewrite the whole block from in-memory desired state (the CLI is its sole writer).  `_LIB_SOURCES_BLOCK_RE` hard-codes the `library_sources:` key — Phase 2 should generalize it to a shared `sync_managed_block(workspace_yaml, key, marker, body_lines)` helper rather than copy-paste the regex.  Consequence: inline user comments *inside* the managed `libraries:` block are not preserved across rewrites — document it as CLI-owned, same contract as `library_sources:`.
- **No transitive-dep resolver exists.** Nothing walks `[project].dependencies` for `chumicro-*` today (`install_libraries.py` does an *import*-AST walk, not a dependency walk; `config_manifest.py` shows the `tomllib.load` + dict-navigate idiom to copy).  Phase 2 builds this fresh: after `fetch_library` lands the sdist, read its `pyproject.toml`, filter `[project].dependencies` for `chumicro-*`, recurse.
- **No `libraries:` table and no `schema_version` field exist** anywhere in `workspace.yml` or its loaders today — the additive-sibling-table assumption holds with zero structural conflict.

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

## Resolved design decisions

Decided 2026-05-12 during workstream resolution pass.  All four open questions answered; Phase 1 unblocked.

### 1. Source channel — PyPI sdist for both channels

Both channels fetch from PyPI as plain HTTPS sdist downloads.  Per-channel package mapping (already implemented by `bundle_manager.py`'s `patch_experimental()`):

| Channel | PyPI package |
|---|---|
| `stable` | `chumicro-<lib>` |
| `experimental` | `chumicro-<lib>-experimental` |

Fetch path: `pip download --no-deps --no-binary :all: chumicro-<lib>==<version>` → unpack the `.tar.gz` → copy contents into `libraries/<name>/`.

The only gating change is sdist content — today each library's `pyproject.toml` ships only `src/` + `VERSION` + `README.md` (10 files, 32 KB for mqtt-0.10.2).  Extending the include list to also ship `tests/` + `examples/` + `docs/` is a one-line edit per library; estimated post-change sdist size is 80-150 KB per library.

**Why not a `full/<lib>/` subtree in the bundle repos:** would create a second source of truth duplicating the PyPI sdist (drift risk), and would conflate the bundle repos' purpose (deployment artifacts for `mip`/`circup`) with source distribution.

**Why not a GitHub tarball backend for a `main` channel:** `release.yml` triggers on `push: main` when any `libraries/*/VERSION` file changes and publishes to `chumicro-<lib>-experimental` on PyPI.  Tracking main HEAD and tracking experimental latest produce identical bytes (modulo unpublished WIP commits a curated user wouldn't want).  An additional fetch backend would add complexity without surfacing useful state — the only thing it could uniquely fetch is unpublished WIP commits, and a developer wanting those is by definition working on chumicro itself and should be in dev mode (sibling checkout) anyway.

### 2. Pin-state location — new `libraries:` table in `workspace.yml`

Sibling to the existing `library_sources:` table:

```yaml
library_sources:                # existing — "where is the code on disk?"
  chumicro_mqtt: libraries/chumicro_mqtt/src
  chumicro_sockets: libraries/chumicro_sockets/src

libraries:                      # NEW — "where did I get it from + at what version?"
  chumicro_mqtt:
    channel: stable
    version: "0.10.2"
  chumicro_sockets:
    channel: stable
    version: "0.4.0"
```

The two tables are complementary, not duplicative.  `library_sources:` is the disk-path pointer the deploy walker reads (chumicro-dev mode points at a sibling checkout, curated mode points at `libraries/<name>/src/` in the workspace itself — same schema, different value, regenerated by `chumicro-workspace setup`).  `libraries:` is the channel/version manifest the curated-mode CLI maintains.

Defer the `libraries.yml` split until the table crosses ~30 entries.

### 3. Default channel `stable`; `--channel experimental` per-add; `--floating` opt-in for `version: HEAD`

A fresh template-cloned workspace defaults to `stable`.  `--channel experimental` overrides per-add and persists per-library — adding `chumicro_mqtt --channel experimental` does *not* leak the channel to its transitive deps unless explicitly named.

Pin format is a PyPI-resolvable semver string for both channels (uniform — no SHA path):

```yaml
libraries:
  chumicro_mqtt:
    channel: stable
    version: "0.10.2"             # default — semver pin from PyPI, frozen until `library update`
  chumicro_sockets:
    channel: experimental
    version: "0.4.1.dev3"         # default — dev-tag pin from PyPI experimental
  chumicro_msgpack:
    channel: experimental
    version: HEAD                 # --floating opt-in — resolver pulls latest of channel's package on every op
```

Reproducibility wins by default — same `workspace.yml` = same library bytes on every machine.  `--floating` (recorded as `version: HEAD`) is the explicit always-fresh escape hatch; two machines on the same `workspace.yml` with `version: HEAD` may land different bytes, which is the documented tradeoff.

A workspace-level default override (`defaults.library_channel: experimental`) is deferred until someone asks.

### 4. Declined transitive deps — record `declined: true` in `workspace.yml`

Option (b) — explicit state in `workspace.yml`, future updates respect the decline:

```yaml
libraries:
  chumicro_mqtt:
    channel: stable
    version: "0.10.2"
  chumicro_sockets:
    channel: stable
    version: "0.4.0"
    declined: true                # user declined at add-time; updates silently skip; record kept for audit
```

CLI behavior:

- `library add chumicro_mqtt` — user declines `chumicro_sockets` at the transitive prompt; entry lands with `declined: true` (audit trail, not silent omission).
- `library update` — declined entries are silently skipped.
- `library add chumicro_sockets` later — flips `declined: true` off (real install).
- `library remove chumicro_sockets` on a declined entry — sets `declined: true` and warns "kept in workspace.yml to track decline; use `library forget` to fully remove."

The library-side ImportError contract from Decision 0062 keeps runtime failures loud: if the user forgot to also add `__chumicro_skip_factories__` to their entrypoint, the deploy still ships and runtime raises `RuntimeError` naming the skipped module and the kwarg to pass instead.

Rejected: (a) refuse-install — hits a friction wall on the common case (user injecting custom transport).  (c) silent install with no record — loses audit trail, every subsequent `library update` re-asks the same question.

## Dev-mode interaction (per-library override, not blanket)

`chumicro-dev.toml` activates dev mode on a **per-library** basis — only for chumicro libraries that exist in the sibling chumicro checkout.  `chumicro-workspace setup` walks libraries individually when regenerating `library_sources:`:

```
For each library named in workspace.yml's `libraries:` table:
  if sibling chumicro checkout has libraries/<name>/ →
      library_sources: <name>: ../chumicro/libraries/<name>/src
  else →
      library_sources: <name>: libraries/<name>/src

For each libraries/<name>/ on disk that is NOT in `libraries:` (user libs, third-party):
  library_sources: <name>: libraries/<name>/src
  (always workspace-local — dev mode never touches)
```

Two consequences worth naming:

- **Partial sibling checkouts work cleanly.** A developer with only `chumicro_mqtt` + `chumicro_sockets` checked out alongside their workspace gets sibling-source resolution for those two and workspace-local resolution for any other curated chumicro libs in the same `libraries:` table.  No manual config, no all-or-nothing.
- **User and third-party libraries are never redirected.** A user's own `libraries/my_helper/` and a curated third-party `libraries/adafruit_thing/` always resolve to themselves regardless of dev-mode state.  Only `chumicro_*` libs that have a sibling source flip.

### Mode toggle UX

- **Switch ON dev mode** (drop in `chumicro-dev.toml`, run `setup`) — `library_sources:` regenerates per-library per the rule above.  `libraries:` table is preserved verbatim; pin state survives the toggle.  Workspace-local `libraries/<name>/` directories for chumicro libs that have a sibling stay on disk dormant (cheap, instant switch-back).
- **Switch OFF dev mode** (delete `chumicro-dev.toml`, run `setup`) — every chumicro library in `libraries:` gets workspace-local resolution.  If `libraries/<name>/` is missing on disk for a pinned entry, `setup` re-fetches per the pin.

### `library add` while in dev mode

`library add chumicro_mqtt` quietly persists to `libraries:` even when `chumicro-dev.toml` is present, so the pin activates the next time dev mode is off.  No warning — the pin is configuration that survives a mode flip; dev mode is just a temporary override.

## Remaining open items

- **Walker integration** — *resolved (Phase 1)*: `chumicro_deploy.sources._resolve_module` iterates `_search_paths` first-match-wins; search-path order is whatever generated the `library_sources:` mapping, so curated-vs-dev resolution is purely a `library_sources:` generation concern (dev mode points the key at the sibling checkout; curated mode at `libraries/<pkg>/src`).  No walker change needed.
- **`workspace.yml` schema bump** — *resolved*: no `schema_version` field.  `workspace.yml` has no version field today and the `libraries:` table is purely additive; the CLI treats a missing `libraries:` key as `{}` (legacy/clean workspaces).  Introducing a schema version now would be speculative — defer until a genuinely breaking schema change forces it.
- **sdist regression-test placement** — *resolved (Phase 1)*: build-time, in `scripts/run.py build` (`scripts/sdist_content.py`), so a contributor sees the failure before push.  A publish-time backstop in `release.yml` was not added — the build-time gate runs in CI's preflight, which gates merge to main, which is what triggers publish; a separate publish-time check would be redundant.

## Out of scope

- **`__chumicro_skip_factories__` mechanism itself** — covered by [Decision 0062](../../decisions/0062-entrypoint-factory-skip.md).
- **Duck-typed factory contract clarification** — separate ADR (planned 0063).
- **mip/circup deprecation** — both stay supported indefinitely.  This workstream provides an alternative, not a replacement.

## Acceptance

Phase 1 — **met**: every library's sdist carries `tests/`/`examples/`/`docs/` (verified against real `python -m build` output for mqtt, timing, runner); the build-time guard catches drops; the end-to-end pull was validated with **real `pip download`** against real locally-built sdists served from a local file index (`chumicro_runner` → `chumicro_timing`, full closure + curated content + transitive walk).  **Residual, CI-gated:** the literal "live PyPI index" variant cannot run until the release pipeline is back on and the experimental packages publish — at audit time `chumicro-mqtt[-experimental]` 404s on PyPI and `release.yml` has not produced tags for the Phase 1 VERSION bumps.  This is an environmental block on the *last hop* (the `pip download` shell-out is unit-tested and the entire downstream path is validated against real artifacts), not an open code risk.  Re-run the live variant as the first smoke test when CI is restored.

Phase 2 — **met**: `chumicro-workspace library add chumicro_mqtt` from a fresh workspace resolves the closure, per-dep prompts, and lands the libraries in `libraries/` (covered by 18 cli-library tests + the real-pip end-to-end).  The "`deploy` ships the right subset per Decision 0062" clause rides on Decision 0062's own bench validation + the walker's first-match-wins resolution verified in Phase 1 — not re-benched here (no curated-lib-specific deploy path; the walker treats `libraries/<pkg>/src` identically to a mono-repo library).

Phase 3 + 4: deferred.  Trigger conditions:
- Phase 3 fires when a user asks for an Adafruit / mp library through `library add` (real demand, not hypothetical).
- Phase 4 fires when Phase 2 has been used in anger for one release cycle and the "run example from curated lib" workflow has surfaced friction.
