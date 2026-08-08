# Workstream: Pyright Cleanup

Status: **parked.**  Phase 0 (config-only scoping, two passes) + Phase 1 (categorization) + Family A (real-defect shape-preserving fixes) + example-side spot-fixes shipped 2026-05-09 (1054 → 259 errors / 44 → 0 warnings).  Families B + C and Phases 3 + 4 + 5 + 6 deferred — pyright caused more friction than it surfaced this session, and the remaining buckets all need either user-driven structural decisions (Phase 4 ADR), readability tradeoffs we don't want to make speculatively (Families B + C), or are happy to live as-is until a forcing function appears.  Reopen when there's a concrete reason to return to it (e.g., adding pyright to preflight, or a real bug pyright would have caught).  The `pyright-lsp` plugin is currently disabled in `.claude/settings.json` for the same reason — IDE-strict diagnostics didn't honor `pyrightconfig.json`'s `ignore` globs and were noisier than the CLI.

## Purpose

Pyright was set up via the `pyright-python` plugin some time back; nothing has been done with it since.  A first scan against the whole workspace surfaced **1,053 errors + 1 warning** across 442 files.  Most are not bugs — they are pyright struggling with patterns the codebase uses deliberately (`object`-typed polymorphic seams for the cross-runtime `from_config` factories, ad-hoc test fakes, MicroPython-only attribute names guarded by `hasattr`).  A smaller fraction are real defects pyright is correctly catching (Optional narrowing gaps, possibly-unbound variables in error paths).

Goal: drive the count to a maintainable number where preflight could plausibly add a `pyright` phase and have it stay green.  We are not chasing zero on day one — the structural decisions (Phase 4) need user input.

## Load-bearing principle: pyright is host-side

Pyright runs only on the developer's laptop / CI runner — never on the device.  Library code under `libraries/` and `support/test_harness/` runs on a 256 KB MCU with a few MB of flash and a tick-loop budgeted in milliseconds.  **Never restructure runtime code to silence a host-side type-checker.**  Specifically off-limits in `libraries/` and `support/test_harness/`:

- Adding `getattr(module, "name")()` instead of a direct `module.name()` call — the `getattr` lookup costs a dict probe + a function-call frame on every invocation.  On a hot path (NTP-server tick, frame parser, inbound recv) this is a real measurable hit.
- Adding `assert <var> is not None` plus a `local = self._foo` rebind just because pyright can't see a state-machine invariant — every `assert` is a branch + a string-literal const + bytecode that ships in flash and runs every call.  Locals frame slots cost RAM.  *Pyright thinks the cost is free; on these targets it isn't.*
- Wrapping platform-only attribute accesses in helper functions that funnel through `getattr` — same overhead, plus an extra Python call frame per use.
- Hoisting imports out of intentionally-lazy positions just to make pyright happy — re-evaluate the *why* first; some lazy imports exist to keep RAM unloaded until needed, and reordering them silently regresses startup behavior.

Acceptable mitigations in runtime code, in order of preference:

1. **Pyrightconfig-level scoping** — `ignore` patterns or per-path severity overrides in `pyrightconfig.json`.  Zero source change, zero runtime cost, zero flash cost.  Use when the same noise pattern hits many files in a tree (tests, functional_tests, examples).
2. **File-level suppression** — `# pyright: <directive>` as a single line at the top of one specific file.  One comment that covers every diagnostic in the file.  Use when a single file is the noise epicenter and the file is small enough that the one comment line of flash is worth silencing many errors of IDE noise.
3. **Per-line `# pyright: ignore[<ruleName>]`** — comment text that ships to devices in the `.py` file.  Comments are not free: a `.py` file deployed to flash carries every comment byte (only `.mpy` cross-compilation strips them, and devices typically run `.py` until release).  Use sparingly — only when the suppression is high-value (silences multiple downstream noise lines) and no upstream mitigation fits.
4. **Accept the noise** — no source change, no config change.  The right default when the diagnostic is just pyright misunderstanding a cross-runtime pattern.  Real defect fixes still happen normally; the noise is signal that those patterns exist, and reviewers learn to skim past it.

Real defect fixes that change behavior for the better even without pyright (Family A entries qualify) are always fine.

