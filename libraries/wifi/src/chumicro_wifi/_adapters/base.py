"""``WifiAdapter``: the base class every per-runtime wifi adapter extends."""


class WifiAdapter:
    """Duck-typed adapter contract for :class:`WifiService`.

    A concrete adapter implements ``configure(config)``,
    ``connect(config, timeout_ms=None) -> bool``, ``is_linked() -> bool``,
    and ``ip() -> str | None``, and overrides the three class attributes
    below.  ``timeout_ms`` is the allowance for that connect attempt in
    ms; ``None`` means ``config.connect_timeout_ms``.  A blocking adapter
    bounds its in-call wait with it; a non-blocking adapter may ignore it
    because the service polls ``is_linked()`` over the same window.
    """

    # Plain class, not a Protocol: MicroPython has no typing module to import.
    name = "base"

    # True = connect() blocks until linked (CP); False = non-blocking join, is_linked() reports later (MP).
    connect_blocks = True

    # CircuitPython radio handle for downstream socketpool routing; None on MP/CPython.
    radio = None
