# Learnings

Non-obvious facts about the world this project lives in — discovered the hard way and worth re-reading before the same surface is touched again.

This file is the **compression tier** for "we tripped on X, here's what we know about X." Distinct from sibling files:

- **`decisions/`** = *why* we chose X over Y. Tradeoffs we made.
- **`patterns.md`** = *how* to implement X correctly. Code shape.
- **`history.md` §Rejected approaches** = approaches we *tried as a project decision* and rejected. Path-not-taken.
- **`learnings.md` (this file)** = facts about hardware, tools, runtimes, and OS behavior. Not policies — *physics*.

If a learning grows enough scope that the right response is "we should change how we build", promote it to a Decision and link back here. If it grows enough code surface to reuse, promote to a Pattern. Otherwise it lives here, terse.

Each entry: one heading + 2–6 lines + a commit reference. If you can't say it in 6 lines, you're probably writing a Pattern or a Decision.

---

## macOS hardware deploy

### macOS FSKit can wedge `diskarbitrationd` on FAT12 errors

Recent macOS replaced the in-kernel `msdosfs` driver with a user-space FSKit extension (`com.apple.fskit.msdos.appex`). When it errors mid-probe on a small FAT12 CIRCUITPY volume, `diskarbitrationd` enters an uninterruptible kernel wait (`ps` state contains `U`) and every subsequent DiskArbitration call queues behind it. Unplug/replug does nothing.

Recovery (surface to user, never auto-run): `sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd && launchctl kickstart -k gui/$(id -u)/com.apple.DiskArbitrationAgent`. The per-user `DiskArbitrationAgent` needs `kickstart -k`, not just `killall`, because its launchd plist has `KeepAlive=false` — a bare kill leaves it dead and CIRCUITPY drives mount but never appear in Finder Locations.

Detector lives at `workbench/deploy/src/chumicro_deploy/macos_fskit.py`. Fails open on any subprocess error — never block a legitimate retry. See `DeployFailureKind.MACOS_FSKIT_WEDGED`. Commit `6fdc132`.

### Finder sidebar regression after FSKit recovery is a separate Apple bug

After `MACOS_FSKIT_WEDGED` recovery, drives mount cleanly and tools see them, but Finder's Locations sidebar may still hide them. AppleScript, CLI tools, Finder Computer view, and the deploy tool all see the volumes — only the sidebar classifier filters them out. No userspace command fixes it. Tell the user, don't chase it. Workarounds: Shift+Cmd+C → drag to Favorites. Commit `6fdc132`.

### Lolin S2 Mini gets stranded after esptool default `--after hard_reset`

Single-invocation `esptool.py erase-flash write-flash …` left the Lolin S2 momentarily un-enumerable on macOS. Fix: run erase and write as two invocations, `--after no_reset` on erase, one-second settle, then write. esptool v5 also refuses chained `erase-flash` + `write-flash` in one call regardless. See `chumicro_deploy/firmware.py`. Commits `5c5ef53`, in slice 1e.2 round 2.

---

## CircuitPython runtime quirks

### Raw paste mode (Ctrl-E) is unresponsive on ESP32-S2 CP

Validated on Lolin S2 Mini during Decision 0027 PoC. Use Ctrl-A raw REPL mode instead. The `chumicro-deploy` `CircuitpythonTransport` and `chumicro-repl` `ReplSession` both standardize on Ctrl-A. Earlier planning docs referenced "raw paste mode" — those are stale; the implemented protocol is Ctrl-A only.

### `types.ModuleType` and `hashlib.sha256` are absent on ESP32-S2 CP

Means: no module-injection helpers that rely on `types.ModuleType()`, no SHA-256 staging hashes in CP RAM-mode bootstraps. Class-as-module injection (assigning a class instance into `sys.modules`) is the workaround for the missing `ModuleType`. See the bootstrap builders in `workbench/deploy/src/chumicro_deploy/`.

### CIRCUITPY drive must be re-probed after eject; EACCES is not a permission error

When `/Volumes/CIRCUITPY` lingers as a placeholder after Finder eject (or during an FSKit wedge), writing to it raises `OSError: [Errno 13] Permission denied`. The classifier must check drive-not-found patterns *before* port-unavailable patterns — the nested `permission denied` substring will otherwise misroute to `PORT_UNAVAILABLE` and skip the FSKit wedge detector. Transport-level guard: write a `.chu-probe` marker file before any rsync; catch `OSError` and re-raise with the drive-not-found message. Commit `38fb039`.

### CP flash deploy needs a settle delay after the board sees a new entrypoint

Without a post-visible settle, output captured immediately after `autoreload` re-engagement is one cycle behind reality. See `_BOARD_FILE_VISIBLE_POST_SETTLE` in `chumicro_deploy/transports/`. Hardware-tuned, do not remove. Commits `a561c02`, `3f11d09`.

---

