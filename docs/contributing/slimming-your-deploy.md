# Slimming your deploy

An import-graph deployment follows imports in your project and its libraries, including imports inside functions and conditional branches. Supplying a custom transport at runtime does not tell this static scan which construction path the application will take.

If every consumer supplies its own transport, you can exclude the unused default factory module. Other imports can still require parts of `chumicro_sockets`, so check the resulting file map before assuming the whole library is absent.

[Decision 0062](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0062-entrypoint-factory-skip.md) lets you say "skip the default builder; I'm bringing my own."  Add one line to your `app.py` (or `code.py`, whichever your project's entrypoint is):

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

The deployer skips the named factory module and stops following imports through it. Modules reached through another import remain. With MQTT, supplying a socket and clock plus this marker can exclude sockets, while timing, config, and msgpack remain reachable through other imports. Runtime dependency injection, package installation, and deployed files are separate decisions.

Inspect the intended file map from your prepared workbench before deployment. Replace `<project>` with your project's name:

```bash
chumicro-workspace deploy <project> --import-graph --dry-run
```

This prints the prospective payload without writing to the board. In a template workbench, use `python3 run.py` in place of `chumicro-workspace`.

## Family form and exact form

Use a family name to match every discovered factory with that stem:

```python
# app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

Or name one existing module exactly:

```python
__chumicro_skip_factories__ = ("chumicro_sockets.sockets_factory",)
```

Both examples select ChuMicro's shared transport factory. A tuple can combine family names and exact module names when several factory modules exist.

## Two failure modes that surface loudly, not silently

**Typo.**  An entry that matches zero discovered factory modules fails the deploy:

```
ValueError: __chumicro_skip_factories__ entries did not match any discovered
factory module: ['socet_factory'].  Discovered families: ['sockets_factory'].
```

A silent skip that shipped the unwanted library would be a worse outcome than refusing to deploy.

**Misuse at runtime.** If you skip the factory and call `MQTTClient.from_config(...)` without supplying `socket=` or `transport_factory=`, its default-factory import fails:

```
RuntimeError: chumicro_sockets.sockets_factory not available
(excluded via __chumicro_skip_factories__ or not on the board);
pass transport_factory= or socket= explicitly.
```

Passing either explicit MQTT transport argument bypasses that default import. Other networking libraries have their own transport parameters; check the library's constructor or `from_config` documentation. The same error can indicate an incomplete manual installation.

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
__chumicro_skip_factories__ entry 'chumicro_sockets.sockets_factory'
matches ['chumicro_sockets.sockets_factory'] but none of those
libraries are imported; skip entry has no effect.
```

The `sockets_factory` family entry now resolves to the single shared `chumicro_sockets.sockets_factory` module, so it counts as live whenever any networking library's default wiring reaches that module, and goes dead only when nothing in the deploy does.

## When this matters (and when it doesn't)

The marker is interpreted by `ImportGraphSource`, which the workspace's `--import-graph` route uses. It does not remove files already installed on the laptop or instruct `circup` and `mip` to change their installation. See [Installing ChuMicro libraries](../install.md) for those routes.

Use it when:

1. Your project's import graph reaches a `<stem>_factory.py` module, including a shared factory imported by another library.
2. You supply your own version of whatever the factory produces through the constructor (`transport_factory=` / `socket=` / `listener=` on the libraries that take a transport).
3. You deploy via `chumicro-workspace deploy --import-graph`.

Confirm the effect in the dry-run map. Unmatched names fail, direct imports override a skip, and other imports can keep a dependency reachable.

## Compatibility with on-device library curation

`chumicro-workspace library add` acquires source from a published channel snapshot into the laptop's `libraries/` folder. It reads each library's `pyproject.toml` to resolve ChuMicro dependencies. The deploy walker then reads imports from those local files. A factory skip changes that deployment scan; it does not change package metadata or the acquired source tree.

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
