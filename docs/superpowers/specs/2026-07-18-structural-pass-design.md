# Structural pass before stable launch

Date: 2026-07-18 (revised same day after user review)
Status: awaiting user review of this revision

## Context

The stable PyPI promotion wave is mid flight (4 of 17 projects promoted).
Decision 0092 makes breaking changes nearly free until real users pin stable
versions, and expensive after.  The user chose to pause the stable wave, land
the structural items below first, and let the roughly 2026-07-19 promotion
window lapse deliberately.

Three fresh-eyes sweeps of the repo (product gaps, code architecture,
decision records) plus outside ecosystem research fed a larger candidate
list.  The user reviewed it item by item on 2026-07-18; this revision keeps
only what survived.  Rejected items are recorded in Non-goals so future
sessions do not re-propose them.

Findings that motivated the surviving items:

- Decision 0093 duplicates transport-factory plumbing into five libraries
  (mqtt 33 lines, websockets 25, requests 16, http_server 47, ntp 8).  The
  copies drifted into three incompatible contracts once already (finding
  M77, July 2026 audit) before being realigned by hand.  Each copy is a
  config-key validation wrapper around `chumicro_sockets.connector`; the
  natural home is the sockets package itself.
- The README already teaches generators first (Decisions 0087 and 0089);
  the three networking library guides do not yet match it.
- `scripts/run.py` is 4,222 lines with 71 subcommands in one file.
- The parked `logging` library still appears in the README libraries table,
  which fails the project's own measured-claims rule.
- No security policy exists, and every demo requires a physical board.

Decisions the sweeps validated and this design leaves alone: the runner
reactor (Decision 0080), the three-runtime support with CPython as the host
test seam (Decision 0049), the generator plus check/handle dual surface
(user call: keep both, teach generators first), the sockets runtime-dispatch
seam, per-library install independence, and the test discipline.

## Goals

1. Land the public-API break (factory relocation) before the stable wave
   resumes, so stable users never experience it.
2. Finish the generator-first teaching the README already started.
3. Decompose `run.py` and delete dead subcommands.
4. Ship the accepted adoption items: security policy, conduct file,
   no-hardware demo, README truth fixes, workspace-template first-run fixes.
5. Resume and finish the stable wave (17 of 17) as the final step.

## Non-goals (user rulings, 2026-07-18)

Rejected in this session's review.  Do not re-propose without new evidence
and an explicit user ask:

- A new `chumicro-transport-factory` package.  The glue moves into
  `chumicro_sockets` instead (see 1.1).
- A `chumicro-app` facade library.  Wiring config, WiFi, runner, and
  transports together is the workspace template's job, not a mono-repo
  library.
- Any asyncio stance change: no evidence refresh, no bridge, no lint-ban
  rescoping.
- Any change to the minifier (Decision 0090 stands as is).
- Freezing or parking the REPL TUI.
- Retiring the prose-cosmetic lint rules.  They are built and working.
- Any webui change.  Decision 0100 already records its shape and
  deliberately keeps it out of the README and out of publishing.
- Per-library changelogs.
- CircuitPython Community Bundle listing.
- New device capabilities (OTA update, WiFi provisioning, mDNS, power
  management, watchdog).  Post-launch roadmap candidates only.
- Backwards-compatibility shims of any kind (Decision 0092 stands).

## Phase 1: library surface and teaching

These gate the stable wave; 1.1 is the API break.

### 1.1 Transport-factory glue moves into chumicro_sockets

A `factories` module inside `chumicro_sockets` provides the connect, listen,
and UDP factory variants.  The five per-library `sockets_factory.py` copies
are deleted, and examples and guides import from `chumicro_sockets` instead.
The config import stays lazy so the sockets package gains no hard dependency
edge.  A new decision record supersedes 0093 with this shape and records the
measured flash delta on the smallest supported board.

Dependency-direction constraint: the factories are generic.  They take host
and port (or config key names) as parameters; protocol-specific key names
like `mqtt.broker.host` stay in each protocol library's examples and guide.
The sockets package must not learn any protocol's config namespace.  The
injection seam is unchanged either way: protocol libraries keep taking a
`transport_factory` argument and never import a transport implementation.
The move actually tightens this, since today each protocol package ships
glue that lazily imports `chumicro_sockets`, and a bring-your-own-socket
deploy carries that dead module; afterward the protocol packages contain no
reference to sockets at all.

### 1.2 Finish generator-first teaching

