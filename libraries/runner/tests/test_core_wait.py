"""``Runner.wait``: poll-set registration, interest sync, and io_error
dispatch to duck-typed I/O services.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""


import select

from _core_helpers import _IOService, _IOServiceWithErrorHook
from chumicro_runner import Runner
from chumicro_runner.testing import FakePoller
from chumicro_timing.testing import FakeTicks

# -- Helpers --


class _AdapterWrapper:
    """Stand-in for a chumicro_sockets adapter wrapper: the runtime's
    pollable lives on ``.sock``, the wrapper itself is not registrable."""

    def __init__(self, sock: object) -> None:
        self.sock = sock


class _ClosableSocket:
    """Socket-shaped stand-in that answers -1 from ``fileno()`` once
    closed, the way a CPython socket does."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def fileno(self) -> int:
        return self._descriptor

    def close(self) -> None:
        self._descriptor = -1


class _DescriptorKeyedPoller(FakePoller):
    """Stand-in for CPython's ``select.poll``, whose set is keyed by file
    descriptor rather than by object: every call reads ``fileno()`` off
    the object it is handed, and a closed socket answers -1, which the
    poller rejects.  ``FakePoller`` keys by ``id(obj)`` and so cannot
    show a descriptor being stranded."""

    def __init__(self) -> None:
        super().__init__()
        #: Descriptor -> eventmask, the poll set as the OS holds it.
        self.descriptors: dict = {}

    def register(self, obj: object, eventmask: int) -> None:
        super().register(obj, eventmask)
        self.descriptors[self._descriptor_of(obj)] = eventmask

    def modify(self, obj: object, eventmask: int) -> None:
        super().modify(obj, eventmask)
        self.descriptors[self._descriptor_of(obj)] = eventmask

    def unregister(self, obj: object) -> None:
        super().unregister(obj)
        self.descriptors.pop(self._descriptor_of(obj))

    @staticmethod
    def _descriptor_of(obj: object) -> int:
        descriptor = obj if isinstance(obj, int) else obj.fileno()
        if descriptor < 0:
            raise ValueError(
                "file descriptor cannot be a negative integer (-1)",
            )
        return descriptor


# -- Runner.wait --


def test_wait_is_noop_when_no_entries() -> None:
    """A runner with no tasks returns immediately and never touches the poller."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)

    runner.wait(0)

    assert poller.ipoll_calls == []
    assert poller.register_calls == []


def test_wait_default_poller_stays_unbuilt_when_no_socket() -> None:
    """A runner with only timer-based entries never lazy-builds the poller."""
    runner = Runner(ticks=FakeTicks())  # poller=None => lazy
    runner.add_periodic(lambda now_ms: None, period_ms=100)

    runner.wait(0)

    assert runner._poller is None


def test_wait_registers_service_socket() -> None:
    """A service exposing io_socket + io_interest==IO_READ registers with POLLIN."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)

    runner.wait(0)

    assert (sock, select.POLLIN) in poller.register_calls
    assert poller.ipoll_calls == [100]


def test_wait_unwraps_adapter_wrapper_before_registering() -> None:
    """An ``io_socket`` returning an adapter wrapper registers the inner
    pollable — the unwrap lives in the runner, so no producer has to
    remember the ``.sock`` convention (a missed producer-side unwrap
    used to hand the wrapper to ``poll.register``, an OSError on MP)."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    inner = object()
    service = _IOService(sock=_AdapterWrapper(inner), wants_read=True)
    runner.add(service, period_ms=100)

    runner.wait(0)

    assert (inner, select.POLLIN) in poller.register_calls
    assert all(
        not isinstance(entry[0], _AdapterWrapper)
        for entry in poller.register_calls
    )


def test_wait_dispatches_io_error_through_adapter_wrapper() -> None:
    """POLLERR reported for the inner pollable still matches a service
    whose ``io_socket`` returns the wrapper — the io_error reverse
    lookup unwraps the same way registration does."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    inner = object()
    service = _IOServiceWithErrorHook(
        sock=_AdapterWrapper(inner), wants_read=True,
    )
    runner.add(service, period_ms=100)
    runner.wait(0)  # First wait registers the inner pollable.

    poller.set_ready(inner, select.POLLERR)
    runner.wait(0)

    assert service.io_error_calls == [(0, select.POLLERR)]


def test_wait_ors_masks_when_two_services_share_one_socket() -> None:
    """A reader and a writer on the same socket register the OR of their
    interests, so neither service's wake direction is lost."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    reader = _IOService(sock=sock, wants_read=True)
    writer = _IOService(sock=sock, wants_write=True)
    runner.add(reader, period_ms=100)
    runner.add(writer, period_ms=100)

    runner.wait(0)

    combined = select.POLLIN | select.POLLOUT
    registered = poller.register_calls + poller.modify_calls
    assert (sock, combined) in registered
    # The socket is registered once (id-keyed), not fought over.
    assert sum(1 for entry in poller.register_calls if entry[0] is sock) == 1


def test_wait_combines_read_and_write_into_one_eventmask() -> None:
    """A service wanting both read and write registers with POLLIN | POLLOUT."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True, wants_write=True)
    runner.add(service, period_ms=100)

    runner.wait(0)

    expected = select.POLLIN | select.POLLOUT
    assert (sock, expected) in poller.register_calls


