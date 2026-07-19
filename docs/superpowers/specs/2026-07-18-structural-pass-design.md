# Deep structural pass before stable launch

Date: 2026-07-18
Status: awaiting user review

## Context

The stable PyPI promotion wave is mid flight (4 of 17 projects promoted).
Decision 0092 makes breaking changes nearly free until real users pin stable
versions, and expensive after.  The user has chosen to pause the stable wave
and land a deep structural pass first.

Three fresh-eyes sweeps of the repo (product gaps, code architecture, decision
records) plus outside research produced the diagnosis this design answers:

- The repo carries roughly 124,000 lines of host tooling (workbench plus
  scripts) against roughly 14,000 lines of shipped library source.
  `scripts/run.py` alone is 4,222 lines with 71 subcommands.
- The simplest networked program (`demos/requests_fetch/app.py`, 56 lines)
  requires a beginner to learn about 13 concepts.  There is no high-level
  front door.
- Decision 0093 duplicates transport-factory plumbing into five libraries.
  The copies drifted into three incompatible contracts once already
  (finding M77, July 2026 audit) before being realigned by hand.
- The 2026-07-04 census found 43 check/handle service registrations and
  zero application-code generator tasks, yet the generator lane is the
  README's flagship pitch.  The user's call: keep generators and make them
  the primary idiom users are taught.  The zero-usage figure mostly
  reflects that no user applications exist yet.
- The asyncio ban in Decision 0087 cites a 2021 Adafruit issue as current
  evidence.  CircuitPython asyncio has been maintained through 2026 and the
  citation needs re-verification.
- Adoption plumbing is missing: no changelog in any library, no security
  policy, no way to try the project without a physical board, a parked
  `logging` library still advertised in the README table, and a 2,530-line
  `webui/` directory referenced nowhere.

Decisions the sweeps validated and this design leaves alone: the runner
reactor (Decision 0080, device validated on four boards), the three-runtime
support with CPython as the host test seam (Decision 0049), the single
runtime-dispatch seam in sockets, per-library install independence, and the
test discipline (about 2.3 lines of test per line of source).

## Goals

1. Land every public-API break before the stable wave resumes, so stable
   users never experience them.
2. Give the project a front door: a facade library and a generator-first
   README story that take a first program from about 13 concepts to about 4.
3. Shrink the maintained surface with measurements attached: no copied
   factory code, the cosmetic lint tail retired, `run.py` decomposed,
   the minifier scoped to the one job that needs it.
4. Ship the adoption plumbing users expect: changelogs, a security policy,
   a no-hardware demo, a truthful README.
5. Resume and finish the stable wave (17 of 17) as the final step.

## Non-goals

- CircuitPython Community Bundle listing (user's explicit call).
- New device capabilities: OTA update, WiFi provisioning, mDNS, power
  management, watchdog.  These are recorded as post-launch roadmap
  candidates and deliberately not designed here.
- Any change to the runner reactor, the three-runtime model, the sockets
  adapter seam, or per-library install independence.
- Backwards-compatibility shims of any kind (Decision 0092 stands).

## Phase 1: library-side structural changes

These are the API breaks.  Stable promotion stays paused until they land.

### 1.1 Shared transport-factory package (supersedes Decision 0093)

A new small library, `chumicro-transport-factory`, replaces the five copied
`sockets_factory.py` modules in mqtt, websockets, requests, http_server, and
ntp (today 33, 25, 16, 47, and 8 lines respectively).  The existing
skip-factories opt-out (Decision 0062) is preserved.  The five libraries gain
one dependency edge; in exchange the drift class that already produced three
incompatible contracts is structurally eliminated.  A new decision record
supersedes 0093 and records the measured flash cost of the extra package on
the smallest supported board.

### 1.2 Facade library: chumicro-app

A thin meta-library (target under 400 lines of source) that wires config
loading, the WiFi service, the Runner, and a transport factory into one
object.  A first program becomes: construct the app, add a generator or a
periodic callback, run.  It depends on existing libraries and adds no code to
them.  Per-library independence is untouched; the facade is additive.
Networking clients beyond WiFi (mqtt, requests) attach through optional
extras rather than hard dependencies.  The facade gets its own flash-size
budget and the standard library scaffold (docs, examples, tests,
functional tests) via the new-library lifecycle.

### 1.3 Generator-first teaching

The README's first full example uses the facade with a generator.  Library
guides for requests, websockets, and mqtt lead with the generator surface and
present check/handle as the service-author idiom.  Both lanes remain public
API.  Decision 0087 and Decision 0089 are amended to record the new teaching
order and the refreshed evidence, not to change the contract.

### 1.4 Asyncio stance refresh

Re-verify the CircuitPython asyncio socket and stream state against 2026
reality and replace the 2021 citation in Decision 0087 with current evidence.
Narrow the lint ban from "no async keywords anywhere" to "no asyncio
scheduler inside device libraries".  Build the small polling bridge (drive a
Runner from inside an asyncio event loop) now, as a separate optional module
or package, so the first asyncio user has a supported path instead of a
refusal.  The bridge ships with tests on CPython and MicroPython's asyncio.

