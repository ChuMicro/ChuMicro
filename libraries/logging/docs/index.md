# chumicro-logging

**Leveled logging for ChuMicro libraries — non-blocking, zero dependencies.**

Familiar stdlib-logging shape (level integers, named loggers, attached handlers) plus a `BufferedHandler` that drains records off the hot tick path on each runner tick.

## Quick example

```python
from chumicro_logging import INFO, Logger, StreamHandler

logger = Logger("boot", level=INFO, handlers=[StreamHandler()])
logger.info("hello")
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — fakes for downstream test suites

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/logging) · \
[PyPI](https://pypi.org/project/chumicro-logging/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
