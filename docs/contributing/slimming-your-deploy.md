# Slimming your deploy

A project deploy copies onto the board every ChuMicro library that anything in the project imports. That includes `chumicro_sockets.sockets_factory`, the small helper the networking libraries share to build their default transport.

A project that passes its own transport into a library, such as `MQTTClient(transport_factory=my_factory, ...)`, never runs that helper, or the `chumicro_sockets` code under it. The deployer can't tell at deploy time which path the code takes at runtime, so it ships both.

One line in the project's entrypoint, `app.py` or `code.py`, leaves the default builder out ([Decision 0062](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0062-entrypoint-factory-skip.md)):

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

The deployer reads the constant and leaves the named factory modules out of the deploy, so the libraries only they pull in, usually `chumicro_sockets`, stay off the board.

## Family form and exact form

The constant takes two kinds of entry, mixed freely:

```python
# app.py
__chumicro_skip_factories__ = (
    "sockets_factory",                       # family: skip every <library>.sockets_factory
    "chumicro_sockets.sockets_factory",      # exact: skip just this one module
)
```

A bare stem with no dot, such as `"sockets_factory"`, matches every library's `sockets_factory.py`. A dotted path, such as `"chumicro_sockets.sockets_factory"`, matches one module. The libraries ship one factory module, `chumicro_sockets.sockets_factory`, so both forms select that file.

## Mistakes that fail loudly

**A typo.** An entry that matches no discovered factory module fails the deploy:

```
ValueError: __chumicro_skip_factories__ entries did not match any discovered
factory module: ['socet_factory'].  Discovered families: ['sockets_factory'].
```

The deploy refuses, because a silent skip would ship the library you meant to leave off.

**Calling `from_config` after skipping its factory.** `from_config` imports the factory lazily, and raises `RuntimeError` when the import fails:

```
RuntimeError: chumicro_sockets.sockets_factory not available
(excluded via __chumicro_skip_factories__ or not on the board);
pass transport_factory= or socket= explicitly.
```

The `from_config` methods in mqtt, requests, websockets, ntp, and http_server all raise this error, each naming its own keyword argument. The message's "not on the board" half covers a `circup` or `mip` install that left the factory module out, which fails the same way. [Deploy refused, or ImportError on boot](../troubleshooting/deploy-refused-importerror.md#runtimeerror-chumicro_socketssockets_factory-not-available) has the fix.

## Warnings from `source.skip_factories_warnings()`

The deploy's import walker collects non-fatal hints on the source object.

**A direct import of a skipped module.** When the entrypoint imports a skip target itself, for example `import chumicro_sockets.sockets_factory` at module top, the walker keeps the file in the deploy and warns:

```
__chumicro_skip_factories__ names 'chumicro_sockets.sockets_factory' but
the entrypoint imports it directly; shipping it anyway.
```

The explicit import wins over the skip entry.

**A dead skip.** When an entry matches discovered modules, and the deploy imports none of their libraries:

```
__chumicro_skip_factories__ entry 'sockets_factory' matches
['chumicro_sockets.sockets_factory'] but none of those libraries are
imported; skip entry has no effect.
```

The `sockets_factory` family entry matches one module, the shared `chumicro_sockets.sockets_factory`. The entry is live whenever any networking library's default wiring reaches that module. It goes dead when nothing in the deploy reaches it.

## When the skip saves space

The skip applies to `chumicro-workspace deploy <project>` only. `circup` and `mip` install every dependency a package declares, through their own resolution ([Decision 0042](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0042-library-dependency-policy.md)). [Decision 0062](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0062-entrypoint-factory-skip.md) records the bench measurements.

The skip saves space when all of these hold:

1. The project imports a ChuMicro library whose default wiring reaches a `<stem>_factory.py` module. mqtt, requests, websockets, ntp, and http_server all reach `chumicro_sockets.sockets_factory`.
2. The project passes its own transport through the constructor: `transport_factory=`, `socket=`, or `listener=`, depending on the library.
3. The project deploys through `chumicro-workspace`.

When the project imports no such library, the constant changes nothing, and the dead-skip warning says so. When the project still calls `from_config`, the skip breaks it at runtime, as [Mistakes that fail loudly](#mistakes-that-fail-loudly) shows.

## With `library add`

`chumicro-workspace library add` fetches a ChuMicro library, and every ChuMicro library it depends on, from a channel snapshot into the workspace's `libraries/` folder. The deploy walker treats those like local libraries, so the skip constant works on them unchanged.

## For library authors: how the convention works

The transport factory builders live in one shared module, `chumicro_sockets.sockets_factory`. A networking library's `from_config` imports the builder it needs lazily, and wraps the import so a skipped or missing module fails loudly:

<!-- fragment -->
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

Every `from_config` in mqtt, requests, websockets, ntp, and http_server follows this shape, and a new networking library follows it too.

The walker finds factory modules by name: every top-level file in a `chumicro_*` package whose name matches `[a-z][a-z0-9_]*_factory.py` is a candidate, so the skip covers a new factory family without changes. Place such a file at the package root, `libraries/<name>/src/chumicro_<name>/<stem>_factory.py`. A subfolder such as `factories/` hides it from the walker. Pick a stem that names what the module builds: `sockets_factory` builds TCP and UDP transports, and an SSL-context family might be `tls_factory`. The family-form skip matches that bare stem.
