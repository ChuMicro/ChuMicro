"""Test fakes for the chumicro-screens panel protocol."""

__chumicro_test_support__ = True


class FakePanel:
    """Panel fake whose flush performs a configurable number of transfers.

    Implements the flush protocol ``ScreenService`` drives: ``flush()``
    returns an iterator and each advance performs one bus transfer.
    Counters record how the service paced the work.

    Set ``fail_on_transfer`` to an index to raise ``OSError`` in place
    of that transfer, simulating a bus fault mid-frame.

    Args:
        transfers_per_flush: Bus transfers one frame needs; the frame
            completes after that many iterator advances.
    """

    def __init__(self, transfers_per_flush: int = 1) -> None:
        self.transfers_per_flush = transfers_per_flush
        self.fail_on_transfer: int | None = None
        self.flushes_started = 0
        self.flushes_completed = 0
        self.transfers_completed = 0

    def flush(self) -> object:
        """Return the frame's transfer iterator and count the start."""
        self.flushes_started += 1
        return self._run_flush()

    def _run_flush(self) -> object:
        for transfer_index in range(self.transfers_per_flush):
            if transfer_index > 0:
                yield
            if transfer_index == self.fail_on_transfer:
                raise OSError("injected bus fault")
            self.transfers_completed += 1
        self.flushes_completed += 1
