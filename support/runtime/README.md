# chumicro-runtime

Small runtime detection helpers shared by Chumicro packages.

This package is intentionally narrow. It exists to keep runtime checks in one place so later libraries do not duplicate CPython, MicroPython, and CircuitPython detection logic.

## API

| Symbol | Description |
|---|---|
| `runtime_name()` | Return a stable runtime name: `"cpython"`, `"micropython"`, `"circuitpython"`, or `"unknown"` |
| `is_cpython()` | Return whether the active runtime is CPython |
| `is_micropython()` | Return whether the active runtime is MicroPython |
| `is_circuitpython()` | Return whether the active runtime is CircuitPython |
