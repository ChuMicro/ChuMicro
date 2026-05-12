# Slimming your deploy

When you deploy a project, `chumicro-workspace` copies every chumicro library that anything in your project imports onto the board — including the small helper each library uses to build its default transport (typically a `chumicro_sockets` socket).

Most of the time that's fine.  But if you're passing your own socket into a library — say `MQTTClient(socket_factory=my_factory, ...)` — the default-builder helper is dead code on your board, and so is `chumicro_sockets` underneath it.  The deployer can't tell at deploy time which path your code will take at runtime, so it ships both.

[Decision 0062](../../plans/decisions/0062-entrypoint-factory-skip.md) lets you say "skip the default builder; I'm bringing my own."  Add one line to your `app.py` (or `code.py` — whichever your project's entrypoint is):

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

The deployer reads that constant, leaves the named factory helpers out of the deploy, and the libraries they pull in (typically `chumicro_sockets`) stay off the board.

## Family form and exact form

The skip constant accepts two entry shapes, mix freely:

```python
# app.py
__chumicro_skip_factories__ = (
    "sockets_factory",                       # family — skip every <library>.sockets_factory
    "chumicro_websockets.tls_factory",       # exact — skip just this one
)
```

A bare stem like `"sockets_factory"` (no dot) matches every library's `sockets_factory.py`.  A dotted path like `"chumicro_websockets.tls_factory"` matches one module only.

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
RuntimeError: chumicro_mqtt.sockets_factory not available
(excluded via __chumicro_skip_factories__ or not on the board) —
pass socket_factory= or socket= explicitly.
```

The five library `from_config` methods that lazy-import a factory submodule — mqtt, requests, websockets, ntp, http_server — all emit this message with their own bypass-kwarg names.  The "not on the board" half of the message covers manual `circup` / `mip` installs that selected the library but omitted its factory submodule — the failure mode is the same loud `RuntimeError` either way.

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

1. Your project's entrypoint imports a chumicro library that has a `<stem>_factory.py` submodule.
2. You supply your own version of whatever the factory produces through the constructor (`socket_factory=` / `connection_factory=` / `listener_factory=` / `socket=` on the libraries that take a transport).
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