### 1.5 Wait-vocabulary consolidation, audit gated

One documented mental model covering Signal, wait_for, Deadline, Rate,
ReadWait, WriteWait, and the runner's deadline and interest tokens.  The
audit lists every primitive, its unique capability, and its users.  A
primitive is removed only if the audit shows it has zero unique capability or
zero users; otherwise it stays and the documentation carries the load.
Decision 0095 already refereed this vocabulary once, so removals need
evidence, not taste.

### 1.6 Service contract declared

The runner's optional service methods (check, handle, io_interest, io_socket,
next_deadline, io_error) become an explicitly documented protocol with a
validation helper in the runner's testing module that checks a service
implements a coherent subset.  No members are added or removed; Decision 0097
already slimmed the contract and this item only makes it visible and
checkable.

### 1.7 Orphan dispositions

- `logging` leaves the README libraries table and the libraries index while
  it remains parked (Decision 0107).  Advertising an uninstallable library
  is a false claim and fails the project's own measured-claims rule.
- `compat` is checked for real importers.  If nothing imports it, its single
  polyfill moves to the one consumer that needs it and the library is parked
  or deleted; if importers exist, it stays and the finding is recorded as
  wrong.

## Phase 2: tooling and process diet

No public-API coupling.  Runs after Phase 1 or interleaved where independent.

### 2.1 Minifier scoped down (amends Decision 0090)

The ship-.mpy deploy path (already phase 0 of the library-size-cut
workstream) becomes the default mechanism for shrinking deploys.  The
hand-rolled docstring and comment stripper retires everywhere the .mpy path
covers.  The chunked-exec device test path needs line-number sync and small
boards cannot stage full docstrings, so whatever that path still requires is
kept, and the retirement is gated on measurements showing the .mpy path
covers each retired use.

### 2.2 REPL package: scriptable core stays, TUI frozen

The Python API in workbench/repl drives the bench and pytest-device and
stays.  The interactive TUI surface is frozen: no new features, and it
becomes a parking candidate.  Decision 0027 deferred a REPL tool and it was
built anyway; the freeze stops that growth without breaking the bench.

### 2.3 Lint tail retired

The prose-cosmetic rules are removed: the CHU024, CHU029, CHU031, CHU032
family (ADR preamble policing, summary length, noqa separator characters,
docstring phrasing bans), plus any rule in the same class found during
implementation.  Code-shape rules and doc-command-parity rules stay; Decision
0074's evidence supports exactly that split.  A new rule requires
0074-grade evidence (a demonstrated, shipped drift class) before any future
lint lands.

### 2.4 run.py decomposed

Audit the 71 subcommands for dead ones, delete those, and split the file
into modules under a thin entry point with a target of under 1,500 lines for
the entry file.  Subcommands that duplicate chumicro-workspace functionality
move there or die.

