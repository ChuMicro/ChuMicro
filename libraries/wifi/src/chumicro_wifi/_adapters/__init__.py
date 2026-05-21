"""Per-runtime adapters for ``chumicro_wifi``.

Adapters are lazy-imported by ``WifiService._select_adapter``.
A board only loads the substrate it targets, so a CP board never
parses the MP adapter and vice versa.

Single-underscore convention for the package marks it as not part
of the public API contract.  Rewrites inside an adapter don't bump
the major version.
"""
