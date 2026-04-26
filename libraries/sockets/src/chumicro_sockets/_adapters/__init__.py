"""Per-runtime adapter modules.

Lazy-imported by :mod:`chumicro_sockets`'s factories — each adapter
brings in runtime-specific stdlib modules (``socketpool``, ``socket``,
``ssl``) that aren't available everywhere.  Importing the wrong
adapter module on a runtime that lacks its dependencies fails
loudly; the factory routes around that by inspecting
``sys.implementation.name`` first.
"""
