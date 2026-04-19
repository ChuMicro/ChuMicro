# Open Questions

Unresolved questions that need thought but aren't blocking active work.
When a question is resolved, move it to the **Resolved** section with a
one-line answer and link to the decision or commit that settled it.

Questions that become blocking should move to `next-up.md` (Blocked section).
Questions that lead to structural tradeoffs should become decisions in
`plans/decisions/`.

---

## Active

### When should the transport layer be extracted into `chumicro-deploy`?

Decision 0028 envisions a standalone pip-installable package for deploying
user projects to MicroPython and CircuitPython boards.  The transport layer
in `support/device_transport/` is shaped for extraction, but questions remain:

- What public API should `chumicro-deploy` expose?  CLI only, or also a
  Python API?
- Should it handle dependency resolution from bundle repos, or just raw
  file deployment?
- Should a companion `chumicro-project-template` repo exist, and what does
  its structure look like?
- Should `.mpy` compilation be built-in or opt-in?

Not blocking any current work.  Phase 2 (CircuitPython transport) and deploy
modes (Decision 0028) are complete.  Revisit when the transport layer
stabilizes after Phase 3 (IDE integration) and real-world usage.


### Is ESP32 NVS worth a dedicated backend?

The settings library design (next-up.md) defers an NVS backend because NVS
has per-key semantics rather than blob storage.  Worth investigating whether
a thin NVS adapter could present the same `read`/`write` protocol, or whether
NVS is different enough to warrant a separate storage abstraction entirely.

### How much test boilerplate can be reduced?

`next-up.md` mentions "explore test ergonomics."  Common patterns across test
files (importing fakes, constructing services with FakeTicks, asserting on
check/handle cycles) might benefit from shared fixtures or a small test DSL.
Risk: test-only abstractions that obscure what's being tested.

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
experience also includes: good-first-issue labeling, response time
expectations, mentoring patterns for agent-assisted contributors, and
community channels.  What's the minimum viable contributor experience
before actively seeking contributions?

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
- What's the interaction with `circuitpy_drive_path` in `devices.yml`?
  A board in development mode wouldn't have a drive path.

Not worth implementing now — the device transport layer works for current
needs.  Revisit when `chumicro-deploy` extraction begins or when the CIRCUITPY
drive becomes a real friction point in daily development.

Related: Decision 0027 (device testing), Decision 0028 (deploy modes).

### Should we use a unified logging framework across scripts?

Currently scripts use `print()` for warnings and status.  A unified
`logging` setup would allow log levels, consistent formatting, and
filtering — but only makes sense if applied across all scripts, not
piecemeal.  Parked for a rainy day.

---

## Resolved


### Should the coverage gate be higher?

Resolved by Decision 0025: dual thresholds — 85 % baseline for humans
(in `pyproject.toml`), 94 % for agents (via `--coverage-threshold 94`).

