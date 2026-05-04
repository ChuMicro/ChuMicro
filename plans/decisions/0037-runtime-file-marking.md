# Decision 0037: Per-runtime file marking and bundle filtering

Status: `accepted`
Date: `2026-04-26` (amended `2026-05-04` — see "Amendments" below)
Related: Decision 0015 (supported board class), Decision 0018 (distribution bundle repo), Decision 0021 (annotations), Decision 0010 (testing fakes), the 2026-04-26 Pi Pico W flash-footprint learning in `plans/learnings.md`.

> **Note:** See also [Decision 0044](0044-deploy-time-runtime-filtering.md), which extends the marker filter to every host-side deploy path (workspace deploy, `chumicro_deploy` CLI, pytest-device staging, examples, functional tests).

## Context

Pi Pico W ships ~870 KB of CIRCUITPY space on FAT12 with 4 KB clusters.  Every `.py` or `.mpy` file pays ≥ 4 KB on disk regardless of content size.  At 51 source files in the workspace (after the 2026-04-26 MQTT 8 → 4 consolidation and `testing.py` exclusion), per-file FAT cluster overhead alone consumes ~204 KB.

A material fraction of those files are runtime-specific and never executed on the runtime they ship to:

- `chumicro_wifi/_adapters/` — 4 adapter implementations (`cp.py`, `mp_esp32.py`, `mp_rp2.py`, plus historically `fake.py`); only one runs per device.
- `chumicro_kvstore/_backends/` — 4 backend implementations (`cp_nvm.py`, `mp_nvs.py`, `mp_littlefs.py`, `memory.py`); only one (or two — memory + a substrate one) runs per device.
- `chumicro_sockets/_adapters/` — 3 adapters (`cp.py`, `mp.py`, `cpython.py`); only one runs per runtime.

Runtime selection at import time (e.g. `chumicro_wifi.service._select_adapter`) avoids the *parse* cost on the wrong runtime, but the *files themselves* still ship and consume FAT clusters.  ~10 dead-weight files per device, ~40 KB.

The bundle pipeline (`scripts/bundle_manager.py`) currently ships every `.py` under each `src/chumicro_*/` package — no per-runtime filtering — into both the CP-mpy and MP-mpy bundles.  The `testing.py` exclusion landed 2026-04-26 (commit `f8b28d6`) but is the only filter in place.

## Decisions

### 1. Module-level `__chumicro_runtimes__` marker

Files that are runtime-specific declare their runtimes at module scope:

```python
# chumicro_wifi/_adapters/cp.py
"""CircuitPython wifi.radio adapter."""

__chumicro_runtimes__ = ("circuitpython",)

import wifi
# ...
```

The marker is a tuple of canonical runtime names:

| Marker value          | Where the file ships                                      |
|-----------------------|------------------------------------------------------------|
| `("circuitpython",)`  | CP-mpy bundle, source bundle, PyPI sdist + wheel          |
| `("micropython",)`    | MP-mpy bundle, source bundle, PyPI sdist + wheel          |
| `("cpython",)`        | **PyPI sdist + wheel only** (no bundle, no device deploy) |
| `("circuitpython", "micropython")` | both device bundles + source bundle + PyPI       |
| absent / not declared | every bundle + every deploy + PyPI (default-safe)         |

The PyPI sdist / wheel always ships every file under `src/` regardless of marker — `pip install chumicro-foo` on a CPython host gets the complete library, including host-only fakes and runtime-specific adapters.  Build pipelines that produce the bundle artifacts (mip / circup consumers) and every host-side deploy path apply the marker filter.

The bundle pipeline reads the marker via a small AST walk (no module execution — `ast.parse` + `ast.Assign` to top-level `__chumicro_runtimes__`).  No execution because the file may itself import runtime-only modules (`import wifi`, `import esp32`) that fail at parse-execute time on the host.

Sub-runtimes (`micropython_esp32` vs `micropython_rp2`) are recognised but currently fold into `micropython` for bundle filtering — both MP variants ship the same `mpy6/` bundle today.  When a future board class diverges enough to warrant per-port mpy bundles, the marker vocabulary already supports it.

### 2. Filename suffix is convention only — not load-bearing

The repo's existing naming (`cp.py`, `mp_esp32.py`, `mp_rp2.py`, `cpython.py`, `fake.py`) is documentation that helps a reader scan a directory.  The bundle pipeline does **not** infer the runtime from the filename alone — too easy for a renamed file to silently regress.  The explicit marker is the contract.

### 3. Test fakes consolidate into `testing.py`

`testing.py` is the host-only test-fake module per Decision 0010.  It declares `__chumicro_runtimes__ = ("cpython",)` so the marker filter drops it from every bundle (CP-mpy, MP-mpy, universal source) and every host-side deploy path.  PyPI installs (sdist + wheel) ship it unchanged — that's the only legitimate consumer of the fakes.  Per-library `_adapters/fake.py` (and equivalent `_backends/fake.py` if any appear) folds into `testing.py`:

