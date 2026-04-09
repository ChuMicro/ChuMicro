"""Freeze keyword arguments and override them at call time.

Demonstrates how ``partial`` freezes keyword arguments and how the
caller can override them when calling the resulting object.

Example output::

    connecting to api.example.com:443 (timeout=5s)
    connecting to api.example.com:443 (timeout=10s)

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_compat.functools import partial


def connect(host: str, port: int = 80, timeout: int = 5) -> None:
    """Simulate opening a connection."""
    print(f"connecting to {host}:{port} (timeout={timeout}s)")


# Freeze the host and port.  timeout keeps its default but can be
# overridden by the caller.
connect_api = partial(connect, "api.example.com", port=443)

connect_api()             # uses default timeout=5
connect_api(timeout=10)   # overrides timeout to 10
