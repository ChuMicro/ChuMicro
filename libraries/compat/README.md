# chumicro-compat

Cross-runtime compatibility polyfills for CPython, MicroPython, and CircuitPython.

Provides lightweight reimplementations of CPython standard-library features that are missing or incomplete on microcontroller runtimes.  Each module works identically across all three runtimes.

## Status

No modules shipped yet.  Planned additions include `functools` polyfills.

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

All modules will use only basic Python features compatible with CPython, MicroPython, and CircuitPython.

## Docs

- [User guide](docs/guide.md)
- [API reference](docs/api.md)
