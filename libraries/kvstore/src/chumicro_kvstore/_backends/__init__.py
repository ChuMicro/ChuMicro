"""Backend implementations for ``chumicro_kvstore``.

Backends are imported lazily by ``core._resolve_backend`` so that
constructing a ``KVStore(backend="memory")`` on a non-CP/MP host
doesn't try to import ``microcontroller`` or ``esp32``.

Names under this package start with a single underscore at the
``_backends`` level (per workspace convention for non-public
sub-trees); individual backend modules sit at the next level
(``cp_nvm``, ``mp_nvs``, ``mp_littlefs``, ``memory``).
"""
