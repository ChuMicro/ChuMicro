# chumicro-config

Standardized runtime-config helpers for ChuMicro libraries — section loader + on-device runtime-config reader.

## Quick example

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) · \
[PyPI](https://pypi.org/project/chumicro-config/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
