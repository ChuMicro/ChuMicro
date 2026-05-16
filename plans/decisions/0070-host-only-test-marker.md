# Decision 0070: Explicit host-only test marker

Status: `accepted`
Date: `2026-05-16`
Related: [Decision 0016](0016-cross-runtime-unit-tests.md) (cross-runtime unit suite + the `_pytest` filename convention this retires — amended on acceptance), [Decision 0058](0058-test-skips-must-be-loud.md) (owns `__chumicro_runtimes__` — this decision reuses it for the cpython-only case and adds an orthogonal axis), [Decision 0069](0069-test-support-module-marker.md) (the test-support marker — `__chumicro_host_only__` is its boolean sibling; this decision preserves 0069's collect-vs-ship split), [Decision 0037](0037-runtime-file-marking.md) §2 (path-inference rejected — same principle), [Decision 0044](0044-deploy-time-runtime-filtering.md) (the deploy filter that exposes the gap), [Decision 0068](0068-unified-deploy-mode-resolution.md) (the on-device unit sweep that surfaced this — resolves its Phase 4b.2 issue (i)).

## Context

Decision 0016 split `libraries/<name>/tests/test_*.py` into two lanes by a *filename* convention: `*_pytest.py` is CPython-only (uses pytest fixtures MP/CP lack), everything else is cross-runtime, and its directory table claims the cross-runtime lane "runs on CPython, MP/CP unix-ports, real devices." Decision 0068's on-device unit sweep (`--target device-unit`) took that literally and broke on six files:

`kvstore/tests/test_{cp_nvm,mp_littlefs,mp_nvs}_backend.py`, `wifi/tests/test_{cp,mp}_adapter.py`, `sockets/tests/test_cp_adapter.py`.

Each imports a runtime-marked source module (`_backends.mp_nvs`, `_adapters.cp`, …) and drives it with a host fake, asserting *off-target* behaviour — e.g. `test_runtime_acquisition_raises_on_cpython` is true only where `esp32`/radio hardware is absent. On a non-matching board the Decision 0044 filter correctly strips the imported runtime module (`ImportError`); on a *matching* board the off-target assertion is false (real `esp32` exists ⇒ no raise). These are coherent **host** tests of runtime-specific source. They run on three host interpreters (CPython + MP unix-port + CP unix-port) and were never device-eligible by construction. Their `test_mp_`/`test_cp_` prefix says nothing about where they run, and the `_pytest` suffix is wrong for them: they *do* run on MP/CP unix-port — that is their cross-runtime value.

Two distinct gaps, not one. The `_pytest` filename convention is the path-inference Decision 0037 §2 rejected and Decision 0069 replaced for test-support — a renamed file silently changes lane. Separately, "runs on the host but never silicon" has no in-file expression at all.

## Decision

Resolve the two gaps with two mechanisms, not a new combined one:

### CPython-only test files reuse `__chumicro_runtimes__`

CPython-only is a *runtime* restriction. A test file that needs pytest fixtures declares the existing marker (Decision 0058):

```python
__chumicro_runtimes__ = ("cpython",)
```

`_filter_targets_by_marker` (`pytest-device/plugin.py`) already drops every device/unix-port target whose `runtime` is not in the marker, and plain CPython pytest still runs the file. That is byte-for-byte the `*_pytest.py` outcome with no new concept. Collection stops matching the `_pytest` suffix; the marker is the contract. The filename suffix is **not** renamed away: 8 of the 14 files would collide with an existing cross-runtime sibling (`test_msgpack_pytest.py` and `test_msgpack.py` are different files — Decision 0016's own coexistence example), and per the marker-is-the-contract principle the filename is cosmetic anyway. The `_pytest` suffix may stay as a human hint with no load-bearing role, exactly as the six host-only files keep their `test_{mp,cp}_*` names.

### Host-only test files get a dedicated boolean

"Runs on every host interpreter but never real silicon" is orthogonal to runtime ABI — there is no runtime-name subset that means "unix-port yes, board no" (`_filter_targets_by_marker` matches `device.runtime`; host-vs-silicon is a target *kind*, not a runtime). It gets its own marker, a boolean parallel to Decision 0069's `__chumicro_test_support__`:

```python
__chumicro_host_only__ = True
```

A reader `is_host_only_test(path) -> bool` joins `read_runtime_marker` / `is_test_support_module` in `chumicro_deploy.runtime_marker` (AST-only, no execution; re-exported). The `--target device-unit` collection (`_is_library_unit_test` / the `pytest_collect_file` / `pytest_pycollect_makemodule` hooks) excludes host-only files; `--target unix-port` and plain CPython include them. The marker is the sole contract — collection no longer matches any filename pattern, mirroring Decision 0037 §2 and Decision 0069. A filename rename for human honesty may follow but is cosmetic, not load-bearing.

### Marker inventory after this decision (three, none reducible)

| Marker | Reader | Decides | Population |
|---|---|---|---|
| `__chumicro_runtimes__` | ship filter + `_filter_targets_by_marker` | which runtime ABIs the code is valid on (incl. cpython-only tests) | `src/` + test files |
| `__chumicro_test_support__` | `is_test_support_module` (ship filter) | "a fake — never ship to a product; stage for device-unit" | `testing.py` |
| `__chumicro_host_only__` | `is_host_only_test` (pytest collector) | host interpreters only — never real silicon | `tests/test_*.py` |

`__chumicro_host_only__` cannot fold into `__chumicro_runtimes__` (host-only is not a runtime restriction — the six files run on MP/CP unix-port) nor into `__chumicro_test_support__` (different reader — collector vs ship filter — and different population; Decision 0069 deliberately split collect-vs-ship and its rationale forbids re-merging). `__chumicro_runtimes__` and `__chumicro_test_support__` stay split for Decision 0069's original reason (a fake runs on every runtime; the old `("cpython",)` on `testing.py` was a lie).

### Alternatives considered

- **One 3-valued `__chumicro_test_lane__` string (`device`/`host`/`cpython`).** The `cpython` value duplicates `__chumicro_runtimes__ = ("cpython",)`, which already drives test collection via `_filter_targets_by_marker`. A new marker that re-expresses an existing one is marker sprawl; reuse `__chumicro_runtimes__` and add only the irreducible host-only bit.
- **Mark the six files `__chumicro_runtimes__ = ("cpython",)`.** False — they run on MP/CP unix-port, and it would silence their deliberate `test_runtime_acquisition_raises_*_on_cpython` and still fail a matching board. Host-only is orthogonal to runtime identity.
- **A second filename suffix (`_hostonly.py`).** Two path-inference conventions instead of zero; a moved file silently changes lane — exactly what Decision 0037 §2 and Decision 0069 rejected.
- **Skip device-ineligible files at runtime via the loud-skip primitive (Decision 0058).** A skip is a per-run report; host-only is a static property. The file is also imported on-device before any skip can fire — the `ImportError` is at import.

## Consequences

- The on-device unit sweep (Decision 0068 Phase 4b.2 issue (i)) is unblocked: device-unit collection no longer drags host-only files onto silicon. The `plans/open-questions.md` "How does a unit-test file opt out…" entry is resolved on acceptance.
- Decision 0016's filename-convention paragraphs and its directory-table "real devices" claim are amended in place on acceptance: the `_pytest` suffix becomes `__chumicro_runtimes__ = ("cpython",)`, and the cross-runtime lane's silicon applicability becomes host-only-gated.
- A regression test asserts a host-only file is collected under `unix-port` and CPython but absent from a `device-unit` stage, and a `("cpython",)` test file only under plain pytest — a missed collection site fails the test, not a board.
- Migration touches every site that keys off the `_pytest` filename, not just the collector: add `__chumicro_host_only__ = True` to the six files; add `__chumicro_runtimes__ = ("cpython",)` to the 14 `*_pytest.py` files (filenames unchanged — 8 would collide with a cross-runtime sibling, and the marker is the contract); `pytest-device/plugin.py` `_is_library_unit_test` drops the suffix exclusion and the `device-unit` collection hooks add an `is_host_only_test` gate (the `("cpython",)` case is already handled by the existing `_filter_targets_by_marker`); `scripts/run.py` `_library_has_cross_runtime_unit_suite` switches from the filename glob to marker reads; `support/test_harness/discovery.py`'s import-failure hint (advice text, no filtering) names the marker instead of a rename. The scaffold (`new-library`) and Decision 0016's naming guidance update with it.
- Adding a host-only or CPython-only test means declaring it in the file — no path-based guess, consistent with Decision 0037 §2 and Decision 0069.
