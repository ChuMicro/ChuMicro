"""Package PEP 562 lazy loading (chumicro_websockets.__init__).

Runs on every runtime.  Confirms the module ``__getattr__`` resolves
the client and server halves on first attribute access and rejects
unknown names, so ``from chumicro_websockets import WebSocketClient``
keeps working without eagerly importing ``server`` (and vice versa).
"""

import chumicro_websockets
from chumicro_test_harness.assertions import raises


class TestLazyPackageAttributes:
    def test_client_resolves_via_package_attribute(self):
        from chumicro_websockets.client import WebSocketClient

        assert chumicro_websockets.WebSocketClient is WebSocketClient

    def test_server_symbols_resolve_via_package_attribute(self):
        from chumicro_websockets.server import Connection, WebSocketServer

        assert chumicro_websockets.WebSocketServer is WebSocketServer
        assert chumicro_websockets.Connection is Connection

    def test_when_oversized_stays_eager(self):
        from chumicro_websockets._session import WhenOversized

        assert chumicro_websockets.WhenOversized is WhenOversized

    def test_unknown_attribute_raises(self):
        missing_name = "Nonexistent"
        with raises(AttributeError, match="Nonexistent"):
            getattr(chumicro_websockets, missing_name)
