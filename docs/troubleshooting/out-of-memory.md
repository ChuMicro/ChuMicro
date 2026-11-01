# Running out of memory

`MemoryError` and `OSError: [Errno 12]` both mean the board ran out of memory. A microcontroller's free memory, its *heap*, is small: a Pi Pico W leaves about 150 KB for your program once its firmware has started. A program that runs comfortably on a laptop can run out of room there.

## `MemoryError` the first time your program imports a library partway through a run

Do the imports, and create your clients for wifi, MQTT, or HTTP, at the top of your program, before the main loop starts. Memory is still in one piece then.

```python
from chumicro_mqtt import MQTTClient    # import and build at startup...

mqtt = MQTTClient.from_config(config, radio=radio)

while True:                             # ...then run the loop
    ...
```

Importing a library on the board compiles its source right there. The compiler needs one large block of free memory while it works: importing `chumicro-mqtt` needs about 95 KB free at that moment on a Pi Pico W. Board memory never gets rearranged, so after a while of running, the free space sits scattered in small gaps between objects the program still holds. The total can look healthy while no single gap is big enough.

## `OSError: [Errno 12]` when an HTTPS or `wss://` connection starts

[TLS and HTTPS failures](tls-https-failures.md#oserror-errno-12-during-the-tls-handshake) covers the memory the encrypted handshake needs, and the fixes.

## `MemoryError` or `INSUFFICIENT_MEMORY` during a RAM-mode deploy

Deploy without `--force-deploy-mode ram`. A deploy switches to flash mode on its own whenever the network libraries would run a small board out of memory in RAM mode, and that flag overrides the switch. [Deploys and file persistence](deploys-and-file-persistence.md#the-deploy-prints-switching-to-flash-mode-after-you-asked-for-ram) explains the two modes.

## `ImportError` naming `deque` when importing a ChuMicro library

Move the project to a board ChuMicro supports, running a full CircuitPython or MicroPython build: the ESP32 family, RP2040 and RP2350 (Pi Pico W, Pico 2 W), or STM32. ChuMicro supports boards with at least 256 KB of RAM.

ChuMicro libraries use `collections.deque`, a list built for adding and removing at both ends. CircuitPython leaves it out on every SAMD21 and SAMD51 board, and on its reduced builds for small chips, which include most nRF52 boards. MicroPython leaves it out of its smallest builds.
