"""Per-runtime wifi adapters, lazy-imported by ``WifiService``.

A board only loads the substrate it targets, so a CircuitPython board never
parses the MicroPython adapter and vice versa. Private package: the adapter
surface is not part of the public API.
"""
