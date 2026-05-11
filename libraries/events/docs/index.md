# chumicro-events

**Tiny in-process pub/sub event bus.**

Bounded queue with drop-oldest overflow, batched dispatch on each runner tick, zero dependencies.

## Quick example

```python
from chumicro_events import EventBus

bus = EventBus()
bus.subscribe("wifi.state", lambda topic, payload: print(topic, payload))
bus.publish("wifi.state", "connected")
bus.handle(now_ms=0)
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — fakes for downstream test suites

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/events) · \
[PyPI](https://pypi.org/project/chumicro-events/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
