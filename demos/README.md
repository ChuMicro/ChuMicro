# Demos

Each demo is a small project that runs with one command. The command
puts code on your board and starts the laptop side the board talks
to: a web server, an echo server, or an MQTT broker. It prints both
sides as they talk.

Demos run from a clone of this repository after
`python3 scripts/prepare_workspace.py`. Every demo except
[`laptop_roundtrip`](laptop_roundtrip/) needs a board registered with
`chumicro-workspace add-device` and your WiFi details in
`secrets.toml`, as
[Wiring WiFi credentials](../docs/wiring-wifi-credentials.md) shows.
The MQTT demos also need `mosquitto` on your PATH, from
`brew install mosquitto` or `apt install mosquitto`.

Every demo keeps running after its first full pass. The board repeats
its work on a timer until you unplug it or deploy something else.

## Simplest first

1. [`laptop_roundtrip`](laptop_roundtrip/): no board. A pretend LED
   keeps flipping on and off while your laptop fetches a slow web page
   from itself, over and over.
2. [`sockets_tcp_roundtrip`](sockets_tcp_roundtrip/): the board sends a
   line of text to your laptop every five seconds and reads it back,
   with plain socket calls.
3. [`requests_fetch`](requests_fetch/): the board fetches a web page
   from your laptop every five seconds and prints what came back.
4. [`http_server_roundtrip`](http_server_roundtrip/): the board serves
   web pages, and your laptop requests three of them. The board keeps
   serving and prints a status line.
5. [`sockets_tls_roundtrip`](sockets_tls_roundtrip/): the
   `sockets_tcp_roundtrip` echo over an encrypted link, trusting a
   certificate made on the spot.
6. [`mqtt_pub_sub`](mqtt_pub_sub/): the board and your laptop trade
   MQTT messages through a broker on your laptop. The board publishes
   every two seconds.
7. [`websockets_stream`](websockets_stream/): the board opens a
   websocket to your laptop and prints each message that streams in.
   Five seconds after a stream ends, it reconnects for another.
8. [`press_through_fetch`](press_through_fetch/): wire a button. The
   board fetches a page every three seconds. Every press lands on
   time, mid-fetch included.
9. [`mqtt_sensor_motor`](mqtt_sensor_motor/): a temperature-controlled
   fan over MQTT. The board publishes its temperature and drives a
   motor signal, with the onboard LED standing in for the motor.
10. [`sockets_runner_connector`](sockets_runner_connector/): the echo
    from demo 2, written so the board never sits waiting. A heartbeat
    line proves it. Start from this demo for a TCP protocol of your
    own.
11. [`sockets_runner_connector_explicit`](sockets_runner_connector_explicit/):
    the same echo written as a service class with `check()` and
    `handle()` methods, like every ChuMicro service.

## Running a demo

```bash
.venv/bin/python demos/<name>/driver.py

# laptop_roundtrip runs its app.py directly:
cd demos/laptop_roundtrip && ../../.venv/bin/python app.py
```

Each driver picks a default board from `devices.yml`. Pass
`--device <id>` for a specific board, or `--runtime micropython` for
the first MicroPython one. `driver.py --help` lists every option.
Lines starting `board |` are what the board prints. Lines starting
`driver:` come from the script on your laptop.

## What a demo is

A demo is a directory under `demos/<name>/` with these files:

- `app.py` runs on the board. It shares its name with
  `projects/<name>/app.py` in a workspace made from the workbench
  template, so a demo reads like a real project.
- `driver.py` runs on your laptop. It deploys `app.py`, starts the
  laptop side, prints every line the board prints, and waits on the
  board's marker lines to check each step. Once it has seen every
  marker it waits for, it stops the laptop side and exits. The board
  keeps running.
- `README.md` says what you will see, what you need, the command to
  run, and what to try next.

`laptop_roundtrip` is the exception: its `app.py` runs on your laptop
with `python app.py`, so it has no `driver.py`.

A driver may import anything in this repository: `workbench/`
packages, `chumicro_pytest_device.fixtures.*`, and internal helpers. A
demo shows how the board and the laptop pieces fit together. A driver
limited to library imports would hide the laptop half. Demos run from
a clone of this repository and never ship to PyPI.

## Demo or example?

