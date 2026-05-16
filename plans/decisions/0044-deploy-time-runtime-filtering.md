# Decision 0044: Deploy-time runtime-file filtering

Status: `accepted`
Date: `2026-05-02`
Related: [Decision 0037](0037-runtime-file-marking.md) (per-runtime file marking + bundle filtering), Decision 0027 / 0028 (transport protocols), Decision 0029 (workspace deploy layouts), Decision 0042 (library dependency policy).

## Context

Decision 0037 introduced the `__chumicro_runtimes__` marker so the bundle pipeline (`scripts/bundle_manager.py`) could ship only matching files into per-runtime mpy bundles consumed via `circup` / `mip`.  At the time the universal source bundle (mip-installable from the bundle root) was left unfiltered, and PyPI sdists ship every file regardless of marker — the on-device runtime selector (`_select_adapter`, `_select_backend`) decides which adapter to import.

That left a gap: every other on-device deploy path also shipped unfiltered.  When `chumicro_workspace deploy` pushes a project to a CircuitPython board, when `chumicro_deploy` flashes a bundle of files, when `pytest-device` stages a library for a functional test, when an example gets copied to a board — wrong-runtime adapter source still landed on the device.  Default-safe in the sense that the runtime selector imports only the matching adapter, but wasted flash and surprising for users who reasonably assumed `__chumicro_runtimes__` controlled what reached the device.

The cost is meaningful on tier-floor hardware (256 KB RAM, 4 MB flash per Decision 0015): the unused `cp.py` / `mp.py` / `cpython.py` adapters across `sockets`, `wifi`, and `kvstore` total a few KB per library — small individually, larger when a workspace ships many libraries.  More importantly, the marker semantics didn't match user intuition: "I marked this CP-only, why is it on my MP board?"

## Decision

The `__chumicro_runtimes__` marker filters every host-side path that copies library files to a board.  Filtering is **on by default** at every deploy boundary; the only knob is which runtime to filter for.

### Layering

The marker reader lives in `chumicro_deploy.runtime_marker` (extracted from `bundle_manager.py` so the bundle pipeline and the deploy paths share one implementation; `read_runtime_marker` and `file_targets_runtime` are also re-exported from `chumicro_deploy.__init__`, so callers can `from chumicro_deploy import read_runtime_marker`).  Two functions:

```python
def read_runtime_marker(path: Path) -> frozenset[str] | None: ...
def file_targets_runtime(path: Path, *, target_runtime: str | None) -> bool: ...
```

`target_runtime=None` means "no filter" — the legacy default kept for callers that haven't opted into a target.  Every other consumer passes a concrete runtime (transports, deploy CLIs) or a frozenset of acceptable runtimes (the universal source bundle in `bundle_manager`).

Test-support modules (`testing.py`) are filtered by a *separate*, runtime-independent rule — `is_test_support_module()`, also in `chumicro_deploy.runtime_marker` ([Decision 0069](0069-test-support-module-marker.md)).  It is applied alongside the runtime filter at every boundary below: a file is dropped if the runtime marker excludes it **or** it is a test-support module.  The single exception is the on-device unit sweep (`--target device-unit`, [Decision 0068](0068-unified-deploy-mode-resolution.md)): `CircuitpythonTransport.stage()` / `MicropythonTransport.stage()` take an `include_test_support` flag (default `False`) that only the device-unit staging path sets `True`, because the cross-runtime unit tests legitimately import the fakes — exactly as unix-port already resolves them in place.

### Where filtering applies

| Layer | Filter source | User override |
|---|---|---|
| `DirectorySource` / `ImportGraphSource` (primitives) | `target_runtime` constructor kwarg, defaults `None` | n/a — caller decides |
| `CircuitpythonTransport.stage()` (RAM + flash) | hard-coded `"circuitpython"` (transport identity) | n/a |
| `MicropythonTransport.stage()` | hard-coded `"micropython"` (transport identity) | n/a |
| `chumicro_deploy` CLI (`deploy`) | probe / `--transport` value of the device | `--target-runtime <name>` |
| `chumicro_workspace deploy` | `device.transport` of the resolved deploy target | `--target-runtime <name>` |
| `pytest-device` plugin | inherited from transport | n/a — runtime is implicit |
| `flash_drive.merge_packages` | passed by caller (transport) | `target_runtime` kwarg |

The transports (`CircuitpythonTransport`, `MicropythonTransport`) own the deploy-time runtime as part of their identity.  Selecting one *is* declaring the target runtime; no override flag is needed at the transport layer.

The orchestration layer (CLIs) defaults to filtering by the device's configured runtime.  `--target-runtime <name>` overrides for unusual cases (cross-runtime testing, dev tooling); there is no `--no-runtime-filter`.

### Sub-runtime fold

Sub-runtime markers (`micropython_esp32`, `micropython_rp2`) fold into `"micropython"` for matching, mirroring the bundle-pipeline behavior (Decision 0037).  When per-port mpy bundles arrive, transports can pass the more specific name — the marker vocabulary already supports it.

### What stays unchanged

- **PyPI sdist / wheel** — built by `python -m build` (not `bundle_manager`); ships every file under `src/` including `testing.py` (test-support) and every runtime adapter.  `pip install chumicro-foo` on a CPython host gets the complete library.
- **circup / mip per-runtime bundles** — already filtered by `bundle_manager`, no change.
- **`FileMapSource`** — caller already chose bytes; no walk to filter.
- **Runtime selector code** — `_select_adapter` / `_select_backend` are unchanged.  They remain the device-side counterpart; the deploy filter is the host-side counterpart.
- **`verify-examples`** — host-side import check, not a board deploy.

## Consequences

- Wrong-runtime adapter files no longer land on the device for any deploy path: workspace `deploy`, `chumicro_deploy` CLI, `pytest-device` staging, examples, functional tests.  The `__chumicro_runtimes__` marker now matches user intuition end-to-end.
- A few KB of flash / RAM saved per library on tier-floor boards.  More noticeable as workspaces grow; aligns with the Pi Pico W flash-footprint learning that drove Decision 0037.
- Decision 0037's "default-safe" rule still applies: unmarked files ship to every target.  We do not enforce marker presence — a runtime-only file without a marker still ships everywhere (lint-rule territory if we want to tighten later).
- The bundle pipeline and the deploy paths now share `chumicro_deploy.runtime_marker`.  Future changes to marker semantics (new sub-runtimes, fold rules, etc.) live in one place.
- The `ImportGraphSource` docstring used to document its deliberate "ship both adapters" behavior — that comment is preserved as the `target_runtime=None` semantics, since the runtime selector still demands both adapters be present when the host doesn't know the target.  Once `target_runtime` is set (the workspace / CLI default), only the matching adapter ships.
