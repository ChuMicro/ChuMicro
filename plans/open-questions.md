# Open Questions

Unresolved questions that need thought but aren't blocking active work.
When a question is resolved, move it to the **Resolved** section with a
one-line answer and link to the decision or commit that settled it.

Questions that become blocking should move to `next-up.md` (Blocked section).
Questions that lead to structural tradeoffs should become decisions in
`plans/decisions/`.

---

## Active

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

#### What the user's pushback implicitly proposes

"It should be importing and calling modules and methods" suggests
splitting bootstrap from dispatch:

* `run.py` becomes a thin dispatcher that imports
  `chumicro_workspace.cli` and calls its main.  Only runs after the
  venv exists and is on the user's `PYTHONPATH`.
* Bootstrap becomes a separate step the user does explicitly —
  either standard Python tool conventions (`python -m venv .venv`,
  `.venv/bin/pip install -e .`, `.venv/bin/python run.py setup`)
  or a separate one-shot script (the mono-repo's
  `prepare_workspace.py` pattern).

This is what the chumicro mono-repo already does:
`scripts/prepare_workspace.py` for fresh-clone bootstrap (302 lines,
stdlib + subprocess only at top), `scripts/run.py setup` for the
idempotent everyday refresh (heavy imports at top).

#### Honest evaluation (Claude, 2026-05-02)

