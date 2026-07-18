"""Per-runtime adapter modules.

Lazy-imported by the :mod:`chumicro_sockets` factories, which pick the right
one from ``sys.implementation.name``. Each adapter imports runtime-specific
stdlib modules (``socketpool``, ``socket``, ``ssl``) that are not available on
every runtime, so importing the wrong one fails loudly.
"""
