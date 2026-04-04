# chumicro-compat

Cross-runtime compatibility polyfills for CPython, MicroPython, and CircuitPython.

Provides lightweight reimplementations of CPython standard-library features that are missing or incomplete on microcontroller runtimes.  Each module works identically across all three runtimes.

## Modules

### `chumicro_compat.abc` — Abstract Base Classes

Lightweight `ABC` and `abstractmethod` without metaclasses.  Uses `__init_subclass__` (MicroPython ≥1.19.1, CircuitPython ≥8.x) to collect abstract methods at class-definition time, and `__new__` to enforce them at instantiation.

```python
from chumicro_compat.abc import ABC, abstractmethod


class Sensor(ABC):

    @abstractmethod
    def read(self):
        """Subclasses must implement this."""


class TemperatureSensor(Sensor):

    def read(self):
        return 22.5


TemperatureSensor()  # OK
Sensor()             # TypeError: Can't instantiate abstract class Sensor ...
```

Supports multi-level inheritance, diamond patterns, and `__init__` with arguments.

## Installation

```bash
# CPython (pip)
pip install chumicro-compat

# CircuitPython (circup) — coming soon
# circup install chumicro-compat

# MicroPython (mip) — coming soon
# import mip; mip.install("chumicro-compat")
```

## Platform support

All modules use only basic Python features.  Works identically on CPython, MicroPython (≥1.19.1), and CircuitPython (≥8.x).  Requires `__init_subclass__` support.

## Docs

- [User guide](docs/guide.md)
- [API reference](docs/api.md)