The user's instinct that "running python through python feels off"
is aesthetically fair, but the technical claim "import and call
modules" can't directly replace the `os.execv` step — the running
interpreter genuinely can't switch to a different Python's
site-packages mid-execution.  However, the user's *deeper* point is
valid: the workspace template chose "self-bootstrap in one
invocation" as the UX, and that choice forces the exec-dance.  An
alternative UX ("user creates the venv themselves, then runs
`run.py`") sidesteps the dance entirely and matches every other
Python project's bootstrap convention.

So the open question is **whether the convenience of one-command
self-bootstrap is worth the architectural quirk of the exec-dance**,
or whether the workspace template should align with conventional
Python project bootstrap (mono-repo's pattern: separate
`prepare_workspace.py`).

#### Research questions for a future agent

1. Is `os.execv` truly the only way to self-bootstrap in a single
   Python invocation, or is there a mechanism (interpreter-swap
   library, `importlib` reload tricks) that avoids it?  (My read:
   no, but a focused research pass should confirm.)
2. What do other Python projects with self-bootstrapping entry
   points (e.g. poetry's `poetry install`, hatch's `hatch env`,
   Django's `django-admin startproject`) actually do?  Do any of
   them avoid the exec-dance?
3. If we keep the self-bootstrap UX, can the exec-dance be made
   less visible (e.g. wrapped in a single helper that hides the
   `subprocess.run` + `os.execv` chain)?
4. If we drop the self-bootstrap and align with mono-repo's
   pattern (separate `prepare_workspace.py` + `run.py setup`),
   what does the workspace-template README's quickstart look like?
   Three commands instead of one?  Is that acceptable for the
   beginner audience the workspace template is aimed at?
5. Is the user's concern partly about *audibility* — the
   subprocess output ("creating .venv at ...", "upgrading pip",
   "installing workspace ...") being noisy vs. an import-and-call
   shape that runs silently?  If so, suppressing or restructuring
   the bootstrap output might address the surface concern without
   restructuring the architecture.

#### Constraints any future change must respect

* Mono-repo `scripts/run.py` — the chicken-and-egg that
  `prepare_workspace.py` solves there is the same problem the
  workspace template's `run.py` solves with `os.execv`.  Any
  change should pick a shape that works for both, or document
  why they need to differ.
* Decision 0046 left the workspace template's `run.py` as
  "tool-owned, rewritten by `update`" — changes to its shape
  flow to every existing workspace via `update`.  The change
  must be compatible with that update flow.
* The user's broader direction (Decision 0046, 2026-05-02
  audit) is "less doc volume, fewer entry points" — a change
  that *adds* steps to the quickstart cuts against that.

### Library dependency policy (hard-injection vs. lazy default vs. hard dep)

Today every chumicro service takes its dependencies via constructor injection
(e.g. `MQTTClient(sockets=…)`).  Clean for testing, but creates an onboarding
cliff — users without prior context don't know they need to install
`chumicro-sockets` separately, and every example carries injection boilerplate.

`plans/workstreams/library-pipeline.md` §"Dependency policy" lays out three
options (A: hard-injection, B: lazy default with optional dep, C: hard dep
with override) and recommends a split: **hard-dep + override** for *core
infrastructure* (sockets, runner, timing) so libraries work on a single
`pip install`; **callbacks-only** for *decoration / observability*
(events, logging, the proposed presence/feedback layer) so they can never
become required deps.  Decide before the next batch of libraries
(logging, ntp, events) lands and audit existing `pyproject.toml` files
against it.  Should land as `plans/decisions/NNNN-library-dependency-policy.md`.

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
`plans/workstreams/project-workspace.md`,
`plans/workstreams/phase-7-integration.md`.


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

### Shared `FakeTime` / fake-clock home for workbench packages

`chumicro_deploy.testing` ships `FakeTime` (seconds-domain, host-side,
satisfies the `TimeSource` protocol the transport accepts via
constructor injection).  The 2026-04-24 audit moved it from the
internal-only `chumicro_abstractions` package — co-locating fakes with
the package they test, per Decision 0010 — and as a one-consumer fake
this is the right shape.

But the planned `chumicro-repl` workbench package (and likely future
ones) will probably need the same seconds-domain time fake to test
their own retry / polling loops.  At that point we have three options:

1. **Duplicate the ~80 lines** of `FakeTime` into each new workbench
   package's `testing.py` (the Decision 0010 default).  Cheap for one
   or two consumers; starts feeling silly past three.
2. **Have `chumicro-repl` depend on `chumicro-deploy`** just to import
   `FakeTime`.  Wrong direction — repl shouldn't need deploy.  Reject.
3. **Hoist into a shared workbench-fakes package** — e.g. a published
   `chumicro-workbench-fakes` (or similar name) that every workbench
   package depends on for shared host-side test fakes.  Adds a new
   PyPI surface and a release lifecycle, but solves the recurrence
   cleanly.

Resolution criterion: when the **second** workbench package needs
`FakeTime`, duplicate.  When the **third** does, do option 3.  Until
then, the per-package pattern wins — duplication of 80 lines is
cheaper than the abstraction tax of an extra published package.

---

## Resolved


### Is `test-everything` the right name for an opt-in-device sweep?

Resolved by the 2026-04-24 `run.py` command audit: dropped
`test-everything` entirely.  The CI-mirror sweep is `preflight`
(append `--with-functional` to also run hardware-gated suites);
hardware-only runs are `test-functional` (libraries + workbench)
or the individual `test-libraries-functional` /
`test-workbench-functional` commands.  The unit-only deep sweep
that prompted the original question is `test-all-runtimes`.

### Should the coverage gate be higher?

Resolved by Decision 0025: dual thresholds — 85 % baseline for humans
(in `pyproject.toml`), 94 % for agents (via `--coverage-threshold 94`).

### Lolin S2 CP flash deploys occasionally surface `OSError: [Errno 5]`

Resolved by [`75dfdaf` "Fix one-cycle-delayed capture on slow CP flash
deploy"](https://github.com/ChuMicro/ChuMicro/commit/75dfdaf) and
[`2163927` "Add post-visible settle delay after board sees new
entrypoint"](https://github.com/ChuMicro/ChuMicro/commit/2163927).
`CircuitpythonTransport._wait_for_board_to_see_entrypoint` polls
`os.stat` over raw REPL until the board reports the just-written
entrypoint at its new length, then sleeps
`_BOARD_FILE_VISIBLE_POST_SETTLE` (0.5 s) to let in-flight flash /
FAT bookkeeping quiesce before `Ctrl-D` triggers the soft-reboot.
Paired with the UID-based drive verification from the sibling branch,
`demo_recovery_hand_holding.py` "all / 1,2" is now 5/5 green across
both CP boards (40/40 scenarios, zero EIOs, zero stale captures).