CPython-only trees (`workbench/`, `scripts/`, `tests/`, `functional_tests/` body code) do not have these constraints — restructuring there is fine.

This principle is load-bearing because it inverts the default reflex of "the type checker found a problem, fix the code."  On these targets, the type checker is the wrong source of truth for what "the code" should look like.

## Phase 0 — pyrightconfig tuning (shipped)

`pyrightconfig.json` now sets `pythonVersion: "3.11"` (matches root `pyproject.toml` `target-version = "py311"`) and `reportMissingModuleSource: none`.  The latter silences the 43 "Import 'X' could not be resolved from source" warnings against CircuitPython / MicroPython platform modules (`microcontroller`, `esp32`, `wifi`, `socketpool`, `ssl`, `digitalio`, `bitbangio`, `analogio`, `board`, `micropython`, …) that ship as type stubs only — those are expected, not actionable.

A second pass added an `ignore` glob list: `**/tests/**`, `**/functional_tests/**`, and `support/test_harness/src/chumicro_test_harness/runner.py`.  Tests use ad-hoc fakes pyright can't introspect; functional_tests import platform modules as bare `import wifi` etc.; the test_harness runner is the cross-runtime adapter seam whose entire purpose is to pretend it's MP/CP on the host.  All three trees are noise epicenters where pyright is least useful.  Pyrightconfig `ignore` is the right tool: the files are skipped from analysis but still importable from analyzed files.  Zero source change, zero runtime cost, zero flash cost.

Net change after both phase-0 passes: **44 → 0 warnings, 1054 → 266 errors** (758 silenced).  Examples are intentionally kept in scope — they are user-facing reference code where readability matters and the count tells us when the example is broken.

## Phase 1 — categorization (this doc)

Distribution after Phase 0, by tree kind:

| kind | count | character |
|------|------:|-----------|
| `tests/` | 653 | mostly ad-hoc fakes pyright can't introspect |
| `src/` | 254 | mix of real bugs, duck-typed seams, runtime-guarded attrs |
| `functional_tests/` | 99 | on-device tests that import platform modules |
| `examples/` | 36 | similar to functional_tests |
| `scripts/` | 12 | mostly real fixes |

Source-only distribution (the lever that matters most), by area:

| area | count | dominant pattern |
|------|------:|------------------|
| libraries/requests | 45 | `from_config(config: object, ...)` → `config.get(...)` (22) + Optional narrowing (8) + duck-typed `connection_factory` (rest) |
| libraries/mqtt | 30 | duck-typed `config: object` (10) + duck-typed `socket: object` (8) + Optional narrowing (3) + WhenOversized literal-vs-enum mismatch (5) |
| libraries/websockets | 29 | Optional narrowing on `_session: WebSocketSession \| None` paths (14) + duck-typed `connection_factory` (11) |
| workbench/workspace | 24 | mostly `cli.py` ApplyReport iteration (3) + Optional narrowing on probe results (15) + asserts pyright loses track of (rest) |
| support/test_harness | 22 | MicroPython-only attrs (`time.ticks_ms`, `gc.collect`, `gc.mem_free`, `sys.print_exception`) guarded by `hasattr` (18) + Optional narrowing in error paths (4) |
| libraries/sockets | 19 | `__init__.py` re-exports lose attribute typing (16) + duck-typed `recv_into` returns (3) |
| libraries/http_server | 17 | `_socket: object \| None` set to `None` in `close()` then accessed in `_drive_recv` / `_drive_send` (12) + duck-typed `config.get` (5) |
| libraries/runner | 15 | `ticks: object \| None` parameter never narrowed; tasks typed `object` (15) |
| libraries/wifi | 14 | duck-typed `radio: object` access in `service.py` (9) + Optional narrowing on connection state (5) |
| libraries/ntp | 11 | duck-typed `socket: object` + `config: object` (11) |
| libraries/{config,kvstore,timing} | 5 each | mixed |
| scripts/ | 12 | 6× `result` possibly-unbound in `validate_mip_install.py` + smaller fixes |

## Diagnostic family → fix shape

These are the patterns the categorization above collapses to.  Each row is a recipe a future agent can apply uniformly across the source files where it shows up.

