# chumicro-ntp

Runner-shaped SNTP client over an injected UDP socket — pure-Python, cross-runtime.

## Quick example

```python
from chumicro_ntp import NTPClient
from chumicro_ntp.sockets_factory import chumicro_sockets_factory

sock = chumicro_sockets_factory(radio=wifi.adapter.radio)
client = NTPClient(socket=sock, server="pool.ntp.org")
request = client.query()
while not request.done:
    if client.check(now_ms()):
        client.handle(now_ms())
print("unix seconds:", request.unix_seconds)
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
