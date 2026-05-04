# Workspace template: dev-mode vs regular-mode gaps

A live shake-down of the [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) end-to-end against a sibling `chumicro` checkout, plus the published bundles, surfaced a handful of half-wired or undocumented edges. This report captures what's broken, what's confusing, and what the fix looks like for each. Two operating modes need to work cleanly:

- **dev mode** — workspace pulls *everything* (host CLI **and** on-device libraries) from a sibling clone of the [`chumicro` mono-repo](https://github.com/ChuMicro/ChuMicro). The intended path for contributors who edit chumicro libraries while iterating on a thing.
- **regular mode** — workspace pulls *everything* from the public packages: `chumicro-workspace`/`chumicro-deploy` from PyPI, on-device libraries from `circup` (CP) or `mip` (MP) against [`ChuMicro-Bundle`](https://github.com/ChuMicro/ChuMicro-Bundle). The intended path for users.

Each gap below is listed with severity (**P0** = blocks the documented happy-path on a fresh clone, **P1** = forces an undocumented manual step, **P2** = polish / doc rot), the reproducer, and the fix surface (mono-repo vs. template repo vs. both).

---

## TL;DR — recommended fixes ordered by impact

| # | Severity | Fix surface | One-line |
|---|----------|-------------|----------|
| 1 | ~~P0~~ | mono-repo | ~~Declare `cryptography` in `requirements-dev.txt`.~~ Done — landed in `8bcfb6b`. |
| 2 | ~~P0~~ | mono-repo | ~~Convert remaining cross-tree relative doc links (`../../../plans/...`, `../README.md`) to absolute GitHub URLs; fix two slug mismatches in `workbench/deploy/docs/guide.md`.~~ Done — landed in `d9d039e`. |
| 3 | ~~P0~~ | mono-repo | ~~Wire **on-device** library shipping for dev mode.~~ Done — (a) `setup` auto-emits `library_sources:` from `chumicro-dev.toml` (`chumicro_workspace.chumicro_dev` module); (b) `deploy --boot-shim --import-graph` ships both the boot-shim layout and import-graph-discovered libraries (closed by gap 5's combiner). |
| 4 | P0 | template | Document and scaffold **regular mode**. Today the template README jumps straight to `deploy example_sensor` with no mention of installing the chumicro libs onto the board first via `circup`/`mip`. |
| 5 | ~~P1~~ | mono-repo | ~~Make `--import-graph` and `--boot-shim` composable, or pick one canonical "thing with `def run()` + chumicro lib deps" deploy path.~~ Done — combiner landed (`project_boot_with_import_graph_source`); CLI now accepts `--boot-shim --import-graph` and ships both the boot-shim layout and import-graph-discovered libraries in one deploy. |
| 6 | ~~P1~~ | mono-repo | ~~`add-device` should populate `devices.yml`'s `defaults:` block on first registration per runtime — the existing comment claims it does.~~ Done — `chumicro_deploy.config.devices_yaml.add_device` already had `set_default=True` baked in but its existence check (`runtime not in defaults`) skipped present-but-null slots, which is exactly what the materialized template ships.  Switched to `defaults.get(runtime) is None` so null-valued and absent are treated identically. |
| 7 | ~~P2~~ | mono-repo | ~~When `chumicro-dev.toml` is present, auto-derive `library_sources:` from `<chumicro_path>/libraries/*/src` instead of requiring the user to hand-list every package in `workspace.yml`.~~ Done — closed by gap 3(a) (`sync_library_sources` walks the sibling `libraries/` tree, writes a managed block into `workspace.yml`, idempotent re-write on re-run). |
| 8 | P2 | mono-repo | Single-source the bootstrap entry point — `chumicro-workspace-template/run.py` solves the same chicken-and-egg as `chumicro/scripts/prepare_workspace.py`, with a cleaner one-file pattern. |
| 9 | ~~P2~~ | mono-repo | ~~Tighten zensical version pin so a fresh `pip install -r requirements-dev.txt` produces the same docs result as CI.~~ Done — every host-tooling dep in `requirements-dev.txt` now pinned exact (`==X.Y.Z`); `mike` pinned to a specific commit hash on `squidfunk/mike` since it ships from a git URL.  Pin policy ("host tooling exact, library deps minimum-bound") documented in the file header. |

---

## 1. Missing `cryptography` test dep — P0

**Symptom:** `python scripts/run.py preflight` fails on a fresh clone:

```
libraries/sockets/tests/test_factories.py:144:
  ModuleNotFoundError: No module named 'cryptography'
... 4 failed in TestSslContextWithCertAndKey* / TestCPythonTLSListener
```

The test file even has an inline comment claiming it's "already a dev dep for our other server-side tests" — but it isn't listed in `requirements-dev.txt`.

**Fix surface:** mono-repo `requirements-dev.txt`.

**Status:** Done — landed in `8bcfb6b` ("requirements-dev: declare cryptography test dep").

---

## 2. Docs phase fails on fresh clones — P0

**Symptom:** `scripts/run.py preflight` exits non-zero at the docs phase. Five "page does not exist" errors in `workbench/workspace/docs/`, plus two latent "anchor does not exist" warnings in `workbench/deploy/docs/guide.md` that didn't fail-the-build before but were always wrong.

**Root cause:** zensical (currently 0.0.39, unpinned) treats markdown links to files outside the per-package `docs_dir` as broken pages. The mono-repo had already converged on absolute GitHub URLs almost everywhere; five files were stragglers using `../../../plans/decisions/<n>.md` or `../README.md`.

The slug mismatches in `workbench/deploy/docs/guide.md` are independent: `Devices.yml` slugifies to `devicesyml-…` (zensical drops the dot, doesn't replace with hyphen), and an unintended doubled hyphen in `#interactive-recovery--interactivedeployer`.

**Fix surface:** mono-repo docs.

**Status:** Done — landed in `d9d039e` ("docs: convert cross-tree links to absolute github urls + fix slug mismatches").

**Suggested follow-up:** pin zensical in `requirements-dev.txt` (`zensical==0.0.39` or whatever CI runs) to keep this from drifting again. Today the file just says `zensical`.

---

## 3. On-device libraries in dev mode have no documented path — P0

**This is the biggest hole.** A workspace using a sibling `chumicro` clone can install editable host packages via `chumicro-dev.toml`, but the boards still need the chumicro libraries on their flash filesystem — and there's no first-class path for that.

### What `chumicro-dev.toml` actually wires today

The template's `run.py` reads `chumicro-dev.toml`, walks `<chumicro_path>/libraries/*` and `<chumicro_path>/workbench/*`, and pip-installs each as editable into the workspace's `.venv/`. That makes `chumicro-workspace`, `chumicro-deploy`, etc. live-editable from the host CLI's perspective. Good and useful.

### What it does **not** wire

The libraries the *board* runs (`chumicro_config`, `chumicro_kvstore`, `chumicro_mqtt`, `chumicro_msgpack`, `chumicro_runner`, `chumicro_sockets`, `chumicro_timing`, `chumicro_wifi` for `example_sensor`) aren't shipped to the device by `setup` and aren't auto-included in `deploy`. The user has to either:

- **Hand-author `library_sources:`** in `workspace.yml`, mapping each `chumicro_<name>` import name to `<chumicro_path>/libraries/<name>/src`, *and* deploy with `--import-graph` (which is mutually exclusive with `--boot-shim` — see gap #5).
- **Pre-install the libraries onto each board** by hand (`mpremote cp -r` or copying onto the CIRCUITPY drive). Then deploy with `--boot-shim`. But the next `--boot-shim` deploy will diff-prune those libraries because they're not declared in the deploy file map.

Neither is documented in the template README, the workspace guide, or `chumicro-dev.toml`'s comments. The `example_sensor` walkthrough silently assumes the libraries are already there.

### Recommended fix — two compatible pieces

**(a) Auto-populate `library_sources:` from chumicro-dev.toml.** When `chumicro-dev.toml` is present and `setup` runs, write a managed block into `workspace.yml`:

```yaml
# managed by chumicro-workspace setup — chumicro-dev.toml mode
library_sources:
  chumicro_compat:    ../chumicro/libraries/compat/src
  chumicro_config:    ../chumicro/libraries/config/src
  chumicro_events:    ../chumicro/libraries/events/src
  chumicro_http_server: ../chumicro/libraries/http_server/src
  chumicro_kvstore:   ../chumicro/libraries/kvstore/src
  chumicro_logging:   ../chumicro/libraries/logging/src
  chumicro_mqtt:      ../chumicro/libraries/mqtt/src
  chumicro_msgpack:   ../chumicro/libraries/msgpack/src
  chumicro_ntp:       ../chumicro/libraries/ntp/src
  chumicro_requests:  ../chumicro/libraries/requests/src
  chumicro_runner:    ../chumicro/libraries/runner/src
  chumicro_sockets:   ../chumicro/libraries/sockets/src
  chumicro_timing:    ../chumicro/libraries/timing/src
  chumicro_websockets: ../chumicro/libraries/websockets/src
  chumicro_wifi:      ../chumicro/libraries/wifi/src
```

`setup` already discovers `<chumicro_path>/libraries/*` for editable host installs — extend it to write that block for the on-device side too. Idempotent re-write so users can `setup` after pulling new chumicro libs.

**Fix surface:** template repo (`run.py setup` extension) + mono-repo (`chumicro_workspace.cli` if `setup` lives there).

**(b) Make `deploy` ship libraries even with `--boot-shim`.** See gap #5.

**Status:** Done.

* (a) — `chumicro_workspace.chumicro_dev` (new module) provides
  `read_chumicro_dev_path`, `discover_chumicro_libraries`, and
  `sync_library_sources`.  Wired into `_cmd_setup`: when
  `chumicro-dev.toml` is present at the workspace root, `setup`
  walks `<chumicro_path>/libraries/`, builds the
  `{chumicro_<name>: <chumicro_path>/libraries/<name>/src}` map,
  and writes a managed block to `workspace.yml` with a marker
  comment above (`managed by chumicro-workspace setup —
  chumicro-dev.toml mode`).  Paths are written relative to the
  workspace root when possible (sibling-checkout case yields
  `../chumicro/libraries/<name>/src`).  Idempotent — re-running
  `setup` after pulling new chumicro libraries refreshes the block;
  re-running with an unchanged set is a no-op.  Also closes gap
  #7 (P2 polish — same auto-derivation by a different framing).
* (b) — closed by gap #5's `project_boot_with_import_graph_source`
  combiner; `deploy --boot-shim --import-graph` now ships the
  boot-shim layout AND the import-graph-discovered libraries in
  one deploy.

---

## 4. Regular mode — undocumented and unscaffolded — P0

The template README ([source](https://github.com/ChuMicro/ChuMicro-Workspace-Template/blob/main/README.md)) shows:

```
python3 run.py setup
python run.py add-device my-board --address /dev/cu.usbmodem1101 --runtime micropython
python run.py new my-thing
python run.py deploy my-thing
```

Then for `example_sensor`:

```
python3 run.py setup
python run.py add-device …
$EDITOR secrets.yml
$EDITOR things/example_sensor/config.toml
python run.py deploy example_sensor
```

Both omit the **chumicro libraries onto the board** step, which is mandatory for any thing that imports `chumicro_*`. In dev mode it's gap #3. In regular mode it should be:

```
# CircuitPython
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-config chumicro-kvstore chumicro-mqtt chumicro-msgpack \
               chumicro-runner chumicro-sockets chumicro-timing chumicro-wifi

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_config \
                     github:ChuMicro/ChuMicro-Bundle/chumicro_kvstore \
                     ...
```

…but a user shouldn't be running circup/mip by hand for every chumicro lib their thing imports. Two recommended fixes:

**(a) Add `chumicro-workspace install-libraries <thing>` (or roll into `deploy`)** that AST-walks the thing's entrypoint, resolves chumicro imports, and shells out to `circup` (CP) or `mpremote mip` (MP) per detected runtime, against the right bundle channel (stable/experimental). This is the regular-mode mirror of dev-mode's gap-#3-(a).

**(b) Document the manual fallback** in the template README *and* the workspace guide. Even if (a) lands, users on edge platforms (no internet on the host, custom registries, air-gapped) need the manual recipe.

**Fix surface:** mono-repo (workspace CLI extension) + template repo (README + maybe a `_templates/install-libraries.sh` ready-to-run script for cold starts).

---

## 5. `--import-graph` and `--boot-shim` are mutually exclusive — P1

Today the workspace deploy CLI has three layouts:

| Layout | Triggered by | Ships thing files | Ships chumicro libs | Boot pattern |
|---|---|---|---|---|
| flat | (default) | yes, at `/` | no | thing's own `main.py`/`code.py` |
| `--boot-shim` | `--boot-shim` | yes, at `/lib/things/<name>/` | **no** | `workspace_runtime.boot()` calls `things.<name>.app.run()` |
| `--import-graph` | `--import-graph` | yes (only AST-reachable) | yes | thing's own `main.py`/`code.py` |

The chumicro `example_sensor` thing is authored for `--boot-shim` (it has `app.py` with `def run()` and no `main.py`/`code.py`). But `--boot-shim` doesn't ship the chumicro libraries it imports. And the CLI flat-out rejects `--boot-shim --import-graph`.

The workaround I had to use to run the example end-to-end: drop a two-line `main.py` *and* `code.py` shim into `things/example_sensor/`, deploy with `--import-graph`. That collapses the boot-shim convention but works.

### Recommended fix

Allow `--boot-shim --import-graph` to compose: keep the boot-shim layout for the thing (`/code.py` shim → `workspace_runtime.boot()` → `things.<name>.app.run()`) **and** ship import-graph-discovered libraries to `/lib/`. The two source classes (`thing_boot_source`, `thing_import_graph_source`) operate on disjoint device paths — `/code.py`/`/active.py`/`/lib/things/...` vs `/lib/<package>/`. A thin combiner that merges their `files()` maps would do the job.

Alternative if combining is too invasive: deprecate `--boot-shim` and bake the `app.py` + `def run()` convention into the import-graph path — the entrypoint shim writes itself when `app.py` is detected and no `main.py`/`code.py` exists.

**Fix surface:** mono-repo `chumicro_workspace.cli._cmd_deploy` + a new combiner in `chumicro_workspace`.

**Status:** Done — `project_boot_with_import_graph_source` in `chumicro_workspace.boot_shim` composes the two layouts; the boot-shim is authoritative on overlapping device paths (entrypoint shim, `active.py`, `workspace_runtime` payload, namespace markers, project files under `/lib/projects/<...>/<project>/`); the import-graph contribution fills `/lib/<package>/...` with libraries reachable from the project's `app.py`.  Project-local files the walker reaches via `project_dir`-as-search-path are filtered out post-hoc to avoid double-shipping under `/lib/<basename>.py`.  CLI dispatch in `_cmd_deploy` adds a third branch (`if args.boot_shim and args.import_graph: …`); the prior mutual-exclusion rejection is gone.  Deploy mode label in dry-run output: `boot-shim+import-graph`.  chumicro-workspace 0.3.1 → 0.4.0 (new public API).

---

## 6. `add-device` doesn't populate `devices.yml`'s `defaults:` block — P1

**Symptom:** the `defaults:` keys stay null after the first `add-device` of each runtime, despite the comment in the materialized `devices.yml`:

```yaml
defaults:
  # Pin which device id each runtime defaults to when no --device-id
  # flag is passed.  Filled by `add-device` on first registration.
  micropython:
  circuitpython:
```

This forces every `deploy`/`repl`/`probe` to pass `--device <id>` even when there's only one MP and one CP board in the workspace.

**Fix surface:** mono-repo `chumicro_workspace.cli._cmd_add_device` (or wherever the `devices.yml` write happens) — fill `defaults.<runtime>` with the new device id when the slot is null *and* this is the first device of that runtime.

**Status:** Done — fix landed in the *library*, not the CLI.  Investigation found `chumicro_deploy.config.devices_yaml.add_device` already had a `set_default=True` parameter (defaults to True) that auto-seeds `defaults.<runtime>: <device_id>` when the slot isn't taken — but the existence check (`if runtime not in defaults:`) skipped slots where the key existed with a null value, which is exactly the shape the materialized `_workspace_template/devices.yml` ships (`micropython:`, `circuitpython:` — keys present, values null).  Switched the check to `defaults.get(runtime) is None` so absent-key and present-but-null are treated identically.  Five tests cover the behavior (`TestAddDeviceAutoDefaults` in `test_cli.py` + a new `test_seeds_default_when_runtime_key_present_but_null` in `test_devices_yaml.py`).  chumicro-deploy 0.6.0 → 0.6.1 (bug fix to existing API).

---

## 7. `library_sources:` should be derivable from `chumicro-dev.toml` — P2

Subset of gap #3-(a). Today users have to hand-write 8–15 lines of `library_sources:` to mirror the chumicro-dev.toml `chumicro_path`. Since `setup` already walks `<chumicro_path>/libraries/*` for editable host installs, it knows the full list — extend it to emit the `library_sources:` block too.

Open-question stub: should the auto-emitted block include *every* chumicro library, or only the ones a thing in this workspace currently imports? Including every library is simpler and harmless (entries that aren't imported just sit unused); a per-thing scan is fancier but adds a re-run trigger when a thing's imports change.

---

## 8. Two different bootstrap patterns for the same chicken-and-egg — P2

Both the mono-repo and the workspace template have to solve "run a script on a fresh clone with no third-party deps yet, then re-exec into the venv":

- **Mono-repo:** `scripts/prepare_workspace.py` (cold-start safe) + `scripts/run.py` (third-party-heavy). Two files. `scripts/run.py` blows up with `ModuleNotFoundError` if invoked before `prepare_workspace.py`.
- **Workspace template:** `run.py` does both jobs in one file by deferring the `from chumicro_workspace.cli import main` to inside `main()`, after the venv is built and we re-exec. Cleaner single-file pattern.

The template's pattern strictly subsumes the mono-repo's. Worth converging on the single-file approach in the mono-repo too — pulls one less file out of `scripts/` and removes the foot-gun where running `python3 scripts/run.py --help` on a fresh clone produces a confusing import error instead of a "run prepare_workspace first" message.

**Fix surface:** mono-repo `scripts/run.py` — fold the `prepare_workspace.py` bootstrap into the top of `run.py`, then delete `prepare_workspace.py`. Update `CONTRIBUTING.md` and `AGENTS.md` references.

---

## 9. Pin zensical (and other tools) in `requirements-dev.txt` — P2

Symptom: docs phase passes on one machine, fails on another, because zensical was unpinned and the two machines resolved to different versions. The newer version added stricter cross-tree link validation, surfacing the latent broken links in gap #2.

Same risk applies to any other unpinned tool in `requirements-dev.txt` (`pytest`, `ruff`, `build`, `hatchling`, `griffe`, `pyserial`, `pyyaml`, `mpremote`, `mike`, `mkdocstrings`).

**Fix surface:** mono-repo `requirements-dev.txt` — pin to whatever version CI uses (probably worth running `pip freeze` from a green CI run and pasting). Decision-record optional but useful: "we pin host tooling exact, library deps minimum-bound."

**Status:** Done — every host-tooling dep pinned exact (`==X.Y.Z`).  Pinned versions match what was installed in the green-preflight venv on 2026-05-03 (already on latest PyPI release across the board, so no version-change bugs surfaced).  `mike` ships from a git URL (`squidfunk/mike`) — pinned to the specific commit hash on `main` for reproducibility.  Pin policy documented in the file header so future intentional upgrades follow the same shape.

---

## Side-finding: `chumicro_*` install size budget on small flash

Not a bug, but useful to record. The Pi Pico (RP2040) ships with an ~868 KB internal filesystem. A naive `mpremote cp -r libraries/<lib>/src/chumicro_<lib>` for the eight `example_sensor` deps blows past that because it copies `__pycache__/*.pyc`. A clean staging step (drop `__pycache__`, drop `*.pyc`, drop `testing.py`, runtime-marker filter per Decision 0044) brings the install to **34 files / 276 KB** — fits with ~376 KB free for thing files + runtime config + kvstore msgpack.

Implication for fix #4 (regular-mode library install command): on small-flash boards the install path *must* respect runtime markers and skip test fakes. `circup`/`mip` already do this for bundle artifacts; a host-side helper writing files directly should mirror that filtering.

---

## Verification commands used while shaking this down

```bash
# Mono-repo bootstrap + preflight
git clone git@github.com:chumicro/chumicro.git
cd chumicro
python3 scripts/prepare_workspace.py
.venv/bin/python scripts/run.py preflight --coverage-threshold 94

# Workspace template + dev mode
git clone git@github.com:chumicro/chumicro-workspace-template.git
cd chumicro-workspace-template
echo 'chumicro_path = "../chumicro"' > chumicro-dev.toml
python3 run.py setup
python3 run.py add-device pico-mp   --address /dev/ttyACM0 --runtime micropython
python3 run.py add-device pico-w-cp --address /dev/ttyACM1 --runtime circuitpython

# Local mosquitto bound to the wifi IP only (the systemd one stays on 127.0.0.1)
mosquitto -c .scratch/mosquitto.conf -d   # listener 1883 <wifi-ip>; allow_anonymous true
mosquitto_sub -h <wifi-ip> -t 'chumicro/example/#' -v

# Deploy (both runtimes — after manual library_sources: edit + main.py/code.py shim)
python3 run.py deploy example_sensor --device pico-mp   --import-graph --non-interactive
python3 run.py deploy example_sensor --device pico-w-cp --import-graph --non-interactive
```

End-to-end verified: heartbeat JSON arriving from both Picos with distinct CPU temperatures (~22–27 °C on the bare Pico, ~32–33 °C on the Pico W) and the `chumicro_kvstore` boot counter persisting across resets on each board independently.