### A. Real defects pyright is correctly flagging

| pattern | example | fix |
|---|---|---|
| `result` possibly-unbound when an exception path skips the assignment | `scripts/validate_mip_install.py` L247 | Initialize `result = None` before the try, and check `if result is None: raise` before the consumers — or restructure so the consumers live inside the try-success branch. |
| `YAMLError` possibly-unbound when the import is conditional | `workbench/workspace/src/chumicro_workspace/health.py` L87 | Hoist the import unconditionally (yaml is a hard dep on this code path) or assign `YAMLError = Exception` in the `except ImportError:` branch. |
| `__all__` includes `"config"` but pyright can't see the PEP-562 lazy attr | `libraries/config/src/chumicro_config/__init__.py` L64 | Inline `# pyright: ignore[reportUnsupportedDunderAll]` with a one-line "lazy via `__getattr__`" rationale. |
| Sentinel-style `if False:` re-export idiom not picked up | sockets `__init__.py` re-exports | Move re-exports to a static `from .submodule import …` form pyright can follow. |

Estimated count: **~12 source-side**.  Low risk; do them library-by-library with the existing test gate.

### B. Optional narrowing pyright loses across method boundaries

The pattern is `self._x: object | None`, set to a real value in `__init__`, set to `None` in `close()`.  Methods that only run when `self._x is not None` (because some `is_done` flag flipped first) read `self._x.foo()` and pyright complains.

The first attempt at this family added the `local = self._x; assert local is not None` pattern across requests / websockets / ntp.  That approach was reverted on user feedback: every assert + locals-frame slot is real flash + RAM + per-tick branch overhead on a 256 KB MCU, and pyright is not aware of the platform constraints that make those costs material.  See "Load-bearing principle" above.

The viable mitigations on runtime code:

- **Per-line `# pyright: ignore[reportOptionalMemberAccess]`** at the access site, with a one-line comment naming the runtime invariant pyright can't see (`# state == RECEIVING implies _socket bound`).  Zero runtime cost.
- **Accept the noise** for paths where the suppression noise is itself worse than the diagnostic noise.  Pyright count stays high, but no source change.

`workbench/workspace/src/chumicro_workspace/cli.py` is CPython-only — its 15 cases are fair game for normal narrowing rewrites and roll into Phase 3.

Estimated count if we apply per-line ignores in the library hotspots: **~50 source errors silenced, runtime byte-identical**.  Hold on whether the user wants the suppression noise — it could go either way.

### C. MicroPython-only attributes guarded by `hasattr`

`support/test_harness/src/chumicro_test_harness/runner.py` does `if hasattr(time, "monotonic"): _now_seconds = time.monotonic; else: def _now_seconds(): return time.ticks_ms() / 1000`.  Pyright walks the `else` branch and flags `time.ticks_ms` as unknown.

Same shape: `gc.collect()` / `gc.mem_free()` (gated by `_gc is not None and hasattr(_gc, 'mem_free')` then assigned to a local that pyright loses), `sys.print_exception` (gated by `hasattr(sys, 'print_exception')`).

The first attempt at this family swapped every `_gc.collect()` / `gc.mem_free()` / `time.ticks_ms()` / `sys.print_exception(exc)` call for either `getattr(module, "name")()` or a `_gc_collect()` / `_gc_mem_free()` helper-function wrapper that called `getattr` internally.  That commit was reverted on user feedback: `getattr` is a runtime dict probe + function-frame on every call, helper functions add another Python call frame, and the only justification was silencing pyright on host-side scans of code that runs hot on every test on every device.  See "Load-bearing principle" above.

Viable mitigations on this file:

- **Per-line `# pyright: ignore[reportAttributeAccessIssue]`** on each `time.ticks_ms()` / `gc.collect()` / `gc.mem_free()` / `sys.print_exception(exc)` call, with a one-line "MicroPython-only, gated by hasattr above" comment.  Comment-only, zero runtime cost.
- **Accept the noise.**  This file is the runtime-adapter seam — its job is to pretend it's MP/CP on the host.  ~22 errors here are an honest signal that the file is doing what it's supposed to.

