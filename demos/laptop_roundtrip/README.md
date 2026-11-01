# laptop_roundtrip: watch the loop at work, no board required

Every other demo here needs a board on your desk. This one needs only
Python. It runs a web server, a client that fetches from it over and
over, and a pretend LED that flips on and off, all in one Python process
on your laptop.

Each fetch takes about two seconds, because the server sends its reply
one line at a time. The LED keeps flipping every quarter second the
whole time. Nothing in the loop waits on the fetch, so the LED never
skips a beat. That is the idea every ChuMicro program runs on, board or
laptop.

## What you need

The repo's one-time setup, and nothing else:

```bash
python3 scripts/prepare_workspace.py     # creates .venv and installs everything
source .venv/bin/activate
```

No board, no wifi, no second terminal. The server and the client talk to
each other over `127.0.0.1`.

## Run it

```bash
cd demos/laptop_roundtrip
python app.py
```

It keeps going until you press Ctrl-C.

## What you will see

```
laptop_roundtrip: serving http://127.0.0.1:51579/slow, press Ctrl-C to stop
  fetch 1: GET http://127.0.0.1:51579/slow
  LED on
  LED off
  LED on
  LED off
  LED on
  LED off
  LED on
  fetch 1: 200, 224 bytes, while the LED flipped 7 times
  LED off
  LED on
  LED off
  LED on
  fetch 2: GET http://127.0.0.1:51579/slow
  LED off
  ...
^C
laptop_roundtrip: stopped.
```

The operating system picks the port, so it changes each run. The flip
count can vary by one between fetches: the LED keeps its own time, and
the fetch finishes whenever its last line arrives.

## Try next

- Set `LINE_GAP_MS = 1000` in `app.py`. Each fetch takes four times as
  long, and the LED still flips every quarter second.
- Set `BLINK_MS = 50` and watch the LED lines speed up while the fetches
  keep their own pace.
- Move on to [`sockets_tcp_roundtrip`](../sockets_tcp_roundtrip/), the
  simplest demo that runs on a board.

## How `app.py` works

- **One `Runner`, three jobs.** `runner.add(server)` registers the web
  server, `runner.add_periodic(blink, period_ms=BLINK_MS)` flips the LED
  on a timer, and `runner.add_generator(fetch_forever(...))` runs the
  client.
- **`fetch_forever` reads top to bottom.** It fetches, prints the
  result, rests one second, and goes again. Each `yield from` is a place
  it pauses so the server and the LED get their turns.
- **The main loop is two lines.** `runner.tick()` gives each job one
  small step, and `runner.wait(now_ms)` idles the CPU until a socket has
  something or the next timer is due, the same way it saves power on a
  battery-powered board.

The board demos split into an `app.py` that runs on the board and a
`driver.py` that runs on your laptop and talks to it. This one has no
board, so `app.py` is the whole demo.
