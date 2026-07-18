"""Backend implementations for ``chumicro_kvstore``.

``core._resolve_backend`` imports these lazily so constructing a
``KVStore(backend="memory")`` on a non-CP/MP host never imports
``microcontroller`` or ``esp32``.
"""