## MicroPython runtime quirks

### MP ESP32 firmware lives at flash offset `0x1000`, not `0x0`

Per-runtime esptool offsets matter — MicroPython ESP32 binary at `0x0` will boot to a brick. Fixed in slice 1e.2; see `chumicro_deploy/firmware.py` `_RUNTIME_FLASH_OFFSETS`. Commit `c4e6ac1`.

### `mpremote` "failed to access" / "may be in use" is a port-unavailable signal

Classifier must route these strings to `PORT_UNAVAILABLE`, not `BOOTSTRAP_EXEC_FAILED`. Otherwise an unplugged board produces a "fix your source" message. Patterns added to `_PORT_UNAVAILABLE_PATTERNS`. Commit `38fb039`.

### Every `import` on MicroPython mount-mode is an mpremote RPC round-trip

`mpremote mount` exposes the host file system to the device via a `RemoteFS` hook. Every `import` triggers a serial-intercept callback that fetches the source file over USB CDC. A single lazy import inside a hot path (e.g. `Runner.__init__` deferring `chumicro_timing.ticks`) pulled three files over the wire on first call and added ~1 second of inflation on the Lolin S2 mini.

Implication for tests / measurement: when profiling MicroPython mount-mode, the first run of any test that exercises new imports is dominated by RPC round-trips, not by the test body. The CircuitPython numbers don't show this because CP runs the source from RAM after staging.

Fix knobs that *don't* work: eager-importing at package top level was tried (commit `9eb5980`) and reverted (commit `8b44325`) — see Rejected approaches §18 in `history.md`. The only durable fix is to amortize: batch-execute test functions, hold one `SerialTransport` per session (see `patterns.md` §mpremote internals §4), and stage all files in one rsync pass. Commit `9eb5980` (root cause analysis), `8b44325` (revert).

### MicroPython RAM-mode functional tests run noticeably slower than CP RAM-mode

Observed during 2026-04-19 live PyCharm testing. Suspect: per-file `mpremote mount` cost + cold-start interpreter overhead. Profile against the batched-execute path before optimizing — there's an open investigation in `next-up.md`. Not yet root-caused.

---

## Tooling and process

### Classifier ordering matters: drive-specificity before errno-substring

When several pattern lists feed one classifier, order by *prefix specificity* not by category, because nested errno strings will win against more-specific drive/port patterns. Rule: most-specific message prefix first. The CIRCUITPY-drive-found fix above is the canonical example. Commit `38fb039`.

### `replace_all` substring collisions silently corrupt longer names

Before `replace_all` on `_foo`, grep for longer names containing it (e.g. `_apply_foo`). Literal substitution does not respect identifier boundaries and will silently change `_apply_foo` → `_apply_bar` if you replace `_foo` → `_bar`. From user feedback memory; surfaced often enough to belong here too.

### `git commit -m` breaks in zsh on special characters

Always write the message to `.scratch/commit-msg.txt` with a file tool, then `git commit -F .scratch/commit-msg.txt`. The `git-commit` skill captures the full procedure. Heredoc / `echo` / `printf` from the agent terminal also fail — they truncate multi-line input and lose closing delimiters.

### Commits in this repo are authored by the human, not the agent

Strip Claude Code's default `Co-Authored-By: Claude …` trailer before writing the commit message. The agent is a tool, not a co-author. Enforced in `git-commit` skill. Commit `f0b9df1`.

### Branch protection breaks PAT-based bundle pushes; use SSH deploy keys

When the bundle repos got branch protection, `BUNDLE_TOKEN` (a PAT) couldn't bypass rules cleanly. Per-repo SSH deploy keys (single-repo scoped, least privilege) work. PAT retained only for `gh release create` API calls. See Decision 0019 area. Commit history pre-2026-04-15.

### `sys.modules`-walk leakage tests must capture *delta*, not absolute state

`test_public_api_alone_is_sufficient` originally walked global `sys.modules` after importing the third-party fixture, asserting nothing from `chumicro_timing` etc. was present. This works under per-package pytest (clean module table per subprocess) but false-positives under root-level pytest where prior library tests leave their modules cached.

Fix: snapshot `sys.modules` before the fixture import, snapshot again after, assert nothing prohibited appears in the *delta*. Correct under both regimes. Apply this pattern any time you assert "import of X did not transitively pull Y." Commit `73e9270`.

### Transport caches must invalidate on batch-execution failure, not just record the error

When the IDE-side `pytest_device.py` plugin caches a `Transport` per `(device, file)` tuple and a batch execution fails, **invalidating only the cached *result* leaves the transport itself in whatever state it crashed in** (raw REPL stuck mid-Ctrl-D, mpremote stuck mid-mount). The next file gets a cache hit, reuses the broken transport, and cascade-fails with cryptic errors.

