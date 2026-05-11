# chumicro-msgpack

**Cross-runtime [MessagePack](https://msgpack.org) serialization for CircuitPython, MicroPython, and CPython.**

Encodes Python objects to compact binary bytes and decodes them back.  On CircuitPython boards with the native `msgpack` C module, all functions delegate to the built-in — the pure-Python encoder is never loaded.

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

- [User Guide](guide.md) — getting started, usage patterns, size comparison
- [API Reference](api.md) — full API documentation

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) · \
[PyPI](https://pypi.org/project/chumicro-msgpack/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
