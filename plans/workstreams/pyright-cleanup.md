# Workstream: Pyright Cleanup

Status: **active.**  Phase 0 (config tuning) shipped 2026-05-09; Phase 1 (this categorization) shipped 2026-05-09.  Phases 2–5 are scoped below; the load-bearing call is Phase 4 (the duck-typed-seam ADR), since it gates the largest single bucket of source-side errors.

## Purpose

Pyright was set up via the `pyright-python` plugin some time back; nothing has been done with it since.  A first scan against the whole workspace surfaced **1,053 errors + 1 warning** across 442 files.  Most are not bugs — they are pyright struggling with patterns the codebase uses deliberately (`object`-typed polymorphic seams for the cross-runtime `from_config` factories, ad-hoc test fakes, MicroPython-only attribute names guarded by `hasattr`).  A smaller fraction are real defects pyright is correctly catching (Optional narrowing gaps, possibly-unbound variables in error paths).

Goal: drive the count to a maintainable number where preflight could plausibly add a `pyright` phase and have it stay green.  We are not chasing zero on day one — the structural decisions (Phase 4) need user input.

## Phase 0 — pyrightconfig tuning (shipped)

`pyrightconfig.json` now sets `pythonVersion: "3.11"` (matches root `pyproject.toml` `target-version = "py311"`) and `reportMissingModuleSource: none`.  The latter silences the 43 "Import 'X' could not be resolved from source" warnings against CircuitPython / MicroPython platform modules (`microcontroller`, `esp32`, `wifi`, `socketpool`, `ssl`, `digitalio`, `bitbangio`, `analogio`, `board`, `micropython`, …) that ship as type stubs only — those are expected, not actionable.

Net change: **44 → 1 warning, 1054 → 1053 errors**.  The warning channel is now signal-only; future "missing source" reports point at real misconfiguration.

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

| file | hot lines | fix shape |
|---|---|---|
| `libraries/http_server/src/chumicro_http_server/server.py` | `_drive_recv` L329, `_drive_send` L386 | Add `assert self._socket is not None` at the top of each method.  Asserts compile on MicroPython too — the runtime cost is one branch.  Or, narrow at the call site: `socket = self._socket; assert socket is not None; socket.recv_into(...)`. |
| `libraries/websockets/src/chumicro_websockets/server.py` | L209–226 (`_session` access path) | Same pattern: hoist `session = self._session; assert session is not None`. |
| `libraries/mqtt/src/chumicro_mqtt/client.py` | L346–349 | `socket = self._socket; assert socket is not None` before the `.get()` chain. |
| `libraries/requests/src/chumicro_requests/client.py` | 8× `Optional[Response]` accesses on a redirect-following loop | Local-narrow once at the top of `_follow_redirect`; the variable is bound before each iteration's reads. |
| `workbench/workspace/src/chumicro_workspace/cli.py` | L2098–2100 | `firmware_info = probe_result; assert firmware_info is not None`. |

Estimated count: **~70 source-side**.  Mechanical and runtime-safe.  Do as a single pass per library.

### C. MicroPython-only attributes guarded by `hasattr`

`support/test_harness/src/chumicro_test_harness/runner.py` does `if hasattr(time, "monotonic"): _now_seconds = time.monotonic; else: def _now_seconds(): return time.ticks_ms() / 1000`.  Pyright walks the `else` branch and flags `time.ticks_ms` as unknown.

Same shape: `gc.collect()` / `gc.mem_free()` (gated by `_gc is not None and hasattr(_gc, 'mem_free')` then assigned to a local that pyright loses), `sys.print_exception` (gated by `hasattr(sys, 'print_exception')`).

| fix shape | when |
|---|---|
| `getattr(module, "name")()` form | One-shot calls.  Pyright treats the result as `Unknown` and skips the attribute check entirely. |
| `# type: ignore[attr-defined]  # MicroPython-only` | Repeated calls in tight loops where `getattr` is overhead. |

Estimated count: **~22 source-side** (concentrated in `support/test_harness/runner.py`).  Mechanical; one-file PR.

### D. Duck-typed polymorphic seams (the big bucket — needs ADR)

The largest single category.  Affects every `from_config` factory shipped during the [config-aware refactor](archive/library-config-aware-refactor.md), plus the runner's tick source, every library's socket parameter, the `connection_factory` seams, and the radio parameter.

The pattern, as it stands today:

