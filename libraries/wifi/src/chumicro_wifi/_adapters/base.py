"""``WifiAdapter``: the base class every per-runtime wifi adapter extends."""


class WifiAdapter:
    """Duck-typed adapter contract for :class:`WifiService`.

    A concrete adapter implements ``configure(config)``, ``connect(config)
    -> bool``, ``is_linked() -> bool``, and ``ip() -> str | None``, and
    overrides the three class attributes below.
    """

    # Plain class, not a Protocol: MicroPython has no typing module to import.
    name = "base"

    # True = connect() blocks until linked (CP); False = non-blocking join, is_linked() reports later (MP).
    connect_blocks = True

    # CircuitPython radio handle for downstream socketpool routing; None on MP/CPython.
    radio = None
