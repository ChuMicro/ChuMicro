# Open Questions

Unresolved questions that need thought but aren't blocking active work.
When a question is resolved, **delete** it from this file — the ADR
(or the commit that settled it) is the durable record, and `git log` on
this file preserves the question text for anyone who needs to recover
the historical context.

Questions that become blocking should move to `next-up.md` (Blocked section).
Questions that lead to structural tradeoffs should become decisions in
`plans/decisions/`.

---

### `chumicro-presence` design from Decision 0042 §167-168 — re-audit before anything rides on its shape

**Surfaced 2026-05-12** during the `/audit-integration` pass on `chumicro-events ↔ wifi + mqtt`.  Decision 0042 names a future `chumicro-presence` library as the centralized binder for wifi/mqtt state into the events bus: *"`chumicro-presence` ships a one-line `presence.bind(wifi=..., mqtt=...)` that does the callback wiring centrally"* (§167-168).  Library doesn't exist yet (`ls libraries/` confirms — no presence directory).  The `presence.bind(wifi=..., mqtt=...)` shape was sketched long ago — the user flagged it as possibly stale or wrong, and the binding method it promises should be considered suspect until re-audited.

**Why this matters now:**
- `chumicro-events` deliberately supports two producer shapes (wifi's registration-method `on_state_change(cb)` and mqtt's replaceable-attribute `on_connect = cb` etc.), bridged by `publisher(topic)` returning a `*args` closure.  That divergence is coherent today.  But the future `presence.bind` would have to bridge them too, paying the bridging cost in a central place.
- The 2026-05-12 audit-integration pass explicitly deferred the "should wifi and mqtt converge on one callback shape?" question to a workspace-level pass — but a workspace decision driven by an *outdated presence design* would be twice wrong.  Any convergence work needs to verify presence's actual planned shape first, not the §167-168 sketch.

**Audit before:**
- Any structural decision that argues "we should converge wifi/mqtt callback shapes because presence will need it."
- Any work that starts implementing `chumicro-presence` from the §167-168 description.
- Any ADR amendment to Decision 0042 that ratifies §167-168 as the binding contract.

**Audit shape (when triggered):**
1. Read every `presence` reference across `plans/` (Decision 0042, workstreams, archive) — collect the original design intent.
2. Re-evaluate against today's wifi + mqtt callback surfaces — does `presence.bind(wifi=..., mqtt=...)` still make sense, or has the seam shifted?
3. If the design is salvageable, propose a new ADR (`chumicro-presence` library charter) that supersedes Decision 0042's §167-168 sketch and codifies the actual binding shape.
4. If not, retire the reference from Decision 0042 and surface the gap as a separate open question (what *does* central wifi+mqtt event binding look like?).

Not blocking anything today — but a "fix two-shape divergence" workstream proposal would block on this.

### Next CP hard fault on stale socketpool state — investigate

**Surfaced 2026-05-09** during the 4-board example sweep on Lolin S2 CP.  After a
prior `websockets/examples/circuitpython_server.py` deploy left a `socketpool.SocketPool(radio)`
allocated, deploying `sockets/examples/tcp_roundtrip.py` (then targeting `127.0.0.1:8000`)
produced `Hard fault: memory access or instruction error` → safe mode.  Fresh-boot
reproducer raised a clean `OSError [Errno 104] ECONNRESET` against the same target.

The sweep can no longer reproduce it — `tcp_roundtrip.py` was rewritten to hit
`example.com:80` and the old `127.0.0.1:8000` shape is gone.  Recovery from safe
mode is clean (RESET, FAT volume intact); the crash happens inside CP core code
(likely the socketpool C implementation), not chumicro_sockets Python.

**Repro recipe (when it shows up again, on Lolin S2 CP):**
1. Deploy `websockets/examples/circuitpython_server.py` to the board, let it bind
   `0.0.0.0:8765` for a few seconds.
2. Deploy any code that calls `tcp_client_socket(<unreachable_host>, <port>, radio=…)`.
3. Hard fault appears as `CircuitPython core code crashed hard` in the board's
   serial output.

