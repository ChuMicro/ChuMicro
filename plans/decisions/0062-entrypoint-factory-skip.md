# Decision 0062: Entrypoint opt-out for chumicro factory submodules

Status: `accepted`
Date: `2026-05-12`
Summary: `__chumicro_skip_factories__ = (...)` entrypoint constant tells the deploy walker to skip factory submodules; `from_config` raises a clear error when the skipped module is missing.
Related: [Decision 0042](0042-library-dependency-policy.md) (the sub-rule this corrects), [Decision 0029](0029-project-workspace.md) (the AST walker this extends), [Decision 0037](0037-runtime-file-marking.md) (precedent for entrypoint-level marker constants).

## Context

Decision 0042's "factory helper in its own submodule" sub-rule was meant to give users a deploy-time opt-out: a custom-transport user who never imports `chumicro_<lib>.sockets_factory` would not see `chumicro_sockets` ship to their device, even though it sits in `[project].dependencies`.

Bench-verified 2026-05-12 against `workbench/deploy/src/chumicro_deploy/sources.py` (the AST import-graph walker): the opt-out does not fire.  The walker uses `ast.walk(tree)`, which traverses function bodies recursively.  `from_config`'s lazy `from chumicro_<lib>.sockets_factory import ...` is discovered statically and followed, which pulls the factory submodule into the deploy graph, which in turn pulls `chumicro_sockets` through the closure-internal import.

Two test apps reproduced the failure identically:

```
app_custom.py     # MQTTClient(transport_factory=mine, ...)
app_default.py    # MQTTClient.from_config({...})
```

Both shipped the same eleven files: `chumicro_mqtt/*` + `chumicro_mqtt/sockets_factory.py` + all of `chumicro_sockets/*`.

The walker cannot tell which `from_config` branch will run at runtime, so it must conservatively include both.  A real opt-out needs an explicit signal at the deploy root.

## Decision

Users opt out per-entrypoint via a module-level constant the walker reads at AST time:

```python
# app.py (or code.py — whichever the project's entrypoint is)
__chumicro_skip_factories__ = (
    "sockets_factory",                    # family — skip every <lib>.sockets_factory
    "chumicro_websockets.tls_factory",    # exact — skip just this one
)
```

### Walker rule

When the walker parses an entrypoint, it scans the AST for `__chumicro_skip_factories__` (matching the precedent set by `__chumicro_runtimes__`).  Two match shapes:

- **Exact** — entry contains `.`: matched as a fully-qualified module path against discovered factory submodules.
- **Family** — entry contains no `.`: matched against the last segment of every discovered module whose path matches `chumicro_*/[a-z_]+_factory.py`.

Matched modules are removed from the discovered-imports queue before resolution.  Modules that *were* reachable only through a filtered factory submodule fall out of the graph naturally (the walker resolves nothing pointing at them).  Modules reachable through other paths — e.g. `chumicro_sockets` if the user has `import chumicro_sockets` for direct UDP use — stay in.

### Library-side error contract

Every `from_config` that lazy-imports a factory submodule wraps the import in `try`/`except ImportError` and raises a `RuntimeError` naming the skipped module + the kwarg the user should pass instead.  Example:

```python
if socket is None and transport_factory is None:
    try:
        from chumicro_mqtt.sockets_factory import chumicro_sockets_connector_factory
    except ImportError as exc:
        raise RuntimeError(
            "chumicro_mqtt.sockets_factory not available (excluded via "
            "__chumicro_skip_factories__ or not on the board) — pass "
            "transport_factory= or socket= explicitly.",
        ) from exc
    transport_factory = chumicro_sockets_connector_factory(config, ...)
```

### Walker-side diagnostics

- **Typo guard:** every entry in `__chumicro_skip_factories__` must match at least one discovered factory module.  Unmatched entries fail the walk with a clear error message naming the unmatched entry — silent typos that ship the unwanted library are a worse outcome than refusing to deploy.
- **Direct-import override:** if the user names a skip target *and* references it explicitly elsewhere in the import graph (e.g. `import chumicro_mqtt.sockets_factory` in any user-app file), the direct reference wins.  The walker emits a warning that the skip is contradicted but does not fail — the user gets what they asked for at the direct-import site.
- **Dead-skip warning:** if a skip target matches a discoverable module but the module's parent library is never imported anywhere in the graph, the walker emits an info-level warning that the skip is unused.  Cleanup hint, not a failure.

### Scope

Per-entrypoint only.  Each deployable entrypoint (typically `app.py` or `code.py` in a workspace-template project folder) reads its own constant independently — no workspace-level fallback, no host-level configuration.  Deploy shape stays fully determined by the entrypoint file, preserving reproducibility across machines.

## Consequences

### Positive

- **Beginner path unchanged.** `MQTTClient.from_config(config)` continues to auto-wire and deploy with the default factory.  No opt-in mechanics, no required imports.
- **Power user gets one declarative line at the entrypoint** — exactly where deploy-shape decisions belong.  Per-factory granularity (skip mqtt's default while keeping requests' default).
- **Family form scales to multi-library workspaces.** Custom transport across mqtt + requests + websockets + ntp + http_server becomes a single `"sockets_factory"` entry instead of five exact paths.
- **Reproducibility preserved.** Deploy shape determined by the entrypoint file alone — no global state, no host-config footgun.
- **No library API change.** `from_config` signatures stay identical; only the lazy-import block gains a `try`/`except`.
- **Decision 0042's promise is now actually delivered** — the sub-rule's "deploy-time opt-out" reasoning becomes correct when paired with this mechanism.

### Negative

