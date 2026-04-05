"""Cross-runtime compatibility polyfills for CPython, MicroPython, and CircuitPython.

Import polyfills from their submodules directly to avoid loading
modules you do not need on constrained boards::

    from chumicro_compat.functools import partial

Available modules
-----------------
- ``chumicro_compat.functools`` — ``partial``
"""

