# Running out of memory

This page is for a board that stops with `MemoryError`, or with `OSError: [Errno 12]` (the same thing: out of memory). A microcontroller's free memory, its *heap*, is small: a Pi Pico W leaves about 150 KB for your program once its firmware has started. A program that runs comfortably on a laptop can run out of room there.

## `MemoryError` the first time your program imports a library partway through a run

Importing a library on the board compiles its source right there, and the compiler needs one large block of free memory while it works: importing `chumicro-mqtt` needs about 95 KB free at that moment on a Pi Pico W. Board memory never gets rearranged, so after your program has been running a while, its free space is scattered in small gaps between objects it still holds. The total can look healthy while no single gap is big enough.

Do the imports, and create your clients (wifi, MQTT, HTTP), at the top of your program, before the main loop starts. Memory is still in one piece then.

```python
from chumicro_mqtt import MQTTClient    # import and build at startup...

mqtt = MQTTClient.from_config(config, radio=radio)

while True:                             # ...then run the loop
    ...
```

## `OSError: [Errno 12]` when an HTTPS or `wss://` connection starts

The encrypted handshake needs about 25 KB in one block. [TLS and HTTPS failures](tls-https-failures.md#oserror-errno-12-during-the-tls-handshake) covers the fixes.

## `MemoryError` or `INSUFFICIENT_MEMORY` during a RAM-mode deploy

RAM mode holds your whole program in memory instead of writing it to the board's storage, and the network libraries don't fit that way on a small board. Deploys switch to flash mode on their own to avoid this, so you only meet it after `--force-deploy-mode ram`. Deploy without that flag; [Deploys and file persistence](deploys-and-file-persistence.md#the-deploy-prints-switching-to-flash-mode-after-you-asked-for-ram) explains the two modes.

## `ImportError` naming `deque` when importing a ChuMicro library

ChuMicro libraries use `collections.deque`, a list built for adding and removing at both ends. CircuitPython leaves it out on every SAMD21 and SAMD51 board and on its reduced builds for small chips, which include most nRF52 boards. MicroPython leaves it out of its smallest builds.

ChuMicro supports boards with at least 256 KB of RAM: the ESP32 family, RP2040 and RP2350 (Pi Pico W, Pico 2 W), and STM32. Move the project to one of those, running a full CircuitPython or MicroPython build.
