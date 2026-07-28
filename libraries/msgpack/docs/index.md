# chumicro-msgpack

**Cross-runtime [MessagePack](https://msgpack.org) serialization for CircuitPython, MicroPython, and CPython.**

Encodes Python objects to compact binary bytes and decodes them back.  On CircuitPython firmware that ships the native `msgpack` C module, every function delegates to that built-in and the pure-Python encoder never loads.

## Quick example

```python
from chumicro_msgpack import packb, unpackb

settings = {0: "MyNetwork", 1: "secret", 2: True}

data = packb(settings)       # compact binary bytes
print(len(data))             # much smaller than JSON

restored = unpackb(data)
print(restored)              # {0: 'MyNetwork', 1: 'secret', 2: True}
```

## Documentation

- [User Guide](guide.md): the stream and bytes APIs, when to reach for msgpack instead of `struct`, decoding corrupt or untrusted input, integer keys for compact storage, the supported types, and the size comparison against JSON
- [API Reference](api.md): `packb` and `unpackb` for bytes, `pack` and `unpack` for streams

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) · \
[PyPI](https://pypi.org/project/chumicro-msgpack/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