Estimated count if we per-line-ignore: **~22 source errors silenced, runtime byte-identical**.  Hold on user preference — same call as Family B.

### D. Duck-typed polymorphic seams (the big bucket — needs ADR)

The largest single category.  Affects every `from_config` factory shipped during the [config-aware refactor](library-config-aware-refactor.md), plus the runner's tick source, every library's socket parameter, the `connection_factory` seams, and the radio parameter.

The pattern, as it stands today:

```python
def from_config(cls, config: object, *, radio: object | None = None, ...) -> "HttpClient":
    return cls(
        default_timeout_ms=config.get("requests.default_timeout_ms", DEFAULT_TIMEOUT_MS),  # ← pyright: object has no attribute "get"
        ...
    )
```

`object` is on the signature deliberately — these factories accept any duck-typed config-like / socket-like / radio-like, including the [`RuntimeConfig`](../../../libraries/config/src/chumicro_config/runtime.py) the workbench produces and the test fakes in each library's `testing.py`.  `Protocol` would solve it cleanly, but [Decision 0021](../../decisions/0021-docstring-type-policy.md) bans `from typing import …` in library code because the `typing` module doesn't exist on CircuitPython or MicroPython.

Three plausible answers:

1. **Accept the noise.** Mark these errors as known-by-design.  Cost: ~80 errors stay forever; pyright phase in preflight has a fixed allowlist; ergonomically pyright in IDEs feels noisy on these libraries.
2. **TYPE_CHECKING-guarded Protocol pattern.**  Decision 0021 is silent on this idiom but it works on embedded runtimes:
    ```python
    try:
        from typing import TYPE_CHECKING
    except ImportError:  # CircuitPython / MicroPython have no `typing` module.
        TYPE_CHECKING = False

    if TYPE_CHECKING:  # pyright sees this; runtime never enters.
        from typing import Protocol
        class ConfigLike(Protocol):
            def get(self, key: str, default: object = ...) -> object: ...
    ```
    Annotations become string-quoted (`config: "ConfigLike"`).  Cost: a small Protocol library per `from_config` seam (one ConfigLike, one SocketLike, one RadioLike, one TickSourceLike, one ConnectionFactoryLike — most are reused across libraries so they could live in a shared `chumicro_compat.protocols` module).  Benefit: pyright sees the seam shape, IDE auto-complete starts to work, all 80 errors evaporate.
3. **Concrete types where one exists.**  `RuntimeConfig` is concrete and the only thing the workbench passes to `from_config` in production.  Annotate `config: "RuntimeConfig"` (string-quoted to dodge the import cycle) and let test fakes either subclass or use `cast`.  Cost: less flexible API; tests need adjusting; doesn't address `socket: object` / `radio: object` which have no concrete type.

Recommendation in this workstream: **option 2**.  Cleanest typing story, smallest API change (annotations are stripped at runtime — every existing caller continues to work), and a single 5–10-line "shim" idiom to learn.  Needs a new ADR (use the [`new-decision`](../../../.github/skills/new-decision/SKILL.md) skill) ratifying the TYPE_CHECKING-guarded Protocol pattern as the official answer to "I want a protocol shape on a library seam."  Estimated count once the pattern lands and seams are typed: **~80 source-side errors gone**.

### E. Test-fixture noise (the 653 in `tests/`)

Test files use ad-hoc fake objects (`class FakeSocket: ...` with the methods the test needs, no inherited Protocol).  Pyright sees them as `Unknown` and flags every attribute access.  Two reasonable answers:

1. **Per-file `# pyright: basic` headers** on the worst offenders (top 8 files account for ~430 of the 653).  Cheap and visible.
2. **Reusable Protocol shims in each library's `testing.py`** that the fakes inherit from.  Once Phase 4 lands its TYPE_CHECKING idiom, `testing.py` files can import the same protocols and have `FakeTransport(TransportLike)` etc.  Higher upfront effort, but tests get IDE awareness in return — and the protocols already exist from Phase 4.

Recommendation: **defer until Phase 4 lands**.  Phase 4 produces the protocols Phase 5 wants to inherit from.

### F. Functional tests + examples (135 in those trees)

