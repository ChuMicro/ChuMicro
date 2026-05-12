"""Per-runtime adapters for ``chumicro_wifi``.

Adapters are lazy-imported by ``WifiService._select_adapter`` so a
board only loads the one substrate it actually targets — a CP board
never parses the MP adapter and vice versa.

Single-underscore convention for the package marks it as not part
of the public API contract; rewrites inside an adapter don't bump
the major version.
"""