- `chumicro_wifi._adapters.fake.FakeWifiAdapter` → `chumicro_wifi.testing.FakeWifiAdapter`
- `chumicro_sockets._adapters.cpython` stays separate — it's a real CPython adapter (uses stdlib `socket` to talk to real servers from CPython hosts), not a host fake.

Production code that currently lazy-imports the fake (e.g. `chumicro_wifi.service._select_adapter`'s CPython fallback) lazy-imports from `testing` instead.  The lazy-import shape protects against the cycle (`testing.py` imports `service.py`).

### 4. Runtime-selection gates stay in code

`_select_adapter` / `_select_backend` continue to branch on `sys.implementation.name`.  Bundle filtering removes the dead source files from devices but the gate runs on every runtime (including host CPython, which still has every adapter source via the editable install).  Without the gate, host tests would attempt to import device-only modules (`import wifi` / `import esp32`) and crash at module-load time.

### 5. Bundle pipeline filtering is per-target

`bundle_manager._find_bundle_modules` takes a runtime selector:

```python
def _find_bundle_modules(
    library_dir: Path,
    *,
    target_runtime: str | frozenset[str] | None = None,
):
    # target_runtime=DEVICE_RUNTIMES — universal source bundle (drops cpython-only)
    # target_runtime="circuitpython" — CP-mpy bundle (drops MP + cpython markers)
    # target_runtime="micropython"   — MP-mpy bundle (drops CP + cpython markers)
    # target_runtime=None             — legacy "no filter" (not used by bundle pipeline)
```

`build_bundle` calls it three times (once per output bundle) with the appropriate target.  The universal source bundle passes `DEVICE_RUNTIMES` (frozenset of `{"circuitpython", "micropython"}`) so any file marked exclusively for `cpython` (notably `testing.py`) drops out — those files only land in the PyPI sdist / wheel, since `pip install` doesn't go through this pipeline.

## Consequences

- ~10 dead-weight files per device drop out of CP-mpy / MP-mpy bundles.  Pi Pico W MP shrinks ~32 KB on top of the prior 24 KB testing.py win.
- Adding a new runtime-specific file requires explicit `__chumicro_runtimes__` declaration — there is no "guess from path" rule.  The bundle test suite exercises every existing runtime-specific file so a missing marker fails CI.
- The runtime-selection gate code (`_select_adapter`, `_select_backend`, etc.) is unchanged.  It remains the runtime-side counterpart to the build-time bundle filter.
- The marker declaration is plain Python — readable by humans, parseable by the bundle pipeline, and ignored by the runtime (just an unused module attribute).  No new tooling, no registry, no manifest.
- `_adapters/fake.py` per library disappears in the same change; existing imports of `chumicro_*._adapters.fake.*` move to `chumicro_*.testing.*`.  Public API (`chumicro_wifi.testing.FakeWifi` etc.) is unchanged.
- Users on PyPI (`pip install chumicro-foo` on any CPython host) get a complete install — every adapter, every backend, every fake.  Users on mip / circup get the bundle-filtered subset matching their device runtime, with `testing.py` and any other `("cpython",)`-marked files dropped.

## Amendments

### 2026-05-04 — `testing.py` exits the universal source bundle too

Original Decision (2026-04-26) said the universal source bundle was "every non-host-only file unfiltered" and used a name-based `_HOST_ONLY_MODULES = {"testing.py"}` filter to keep `testing.py` out of it.  That left two problems:

1. Two parallel mechanisms (name list + marker filter) drifting independently.
2. `testing.py` was being added to the universal source bundle anyway when the bundle pipeline was bypassed (e.g. workspace deploy via `DirectorySource` walks of a library `src/` tree didn't apply `_HOST_ONLY_MODULES`).  Decision 0044 closed the deploy-side gap, but only for runtime-marked files — `testing.py` had no marker, so deploy paths still shipped it.

The amendment:

- Every `testing.py` declares `__chumicro_runtimes__ = ("cpython",)`.
- `_find_bundle_modules` accepts a frozenset of target runtimes.  The universal source bundle now passes `DEVICE_RUNTIMES = frozenset({"circuitpython", "micropython"})`, which drops any file marked exclusively for `cpython`.
- `_HOST_ONLY_MODULES` is removed.  The marker is the single source of truth.

Consequences: `testing.py` (and any future CPython-only file) ships only in the PyPI sdist / wheel.  No bundle, no device deploy.  The marker mechanism gains slightly more expressiveness (set-of-acceptable-runtimes in addition to single-runtime) without changing the per-file declaration form.