Pattern: on batch-failure, call `transport.recover()` first; if recovery itself fails, drop the transport from the cache (`invalidate_device(device_id)`) but keep the cached batch *result* so subsequent items from the same file see the original failure rather than retrying. The CLI orchestrator had this from the start; the IDE plugin had to be brought into line. Commit `a4566eb`.

### `pytest --import-mode=importlib` is required when duplicate test basenames exist across packages

Once root pytest started collecting `workbench/deploy/tests/` + `workbench/repl/tests/` in the same session, duplicate basenames (`test_cli.py` exists in both) tripped pytest's classic-prepend collector with `ImportPathMismatchError`. Switching root pytest to `--import-mode=importlib` resolves it without renaming files. Commit `73e9270`. Decision 0008 originally selected importlib mode for similar reasons within a single library, then Decision 0009 superseded it for per-library pytest runs — this is the third regime: root-level multi-package collection.

### Workbench packages skip bundle staging + `.mpy` compile but keep VERSION gates

`libraries/` packages flow through `circup` / `mip` / `pip` and need bytecode + bundle staging. `workbench/` packages flow through `pip` only and skip both — but they keep `VERSION` files, `check-version`, `check-api`, and the experimental→stable promotion lifecycle. Decision 0032 codifies this. Both pre-merge gates were extended to walk `workbench/*/` in commit `104e129` (2026-04-25); release-workflow side covered by `fa8628c`.

### CircuitPython RAM-mode silently bypasses module-level `__getattr__`

PEP 562 module-level `__getattr__` is implemented at the firmware level on both MP and CP (verified against pinned source — `MICROPY_MODULE_GETATTR` default-on at `CORE_FEATURES` ROM level), but the **deploy harness's CircuitPython RAM-mode path wraps the package in a class-as-module stub (`_Mod`) that doesn't honour PEP 562**.  Lookups against the wrapper hit the stub's `__dict__` directly without consulting `__getattr__`, so the lazy attr table just silently doesn't fire.

The unit-test hint that masks this: looking up an unknown attr raises `AttributeError` even when the hook is bypassed, so a test like `with raises(AttributeError): module.NotARealSymbol` passes regardless of whether `__getattr__` is being invoked.  To detect bypass, you need a **positive** lazy-resolution test (`module.RealSymbol` returning the resolved value) — that's the one that fails on CP RAM-mode and reveals the harness behavior.

Practical consequence: **package-level PEP 562 `__getattr__` is unsafe for cross-runtime device libraries that need to work via RAM-mode deploy.**  Per-function lazy imports (named `from X import Y` inside a function — what `chumicro_kvstore._select_backend` does) work everywhere because the runtime's import machinery handles them, not the harness's wrapper.

Surfaced when chumicro-wifi Slice 0 added a PEP 562 table at the top of `__init__.py` mirroring `chumicro-deploy`; passed every host-side test, the MP unix-port functional test, and the on-device MP test, but failed exactly the positive-resolution scenarios on real CP boards.  Reverted wifi to eager package-level imports (Tier A — only 3 attrs, well below the threshold the research recommended PEP 562 for); kept lazy adapter selection inside `_select_adapter`.  Updated lazy-loading-research.md + patterns.md PEP 562 entry with the harness caveat.

### MicroPython rejects multiple inheritance from differing-layout `Exception` subclasses

A class like `class MissingConfigKey(ConfigError, KeyError): ...` parses fine on CPython but raises `TypeError: multiple bases have instance lay-out conflict` at module import on MicroPython 1.26 (and CircuitPython by extension).  Built-in exception types each carry their own C-level memory layout; MP's class machinery refuses to combine two of them in a single subclass.

The "ergonomic dual-catch" pattern (`except ConfigError` *or* `except KeyError` both work) is a CPython-only luxury for library code that has to load on device.  Pick **one** parent — usually the library's domain-specific base — and document it.  Callers catch via the single parent.

Surfaced in `chumicro-config` Slice 0 when `MissingConfigKey(ConfigError, KeyError)` and `InvalidConfigType(ConfigError, TypeError)` failed import on the MP unix-port even though host-side CPython tests passed.  Fix: drop the stdlib parents, document the workaround in Decision 0036 §2.

### `griffe check --search` silently ignores absolute paths in 2.x

Pass `--search` as a path *relative to the subprocess cwd*, not absolute. With griffe 2.0.2, an absolute `--search /abs/path/to/src` resolves nothing — griffe exits 0 with empty stdout/stderr regardless of breakages, making any check_api-style gate a silent no-op. The relative form (`--search workbench/deploy/src` from the repo root) works. This bug had been live in `scripts/check_api.py` since the gate was added: every PR was passing it without any actual API comparison. Caught during 2026-04-25 manual end-to-end validation while extending the gates to workbench. Fix: `str((package_root / "src").relative_to(ROOT))`. Always run a real-fixture pass when wiring tools that fail-soft like this — unit tests with mocked subprocesses can't see this class of regression.
