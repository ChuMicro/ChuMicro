"""Host-side HTTP client driven by board-printed sync markers.

For Category 1 server-side tests the board runs the server and prints
``SERVER_READY ip=<ip> port=<port>`` once it is accepting; the host
fixture opens a stdlib HTTP connection to that address and fires the
request.  This module exposes the client side of that handshake.

Surface:

* :func:`bind_to(runner)`: plain function, returns a ``hit(path, ...)``
  callable bound to the supplied :class:`DeviceBootstrapRunner`.  Use
  this when wiring runner + fixture directly from a test or helper
  outside the pytest fixture graph.
* :func:`http_client_against_board`: pytest fixture that returns
  :func:`bind_to` itself, so tests can write
  ``hit = http_client_against_board(runner)`` and stay inside the
  fixture-graph.

The runner is *not* created here.  A consumer fixture (out of scope
for this module) owns runner creation from the session's transport
cache + a board-side test file; this module only owns the
HTTP-client side of the handshake.
"""

from __future__ import annotations

import http.client
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from chumicro_workspace.device_orchestration import (
    build_device_bootstrap,
    resolve_library_source_dirs,
)
from chumicro_workspace.device_runner import DeviceBootstrapRunner
from chumicro_workspace.markers import Marker

from ..collection import (
    _load_fallback_device,
    _resolve_library_dir,
    _session_effective_deploy_mode,
)
from ..session import (
    _encode_runtime_config_extra_files,
    _harness_source_dir,
    _libraries_root,
    _session_cache,
    _session_targets,
    _target_is_device_unit,
)

# How long the fixture's teardown waits for the board bootstrap to finish
# after the host test body returns. Board-side scripts here run a single
# accept-loop iteration; 60 s is well over the natural shape and below
# pytest's default per-test ceiling.
_BOOTSTRAP_COMPLETION_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class HttpResponseSnapshot:
    """The handful of fields a Category 1 test typically asserts on.

    Returned by :func:`bind_to`'s ``hit`` callable in place of the raw
    :class:`http.client.HTTPResponse` so the underlying socket can be
    closed before the call returns, with no caller bookkeeping to remember.

    ``headers`` keys are lowercased so a test can match
    ``response.headers["content-type"]`` without worrying about how
    the server cased the header on the wire.
    """

    status: int
    reason: str
    headers: dict[str, str]
    body: bytes


def bind_to(runner: DeviceBootstrapRunner) -> Callable[..., HttpResponseSnapshot]:
    """Build a ``hit(path, ...)`` callable that drives HTTP against the runner's board.

    The returned callable:

    1. On its first invocation, calls
       :meth:`DeviceBootstrapRunner.wait_for` for the ``SERVER_READY``
       marker (with the per-call ``timeout_s``) and caches the
       resolved ``ip:port``.  Subsequent invocations reuse the
       cached address, because the board prints ``SERVER_READY`` once at
       startup, so re-waiting on every call would block forever
       after the first request consumed the marker.
    2. Opens :class:`http.client.HTTPConnection` to the cached
       ``ip:port``, with ``timeout_s`` as the socket timeout.
    3. Fires the request (``GET`` by default; ``method`` + ``body``
       overridable) and reads the response.
    4. Closes the underlying connection before returning a
       :class:`HttpResponseSnapshot`.

    Args:
        runner: The runner whose marker queue the ``hit`` callable
            should block on for the initial ``SERVER_READY`` resolve.

    Returns:
        A function ``hit(path, *, timeout_s=10.0, method="GET",
        body=None) -> HttpResponseSnapshot``.
    """
    cached_marker: Marker | None = None

    def hit(
        path: str,
        *,
        timeout_s: float = 10.0,
        method: str = "GET",
        body: bytes | None = None,
    ) -> HttpResponseSnapshot:
        nonlocal cached_marker
        if cached_marker is None:
            cached_marker = runner.wait_for(
                "SERVER_READY", timeout_s=timeout_s,
            )
        ip_address = cached_marker.values["ip"]
        port_number = int(cached_marker.values["port"])
        connection = http.client.HTTPConnection(
            ip_address, port_number, timeout=timeout_s,
        )
        try:
            connection.request(method, path, body=body)
            response = connection.getresponse()
            response_body = response.read()
            return HttpResponseSnapshot(
                status=response.status,
                reason=response.reason,
                headers={
                    name.lower(): value for name, value in response.getheaders()
                },
                body=response_body,
            )
        finally:
            connection.close()

    return hit