The requests, websockets, and mqtt guides lead with their generator
surfaces and present check/handle as the service-author idiom, matching the
README.  Both lanes remain public API; no contract change.  Decisions 0087
and 0089 get a note recording the teaching order.

### 1.3 Wait-vocabulary documentation

One page giving the surviving wait primitives (Signal, wait_for, Deadline,
Rate, ReadWait, WriteWait, the runner's tokens) a single mental model and a
"which one do I reach for" table.  Documentation only.  Prior pruning
already happened (0095 refereed the vocabulary, 0096 deleted the events
library, 0097 slimmed the io contract); nothing is removed here without
evidence of zero unique capability and zero users, and none is expected.

### 1.4 Service contract written down

The runner's optional service methods (check, handle, io_interest,
io_socket, next_deadline, io_error) become an explicitly documented
protocol, with a helper in the runner's testing module that validates a
service implements a coherent subset.  This is not a new execution model
and changes zero runtime behavior; it documents the duck type that already
exists.

### 1.5 Orphan dispositions

- `logging` leaves the README libraries table and the libraries index while
  it remains parked.
- `compat` is checked for real importers.  If nothing imports it, its
  polyfill moves to the one consumer that needs it; if importers exist, it
  stays and the sweep finding is recorded as wrong.

## Phase 2: tooling

### 2.1 run.py decomposed

Audit the 71 subcommands for dead ones, delete those, and split the file
into modules under a thin entry point with a target of under 1,500 lines
for the entry file.  Subcommands that duplicate chumicro-workspace
functionality move there or die.

### 2.2 Process rule going forward

Decision records are for structural tradeoffs only, per the existing rule
in plans/decisions/README.md.  New lint rules and new process artifacts
require demonstrated, shipped drift (the Decision 0074 evidence bar) before
they land.

## Phase 3: adoption items and relaunch

### 3.1 Security policy and conduct

SECURITY.md at the repo root with a private reporting path, given that the
project ships TLS and networking code.  A standard code of conduct file
alongside it.

### 3.2 No-hardware demo

One demo under demos/ that runs entirely on CPython with no board attached,
runnable in about a minute from a clone.  It exercises a real exchange (for
example an HTTP fetch plus a simulated LED and a timer) through the same
Runner, so an evaluator without silicon can watch the concurrency story
work.

### 3.3 README truth pass

The logging row leaves the table.  Claims that depend on repos being public
are checked against what is actually live at relaunch time.  Badges (CI,
PyPI) land once the stable wave finishes.

### 3.4 Workspace template first-run fixes

The known first-contact breakages recorded in next-up.md land with this
pass: the ruff line-length mismatch that breaks run.py lint after library
add, and the new --library prefix branding.

### 3.5 Relaunch

The remaining stable promotions (13 of 17 at time of writing) resume after
Phases 1 and 2 are green on the experimental channel and the device matrix.
Relaunch is in this spec as the exit criterion: the session's diagnosis was
that the repo optimizes internals instead of reaching users, so the pass
counts as done only when the stable wave finishes at 17 of 17.  Without
this item the cleanup has no defined end.

## Testing and migration mechanics

- 1.1 follows the existing discipline: cross-runtime lanes green, the
  four-board device sweep (it touches sockets and every networking
  library's examples), and flash-size budgets re-baselined for the code
  moving into the sockets package.
- Under Decision 0092, the factory relocation lands as a single
  break-plus-migrate commit across the mono-repo and the workspace
  template.
- Decision records: one superseding 0093; notes on 0087/0089 for teaching
  order; audit results from 1.3 and 1.5 recorded wherever they land.
- The experimental channel absorbs the churn; stable stays paused until
  Phases 1 and 2 are green.

## Risks

- The pass could grow back toward the rejected list.  Mitigation: the
  phases are closed lists, the Non-goals section names the rejections with
  their date, and anything discovered mid-pass goes to plans/next-up.md for
  after relaunch.
- The launch delay is open ended if "green" is undefined.  Definition:
  Phase 1 and 2 items published on experimental, device sweep passing on
  the registered board matrix, preflight green.

## Success criteria

1. Zero copied transport-factory code in library sources; the factories
   live in `chumicro_sockets`.
2. The requests, websockets, and mqtt guides lead with their generator
   surfaces.
3. run.py entry file under 1,500 lines and no dead subcommands.
4. SECURITY.md and a conduct file exist; the README contains no claim that
   a fresh clone cannot verify.
5. A no-hardware demo runs on a bare CPython clone in about a minute.
6. Stable wave complete at 17 of 17.