These import platform modules (`wifi`, `microcontroller`, `socketpool`, `esp32`) directly — pyright sees stubs but no source.  Phase 0 silenced the "no source" warning channel; the residual errors are mostly attribute-access on those stubs (the stubs are incomplete).  Either let them sit (they're not blocking anyone), or scope `pyright` execution to skip `functional_tests/` + `examples/` once we add a preflight phase.

Recommendation: **defer**.  Revisit when adding pyright to preflight.

## Phase tracker

- [x] **Phase 0** — pyrightconfig tuning (two-pass; shipped 2026-05-09).  Pass 1: `pythonVersion: "3.11"` + `reportMissingModuleSource: none`.  Pass 2: `ignore` for tests / functional_tests / test_harness/runner.py.  Net: 44 → 0 warnings, 1054 → 266 errors (758 silenced, zero source / runtime / flash cost).
- [x] **Phase 1** — this categorization (shipped 2026-05-09).
- [x] **Family A** (real defects, ~14 errors) — shipped 2026-05-09.  Four shape-preserving fixes with no runtime cost: `protocol.py` `...` bodies on Protocol-stub methods (standard idiom; +1 LOAD_CONST per stub, never called), `health.py` import re-order out of a try block whose `except YAMLError` could never catch the import's `ImportError` anyway, `validate_mip_install.py` `result = None` initialization (CPython-only script), `config/__init__.py` `# pyright: ignore` directive on the PEP-562 lazy-attr `__all__` entry.  1053 → 1039 errors.
- [x] **Examples — real-defect spot-fixes** (shipped 2026-05-09).  ~7 errors fixed across 5 example files where pyright was correctly catching broken references (mqtt `is_connected` → `state == ProtocolState.CONNECTED`, config `load_section(prefix=...)` missing kwarg, sockets `sender` possibly-unbound, http_server `WifiConfig.from_dict` → `try_from_config`, http_server `_State` widening annotations).  Pre-Phase-0-pass-2 baseline was 36 example errors; this pass took it to 29.  The remaining 29 are mostly Family-D-derived (downstream of `config.get(key, default) -> object` plus a handful of `board.LED` / `board.D5` board-specific stubs); they stay as honest signal that the example targets a specific board the type checker can't reason about.  No `# type: ignore` sprinkles in example bodies.
- [ ] **Family B** (Optional narrowing, ~50) — held.  First attempt at the local-bind + assert pattern was reverted (runtime cost on embedded targets).  Open question: do we want per-line `# pyright: ignore[reportOptionalMemberAccess]` suppressions in the library hotspots, or accept the noise?  `workbench/workspace/cli.py` (15 cases, CPython-only) splits off into Phase 3 and gets normal narrowing rewrites.
- [ ] **Family C** (hasattr-guarded MP attrs, ~22) — held.  First attempt with `getattr` helpers in `support/test_harness/runner.py` was reverted (real per-call overhead).  Same open question as Family B: per-line ignores or accept the noise?
- [ ] **Phase 3** — workbench + scripts source fixes (~36 source errors).  Pure-CPython trees, no embedded constraints, normal narrowing rewrites are fine.  Independent of the Family B/C call.
- [ ] **Phase 4** — Family D (duck-typed seams, ~80).  Gates on a new ADR ratifying the TYPE_CHECKING-guarded Protocol pattern; then a single shared `chumicro_compat.protocols` module + per-library annotation pass.  Largest single bucket.  Held until user decides on the ADR direction.
- [ ] **Phase 5** — Family E (test-fixture noise, ~653).  Approach picked once Phase 4 lands.
- [ ] **Phase 6** — add `pyright` as a preflight phase once errors are at a maintainable steady-state count.

## Tooling notes

- Re-running pyright: `.venv/bin/pyright --outputjson > .scratch/pyright.json` then `.venv/bin/python -c "import json,collections;data=json.load(open('.scratch/pyright.json'));print(data['summary'])"`.
- Pyright version pinned indirectly via `pyright-python` plugin; current = 1.1.408.  Upgrade hint surfaced on every run; ratchet on intentional refresh, not drift.
- `pyrightconfig.json` is the single config source.  No per-tree `pyright` blocks in any `pyproject.toml`.