@pytest.fixture
def http_client_against_board() -> Callable[
    [DeviceBootstrapRunner], Callable[..., HttpResponseSnapshot],
]:
    """Pytest-fixture wrapper around :func:`bind_to`.

    Tests use it as::

        def test_real_serve(device_bootstrap_runner, http_client_against_board):
            hit = http_client_against_board(device_bootstrap_runner)
            response = hit("/")
            assert response.status == 200
    """
    return bind_to


def _resolve_board_file(request: pytest.FixtureRequest) -> Path:
    """Return the path of the board-side test file paired with the host test.

    Resolution order:

    1. An explicit ``@pytest.mark.device_bootstrap("<board_file>")``
       marker on the test function.  The named file is resolved
       relative to the host test file's directory.
    2. The sibling-name convention: a host file named
       ``test_real_<scenario>_host.py`` pairs with
       ``test_real_<scenario>.py`` in the same directory.

    Calls ``pytest.fail`` with a clear message when neither rule
    produces a real file.  Better an immediate stop than a confusing
    downstream stage failure.
    """
    host_file = Path(str(request.fspath))
    marker = request.node.get_closest_marker("device_bootstrap")
    if marker is not None and marker.args:
        board_file_name = str(marker.args[0])
    else:
        if not host_file.name.endswith("_host.py"):
            pytest.fail(
                f"device_bootstrap_runner requires either a host file "
                f"named `*_host.py` (sibling-name rule strips `_host.py` "
                f"and appends `.py`) or "
                f"`@pytest.mark.device_bootstrap('<board_file>')` on the "
                f"test; got {host_file.name!r}.",
            )
        board_file_name = host_file.name[: -len("_host.py")] + ".py"
    board_file = host_file.parent / board_file_name
    if not board_file.is_file():
        pytest.fail(
            f"device_bootstrap_runner resolved board file {board_file!r} "
            f"does not exist (paired with host file {host_file!r}).",
        )
    return board_file


@pytest.fixture
def device_bootstrap_runner(
    request: pytest.FixtureRequest,
) -> Iterator[DeviceBootstrapRunner]:
    """Stage + deploy the paired board file and yield a started runner.

    Setup:

    1. Find the board file via :func:`_resolve_board_file`.
    2. Pick the first registered target device (or fall back to the
       registry default).  Multi-device parametrization is future
       work; today's shape mirrors the single-device flow most
       Category 1 tests will use.
    3. Get the cached transport for that device + the session's
       effective deploy mode.
    4. Stage the board file's library sources + the board file
       itself via ``transport.stage``.
    5. Build the bootstrap and spawn the runner.

    Teardown:

    1. Join the bg thread with a generous timeout
       (:data:`_BOOTSTRAP_COMPLETION_TIMEOUT_S`).
    2. Call :meth:`DeviceBootstrapRunner.shutdown` for idempotent
       cleanup.

    The captured stdout is still available via
    :meth:`DeviceBootstrapRunner.wait_for_completion` if the host
    test wants to inspect board-side prints (e.g. confirm
    ``SERVER_REQUEST_OBSERVED`` landed); the fixture itself doesn't
    impose a board-side PASS/FAIL check because the host-side
    assertions are the load-bearing ones for this shape.
    """
    board_file = _resolve_board_file(request)

    targets = _session_targets(request.session)
    device_entry = targets[0] if targets else _load_fallback_device(request.session)
    deploy_mode = _session_effective_deploy_mode(request.session, device_entry)
    cache = _session_cache(request.session)
    transport = cache.get_transport(device_entry, deploy_mode)

    library_dir = _resolve_library_dir(board_file)
    source_dirs = resolve_library_source_dirs(
        library_dir,
        libraries_root=_libraries_root(request.session),
        test_files=[board_file],
    )
    transport.stage(
        source_dirs,
        [board_file],
        _harness_source_dir(request.session),
        extra_files=_encode_runtime_config_extra_files(request.session.config),
        include_test_support=_target_is_device_unit(request.session.config),
    )

    bootstrap = build_device_bootstrap(device_entry, transport, board_file, None)
    runner = DeviceBootstrapRunner(transport, bootstrap)
    runner.start()
    try:
        yield runner
    finally:
        try:
            runner.wait_for_completion(
                timeout_s=_BOOTSTRAP_COMPLETION_TIMEOUT_S,
            )
        except TimeoutError:
            # Stash the timeout but don't mask a host-side failure
            # that may have already been raised in the test body.
            pass
        finally:
            runner.shutdown()