**Two angles when the time comes:**
- (a) Add socket cleanup on close to `chumicro_sockets._adapters.cp` so a fresh
  `tcp_client_socket` starts with a clean pool.  Defensive; may not actually
  hit the firmware bug.
- (b) File a CircuitPython upstream issue with a minimal repro that bypasses
  chumicro_sockets entirely (`socketpool.SocketPool(wifi.radio)` →
  `pool.socket(pool.AF_INET, pool.SOCK_STREAM)` → `connect((unreachable, port))`).
  Verify firmware-side responsibility before any chumicro-side workaround.

Was follow-up #5 in `plans/workstreams/example-sweep-stability.md`; moved here
because the workstream's sweep harness can't trigger it on demand and the issue
needs a natural occurrence.

### MicroPython `machine.bootloader()` on ESP32-S2 — missing USB-CDC persist setup

**Surfaced 2026-05-11** during the 4-board reflash bench test of
`chumicro-deploy flash-firmware`.  Lolin S2 mini running MicroPython
1.28.0 — `machine.bootloader()` over the running MP serial port writes
the RTC force-download-boot bit and calls `esp_restart()`, but the chip
does **not** come back as a host-visible USB-CDC ROM bootloader port.
From the host side: original port (`/dev/cu.usbmodem11101`) remains
enumerated but MP runtime is unresponsive (`mpremote ... exec` fails
"could not enter raw repl"), no new `/dev/cu.usbmodem01` appears within
chumicro-deploy's 8-second poll window, esptool's DTR/RTS auto-reset
also fails ("Failed to connect to Espressif device: No serial data
received").  Manual `BOOT + RESET` button-hold recovers cleanly into
ROM bootloader at `/dev/cu.usbmodem01`.

**Root cause** (re-verified against MicroPython `master` HEAD 2026-05-11
via raw.githubusercontent.com — the bug is unchanged from v1.26.0;
`ports/esp32/modmachine.c:277-290` at HEAD):

```c
MP_NORETURN static void machine_bootloader_rtc(void) {
    #if CONFIG_IDF_TARGET_ESP32S3 && MICROPY_HW_USB_CDC
    usb_usj_mode();
    usb_dc_prepare_persist();
    chip_usb_set_persist_flags(USBDC_BOOT_DFU);
    #endif
    #if !CONFIG_IDF_TARGET_ESP32P4
    REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
    esp_restart();
    #else
    REG_WRITE(LP_SYSTEM_REG_SYS_CTRL_REG, LP_SYSTEM_REG_FORCE_DOWNLOAD_BOOT);
    esp_restart();
    #endif
}
```

The function has gained an ESP32-P4 branch since v1.26.0 (LP_SYSTEM_REG
path), but the S2/S3 USB-CDC persist gating is identical: the
persist-flag setup is gated **`CONFIG_IDF_TARGET_ESP32S3` only**.
ESP32-S2 has the same native USB-CDC hardware as S3 and needs the
same persist-flag dance for the USB device to come back up in
ROM-bootloader CDC mode after `esp_restart()`.  Without it, the chip
enters download mode at the silicon level but the host's USB stack
can't smoothly re-enumerate the ROM bootloader's CDC interface.

The auto-define block at `mpconfigport.h:373-379` at HEAD has been
widened to include ESP32-P4 (today: ESP32-S2/S3/C2/C3/P4); S2 has
been in the family since at least v1.26.0, so this isn't a recent
regression — it's been latent for as long as ESP32-S2 has had
`machine.bootloader()`.

**CircuitPython gets this right** for both S2 and S3 — see
`.tools/circuitpython-10.2.0/ports/espressif/common-hal/microcontroller/__init__.c:127-128`:

```c
#if defined(CONFIG_IDF_TARGET_ESP32S2) || defined(CONFIG_IDF_TARGET_ESP32S3)
chip_usb_set_persist_flags(USBDC_BOOT_DFU);
#endif
```

That's why `microcontroller.on_next_reset(RunMode.BOOTLOADER)` +
`microcontroller.reset()` works on the same Lolin S2 hardware running
CP 10.1.4.

**Affected:** any ESP32-S2 native-USB-CDC board running MicroPython
without a TinyUF2 bootloader — Lolin S2 mini, FeatherS2 variants
shipped without TinyUF2, Adafruit MagTag, anything else where the
running firmware is the only path to bootloader-mode entry.  The
auto-define block at `mpconfigport.h:364-370` enables
`machine.bootloader()` for the entire ESP32-S2/S3/C2/C3 SoC family
(only `ARDUINO_NANO_ESP32` overrides), so the symptom applies broadly.

**Fix shape (one logical change, two physical edits at HEAD).**  Widen
both the per-SoC include guard at `modmachine.c:271` and the
persist-flag block at `modmachine.c:278`:

```c
// Was — line 271:
#if CONFIG_IDF_TARGET_ESP32S3
#include "esp32s3/rom/usb/usb_dc.h"
#include "esp32s3/rom/usb/usb_persist.h"
#include "esp32s3/rom/usb/chip_usb_dw_wrapper.h"
#endif

// Was — line 278:
#if CONFIG_IDF_TARGET_ESP32S3 && MICROPY_HW_USB_CDC
usb_usj_mode();
usb_dc_prepare_persist();
chip_usb_set_persist_flags(USBDC_BOOT_DFU);
#endif
```

The S3-specific headers live at `esp32s3/rom/usb/*.h`; the S2
equivalents are at `esp32s2/rom/usb/*.h`.  Function signatures
(`chip_usb_set_persist_flags`, `usb_dc_prepare_persist`,
`usb_usj_mode`) match between targets, so the body of
`machine_bootloader_rtc()` can keep its three-call shape — only the
`#if` predicate widens, and the include section needs the same widen
to pull in the right per-SoC USB-ROM headers conditionally.

**Already verified (2026-05-11):**

- Same gap present at MicroPython `master` HEAD — checked
  `ports/esp32/modmachine.c` + `mpconfigport.h` via raw GitHub.  No
  recent commit has touched the S2/S3 persist gating; the function
  has only gained an ESP32-P4 branch since v1.26.0.
- The flag is broadly enabled — the
  `MICROPY_BOARD_ENTER_BOOTLOADER` auto-define block at
  `mpconfigport.h:373-379` covers ESP32-S2/S3/C2/C3/P4 with only
  `ARDUINO_NANO_ESP32` opting out via its own override.

**Still to verify before opening the upstream issue:**

- Whether ESP32-P4 needs the analogous persist-flag setup too.
  P4 was added to the function body but not to the persist block;
  same questionable shape as the S2 case.  If yes, the PR should
  cover P4 alongside S2 — even if no chumicro bench board uses
  P4 today.
- Build a fixed MP for LOLIN_S2_MINI locally, bench-test that
  `machine.bootloader()` produces `/dev/cu.usbmodem01` within the
  chumicro-deploy 8-second poll window — that's the only bench-side
  proof that matters.
- Whether `MICROPY_HW_USB_CDC` is the right secondary predicate for
  S2 (the LOLIN_S2_MINI board does enable native USB-CDC by default;
  worth re-confirming with `make BOARD=LOLIN_S2_MINI` output).

**Filing target:** https://github.com/micropython/micropython/issues
(new issue, then PR if a maintainer responds positively).  Keep the
chumicro-side workaround (manual-entry prompt + helpful non-interactive
error message in `workbench/deploy/src/chumicro_deploy/firmware.py`'s
`_enter_esp32_rom_bootloader`) regardless — even after upstream lands,
some users will be on old MP versions for a while.

**Not blocking anything in chumicro.**  Current behavior is correct
(try, fall back to manual); the upstream fix would just make the
try-path succeed on more boards.

### Workspace-template `run.py` self-bootstrap pattern

**Surfaced 2026-05-02 by the user** during the audit-of-the-audit
follow-up.  Quote: *"i actually dont like what the workspace template
is doing.  i dont like running python through python like that.  it
should be importing and calling modules and methods.  so its the
workspace that is wrong."*

The pattern under question lives in
[`ChuMicro-Workspace-Template/run.py`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/blob/main/run.py)
— a single file that self-bootstraps a venv on first run, pip-installs
the workspace tooling editable, then `os.execv`'s into the new venv's
interpreter to dispatch to `chumicro_workspace.cli.main()`.

**Half resolved 2026-05-12:** the converse direction (fold mono-repo's
`prepare_workspace.py` into `scripts/run.py` to match the template's
single-file shape — old `workspace-template-gaps` gap #8) was rejected.
Folding would force one of: (a) defer ~2500 lines of `run.py`'s
hot-path imports — cascading refactor for marginal benefit, (b) wrap
every import in try/except — code bloat with no upside, or (c) propagate
the `os.execv` re-exec dance the user explicitly dislikes.  The mono-repo
keeps its two-file pattern (stdlib-only `prepare_workspace.py` for cold
start, third-party-heavy `run.py` for everyday tasks).

**Still open:** should the workspace template *adopt* the mono-repo's
two-file pattern — separate `prepare_workspace.py` (stdlib-only,
creates and activates `.venv`, installs `chumicro_workspace`) + thin
`run.py` (imports `chumicro_workspace.cli` and dispatches) — replacing
the current `os.execv` self-bootstrap?

#### Why the current shape exists

`os.execv` is in there because **a Python interpreter that's already
running can't easily load packages from a different Python
installation** — the system Python that launched `run.py` doesn't
share `site-packages` with the freshly-created venv.  Three real
constraints:

1. Cross-version skew: system Python 3.12 + venv created with 3.11 →
   compiled extensions (PyYAML, ruff, msgpack) won't load.
2. `sys.path` manipulation to add the venv's `site-packages` is
   fragile against ABI mismatch.
3. The "self-bootstrap in a single invocation" UX requires the
   bootstrap process to *become* the dispatcher process at the end,
   which means an interpreter switch.

`os.execv` is the one mechanism that does exactly that: replace the
running process image with the venv's Python and re-run the script.
There's no in-process equivalent.

#### Research questions for a future agent

1. What do other Python projects with self-bootstrapping entry points
   (poetry, hatch, Django's `django-admin startproject`) actually do?
   Do any of them avoid the exec-dance?
2. If we drop the self-bootstrap and align with the mono-repo's
   two-file pattern, what does the workspace-template README's
   quickstart look like?  Three commands instead of one?  Is that
   acceptable for the beginner audience the workspace template is
   aimed at?
3. Is the user's concern partly about *audibility* — the subprocess
   output ("creating .venv at ...", "upgrading pip", "installing
   workspace ...") being noisy vs. an import-and-call shape that runs
   silently?  If so, suppressing or restructuring the bootstrap output
   might address the surface concern without restructuring the
   architecture.

#### Constraints any future change must respect

* Decision 0046 left the workspace template's `run.py` as
  "tool-owned, rewritten by `update`" — changes to its shape
  flow to every existing workspace via `update`.  The change
  must be compatible with that update flow.
* The user's broader direction (Decision 0046, 2026-05-02
  audit) is "less doc volume, fewer entry points" — a change
  that *adds* steps to the quickstart cuts against that.

### Boot-cost measurement benchmark for libraries

The 2026-04-25 lazy-loading investigation
(`plans/workstreams/lazy-loading-research.md`) recommends a Tier A /
Tier B classification but lacks quantitative numbers — we have one
data point (`chumicro-msgpack` pure-Python fallback ≈ 700 B heap on
CP per its docstring) and no systematic measurement.  A small
benchmark harness that imports each library on a target board and
reports heap delta + wall-clock time per import would let us back
the tiering with real numbers and catch regressions when a library
inadvertently bloats boot.  Filed as an investigation rather than a
hard task because it's not blocking — revisit when the wifi work
(Phase 3a) gives us a 4-adapter library to compare eager vs lazy on.

### Remaining sub-questions from the workspace workstream

Decision 0029 scoped the `chumicro-deploy` extraction plus a full project
workspace (template repo, UID-based identity, onboarding, import-graph
deploy, REPL TUI).  Decision 0038 (2026-04-26) revised the bootstrap
shape: the workspace template ships as a Git repo (`ChuMicro/ChuMicro-Workspace-Template`)
that users clone, with `init` / `update` folded into the renamed
`chumicro-workspace` package — *not* a pip-installed scaffolder.  Most
of the originally open sub-questions are answered: CLI is `run.py` in
the template (no global install), there is a Python API surface
exposed by `chumicro-workspace`, dependency resolution is import-graph-
driven rather than bundle-manifest, and `.mpy` compilation remains
opt-in where `mpy-cross` is available.

Sub-questions resolved during Phase 6 / 7 execution (2026-04-25 / 26):

- ~~Sequencing across the five libraries — does `chumicro-mqtt` refactor
  need to land before the first full end-to-end "sensor" template?~~
  **Answered:** yes; `chumicro-mqtt` shipped as Phase 6 (commit
  `409f8bf`), then Phase 7's sensor thing depends on it.
- ~~Conditional-import edge cases for import-graph deploy on heavily
  platform-gated modules — is AST parsing sufficient?~~  **Mostly
  answered:** AST parsing IS sufficient for the static `from foo import
  bar` shape once `_imports_from_file` probes the alias as a candidate
  submodule (commit `157a865`).  Truly-dynamic dispatch
  (`importlib.import_module(<runtime-string>)`) is still AST-invisible,
  but no current chumicro library uses that shape; defer until one does.

Sub-questions still open:

- `devices.yml` round-trip contract on unusual user edits (anchors,
  merge keys, multi-doc) — what does the write-safety contract promise
  versus what the underlying YAML library actually preserves?

Related: Decision 0028, Decision 0029, Decision 0038,
`plans/workstreams/archive/project-workspace.md`,
`plans/workstreams/archive/phase-7-integration.md`.


### Is ESP32 NVS worth a dedicated backend?

The settings library design (next-up.md) defers an NVS backend because NVS
has per-key semantics rather than blob storage.  Worth investigating whether
a thin NVS adapter could present the same `read`/`write` protocol, or whether
NVS is different enough to warrant a separate storage abstraction entirely.

### Should examples be runnable on CPython by default?

Currently, simulated examples must run on CPython without hardware.  Hardware
examples are prefixed `circuitpython_*` / `micropython_*`.  As more libraries
interact with hardware, the ratio will shift.  Should the default assumption
change, or should simulation remain the norm with hardware examples as
opt-in?

### How should the bundle pipeline handle multiple mpy format versions?

CircuitPython 11 will likely introduce mpy v7, and MicroPython will eventually
follow.  The bundle pipeline currently assumes a single CP version range
(`circuitpython-10.x-mpy/`) and a single MP format version (`mpy6/`).

Hardcoded single-version assumptions in `bundle_manager.py`:

- `CP_MPY_FOLDER` and `MPY_FORMAT_FOLDER` are scalar constants.
- `build_bundle()` accepts one `cp_mpy_cross` and one `mp_mpy_cross` binary.
  Multi-version needs a dict-like mapping (e.g. `{"10.x": path, "11.x": path}`).
- `build_circup_zips()` scans only `circuitpython-10.x-mpy/` and produces a
  single `10.x-mpy` zip.  Multi-version needs one zip per CP version range.
- `_dependency_to_mpy_mip_reference()` is hardcoded to `mpy6`.
- `generate_bundle_readme()` references single folder names.

Hardcoded assumptions in CI:

- `release.yml` and `promote.yml` build both mpy-cross compilers from source
  via `prepare-mpy-cross` and pass them to `bundle_manager.py` via
  auto-discovery.  Multi-version CI would need to build and invoke multiple
  mpy-cross binaries per runtime.
- `target-runtimes.toml` pins one CP version and one MP version.  Multi-version
  support would need to pin multiple versions for the transition period.

The current architecture handles one version per runtime correctly.  No code
changes are needed until a new mpy format version actually ships, but the
design should anticipate the shape of the change: folder-per-version,
compiler-per-version, zip-per-version, with `target-runtimes.toml` or a
similar config driving the version list.

See Decision 0024 (naming conventions section) for the folder scheme.

### Should the bundle repo carry per-library version tags for mip pinning?

mip supports version pinning via `version="branch-or-tag"`, but the bundle
repo's release tags are date-based bundle snapshots (e.g. `20260410`), not
per-library versions.  A user who wants "timing v0.1.25" cannot map that to
a bundle tag without reading release notes.

circup has no version-pinning capability at all — it always pulls the latest
bundle release.  That's an upstream limitation we can't fix.

Options considered:

1. **Per-library tags** like `chumicro-timing-0.1.25` on the bundle repo.
   mip users could pin with `version="chumicro-timing-0.1.25"`.  Downside:
   tag proliferation — every library release adds a tag.  The release pipeline
   would need to create them.
2. **Do nothing** — document that mip pins to date-based bundle tags and
   circup always gets latest.  Users who need a specific version download the
   release zip manually.
3. **Per-library branches** (e.g. `chumicro-timing/latest`) — more complex,
   unclear benefit over tags.

Not blocking any current work.  Worth revisiting if users request pinning or
if the library count grows enough that bundle-level snapshots cause unwanted
upgrades of unrelated libraries.

Related: Decision 0018 (bundle architecture), Decision 0024 (mpy folder
serving).

### What does "contributor-ready" look like beyond docs?

CONTRIBUTING.md, issue templates, and PR templates exist.  But contributor
experience also includes: response time expectations, mentoring patterns
for agent-assisted contributors, and community channels.  What's the
minimum viable contributor experience before actively seeking
contributions?

### Should we offer a "drive mode toggle" tool for CircuitPython boards?

CircuitPython's CIRCUITPY USB drive is convenient for beginners but limits
power users: Python code can't write to the filesystem while USB has write
access (`storage.remount` fails with "Cannot remount path when visible via
USB"), the FAT partition has write-endurance concerns for datalogging, and
the auto-reload-on-save behavior interferes with multi-file deployments.
MicroPython doesn't have this problem — the filesystem is just a filesystem.

CircuitPython does provide escape hatches:

- `storage.disable_usb_drive()` in `boot.py` hides the USB drive entirely,
  giving Python code full filesystem access.  Deploy via serial instead of
  drag-and-drop.
- `storage.remount("/", readonly=False)` in `boot.py` gives Python write
  access but makes the USB drive read-only to the host.
- A physical button check in `boot.py` can toggle between modes at boot.

The idea: provide a tool (in this workspace now, eventually in
`chumicro-deploy` as a published package) that can put a connected
CircuitPython board in and out of "drive mode" by writing or updating its
`boot.py`.  Concretely:

1. **"Development mode"** — `storage.disable_usb_drive()` in `boot.py`.
   No CIRCUITPY drive.  Full filesystem from Python.  Deploy via serial
   transport.  Board behaves more like MicroPython.
2. **"Drive mode"** (default CircuitPython behavior) — no `boot.py`
   override, CIRCUITPY drive is visible, drag-and-drop works.
3. **"Hybrid mode"** — `boot.py` checks a GPIO pin or button at boot to
   decide which mode to enter.  Hold a button during reset → drive mode;
   normal boot → development mode.

The tool would:

- Detect the board's current mode by reading `boot.py` via serial.
- Switch modes by writing a new `boot.py` and triggering a reset.
- Optionally configure the GPIO pin for hybrid mode.
- Work as a `run.py` subcommand locally (`python scripts/run.py board-mode`)
  and eventually as a `chumicro-deploy` CLI command.

This would also benefit device testing — flash-mode tests (Decision 0028)
currently require the CIRCUITPY drive to be mounted.  A board in
"development mode" could use serial-only flash deployment instead, avoiding
the host-OS USB drive dependency entirely.

Open sub-questions:

- Is serial-only flash deployment feasible on CircuitPython without the USB
  drive?  `storage.remount` from the REPL may still fail if the board
  entered with USB active.  Needs investigation on actual hardware.
- Should hybrid mode be the default recommendation?  It's the most flexible
  but adds a physical-button dependency.
- Drop the CIRCUITPY-drive dependency entirely for a "development mode" board?
  Today the drive is resolved at deploy time by scanning mounted `CIRCUITPY*`
  volumes and UID-matching the connected board against each `boot_out.txt`;
  a serial-only path would remove that lookup altogether.

Not worth implementing now — the device transport layer works for current
needs.  `chumicro-deploy` extraction is done (project-workspace Phase 1,
2026-04-22) and did not change the CIRCUITPY-drive dependency for CP flash
mode; drive-mode toggling would now be a feature added on top of the
shipped `chumicro-deploy` package rather than a preparatory refactor.
Revisit when the CIRCUITPY drive becomes a real friction point in daily
development.

Related: Decision 0027 (device testing), Decision 0028 (deploy modes), Decision 0032 (workbench folder).

### Should we use a unified logging framework across scripts?

Currently scripts use `print()` for warnings and status.  A unified
`logging` setup would allow log levels, consistent formatting, and
filtering — but only makes sense if applied across all scripts, not
piecemeal.  Parked for a rainy day.

### How does a unit-test file opt out of the on-device sweep? (Decision 0068 Phase 4b.2 issue i)

The `device-unit` sweep assumes every `libraries/<n>/tests/test_*.py`
(non-`_pytest`) is a cross-runtime *device* test.  The 6
`test_{mp,cp}_{adapter,*backend}.py` files break that: they import a
runtime-specific source module (e.g. `chumicro_kvstore._backends.mp_nvs`,
correctly `__chumicro_runtimes__=("micropython",)`) which the
Decision 0044 deploy filter *correctly* strips from a non-matching
board → `ImportError` on device.  They are correct on unix-port/CPython
(verified green there) and not on-device-eligible by construction (a
matching real board would also fail their
`test_runtime_acquisition_raises_*_on_cpython` since real `esp32`
exists).  Need a classification mechanism for "unix-port/host lane
only — not the device-unit sweep," parallel to how `*_pytest.py` is
CPython-only.  Candidate: a per-file marker the `device-unit`
collection honors (cf. Decision 0069's `__chumicro_test_support__`
shape).  Likely its own ADR.  Workstream:
[`deploy-mode-unification.md`](workstreams/deploy-mode-unification.md)
4b.2(i).  Related: Decision 0068, Decision 0044, Decision 0037,
Decision 0069.

### How does the on-device sweep survive a full-scale run on tier-floor flash? (Decision 0068 Phase 4b.2 issue ii)

A full Pi Pico W CP `--deploy-mode flash` sweep (254 s, 663 tests)
degrades partway: libraries that pass standalone (`runner/test_core`
61/61, `wifi/test_wifi` 41/41) show `.FFFF…` (first test of a file
passes, rest fail) from ~67 % onward — transport/board dies
mid-session at scale.  Suspected: FAT/flash churn from hundreds of
rsync `--delete`+restage cycles on the 491 KB drive, or
heap/handle exhaustion.  Reproduced 2× (deterministic, not the
transient evicted-transport state seen earlier).  Needs a design
approach: periodic transport reconnect / soft-reset between
libraries / chunk the sweep into sub-sessions / document a per-board
library ceiling.  The retired "~16-lib RAM-session OOM" sub-question
is the RAM-mode analogue of this.  Workstream:
[`deploy-mode-unification.md`](workstreams/deploy-mode-unification.md)
4b.2(ii).  Related: Decision 0068.
