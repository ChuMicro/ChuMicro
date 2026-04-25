"""Per-runtime adapters for ``chumicro_wifi``.

Adapters are lazy-imported by ``WifiService`` (Tier B per the
2026-04-25 lazy-loading research) so a board only loads the one
substrate it actually targets — CP NVM-class boards never parse the
MP NVS adapter etc.

Single-underscore convention for the package marks it as not part
of the public API contract; rewrites inside an adapter don't bump
the major version.
"""
