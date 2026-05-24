"""Host-side driver paired with ``test_real_serve.py`` (Category 1).

Runs as a regular pytest test on CPython.  The
``device_bootstrap_runner`` fixture deploys + starts the sibling
``test_real_serve.py`` on the registered device; once the board prints
``SERVER_READY ip=<ip> port=<port>``, the test fires a stdlib HTTP
``GET /ping`` against that address and asserts on the response.

The host-only marker keeps ``chumicro_pytest_device`` from treating
this file as a device test — it stays in the regular CPython lane,
where pytest collects it normally and the fixture orchestrates the
device deploy.
"""

from __future__ import annotations

__chumicro_host_only__ = True


def test_real_serve_host_driver_round_trip(
    device_bootstrap_runner,
    http_client_against_board,
) -> None:
    """Round-trip a GET against the device-hosted HttpServer."""
    hit = http_client_against_board(device_bootstrap_runner)
    response = hit("/ping", timeout_s=30.0)
    assert response.status == 200
    assert b'"ok"' in response.body
    assert b"true" in response.body