- **Walker complexity grows modestly.** AST scan for one constant, family-name matching against a discovered factory list, three diagnostic paths (typo / override / dead-skip).  ~50 LOC + tests in `chumicro_deploy.sources`.
- **Library-side boilerplate.** Every `from_config` with a lazy factory import grows three lines for the `try`/`except`/`raise`.  Five existing libraries today (mqtt, requests, websockets, ntp, http_server) need the wrap.
- **Naming convention is load-bearing.** `chumicro_*/[a-z_]+_factory.py` must be honored — a future factory submodule named `connection_helper.py` would silently miss the family-skip mechanism.  Mitigated by the new-library scaffolder generating factory files at the canonical path.

### Alternatives considered

- **Explicit opt-in** — user adds `import chumicro_mqtt.sockets_factory` to their entrypoint to enable the default wiring.  Rejected: breaks the beginner path that today "just works" via `from_config(config)`.  Moves friction to the wrong audience.
- **Interprocedural call-site analysis** — walker reads the entrypoint for `Class.from_config(...)` invocations and decides per-call whether to include the factory.  Rejected: real engineering effort, only catches direct dispatch (misses factory wrappers and indirect call patterns), and fragile to refactors that move construction into helpers.  Revisit if the explicit-skip mechanism hits a real-world friction wall.
- **Global cross-project skip** (`~/.chumicro/skip-factories.yml` or env var).  Deferred: a host-level config makes the same code deploy differently on different machines — reproducibility footgun outweighs the ergonomic gain of "I always skip X."  Reintroduce only if 3+ users independently request it from real projects, not hypothetically.
- **Per-factory marker file** (`__chumicro_conditional__ = True` in each `*_factory.py`).  Rejected as the primary mechanism: adds a file-side declaration the new-library scaffolder must remember to write.  Naming convention covers the same ground at lower cost; reach for an explicit marker only when a factory module legitimately falls outside the convention.

The implementation punch-list (walker change + per-library `try`/`except` wraps + new-library scaffolder updates + the documentation page on slimming deploys) lives in `plans/next-up.md`, not here.

## Bench validation

End-to-end run against the same two fixtures that disproved the original 0042 sub-rule — an `mqtt` deploy through `ImportGraphSource`, with `search_paths` spanning the workspace libraries the mqtt graph reaches (`chumicro_mqtt` + `chumicro_config` + `chumicro_msgpack` + `chumicro_sockets` + `chumicro_timing`) and `target_runtime="circuitpython"` (the `/code.py` deploy shape):

| Fixture | Ships (CircuitPython) |
|---|---|
| `app_default.py` (no constant) | 17 files — `/code.py` + `chumicro_mqtt/{__init__,_wire,client,sockets_factory}.py` + the CircuitPython `chumicro_sockets/*` closure (`__init__`, `_connector`, `_adapters/{__init__,cp}`) + `chumicro_config/{__init__,runtime,section}.py` + `chumicro_msgpack/{__init__,_pure}.py` + `chumicro_timing/{__init__,deadline,ticks}.py` |
| `app_custom.py` with `__chumicro_skip_factories__ = ("sockets_factory",)` | 7 files — `/code.py` + `chumicro_mqtt/{__init__,_wire,client}.py` + `chumicro_timing/{__init__,deadline,ticks}.py`; zero `sockets_factory.py`, zero `chumicro_sockets/*`, `chumicro_config/*`, `chumicro_msgpack/*` |

The one-line marker drops ten files: `chumicro_mqtt/sockets_factory.py` plus its transitive-only closure — four `chumicro_sockets/*` files, three `chumicro_config/*`, and two `chumicro_msgpack/*`.  Config and msgpack fall out because `client.py` reaches them *only* through `sockets_factory.py`'s `from_config` wiring; the DI cleanup that stripped the module-top `chumicro_config` / `chumicro_sockets` / `chumicro_timing` imports from every consumer means nothing else pulls them in.  `chumicro_timing` stays either way: `MQTTClient.__init__` imports its `ticks` submodule as the default tick source regardless of the transport.  Without the marker the walker's behavior is unchanged — the mechanism is opt-in via the entrypoint constant, no default-behavior shift.

The same rerun on `target_runtime="micropython"` ships 19 files by default — the MicroPython adapter `_adapters/mp.py` plus the `_ca_bundle.py` / `_ca_bundle.der` TLS root bundle replace the single CircuitPython `_adapters/cp.py` — and the identical 7 files with the marker, a twelve-file drop.

### Limits as originally bench-validated

When this ADR first landed (2026-05-12) the post-skip count leaned on a walker bug: `chumicro_deploy.sources._resolve_module` returned `None` for an unresolvable import and the walk silently dropped it.  Every consumer of the skipped factory still had module-top imports of `chumicro_config` / `chumicro_sockets` / `chumicro_timing` then — for type guards (`is_config_like` / `InvalidConfigType`), the `is_eagain` hot-path helper, and the `_DEFAULT_TICKS` DI fallback — so those packages vanished from the graph without complaint and the device-side `client.py` would have `ImportError`'d at boot.  Two corrections have since shipped, so the counts above hold on the merits:

1. The eager `chumicro_config` / `chumicro_sockets` / `chumicro_timing` imports were stripped from mqtt / requests / ntp / http_server / websockets (the "drop eager … imports" commits).  A skipped factory now genuinely severs those packages from the graph rather than the walker hiding them.
2. The silent-skip itself became a deploy-time refusal: the walker collects every unresolvable non-builtin import and raises `UnresolvedImportError` instead of shipping a boot-time crash (see `plans/workstreams/walker-unresolved-import-failure.md`).  This rerun therefore cannot under-count via a hidden drop — an unresolved import aborts the bench outright.
