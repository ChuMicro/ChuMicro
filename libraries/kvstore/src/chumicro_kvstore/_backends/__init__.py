"""Backend implementations for ``chumicro_kvstore``.

Backends are imported lazily by ``core._resolve_backend`` so that
constructing a ``KVStore(backend="memory")`` on a non-CP/MP host
doesn't try to import ``microcontroller`` or ``esp32``.
"""