| | Example | Demo |
|---|---|---|
| Purpose | Read it to learn one library | Run it to watch libraries work together |
| Location | `libraries/<lib>/examples/` | `demos/<name>/` |
| Libraries | One | Often several: wifi, http_server, msgpack, ... |
| Imports | Only the library it teaches | Anything in this repo (driver side) |
| Runs on | A board, with your laptop tailing its output | A board plus your laptop (`laptop_roundtrip`: laptop only) |
| Ships to PyPI | Yes, with the library | No |

## When to add a demo instead of an example

If the library is a client and a reader can stand up the other end
with a one-liner (`curl ...`, `python -m http.server`, `nc -ul ...`), a
"Try it locally" section in the example's docstring is enough.

If the library is a server (`http_server`, a websockets server), or
the other end needs real setup (an MQTT broker, a TLS certificate, a
multi-step handshake), write a demo. Its `driver.py` does the setup,
finds the addresses, and checks the result, so the reader runs one
command.

## Adding a demo

1. Create `demos/<name>/` with `README.md`, `app.py`, and `driver.py`.
2. Write `app.py` for someone learning, because that is who reads it.

   **The docstring says what the board does and what you will see.**
   Open with what the board does, paste the real output, and end with
   something to try. Comparisons to sibling demos go in the demo's
   `README.md`, not in the file a beginner opens first.

   **Import only what the demo is demonstrating.** No
   `chumicro_test_harness`, no workbench internals. Marker lines are
   plain `print` calls:

   ```python
   print(f"WIFI_OK ip={wifi.ip}")
   print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
   ```

   The host parser reads `NAME key=value` lines. It drops the whole
   line when any value holds a space or an `=`. Hex-encode bytes, and
   put anything free-form, such as a URL with a query string or a
   message body, on its own indented line. The parser ignores indented
   and lowercase lines, which leaves them free for people to read.

   **The demo never exits and keeps working.** The file ends in a
   module-level `while True:` with no `break`. Nothing raises
   `SystemExit` or calls `sys.exit()`. A lint check enforces both
   rules. Print `DEMO_COMPLETE` after the first full pass, then repeat
   the visible work on a timer: send another line, fetch the page
   again, publish the next reading. Each repeat prints an indented
   line a person can read. A failure prints what went wrong, and the
   next pass retries the work
   ([Decision 0130](../plans/decisions/0130-examples-and-demos-never-exit.md)).

   ```python
   def echo_forever(wifi, link_up, host, port):
       yield from wait_for(link_up)
       while True:
           try:
               payload = yield from echo_once(wifi.adapter.radio, host, port)
               print(f"  echo: {payload.decode()!r} came back")
           except Exception as error:
               print(f"ECHO_FAILED error={type(error).__name__}")
           yield from sleep_until(ticks_add(ticks_ms(), 5000))


   runner.add_generator(echo_forever(wifi, link_up, host, port))

   while True:
       now_ms = runner.tick()
       runner.wait(now_ms)
   ```

   Give the timer to the runner, through `sleep_until` in a generator
   or `runner.add_periodic(...)`, so `runner.wait()` wakes for it. An
   `if` on a `Deadline` in the loop body fires only when something
   else happens to wake the loop.

   **Add no other scaffolding.** Leave out timeout constants,
   completion flags, and state dicts. The driver already times out
   every wait. `session.shutdown()` is safe while the board keeps
   running. A one-second heartbeat that prints `  ...still ticking`
   covers work that cannot repeat. The same heartbeat proves the loop
   never freezes when that is the demo's point.

3. Write `driver.py` around
   `chumicro_workspace.deploy_api.deploy_project(...,
   on_line=echo_board_line)`. That call deploys `app.py`, prints every
   board line as `board | ...`, and returns a session. Wait on the
   board's markers with `session.wait_for(...)`. Use the helpers in
   `chumicro_pytest_device.fixtures.*` for the laptop side. A driver
   that hosts the other end, such as an echo server or a broker, keeps
   it up for a few repeat rounds before stopping it. The demo's README
   says what the board prints once the other end is gone.
4. `python scripts/run.py verify-demos` parses every `.py` under
   `demos/` and fails on syntax errors or empty files. Preflight runs
   it.
