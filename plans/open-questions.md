# Open Questions

Unresolved questions that need thought but aren't blocking active work.
When a question is resolved, move it to the **Resolved** section with a
one-line answer and link to the decision or commit that settled it.

Questions that become blocking should move to `next-up.md` (Blocked section).
Questions that lead to structural tradeoffs should become decisions in
`plans/decisions/`.

---

## Active

### Should the coverage gate be higher?

The threshold (configured in `pyproject.toml`) was chosen early and has worked well.
As the library count grows and test patterns mature, revisit whether a higher gate
is appropriate — or whether the gate should vary by library maturity
(stricter for stable, relaxed for experimental).

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

### What does "contributor-ready" look like beyond docs?

CONTRIBUTING.md, issue templates, and PR templates exist.  But contributor
experience also includes: good-first-issue labeling, response time
expectations, mentoring patterns for agent-assisted contributors, and
community channels.  What's the minimum viable contributor experience
before actively seeking contributions?

---

## Resolved

(none yet)

