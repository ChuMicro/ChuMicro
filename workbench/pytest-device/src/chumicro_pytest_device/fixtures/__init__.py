"""Host-side fixtures shared across networking-library functional tests.

Each submodule owns one endpoint type. Per-library `functional_tests/
conftest.py` files import the helpers they need and orchestrate their
own pytest_configure / pytest_sessionfinish hooks; the helpers
themselves never touch pytest state.

Submodules:

* `lan`: `detect_lan_ip()`, `find_free_port()`, `wait_until_listening()`.
* `mosquitto`: `start_mosquitto_broker()` (spawns a Mosquitto subprocess
  bound to a LAN interface for chumicro-mqtt's functional tests).
* `udp_echo`: `start_udp_echo_server()` (daemon-thread UDP echo for
  chumicro-sockets' transport smoke tests).
"""
