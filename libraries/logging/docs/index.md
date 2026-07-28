# chumicro-logging

**Buffer log lines off the hot path so logging never stalls your control loop.**

Level constants (`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`), named loggers, and attached handlers give you the shape you already know from the standard library's `logging`.  `BufferedHandler` adds the part a device needs: it stores raw records on the hot path and defers both the formatting and the I/O to drain time on your runner tick.  The library stands on its own and depends on nothing else, so you build a `Logger` in your own code and hand it to your own modules.

**Status: parked.**  chumicro-logging works as documented and stays published, but it is not under active development and no other ChuMicro library integrates with it.  Adopt it as a standalone buffered logger, or skip it.

## Quick example

```python
from chumicro_logging import INFO, Logger, StreamHandler

logger = Logger("boot", level=INFO, handlers=[StreamHandler()])
logger.info("hello")        # -> stdout: INFO:boot:hello
logger.debug("invisible")   # below threshold; dropped silently
```

## Documentation

- [User Guide](guide.md): getting started, the runner pattern for `BufferedHandler`, memory and platform notes
- [API Reference](api.md): `Logger`, `StreamHandler`, `BufferedHandler`, and the level constants
- [Testing Helpers](testing.md): using `RecordingHandler` and `FailingHandler` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/logging) · \
[PyPI](https://pypi.org/project/chumicro-logging/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