def test_wait_stable_interest_touches_poller_once_across_sweeps() -> None:
    """Repeated waits with unchanged io_* interest register the socket
    once and issue no further register or modify calls — the poll-set
    sync reuses its per-socket slot each sweep instead of rebuilding a
    scratch container and re-diffing from scratch."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)

    for _ in range(5):
        runner.wait(0)

    assert len(poller.register_calls) == 1
    assert poller.modify_calls == []
    assert len(runner._registered_interest) == 1


def test_wait_modifies_when_interest_changes() -> None:
    """Going from read-only to read+write fires modify, not a second register."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)
    poller.register_calls.clear()

    service.wants_write = True
    runner.wait(0)

    expected = select.POLLIN | select.POLLOUT
    assert (sock, expected) in poller.modify_calls
    assert poller.register_calls == []


def test_wait_idempotent_when_interest_unchanged() -> None:
    """A second wait() with the same io_* state touches the poller zero times."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)
    poller.register_calls.clear()
    poller.modify_calls.clear()
    poller.unregister_calls.clear()

    runner.wait(0)

    assert poller.register_calls == []
    assert poller.modify_calls == []
    assert poller.unregister_calls == []


def test_wait_unregisters_when_service_releases_socket() -> None:
    """A service that goes io_socket=None drops out of the poll set."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    service.io_socket = None
    runner.wait(0)

    assert sock in poller.unregister_calls


def test_wait_drops_only_the_released_socket_keeping_the_other() -> None:
    """One service releases its socket while another keeps its own: only the
    released socket unregisters; the still-wanted one stays in the poll set."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    kept_sock = object()
    dropped_sock = object()
    kept = _IOService(sock=kept_sock, wants_read=True)
    dropped = _IOService(sock=dropped_sock, wants_read=True)
    runner.add(kept, period_ms=100)
    runner.add(dropped, period_ms=100)
    runner.wait(0)  # registers both

    dropped.io_socket = None  # only this one releases
    poller.unregister_calls.clear()
    runner.wait(0)

    assert dropped_sock in poller.unregister_calls
    assert kept_sock not in poller.unregister_calls
    assert id(kept_sock) in runner._registered_interest
    assert id(dropped_sock) not in runner._registered_interest


def test_wait_swallows_valueerror_unregistering_closed_socket() -> None:
    """CPython select.poll raises ValueError unregistering a closed socket
    (its fileno() is -1).  A service that closed its socket is exactly this
    path, so wait() treats it as benign poll-set divergence, not an error."""
    class _ClosedSocketPoller(FakePoller):
        def unregister(self, obj: object) -> None:
            super().unregister(obj)
            raise ValueError("file descriptor cannot be a negative integer (-1)")

    poller = _ClosedSocketPoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)  # registers the socket

    service.io_socket = None  # the service closed and released its socket
    runner.wait(0)  # must not propagate the unregister ValueError

    assert sock in poller.unregister_calls


def test_wait_drops_a_closed_socket_from_a_descriptor_keyed_poll_set() -> None:
    """A service that closes its socket and then leaves the runner — the
    shape of a finished fetch generator — takes its descriptor out of the
    poll set.  A closed socket can no longer name its own descriptor, so
    the object-keyed unregister is refused; stopping there leaves the
    descriptor registered, poll() answers POLLNVAL for it without ever
    blocking, and every later wait() busy-spins instead of idling."""
    poller = _DescriptorKeyedPoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    kept = _IOService(sock=_ClosableSocket(3), wants_read=True)
    finished = _IOService(sock=_ClosableSocket(5), wants_read=True)
    runner.add(kept, period_ms=100)
    finished_handle = runner.add(finished, period_ms=100)
    runner.wait(0)
    assert sorted(poller.descriptors) == [3, 5]

    finished.io_socket.close()
    finished_handle.remove()
    runner.wait(0)

    assert sorted(poller.descriptors) == [3]


def test_wait_leaves_a_reused_descriptor_registered_for_its_new_socket() -> None:
    """The OS hands a freed descriptor straight to the next socket the
    process opens, so a closed socket's descriptor can already belong to a
    live one by the time the drop sweep runs.  The sweep leaves that
    registration alone: taking it out would blind the new socket, which
    would then never wake."""
    poller = _DescriptorKeyedPoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    finished = _IOService(sock=_ClosableSocket(5), wants_read=True)
    finished_handle = runner.add(finished, period_ms=100)
    runner.wait(0)

    # One sweep sees both: the old socket closed and left, a new one took
    # its descriptor and registered for the opposite direction.
    finished.io_socket.close()
    finished_handle.remove()
    accepted = _IOService(sock=_ClosableSocket(5), wants_write=True)
    runner.add(accepted, period_ms=100)
    runner.wait(0)

    assert poller.descriptors == {5: select.POLLOUT}


def test_wait_survives_a_descriptor_the_poller_has_already_forgotten() -> None:
    """The descriptor retry is best-effort.  A poll set that diverged
    out-of-band refuses the descriptor too, and wait() treats that refusal
    the way it treats the refused object unregister — the runner's own
    bookkeeping is the source of truth — rather than letting it escape."""
    poller = _DescriptorKeyedPoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    service = _IOService(sock=_ClosableSocket(5), wants_read=True)
    handle = runner.add(service, period_ms=100)
    runner.wait(0)

    poller.descriptors.clear()  # the poll set diverged behind the runner's back
    service.io_socket.close()
    handle.remove()
    runner.wait(0)  # must not raise

    assert runner._registered_interest == {}


def test_wait_unregisters_when_service_drops_to_no_interest() -> None:
    """io_interest dropping to 0 unregisters even when io_socket is still set."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    service.wants_read = False
    runner.wait(0)

    assert sock in poller.unregister_calls


