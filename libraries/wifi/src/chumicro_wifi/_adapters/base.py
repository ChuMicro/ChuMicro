class WifiAdapter:
    # Plain class, not a Protocol: MicroPython has no typing module to import.
    name = "base"

    # True = connect() blocks until linked (CP); False = non-blocking join, is_linked() reports later (MP).
    connect_blocks = True

    # CircuitPython radio handle for downstream socketpool routing; None on MP/CPython.
    radio = None

    def configure(self, config):
        raise NotImplementedError

    def connect(self, config):
        raise NotImplementedError

    def is_linked(self):
        raise NotImplementedError

    def ip(self):
        raise NotImplementedError