### 2.5 webui resolved

If anything real uses webui/ (Decision 0100 is its only documentation), it
gets a README and a line in the repo map.  If nothing does, it gets a PARKED
marker like logging.  Either way the repo stops carrying an unexplained
top-level subsystem.

### 2.6 Process rule going forward

Decision records are for structural tradeoffs only, per the existing rule in
plans/decisions/README.md, now applied to itself: no decision records about
decision-record formatting.  New lint rules and new process artifacts carry
the same evidence bar as 2.3.

## Phase 3: adoption plumbing and relaunch

### 3.1 Changelogs

Every library gets a CHANGELOG.md seeded from git history at its current
version, and the release flow appends to it from then on.  The existing
version gate (Decision 0113 exempts docstring-only diffs) already defines
what is release relevant; the changelog rides the same definition.

### 3.2 Security policy and conduct

SECURITY.md at the repo root with a private reporting path, given that the
project ships TLS and networking code.  A standard code of conduct file
alongside it.

### 3.3 No-hardware demo

One demo under demos/ that runs entirely on CPython with no board attached,
runnable in about a minute from a clone.  It exercises a real exchange (for
example an HTTP fetch plus a simulated LED and a timer) through the same
Runner, so an evaluator without silicon can watch the concurrency story
work.

### 3.4 README truth pass

The facade example leads.  The logging row leaves the table.  The repo map
gains webui/, support/, and scripts/.  Badges (CI, PyPI) land once the
stable wave finishes.  Claims that depend on repos going public are checked
against what is actually live at relaunch time.

### 3.5 Workspace template first-run fixes

The known first-contact breakages recorded in next-up.md land with this
pass: the ruff line-length mismatch that breaks run.py lint after library
add, and the new --library prefix branding.

### 3.6 Relaunch

The remaining stable promotions (13 of 17 at time of writing) resume only
after Phases 1 and 2 are green on the experimental channel and the device
matrix.  The stable wave finishing at 17 of 17, with the facade published
and the README truthful, is the definition of done for this design.

## Testing and migration mechanics

- Every Phase 1 break follows the existing discipline: cross-runtime lanes
  green, the four-board device sweep for anything touching sockets, wifi, or
  deploy, and flash-size budgets re-baselined where code moves between
  packages.
- Under Decision 0092, each break lands as a single break-plus-migrate
  commit across the mono-repo and the workspace template.
- Each structural change carries its decision record: one superseding 0093,
  amendments to 0087 and 0089, a scope reduction on 0090, and the audit
  results for 1.5 and 1.7 recorded wherever they land.
- The experimental channel absorbs all churn and acts as the canary; stable
  stays paused throughout.

## Risks

- The deep pass could itself become the project.  Mitigation: Phases 1 and 2
  are closed lists; anything discovered mid-pass goes to plans/next-up.md
  for after relaunch, not into this design.
- The facade could grow into a framework.  Mitigation: the 400-line target
  and its own flash budget are acceptance criteria, not aspirations.
- Retiring the minifier could break the device test chunker.  Mitigation:
  measurement-gated retirement in 2.1.
- The launch delay is open ended if "green" is undefined.  Definition:
  Phase 1 items all published on experimental, device sweep passing on the
  registered board matrix, preflight green.

## Success criteria

1. Zero copied transport-factory code in library sources.
2. A first program using the facade touches at most 5 concepts, counted the
   same way the 13 was counted (distinct classes, functions, and protocols a
   reader must understand in the minimal working example).
3. The prose-cosmetic lint rules are gone from the checks package.
4. run.py entry file under 1,500 lines and no dead subcommands.
5. Every published library has a changelog; SECURITY.md exists; the README
   contains no claim that a fresh clone cannot verify.
6. A no-hardware demo runs on a bare CPython clone in about a minute.
7. Stable wave complete at 17 of 17 with the facade included.
