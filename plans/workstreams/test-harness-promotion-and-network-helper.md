# Workstream: test_harness promotion + chumicro_test_harness.network

Status: **proposed.**  Accepts [Decision 0082](../decisions/0082-test-harness-as-infrastructure-library.md) (test_harness as infrastructure library) and tracks the implementation.  Pairs with the forthcoming "functional-test endpoint taxonomy" ADR — that decision names *how* networking tests are organized; this workstream lands the device-side primitive they all share.

## Problem

`support/test_harness/` ships with the mono-repo only.  Workspace-template consumers who pull a networking library via `chumicro-workspace library add` cannot run that library's examples or functional tests because the harness isn't in the snapshot.  Inside the mono-repo, every networking library's `functional_tests/*.py` violates AGENTS.md's test-isolation rule by importing `chumicro_wifi` / `chumicro_config` / `chumicro_timing` directly to bring wifi up.  The fix is to lift the shared wifi-bringup + runtime-config helpers into the harness as a new submodule and move the harness to where the snapshot can ship it.

## Implementation phases

### Phase 1 — `chumicro_test_harness.network` submodule (in-place, no move yet)

Add `support/test_harness/src/chumicro_test_harness/network.py` with `wifi_up(config) -> (radio, ip)` + `runtime_config() -> dict`.  Source-of-truth is the canonical `examples/helpers.py` body (currently duplicated across 5 networking libraries' `examples/`).  Uses only runtime built-ins (CP `wifi`, MP `network`, `struct`).  Cross-runtime test file covers the helper at the harness level.  Bump `support/test_harness/VERSION` accordingly.

### Phase 2 — Networking functional tests switch to the helper + align to [Decision 0083](../decisions/0083-functional-test-endpoint-taxonomy.md) categories

Five libraries: `requests`, `sockets`, `mqtt`, `ntp`, `http_server`.  Per file:

1. Drop `chumicro_wifi` / `chumicro_config` / `chumicro_timing` imports for the wifi-bringup body and switch to `from chumicro_test_harness.network import wifi_up, runtime_config`.
2. Add a one-line category declaration in the module docstring (`"""... Category 1 — host-side Mosquitto fixture."""` / `"""... Category 2 — public NTP pool; interop check."""`).
3. Where the file is currently mis-categorized, re-shape:
   - `http_server/test_real_serve.py` → Category 1: board runs the server (no change), host runs a stdlib socket client driver (new); no more self-loopback through the router.  Drops the `chumicro_requests` import in the same edit.
   - `mqtt/test_real_broker.py` → already Category 1; add declaration only.
   - `sockets/test_real_udp.py` (+ `test_real_tcp.py` if present) → already Category 1; add declaration only.
   - `requests/test_real_get.py`, `requests/test_real_get_tls.py` → Category 2; declaration names `example.com` interop as the rationale.
   - `ntp/test_real_ntp.py` → Category 2; declaration names `pool.ntp.org` interop as the rationale.

Host-side fixtures (Mosquitto, UDP echo, the new HTTP client driver for `http_server`) move from per-library `functional_tests/conftest.py` to a shared home at `workbench/pytest-device/src/chumicro_pytest_device/fixtures/`.  One canonical fixture per endpoint type; per-library conftests import.

On-device re-run per library after the rewrite, against `devices.yml` defaults (Pi Pico W CP + MP).

### Phase 3 — Examples switch to the helper, OR keep inlined per library

Per-library call.  When the per-platform pedagogy in `examples/helpers.py` is load-bearing for the demo's teaching value, the inlined copy stays and the scaffold's canonical source becomes `chumicro_test_harness.network.py`.  When the example doesn't gain pedagogy from the inline expansion, the example switches to the import.  Either way, the workstream `examples-helpers-cross-library-drift.md` is resolved: the source of truth is `chumicro_test_harness.network`; inlined copies in `examples/` are scaffold-seeded and held to canonical-source parity by a sync check.

### Phase 4 — Tree move `support/test_harness/` → `libraries/test_harness/`

`git mv` the tree.  Update `pyproject.toml` to add `[tool.chumicro] kind = "infrastructure"`.  Update inbound path references:

- `AGENTS.md` lines 81 (`support/<name>/src/` clause) and 179 (workspace table row) — both clauses dissolve along with the `support/` tree.
- `plans/decisions/0016-cross-runtime-unit-tests.md`, `plans/decisions/0058-test-skips-must-be-loud.md`, `plans/decisions/0070-host-only-test-marker.md` — inline `support/test_harness/...` references update in place.
- `scripts/`, `workbench/pytest-device/`, any tooling that names the path.
- `support/` directory removed; `support/docs/` either folds into `docs/contributing/` or is removed if redundant.

`python scripts/run.py preflight` green at coverage 94%.

### Phase 5 — Snapshot publishes the `kind` field; CLI filters by it

- `scripts/libraries_channel.py`: when generating `index.json`, read `[tool.chumicro] kind` from each library's `pyproject.toml`; record on the entry.
- `workbench/workspace/src/chumicro_workspace/library_channel.py:LibraryCatalogEntry` gains an optional `kind: str | None = None` field; `_parse_index` reads it.
- `workbench/workspace/src/chumicro_workspace/cli/library.py`: `list` and `browse` filter `kind == "infrastructure"` by default; `list --all` shows them.  `add` / `fetch_closure` ignore the flag.
- Forward-compatibility test: snapshots predating the field treat all entries as visible.

### Phase 6 — Distribution-graph dep declarations

Networking libraries that rely on `chumicro_test_harness.network` in their shipped `functional_tests/` (or that ship `examples/` that use it) add `chumicro-test-harness` to `[project].dependencies`.  Per Decision 0042, this is the authoritative graph the snapshot walker reads; per Decision 0078, `fetch_closure` pulls the dep transitively.

## Validation history

<!-- One line per phase as it lands.  Format: `- **YYYY-MM-DD** Phase N. <short summary> + commit hash.` -->

- **2026-05-24** Phase 1. `chumicro_test_harness.network` submodule (`wifi_up` + `runtime_config` + inline msgpack decoder) landed in-place with cross-runtime test coverage; preflight green at coverage 94 across CPython + MP + CP. Commit `4613ff0d`.
- **2026-05-24** Phase 2 / Slice 1. Eight functional-test files (mqtt + sockets x4 + ntp + requests x2) swapped to `chumicro_test_harness.network`; Category 1 / 2 declarations added per [Decision 0083](../decisions/0083-functional-test-endpoint-taxonomy.md); `test_assertions.py` self-circular `raises` cleanup. Commit `8c3c109f`.
- **2026-05-24** Phase 2 / blocking ADR. [Decision 0085](../decisions/0085-board-to-host-sync-stdout-markers.md) names the stdout-marker sync protocol Category 1 server-side tests need. Commit `11ff6a5f`.
- **2026-05-24** Phase 2 / Slice 2 deferred. `http_server/test_real_serve.py` rewrite blocked on `TransportProtocol.execute` becoming streaming-capable; pulled into [`workstreams/streaming-transport.md`](streaming-transport.md). Re-enters this workstream as a follow-up slice once that lands.
- **2026-05-24** Phase 2 / Slice 3. Host-side fixtures consolidated under `chumicro_pytest_device.fixtures` (`lan.py` / `mosquitto.py` / `udp_echo.py`); mqtt + sockets conftests import from the shared home. pytest-device `0.10.1` → `0.11.0` for the new public API. Preflight green at coverage 94.

## Out of scope

- Two-board functional-test orchestration (deferred to a separate workstream — pytest-orchestrated category 3 in the endpoint taxonomy).
- PyPI publication of `chumicro-test-harness`.  Decision 0082 leaves it as a one-flag follow-up if a downstream consumer asks.
- Restructuring of `chumicro_test_harness.discovery` (host-only) into a separate package.  Per Decision 0082, the runtime marker handles it; a split is future work if a real cost shows up.
