# Decision 0062: Entrypoint opt-out for chumicro factory submodules

Status: `accepted`
Date: `2026-05-12`
Related: [Decision 0042](0042-library-dependency-policy.md) (the sub-rule this corrects), [Decision 0029](0029-project-workspace.md) (the AST walker this extends), [Decision 0037](0037-runtime-file-marking.md) (precedent for entrypoint-level marker constants).

## Context

Decision 0042's "factory helper in its own submodule" sub-rule was meant to give users a deploy-time opt-out: a custom-transport user who never imports `chumicro_<lib>.sockets_factory` would not see `chumicro_sockets` ship to their device, even though it sits in `[project].dependencies`.

Bench-verified 2026-05-12 against `workbench/deploy/src/chumicro_deploy/sources.py` (the AST import-graph walker): the opt-out does not fire.  The walker uses `ast.walk(tree)`, which traverses function bodies recursively.  `from_config`'s lazy `from chumicro_<lib>.sockets_factory import ...` is discovered statically and followed, which pulls the factory submodule into the deploy graph, which in turn pulls `chumicro_sockets` through the closure-internal import.

Two test apps reproduced the failure identically:

```
app_custom.py     # MQTTClient(socket_factory=mine, ...)
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
if socket is None and socket_factory is None:
    try:
        from chumicro_mqtt.sockets_factory import chumicro_sockets_factory
    except ImportError as exc:
        raise RuntimeError(
            "MQTTClient.from_config() default wiring needs "
            "chumicro_mqtt.sockets_factory.  This module was excluded "
            "via __chumicro_skip_factories__ — pass socket_factory= "
            "or socket= explicitly.",
        ) from exc
    socket_factory = chumicro_sockets_factory(config, ...)
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

End-to-end run against the same two fixtures that disproved the original 0042 sub-rule (`mqtt` deploy, search paths over the six infra libraries):

| Fixture | Before walker change | After walker change |
|---|---|---|
| `app_default.py` (no constant) | 20 files including all of `chumicro_sockets/*` + `chumicro_mqtt/sockets_factory.py` | 20 files (identical — no opt-out signal) |
| `app_custom.py` with `__chumicro_skip_factories__ = ("sockets_factory",)` | Same 20 files (opt-out didn't fire) | 12 files — `chumicro_mqtt/{__init__,_wire,client}.py` + transitive `chumicro_config`, `chumicro_msgpack`, `chumicro_timing`; zero `chumicro_sockets/*`, zero `sockets_factory.py` |

The post-implementation diff is the eight-file drop (`chumicro_mqtt/sockets_factory.py` + seven `chumicro_sockets/*` files).  Walker behavior under the legacy fixture is unchanged — the mechanism is opt-in via the entrypoint constant, no default behavior shift.
