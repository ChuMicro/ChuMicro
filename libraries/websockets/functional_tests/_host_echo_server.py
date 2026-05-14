"""Host-side WebSocket echo server for chumicro-websockets functional tests.

Spawned as a subprocess by ``conftest.py`` (one process per pytest
session); echoes every text + binary message it receives back to the
sender prefixed with ``echo: ``.  Uses the `websockets` PyPI package
— a battle-tested third-party server — so the device-side
:class:`chumicro_websockets.WebSocketClient` is exercised against an
implementation that's never going to share bugs with us.

Invoked with two args: ``<bind_host> <bind_port>``.  Prints
``READY <bind_host>:<bind_port>`` to stdout once listening so the
parent process can wait for liveness before signaling the device.
"""

import asyncio
import sys


async def _echo_handler(websocket):
    async for message in websocket:
        if isinstance(message, str):
            await websocket.send(f"echo: {message}")
        else:
            await websocket.send(b"echo:" + message)


async def _serve(bind_host: str, bind_port: int) -> None:
    import websockets

    async with websockets.serve(_echo_handler, bind_host, bind_port):
        sys.stdout.write(f"READY {bind_host}:{bind_port}\n")
        sys.stdout.flush()
        await asyncio.Future()  # run forever — parent kills via SIGTERM


def main() -> int:
    bind_host = sys.argv[1]
    bind_port = int(sys.argv[2])
    try:
        asyncio.run(_serve(bind_host, bind_port))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