```python
def from_config(cls, config: object, *, radio: object | None = None, ...) -> "HttpClient":
    return cls(
        default_timeout_ms=config.get("requests.default_timeout_ms", DEFAULT_TIMEOUT_MS),  # ← pyright: object has no attribute "get"
        ...
    )
```

`object` is on the signature deliberately — these factories accept any duck-typed config-like / socket-like / radio-like, including the [`RuntimeConfig`](../../libraries/config/src/chumicro_config/runtime.py) the workbench produces and the test fakes in each library's `testing.py`.  `Protocol` would solve it cleanly, but [Decision 0021](../decisions/0021-docstring-type-policy.md) bans `from typing import …` in library code because the `typing` module doesn't exist on CircuitPython or MicroPython.

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

Recommendation in this workstream: **option 2**.  Cleanest typing story, smallest API change (annotations are stripped at runtime — every existing caller continues to work), and a single 5–10-line "shim" idiom to learn.  Needs a new ADR (use the [`new-decision`](../../.github/skills/new-decision/SKILL.md) skill) ratifying the TYPE_CHECKING-guarded Protocol pattern as the official answer to "I want a protocol shape on a library seam."  Estimated count once the pattern lands and seams are typed: **~80 source-side errors gone**.

### E. Test-fixture noise (the 653 in `tests/`)

Test files use ad-hoc fake objects (`class FakeSocket: ...` with the methods the test needs, no inherited Protocol).  Pyright sees them as `Unknown` and flags every attribute access.  Two reasonable answers:

1. **Per-file `# pyright: basic` headers** on the worst offenders (top 8 files account for ~430 of the 653).  Cheap and visible.
2. **Reusable Protocol shims in each library's `testing.py`** that the fakes inherit from.  Once Phase 4 lands its TYPE_CHECKING idiom, `testing.py` files can import the same protocols and have `FakeTransport(TransportLike)` etc.  Higher upfront effort, but tests get IDE awareness in return — and the protocols already exist from Phase 4.

Recommendation: **defer until Phase 4 lands**.  Phase 4 produces the protocols Phase 5 wants to inherit from.

### F. Functional tests + examples (135 in those trees)

These import platform modules (`wifi`, `microcontroller`, `socketpool`, `esp32`) directly — pyright sees stubs but no source.  Phase 0 silenced the "no source" warning channel; the residual errors are mostly attribute-access on those stubs (the stubs are incomplete).  Either let them sit (they're not blocking anyone), or scope `pyright` execution to skip `functional_tests/` + `examples/` once we add a preflight phase.

Recommendation: **defer**.  Revisit when adding pyright to preflight.

## Phase tracker

- [x] **Phase 0** — pyrightconfig tuning (shipped 2026-05-09).  Net change: 44 → 1 warning, 1054 → 1053 errors; warning channel is now signal-only.
- [x] **Phase 1** — this categorization (shipped 2026-05-09).
- [ ] **Phase 2** — Family A (real defects, ~12) + Family B (Optional narrowing, ~70) + Family C (hasattr-guarded MP attrs, ~22) source fixes.  Library-by-library, runtime-validated via per-package tests.  Estimated ~104 source errors gone, no new ADRs needed.
- [ ] **Phase 3** — workbench + scripts source fixes (24 + 12 = 36 source errors).  Pure-CPython trees, all errors should be fixable normally.
- [ ] **Phase 4** — Family D (duck-typed seams, ~80).  Gates on a new ADR ratifying the TYPE_CHECKING-guarded Protocol pattern; then a single shared `chumicro_compat.protocols` module + per-library annotation pass.  Largest single bucket.
- [ ] **Phase 5** — Family E (test-fixture noise, ~653).  Approach picked once Phase 4 lands.
- [ ] **Phase 6** — add `pyright` as a preflight phase once errors are at a maintainable steady-state count.

## Tooling notes

- Re-running pyright: `.venv/bin/pyright --outputjson > .scratch/pyright.json` then `.venv/bin/python -c "import json,collections;data=json.load(open('.scratch/pyright.json'));print(data['summary'])"`.
- Pyright version pinned indirectly via `pyright-python` plugin; current = 1.1.408.  Upgrade hint surfaced on every run; ratchet on intentional refresh, not drift.
- `pyrightconfig.json` is the single config source.  No per-tree `pyright` blocks in any `pyproject.toml`.