def test_wait_dispatches_io_error_on_pollerr() -> None:
    """POLLERR on a registered socket fires the service's ``io_error`` hook."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)  # First wait registers the socket.

    # Now script a POLLERR event for the next wait.
    poller.set_ready(sock, select.POLLERR)
    runner.wait(0)

    assert service.io_error_calls == [(0, select.POLLERR)]


def test_wait_dispatches_io_error_on_pollhup() -> None:
    """POLLHUP on a registered socket fires the service's ``io_error`` hook."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    poller.set_ready(sock, select.POLLHUP)
    runner.wait(50)

    assert service.io_error_calls == [(50, select.POLLHUP)]


def test_wait_combined_pollin_pollerr_still_fires_io_error() -> None:
    """A combined POLLIN | POLLERR mask still triggers io_error.

    POLLIN alone is a wake signal only -- runner doesn't dispatch
    anything for it.  POLLERR on the SAME event has to surface so
    the service learns the socket faulted."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    combined = select.POLLIN | select.POLLERR
    poller.set_ready(sock, combined)
    runner.wait(0)

    assert service.io_error_calls == [(0, combined)]


def test_wait_pollin_only_does_not_fire_io_error() -> None:
    """Plain POLLIN (wake signal) doesn't fire io_error -- only error masks do."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    poller.set_ready(sock, select.POLLIN)
    runner.wait(0)

    assert service.io_error_calls == []


def test_wait_pollerr_on_service_without_io_error_hook_is_silent() -> None:
    """A service that doesn't expose ``io_error`` is opted out -- runner
    doesn't crash, just skips it."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)  # no io_error.
    runner.add(service, period_ms=100)
    runner.wait(0)

    poller.set_ready(sock, select.POLLERR)
    runner.wait(0)  # Should not raise.

    # Sanity: the opted-out service didn't sprout an io_error attribute
    # along the way (would mean the runner stored something on it).
    assert not hasattr(service, "io_error")


def test_wait_timeout_uses_nearest_next_due_ms() -> None:
    """The wait timeout is the minimum across every entry's next_due_ms."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=500)
    runner.add_periodic(lambda now_ms: None, period_ms=80)

    runner.wait(0)

    assert poller.ipoll_calls == [80]


def test_wait_honors_next_deadline_hint() -> None:
    """A service exposing next_deadline(now_ms) shortens the timeout when its
    deadline is sooner than its next_due_ms."""

    class _ServiceWithDeadline(_IOService):
        def __init__(self, sock: object, deadline_ms: int) -> None:
            super().__init__(sock=sock, wants_read=True)
            self._deadline_ms = deadline_ms

        def next_deadline(self, now_ms: int) -> int:
            return now_ms + self._deadline_ms

    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _ServiceWithDeadline(sock, deadline_ms=25)
    runner.add(service, period_ms=500)

    runner.wait(0)

    assert poller.ipoll_calls == [25]


def test_wait_returns_immediately_when_deadline_already_passed() -> None:
    """A negative or zero timeout skips ipoll entirely."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()

    class _OverdueService(_IOService):
        def next_deadline(self, now_ms: int) -> int:
            return now_ms - 5  # already in the past

    service = _OverdueService(sock=sock, wants_read=True)
    runner.add(service)

    runner.wait(100)

    assert poller.ipoll_calls == []


def test_wait_drops_ipoll_iteration_result() -> None:
    """Whatever ipoll yields is discarded — check re-gates on the next tick."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    poller.set_ready(sock, select.POLLIN)

    runner.wait(0)

    assert service.handle_count == 0  # wait does not invoke handle()


def test_wait_handler_only_task_has_no_service_to_read() -> None:
    """A handler-only registration sets service=None on the handle so
    wait does not try to read io_* on a function."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    handle = runner.add(handler=lambda now_ms: None)

    assert handle.service is None
    runner.wait(0)  # must not raise

    assert poller.register_calls == []


def test_wait_handler_only_task_has_no_service() -> None:
    """A handler-only registration has no service to read io_* from."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    handle = runner.add(handler=lambda now_ms: None)

    assert handle.service is None
    runner.wait(0)

    assert poller.register_calls == []
