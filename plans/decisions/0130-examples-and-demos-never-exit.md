# Decision 0130: Examples and demos run until the power goes, repeating their work

Status: `accepted`
Date: `2026-10-31`
Summary: Library examples and demo `app.py` files never exit: each ends in a module-level `while True:` that repeats its work on a timer and retries after a failure; `CHU038` enforces the loop.
Related: Decision [0123](0123-demos-read-like-a-first-project.md) (demos read like a first project), Decision [0122](0122-demos-and-examples-write-the-loop-out.md) (the loop is written out), Decision [0013](0013-docs-and-examples-standards.md) (what a library ships in `examples/`), Decision [0074](0074-drift-mechanization-as-project-policy.md) (lintable drift gets a lint).

## Context

Decision 0123 stopped demos from exiting. Library examples kept doing it: on `origin/main`, 21 of the 48 programs under `libraries/*/examples/` and one of the 11 demo apps either raised `SystemExit` or ran off the end after one pass. `ntp_query.py` printed one time and stopped, `connect_to_ap.py` raised `SystemExit` when wifi failed, and the `compat` examples printed their results and returned to the prompt.

The reader these files are for arrives from Adafruit Learn or an Arduino sketch, where a program is imports, then setup, then a loop at the bottom that keeps the board busy. A file that ends leaves that reader at a REPL prompt with nothing moving, and they cannot tell a finished program from a crashed one. The demos had a softer form of the gap: after `DEMO_COMPLETE` they kept the loop turning but only printed a heartbeat, so the work they taught happened once and the board then looked idle.

## Decision

Every file under `libraries/*/examples/` and every `demos/*/app.py` is a program that runs until the power goes.

- **The program never ends itself.** No `raise SystemExit`, no `sys.exit()`, no `exit()` or `quit()`, and no running off the end of the module, on success or on failure.
- **The file ends in a module-level `while True:` with no `break`**, below the imports and the setup. The loop sits at module level, not inside a `main()`, so the reader finds it where an Arduino sketch puts `loop()`.
- **The loop repeats the work the file teaches, on a timer.** After the one-shot part (connect, first query, first round trip) the program does that work again every few seconds: an NTP query asks for the time again, a TCP round trip sends another line, a `partial` example calls its partial again. A bare heartbeat is the fallback for work that cannot repeat, not the default.
- **A failure prints what went wrong and is retried on the next pass.** Wifi that will not join, a broker that refuses, a server that times out: the loop reports it and tries again on its timer.
- **A demo prints `DEMO_COMPLETE` after its first full pass**, then keeps repeating the same work. Decision 0123 covers why the driver can tear down a board that is still running.
- **A script that runs once by design says so in the file.** A benchmark that prints a summary table, or a host-side companion run with `python`, carries a comment-only `# noqa: CHU038 - <reason>` line, which exempts the whole file from the rule and tells its reader why it stops.

`CHU038` enforces the first two bullets: it flags each exit call and each file with no module-level `while True:` free of `break`. Repeating the real work and retrying after a failure are judgment calls, held by review and by `.claude/rules/library-code.md`.

## Rejected

- **Treating an example as a snippet rather than a program.** Readers copy the file to `code.py` and run it. It is a program, and the board treats it as one.
- **Looping on failure and exiting on success.** A finished example looks the same as a crashed one from the serial console, which is the confusion this decision removes.
- **Keeping the heartbeat as the standard tail.** It proves the loop turns, but not that the library survives a second call with its sockets and buffers reused, and a reader watching the console sees the interesting line once.
- **Linting only for a module-level `while`.** A `while not handle.done:` loop at module level would pass and still end the program, so `CHU038` also requires the test to be a true constant and the body to carry no `break` that leaves the loop.

## Consequences

- Examples run a few lines longer, and each `Example output::` block shows the repeated lines.
- `verify-examples` stays static (Decision 0013), since a looping example never finishes under execution.
- `libraries/mqtt/examples/bench.py` and `bench_host.py` carry the whole-file opt-out.
- The new-library scaffold's `basic_usage.py.template` ends in a `while True:` loop, so a fresh library starts compliant, and `docs/contributing/new-library.md`, `docs/contributing/style-guide.md`, and the `new-library` skill describe the shape.
- The workbench template's `examples/*/app.py` files keep their loop inside the `run()` the boot shim calls, so the module-level clause and `CHU038` stay in this repo. The never-exit clause applies there too.
