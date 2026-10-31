# Demos

Each demo is a small project you run with one command. It puts code on
your board, starts whatever the board needs on your laptop (a web
server, an echo server, an MQTT broker), and shows you both sides as
they talk. You need a board registered with
`chumicro-workspace add-device` and your wifi details in `secrets.toml`
([wiring wifi credentials](../docs/wiring-wifi-credentials.md)). The
MQTT demos also need `mosquitto` on your PATH (`brew install mosquitto`).
[`laptop_roundtrip`](laptop_roundtrip/) needs no board at all.

Every demo keeps running once it has shown you its work. The board
repeats it on a timer, the way a project on your desk would, until you
unplug it or deploy something else.

## Which demo first

Simplest first. Each line says what you will see.

1. [`laptop_roundtrip`](laptop_roundtrip/): no board. A pretend LED keeps
   flipping on and off while your laptop fetches a slow web page from
   itself, over and over.
2. [`sockets_tcp_roundtrip`](sockets_tcp_roundtrip/): the board sends a
   line of text to your laptop every five seconds and reads it back,
   with plain socket calls.
3. [`requests_fetch`](requests_fetch/): the board fetches a web page from
   your laptop every five seconds and prints what came back.
4. [`http_server_roundtrip`](http_server_roundtrip/): the board serves
   web pages, your laptop requests three of them, and the board keeps
   serving and printing a status line.
5. [`sockets_tls_roundtrip`](sockets_tls_roundtrip/): the
   `sockets_tcp_roundtrip` echo over an encrypted link, trusting a
   certificate made on the spot.
6. [`mqtt_pub_sub`](mqtt_pub_sub/): the board and your laptop trade MQTT
   messages through a broker on your laptop; the board publishes every
   two seconds.
7. [`websockets_stream`](websockets_stream/): the board opens a websocket
   to your laptop, prints each message that streams in, and reconnects
   for another stream five seconds later.
8. [`press_through_fetch`](press_through_fetch/): wire a button. The
   board fetches a page every three seconds, and every press you make
   lands on time, mid-fetch included.
9. [`mqtt_sensor_motor`](mqtt_sensor_motor/): a temperature-controlled
   fan over MQTT. The board publishes its temperature and drives a motor
   signal, with the onboard LED standing in for the motor.
10. [`sockets_runner_connector`](sockets_runner_connector/): the echo
    from demo 2, written so the board never sits waiting, with a
    heartbeat to prove it. Start here for your own TCP protocol.
11. [`sockets_runner_connector_explicit`](sockets_runner_connector_explicit/):
    the same echo as a service class with `check` and `handle`, the
    shape every ChuMicro service has.

## Running a demo

```bash
.venv/bin/python demos/<name>/driver.py

# laptop_roundtrip has no driver.py; run its app directly:
cd demos/laptop_roundtrip && ../../.venv/bin/python app.py
```

Each driver picks a default board from `devices.yml`. Pass
`--device <id>` for a specific board or `--runtime micropython` for the
first MicroPython one; `driver.py --help` lists every option. Lines
starting `board |` are what the board prints, and `driver:` lines come
from the script on your laptop.

## What a demo is

A directory under `demos/<name>/` holding three files:

- `app.py` runs on the board. It is named like the
  `projects/<name>/app.py` in a workspace made from the workbench
  template, so a demo reads like a real project.
- `driver.py` runs on your laptop. It deploys `app.py`, starts the
  laptop side, prints every line the board prints, and waits on the
  board's marker lines to check each step. Once it has seen what it came
  to check, it stops the laptop side and exits. The board keeps running.
- `README.md` says what you will see, what you need, the command to
  run, and what to try next.

`laptop_roundtrip` is the exception: its `app.py` runs on your laptop
with `python app.py`, so it has no `driver.py`.

A driver may import anything in this repo: `workbench/` packages,
`chumicro_pytest_device.fixtures.*`, internal helpers. A demo shows how
the pieces fit together, and limiting its driver to library imports
would hide that. Demos are never packaged or published to PyPI; they
run from a clone of this repo.

## Demo or example?

| | Example | Demo |
|---|---|---|
| Purpose | Read it to learn one library | Run it to watch libraries work together |
| Location | `libraries/<lib>/examples/` | `demos/<name>/` |
| Libraries | One | Often several: wifi, http_server, msgpack, ... |
| Imports | Only the library it teaches | Anything in this repo (driver side) |
| Runs on | A board; your laptop tails its output | A board plus your laptop (`laptop_roundtrip`: laptop only) |
| Ships to PyPI | Yes, with the library | No |

## When to add a demo instead of an example

If the library is a client and a reader can stand up the other end with
a one-liner (`curl ...`, `python -m http.server`, `nc -ul ...`), a
"Try it locally" section in the example's docstring is enough.

If the library is a server (`http_server`, a websockets server), or the
other end needs real setup (an MQTT broker, a TLS certificate, a
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

   The host parser reads `NAME key=value` and drops the whole line if
   any value holds a space or an `=`, so hex-encode bytes and put
   anything free-form (a URL with a query string, a message body) on its
   own indented line. The parser ignores indented and lowercase lines, so
   they are free for the human.

   **The demo never exits, and it keeps working.** The file ends in a
   module-level `while True:` with no `break`, and nothing raises
   `SystemExit` or calls `sys.exit()`; a lint check enforces both. Print
   `DEMO_COMPLETE` after the first full pass, then repeat the visible
   work on a timer: send another line, fetch the page again, publish the
   next reading. Each repeat prints an indented line a person can read,
   and a failure prints what went wrong and is retried on the next pass
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

   Give the timer to the runner, through `sleep_until` in a generator or
   `runner.add_periodic(...)`, so `runner.wait()` wakes for it. An `if`
   on a `Deadline` in the loop body fires only when something else
   happens to wake the loop.

   **No scaffolding beyond that.** No timeout constants, no completion
   flags, no state dicts: the driver already has a timeout on every
   wait, and `session.shutdown()` is safe while the board keeps running.
   A one-second heartbeat that prints `  ...still ticking` is the
   fallback for work that cannot repeat, or the proof when the demo's
   point is that the loop never freezes.

3. Write `driver.py` around
   `chumicro_workspace.deploy_api.deploy_project(...,
   on_line=echo_board_line)`, which deploys `app.py`, prints every board
   line as `board | ...`, and returns a session. Wait on the board's
   markers with `session.wait_for(...)`, and use the helpers in
   `chumicro_pytest_device.fixtures.*` for the laptop side. If the driver
   hosts the other end (an echo server, a broker), keep it up for a few
   repeat rounds before stopping it, and say in the README what the
   board prints once it is gone.
4. `python scripts/run.py verify-demos` parses every `.py` under
   `demos/` and fails on syntax errors or empty files; preflight runs it.
