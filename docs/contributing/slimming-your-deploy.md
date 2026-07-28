# Slimming your deploy

When you deploy a project, `chumicro-workspace` copies every chumicro library that anything in your project imports onto the board, including the small helper each library uses to build its default transport (typically a `chumicro_sockets` socket).

Most of the time that's fine.  But if you're passing your own socket into a library (say `MQTTClient(transport_factory=my_factory, ...)`), the default-builder helper is dead code on your board, and so is `chumicro_sockets` underneath it.  The deployer can't tell at deploy time which path your code will take at runtime, so it ships both.

[Decision 0062](../../plans/decisions/0062-entrypoint-factory-skip.md) lets you say "skip the default builder; I'm bringing my own."  Add one line to your `app.py` (or `code.py`, whichever your project's entrypoint is):

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

The deployer reads that constant, leaves the named factory helpers out of the deploy, and the libraries they pull in (typically `chumicro_sockets`) stay off the board.

## Family form and exact form

The skip constant accepts two entry shapes, mix freely:

```python
# app.py
__chumicro_skip_factories__ = (
    "sockets_factory",                       # family: skip every <library>.sockets_factory
    "chumicro_websockets.tls_factory",       # exact: skip just this one
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
RuntimeError: chumicro_sockets.sockets_factory not available
(excluded via __chumicro_skip_factories__ or not on the board);
pass transport_factory= or socket= explicitly.
```

The five library `from_config` methods that lazy-import a factory submodule (mqtt, requests, websockets, ntp, http_server) all emit this message with their own bypass-kwarg names.  The "not on the board" half of the message covers manual `circup` / `mip` installs that selected the library but omitted its factory submodule: the failure mode is the same loud `RuntimeError` either way.

## Two informational warnings via `source.skip_factories_warnings()`

The walker accumulates two kinds of non-fatal hints on the source object:

**Direct-import override.**  If your entrypoint imports a skip target explicitly (`import chumicro_sockets.sockets_factory` at module top), the walker keeps the file in the deploy and warns:

```
__chumicro_skip_factories__ names 'chumicro_sockets.sockets_factory' but
the entrypoint imports it directly; shipping it anyway.
```

This catches the contradiction between "I want to skip this" and "I'm using it directly" without forcing you to pick: the explicit import wins.

**Dead skip.**  If a user-written entry matches discovered modules, but none of their parent libraries are imported anywhere in the deploy:

```
__chumicro_skip_factories__ entry 'chumicro_websockets.tls_factory'
matches ['chumicro_websockets.tls_factory'] but none of those
libraries are imported; skip entry has no effect.
```

The `sockets_factory` family entry now resolves to the single shared `chumicro_sockets.sockets_factory` module, so it counts as live whenever any networking library's default wiring reaches that module, and goes dead only when nothing in the deploy does.

## When this matters (and when it doesn't)

The skip mechanism only fires under the `chumicro-workspace` deploy path (`chumicro-workspace deploy <project>`).  `circup` and `mip` install the on-device libraries through their own dep-graph resolution: they read each package's pyproject.toml dependencies and install transitively with no `--no-deps` flag.  See [Decision 0042](../../plans/decisions/0042-library-dependency-policy.md) for the why; the bench evidence is recorded in the body of [Decision 0062](../../plans/decisions/0062-entrypoint-factory-skip.md).

You'll feel the difference if and only if:

1. Your project's entrypoint imports a chumicro library that has a `<stem>_factory.py` submodule.
2. You supply your own version of whatever the factory produces through the constructor (`transport_factory=` / `socket=` / `listener=` on the libraries that take a transport).
3. You deploy via `chumicro-workspace`.

If any of those three is false, the skip constant is a no-op and the dead-skip warning will (correctly) point that out.

## Compatibility with on-device library curation

The `chumicro-workspace library` CLI (`list` / `browse` / `add` / `update` / `remove` / `forget` / `switch-channel`) is the on-device library host: it pulls a chumicro library *and the chumicro libraries it transitively needs* from PyPI into the workspace's `libraries/` folder, where the deploy walker treats them like local libraries.  `library add` resolves the transitive set from each fetched library's `pyproject.toml`, so dropping a library also drops the deps only it reached.  The skip-factories constant is the entrypoint-shape annotation that decides which factory submodules (and therefore which transitive deps) are actually needed; the same constant works for both deploy paths.

## For library authors: how the convention works

The transport factory builders live in one shared module, `chumicro_sockets.sockets_factory`.  A networking library does not carry its own copy; its `from_config` (or any other construction path) lazy-imports the builder it needs and wraps the import so a skipped or absent module fails loudly:

```python
if factory_kwarg is None:
    try:
        from chumicro_sockets.sockets_factory import connector_factory
    except ImportError as exception:
        raise RuntimeError(
            "chumicro_sockets.sockets_factory not available "
            "(excluded via __chumicro_skip_factories__ or not on the "
            "board); pass transport_factory= explicitly.",
        ) from exception
```

That is the contract every `from_config` in mqtt, requests, websockets, ntp, and http_server implements; mirror it for new networking libraries.

The walker discovers factory submodules by glob: every file under `chumicro_*/` matching `[a-z][a-z0-9_]*_factory.py` is a candidate, so the same skip mechanism covers a new factory family if you add one.  Place such a file at the package root (`libraries/<name>/src/chumicro_<name>/<stem>_factory.py`), not in a subdirectory like `factories/`, and pick a descriptive stem (`sockets_factory` for TCP/UDP injection, `tls_factory` for SSL-context injection).  The bare stem is what the family-form skip matches.
