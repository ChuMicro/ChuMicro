# Slimming your deploy

`chumicro-workspace`'s deployer ships exactly the files your `app.py` imports — the AST walker (`chumicro_deploy.ImportGraphSource`) follows every static `import`, including lazy ones inside function bodies.  Most of the time that's exactly what you want.  But for a custom-transport user who never calls into `chumicro_sockets`, the walker still ships every byte of it because `MQTTClient.from_config` (and its four siblings) lazy-imports `chumicro_<lib>.sockets_factory` at config-driven construction time, and that factory imports `chumicro_sockets` in its closure.

[Decision 0062](../../plans/decisions/0062-entrypoint-factory-skip.md) introduces an entrypoint-level opt-out for those factory submodules.  Drop a module-level constant into `app.py` (or `code.py` — whichever your project's entrypoint is) and the walker filters the named factories out of the deploy graph before resolution, taking their closure-only dependencies (typically `chumicro_sockets`) with them.

## The mechanism in one paragraph

```python
# app.py
__chumicro_skip_factories__ = (
    "sockets_factory",                       # family form
    "chumicro_websockets.tls_factory",       # exact form
)
```

`sockets_factory` (no dot) is a *family* match — every discovered `chumicro_*/sockets_factory.py` under your search paths gets filtered.  `chumicro_websockets.tls_factory` (one dot) is an *exact* match — only that one module gets filtered.  Mix both forms freely.

## Two failure modes that surface loudly, not silently

**Typo.**  An entry that matches zero discovered factory modules fails the deploy:

```
ValueError: __chumicro_skip_factories__ entries did not match any discovered
factory module: ['socet_factory'].  Discovered families: ['sockets_factory',
'tls_factory'].
```

A silent skip that shipped the unwanted library would be a worse outcome than refusing to deploy.

**Misuse at runtime.**  If you skip a factory but then call the affected library's `from_config(...)` on the device, the lazy import inside `from_config` is wrapped in `try/except ImportError → RuntimeError`:

```
RuntimeError: MQTTClient.from_config() default wiring needs
chumicro_mqtt.sockets_factory.  This module was excluded via
__chumicro_skip_factories__ — pass socket_factory= or socket= explicitly.
```

The five library `from_config` methods that lazy-import a factory submodule — mqtt, requests, websockets, ntp, http_server — all emit this message with their own bypass-kwarg names.

## Two informational warnings via `source.skip_factories_warnings()`

The walker accumulates two kinds of non-fatal hints on the source object:

**Direct-import override.**  If your entrypoint imports a skip target explicitly (`import chumicro_mqtt.sockets_factory` at module top), the walker keeps the file in the deploy and warns:

```
__chumicro_skip_factories__ names 'chumicro_mqtt.sockets_factory' but
the entrypoint imports it directly; shipping it anyway.
```

This catches the contradiction between "I want to skip this" and "I'm using it directly" without forcing you to pick — the explicit import wins.

**Dead skip.**  If a user-written entry matches discovered modules, but none of their parent libraries are imported anywhere in the deploy:

```
__chumicro_skip_factories__ entry 'chumicro_websockets.tls_factory'
matches ['chumicro_websockets.tls_factory'] but none of those
libraries are imported; skip entry has no effect.
```

A family entry that matches five libraries is dead only when none of those five are imported — a single-library project listing `("sockets_factory",)` doesn't get four spurious warnings.

## When this matters (and when it doesn't)

The skip mechanism only fires under the `chumicro-workspace` deploy path (`chumicro-workspace deploy <project>`).  `circup` and `mip` install the on-device libraries through their own dep-graph resolution — they read each package's pyproject.toml dependencies and install transitively with no `--no-deps` flag.  See [Decision 0042](../../plans/decisions/0042-library-dependency-policy.md) for the why; the bench evidence is recorded in the body of [Decision 0062](../../plans/decisions/0062-entrypoint-factory-skip.md).

You'll feel the difference if and only if:

1. Your project's entrypoint imports a chumicro library that has a `sockets_factory` (or similar) submodule.
2. You supply your own transport (`socket_factory=` / `connection_factory=` / `listener_factory=` / `socket=`).
3. You deploy via `chumicro-workspace`.

If any of those three is false, the skip constant is a no-op and the dead-skip warning will (correctly) point that out.

## Compatibility with on-device library curation

The Tier 2 workstream ([`workstreams/workspace-library-curation.md`](../../plans/workstreams/workspace-library-curation.md)) is building a `chumicro-workspace library` CLI that becomes the on-device library host — it would let you drop a library from a deploy *and* drop the transitive deps that only that library reached.  When that lands, the skip-factories constant becomes the entrypoint-shape annotation the library command reads to decide which deps are needed.  The same constant works for both deploy paths.

## For library authors: how the convention works

The walker discovers factory submodules by glob — every file under `chumicro_*/` matching `[a-z][a-z0-9_]*_factory.py` is a candidate.  Two implications:

* Place the helper at the package root: `libraries/<name>/src/chumicro_<name>/<stem>_factory.py`, not in a subdirectory like `factories/`.
* Pick a descriptive stem that matches its peers across the workspace — `sockets_factory.py` for TCP/UDP injection, `tls_factory.py` for SSL-context injection, etc.  The family-form skip works because users can spell *one* name and mean *all* libraries.

If your library's `from_config` (or any other construction path) lazy-imports its factory submodule, wrap the import in `try/except ImportError → RuntimeError`:

```python
if factory_kwarg is None:
    try:
        from chumicro_<name>.<stem>_factory import <factory_callable>
    except ImportError as exception:
        raise RuntimeError(
            "<ClassName>.from_config() default wiring needs "
            "chumicro_<name>.<stem>_factory.  This module was excluded "
            "via __chumicro_skip_factories__ — pass <kwarg>= explicitly.",
        ) from exception
```

That's the contract every `from_config` in mqtt / requests / websockets / ntp / http_server already implements; mirror it for new libraries.  The `new-library` scaffolder generates the factory file at the canonical path — if you scaffolded via `python scripts/run.py new-library`, the placement is already right.
