# Style Guide

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

These conventions hold for all code in the repository, library, infrastructure, and tests alike, except where a section says otherwise.  `python scripts/run.py lint` enforces most of them.

<br clear="left">

## Baseline

[PEP 8](https://peps.python.org/pep-0008/) with a **110-character line limit**, set in `pyproject.toml` and enforced by [Ruff](https://docs.astral.sh/ruff/).

## Naming

Names spell words out, so the code reads without extra context.  The linter flags common abbreviations and names the replacement.

| Rule | Example | Enforced by |
|---|---|---|
| No single-letter variables (except `_` and for-loop targets) | `index`, not `i`, in assignments, and `for i in range(10)` is fine | `CHU001` linter |
| Abbreviations to expand | `env` → `environment`, `buf` → `buffer`, `src` → `source`, `cmd` → `command`, `msg` → `message`, `err` → `error`, `ref` → `reference`, `addr` → `address`, `exc` → `exception`, `exec` → `execute` | `CHU001` linter |
| Same expansions apply as suffixes | `base_ref` → `base_reference`, `build_env` → `build_environment` | `CHU001` linter |
| Short-but-complete words are fine | `dir`, `key`, `tag`, `raw`, `pin`, `led`, `ok`, `end`, `args`, `config` | none |
| For-loop targets are exempt | `for i in range(10)`, `for k, v in items()` | none |
| Suppress with `# noqa: CHU001` | At upstream-API boundaries: `i2c_addr = kwargs["addr"]  # noqa: CHU001` | none |

The rule renames some domain idioms: datasheets label a pin `ADDR`, git has `refs`, and the table renames both.  [Decision 0022](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0022-naming-conventions.md) weighed that cost and chose one vocabulary.  The `noqa` row covers an upstream API that forces the abbreviation.

**Why.**  Full words read without context: a newcomer, a non-native English speaker, or anyone outside Python's abbreviation habits reads `exception` at once, where `exc` costs a lookup.  Agents also write a large share of the patches here, and agents follow linters more reliably than prose conventions.  So a rule the project cares about becomes a lint rule, and humans share the same gate, which leaves one rule set.  The rule fights the habits of long-time Python writers.  Each hit is a mechanical fix, because the message names the exact replacement, so a first pull request meets several and later ones meet almost none.

## Type annotations

Every function and method signature carries type annotations.  They cost nothing at runtime on a board: CircuitPython and MicroPython parse annotations and drop them at compile time.

Library code imports neither `typing` nor `from __future__ import annotations`, and uses the built-in syntax.  `typing` doesn't exist on CircuitPython or MicroPython.

```python
# ✅ Works on all runtimes (PEP 604 / PEP 585 syntax)
def read(self, timeout: int | None = None) -> bytes | None: ...
def process(self, items: list[int]) -> dict[str, int]: ...

# ❌ Requires typing module (fails on embedded runtimes)
from typing import Optional, List
def read(self, timeout: Optional[int] = None) -> Optional[bytes]: ...
```

`scripts/` may import `typing`, since it runs only on CPython.  Most of `support/` is CPython-only too, but `support/test_harness/` runs on all three runtimes and follows the library rules.

([Decision 0021](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0021-docstring-type-policy.md))

## Imports

Code that runs on a device, in `libraries/*/src/` and `support/test_harness/`, uses **absolute imports only**.  Relative imports break CircuitPython RAM-mode deploys.

```python
# ✅ Works on all runtimes
from chumicro_timing.ticks import ticks_ms, ticks_diff
from chumicro_timing.deadline import Rate

# ❌ Breaks CircuitPython RAM-mode
from .ticks import ticks_ms, ticks_diff
from .deadline import Rate
```

**Why.**  CircuitPython RAM mode assembles library modules as class-as-module stubs and runs them with `exec()` inside the raw REPL.  The namespace passed to `exec()` has no `__package__` attribute, so Python can't resolve a leading `.`, and `from .foo import bar` raises `ImportError`.  Flash mode works, because files land on the device filesystem and get a real `__package__` when imported.  Every published library has a RAM-mode path, so each one works in both modes.

Host-only code can use either style:

- **`workbench/*/src/`**: relative imports work, because these packages run on CPython only and never pass through the raw REPL.  `chumicro-deploy` uses relative imports within its package throughout.
- **`scripts/`**: either style.
- **Tests**: either style ([Decision 0009](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0009-per-library-test-runs.md)).

An import from one publishable library into another stays absolute wherever it lives: `from chumicro_timing import ticks` inside `chumicro_runner` is correct.

**Enforcement.**  Ruff's TID252 rule (`flake8-tidy-imports.ban-relative-imports`) carries the ban, set in `pyproject.toml`.  The `[tool.ruff.lint.per-file-ignores]` table relaxes it for `workbench/**`, `scripts/**`, `**/tests/**`, `**/functional_tests/**`, and `**/examples/**`.  Those trees run on CPython, or stand alone outside any package where a relative import never resolves.  A regression scenario in `scripts/audit_gates.py` confirms the rule fires for `libraries/*/src/` and `support/test_harness/src/`, and stays silent in the relaxed trees.

## Docstrings

Every public function, method, and class needs a docstring, in [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).  Types go on the annotations and descriptions go in the docstring, so a type is written once.

```python
def ticks_diff(end: int, start: int) -> int:
    """Signed difference between two tick values.

    Args:
        end: Later tick value.
        start: Earlier tick value.

    Returns:
        Signed difference in milliseconds.
    """
```

The sections you'll use most:

- **`Args:`** is `name: description`, with no type in parentheses, since the signature already carries it
- **`Returns:`** is a description only, with no `type:` prefix
- **`Raises:`** is `ExceptionType: description`

The published API reference comes from these docstrings.  The docs build fails on any [griffe](https://mkdocstrings.github.io/griffe/) warning about a missing or malformed section, so the hosted reference stays complete.

([Decision 0021](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0021-docstring-type-policy.md))

## Documentation tone

These rules cover prose docs: the root README, every library's README and `docs/guide.md`, every workbench README, and the contributing pages.  [AGENTS.md § Writing](https://github.com/ChuMicro/ChuMicro/blob/main/AGENTS.md#writing) holds the sentence-level rules they all follow.

**The audience is the Adafruit Learn crowd**: beginners and hobbyists, sometimes kids, who have flashed a board, followed a guide or two, and want code that keeps working.  Every sentence is one that reader can follow.  Veterans get receipts, such as measured numbers and decision links, inside the same sentences, never jargon.  The best claims are moments the reader can reproduce at a desk: *"pull your router's plug and watch the LED keep blinking."*

- **Anchor on a concrete promise the user can see, rather than an abstract design principle.**  *"Keep a status LED blinking through a slow network call"* beats *"transparent state matters more than syntactic concurrency."*  A first-time reader shares the LED and lacks the vocabulary.  Design philosophy belongs in ADRs, outside the project's top-level README.
- **Describe the thing, and instruct the reader.**  *"`Rate` says yes once per period"* describes the library, and *"Set `tx_power_dbm = 15`"* gives an instruction.  A sentence about the reader's situation, such as *"you're building a weather station"*, narrates at someone who isn't there.
- **The root README carries the library and workbench matrices.**  Most visitors see one URL, the root, so a one-line link to [`libraries/`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/) hides the matrix there.  Folder READMEs add deeper context, such as the dependency graph and problem-driven selection.
- **Code, prose, and any visual tell the same story.**  When the hero promises an LED, the code shows `led.value = not led.value`, and a `print()` breaks the promise.  When the hero promises composition, the code shows several services on one runner.  A visual depicts what the prose says.  Without a clear need, leave the visual out: prose and code carry the page.
- **A published package's docs describe that package.**  Its README, guide, and module docstrings say what this package does.  A phrase like *"This package doesn't do X, use `other-package` for X instead"* leaks mono-repo awareness into a PyPI-facing artefact.  A relative path like `../workspace/` resolves only on the mono-repo docs site, and breaks PyPI README rendering.  A sentence about how in-scope tools work together belongs.
- **The root README speaks at repository altitude.**  A section earns its place there by showing libraries, tooling, or workflow working together.  Single-library behaviors and protocol details, such as queue policies, replay semantics, and last-will mechanics, belong in that library's README and guide.
- **Code listings suit the page's reader.**  A front-page listing carries only lines its reader can follow.  Expert options, such as last wills, retained state echoes, and tuning knobs, stay in guides and demos even when a real deployment would use them.  A listing that needs three paragraphs of explanation shrinks.
- **A `python` listing parses and imports real names.**  `CHU039` parses each `python` fence in the READMEs and docs, and checks its `chumicro_*` imports against the source.  A listing that shows part of a program carries `<!-- fragment -->` as the last non-blank line above its opening fence, which skips the parse check and keeps the import check.
- **Feature bullets lead with what the user can do, in concrete terms.**  *"Bring your own socket, your own clock"* beats *"Constructor-injected duck-typed I/O dependencies"*.  Name real things: library class names, standard-library alternatives, production scenarios.  Acknowledge the default first, then the swap-out path.  Leave out type-system jargon (`duck-typed`, `Protocol`, `structural typing`), method-name lists, and test fakes: a production swap-in belongs in the pitch.

### Voice

[AGENTS.md § Writing](https://github.com/ChuMicro/ChuMicro/blob/main/AGENTS.md#writing) sets the sentence rules, the em-dash ban among them.  On top of those, the docs sound like this:

- **Plain words over clever ones.**  A phrase that needs decoding, such as *"the runtime split"* or *"transport wiring"*, gets spelled out.  Clever wording that costs the reader a second read is a defect.
- **Say what the project believes, straight.**  When the project holds a position, such as blocking code being a bad foundation for a device, state it.  Diplomacy the project doesn't believe, such as *"that's fine for many projects"*, stays out.
- **Concrete beats rhetorical.**  Measured numbers (80 lines vs 7), named hardware (Pico W, ESP32), real failure moments (a board hanging because the router was unplugged).  Every claim traces to code, a measurement, or a decision record, or it doesn't ship.
- **Normal sentences, varied in length.**  Staccato fragment chains (*"Write it once. Test it. Ship it."*), *"the whole X"*, and symmetrical triads read as performance.
- **Behavior over mechanics.**  Say what the reader can do and what happens when they do it.  How a thing is built inside belongs in ADRs and library guides.
- **At most one metaphor per page, and never the same one twice.**
- **Gloss jargon at first use in beginner-facing docs** (TLS, MQTT, mpremote, venv), then use it freely.  A term in a reference table the reader reaches later needs no gloss.

## String formatting

Build strings with f-strings.  A deferred-formatting API that takes a template plus arguments, such as a logging seam, keeps its template form.

```python
# ✅
print(f"Found {count} items in {directory}")

# ❌
print("Found %d items in %s" % (count, directory))
print("Found {} items in {}".format(count, directory))
```

## Error handling

Host-side infrastructure, in `scripts/`, `workbench/*/src/`, and `support/` outside `test_harness`, never swallows an exception silently.  Every `except:` branch that chooses not to re-raise logs a visible message, a WARNING at minimum, so the problem gets noticed.

```python
# ✅ visible
try:
    subprocess.run(["xattr", "-cr", str(path)], check=True)
except FileNotFoundError:
    print("WARNING: xattr not found: skipping extended attribute removal")
except subprocess.CalledProcessError as exception:
    print(f"WARNING: xattr failed: {exception}")

# ❌ silent
try:
    subprocess.run(["xattr", "-cr", str(path)], check=True)
except Exception:
    pass
```

Library code, in `libraries/*/src/` and `support/test_harness/`, meets the same bar with one more constraint: `print()` costs RAM and I/O time on a board.  It raises a specific exception type the caller can react to, or emits through the library's logging seam where one exists.  It never uses `except: pass`.

Catching an exception and raising a different one is fine: the chained `__cause__` keeps the origin.  Translating errno strings into messages a classifier recognizes, as the transport's `CIRCUITPY drive not found or not writable` re-raise does, follows the same rule.

## Subprocess binary resolution (host tools)

A host-side tool that shells out to an installable CLI binary, such as `mpremote`, `esptool`, or `rshell`, resolves the binary next to the running interpreter first, before a bare name on `PATH`:

```python
import shutil
import sys
from pathlib import Path

def _resolve_binary(name: str) -> str:
    candidate = Path(sys.executable).parent / name
    if candidate.is_file():
        return str(candidate)
    return shutil.which(name) or name
```

**Why.**  PyCharm and VS Code launch test runs through the interpreter path without activating a shell, so `.venv/bin` is missing from `PATH` even on a freshly prepared workspace.  Resolving next to `sys.executable` makes `.venv/bin/<name>` the first candidate.  `shutil.which` handles system-wide installs and Windows `Scripts/<name>.exe`.  The bare-name fallback keeps the subprocess's own error when nothing resolves.

Only the first element of the argument list changes, and the rest of the command stays identical.

## Memory patterns (library code only)

Microcontrollers have little RAM and no virtual memory, and these patterns stretch it.  They matter most in performance-sensitive code.  Write the clear version first, and apply a pattern when a measurement calls for it.

They apply to **publishable library code under `libraries/`** and to **`support/test_harness/`**.  Other infrastructure code, in `scripts/` and the rest of `support/`, runs on CPython and follows standard Python conventions.

| Pattern | Why |
|---|---|
| Pre-allocate `bytearray` in constructor, reuse with `readinto()` | Avoid repeated allocation |
| `memoryview` for slicing | Avoid copies |
| `const()` for numeric constants (import from `micropython`) | Compiler optimization |
| Cache frequently used attributes in local variables | Reduce attribute lookups in hot paths |
| Avoid dynamic string building in loops | GC pressure |

<details>
<summary>Examples (click to expand)</summary>

### `const()` (compile-time constants)

On MicroPython and CircuitPython, `const()` inlines the value at compile time instead of creating a runtime object.  CPython lacks it, so every library that uses it carries a fallback:

```python
try:
    from micropython import const
except ImportError:

    def const(value: int) -> int:
        """Identity fallback so const() works on CPython."""
        return value

_PERIOD = const(1 << 29)       # inlined at compile time, no heap allocation
_MAX = const(_PERIOD - 1)
```

Prefix internal constants with `_` to keep them module-private.  `libraries/timing/src/chumicro_timing/ticks.py` shows a real example.

### `memoryview` (zero-copy slicing)

Slicing a `bytearray` copies the data every time.  A `memoryview` slice points into the original buffer:

```python
# ❌ Each slice copies data
header = data[0:4]       # new bytearray allocated
payload = data[4:20]     # another new bytearray allocated

# ✅ Zero-copy: slices share the original buffer
view = memoryview(data)
header = view[0:4]       # no copy
payload = view[4:20]     # no copy
```

Combine it with a pre-allocated buffer for the full pattern:

```python
class PacketReader:
    """Incremental packet reader with zero-copy slicing."""

    def __init__(self, buffer_size: int = 64) -> None:
        self._buffer = bytearray(buffer_size)  # allocated once
        self._view = memoryview(self._buffer)   # reusable view

    def read_header(self, source: object) -> memoryview:
        """Read from source into the buffer, return the header slice."""
        source.readinto(self._buffer)
        return self._view[0:4]  # zero-copy slice
```

</details>


## Cooperative concurrency

`chumicro-runner` is the one scheduler library code uses.  A service registers with `runner.add(service)` for check and handle, `runner.add_periodic(handler, period_ms=...)` for periodic work, or `runner.add_generator(gen)` for a generator doing sequential I/O, as the [runner guide](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/docs/guide.md#generator-tasks) shows.

[Decision 0087](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0087-generators-for-sequential-io.md) checked both runtimes' compiler sources.  CircuitPython compiles every `await` into an `__await__` method dispatch that allocates a fresh generator on each resume, where MicroPython compiles the same `await` to a single `YIELD_FROM` bytecode.  Adafruit's CircuitPython asyncio port has had a broken socket and stream layer since 2021.  Building on `async` would mean per-await heap churn on one runtime and an unmaintained stream layer, or quietly targeting only the other runtime.  `yield from` is one bytecode on both, and the wait objects it drives are reusable.

**`async`, `await`, and the `asyncio` module are banned across `libraries/`, `support/`, and `workbench/`:**

- `async def`, `await`, `async with`, `async for`.
- `import asyncio` / `from asyncio import …`.
- `import uasyncio` / `from uasyncio import …` (MicroPython alias).
- A module file or directory named `asyncio*`.

The translation is mechanical:

```python
async def fetch():                      # what you'd write elsewhere
    response = await get(url)

def fetch():                            # what you write here
    response = yield from get(transport_factory, url)
```

Lint rule `CHU033` enforces the ban.  It reads the syntax tree, so the keywords inside string literals pass.  It skips `functional_tests/`, where a host-only test server may reach asyncio through a host package.  The ban covers `workbench/` too, where every tool runs on CPython and the device reasons fall away.  One concurrency model across the repository keeps host patterns from drifting into device code, and a contributor moving between trees never switches models.

## Examples and demos

A library example or a demo's `app.py` is often the first program a reader copies onto a board, and a board runs its program until the power goes.  Each one reads the way an Adafruit Learn guide or an Arduino sketch does: imports, then setup, then a `while True:` loop at the bottom that keeps working.

```python
import time

from chumicro_msgpack import packb, unpackb

settings = {"name": "lamp", "brightness": 0}

while True:
    settings["brightness"] = (settings["brightness"] + 25) % 125
    data = packb(settings)
    print(f"packed {len(data)} bytes, restored {unpackb(data)}")
    time.sleep(2)
```

- **The loop repeats the work the file teaches, on a timer.**  The one-shot part, such as joining wifi, asking for the time, or opening a connection, runs first.  The loop then does that work again every few seconds, so the reader watches the library work more than once.
- **A failure prints what went wrong and tries again on the next pass.**  The program never stops itself: no `raise SystemExit`, no `sys.exit()`, no `exit()`, and no running off the end after the work succeeds.
- **The loop sits at module level**, where a reader expects it, outside any `main()` function.  With `chumicro_runner`, the loop reads `now_ms = runner.tick()`, then `runner.wait(now_ms)`.  `runner.run_until(...)` hides that loop from the reader ([Decision 0122](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0122-demos-and-examples-write-the-loop-out.md)).
- **An example imports public packages only**: ChuMicro libraries and the board's own modules, such as `board`, `digitalio`, and `machine`.  It leaves out test harnesses, workbench tools, and the `if __name__ == "__main__":` guard.
- **A board-specific example says so.**  Its filename starts with `circuitpython_` or `micropython_`, and it sets `__chumicro_runtimes__ = ("circuitpython",)` or `("micropython",)` at the top.
- **The module docstring shows what the reader will see**, with real output pasted into an `Example output::` block.
- **The filename describes the example**, such as `sensor_basic_reading.py`.
- **A demo prints `DEMO_COMPLETE` after its first full pass** and keeps repeating the same work.  The host-side driver watches for that line.

A script that runs once by design, such as a benchmark that prints a summary table, says so with a comment-only line naming the reason: `# noqa: CHU038 - benchmark: runs each scenario once, then prints a summary`.

Lint rule `CHU038` flags each exit call, and each file without a module-level `while True:` free of `break`.  `python scripts/run.py verify-examples` checks every example's syntax and imports.  [Decision 0130](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0130-examples-and-demos-never-exit.md) records the reasoning.

## Coverage exclusions

Every library meets the **85 %** coverage threshold set in `pyproject.toml` (`fail_under = 85`) in its own test run.  Agents hold the libraries they change to a higher bar, as [Working with Agents](working-with-agents.md#what-to-expect-from-agent-behavior-here) describes.  Some code runs only on a real board: runtime-specific branches, hardware fallbacks, and defensive guards.  Mark those lines so the coverage count leaves them out.

### `# pragma: no cover` (exclude a line or block)

Add the comment to any line, `if` branch, or function that CPython tests cannot reach:

```python
# Single line
status_pin = board.D5  # pragma: no cover

# Entire branch
if sys.implementation.name == "circuitpython":  # pragma: no cover
    import neopixel
else:
    neopixel = None

# Entire function (put it on the def line)
def _reset_hardware() -> None:  # pragma: no cover
    """Hard-reset the I2C bus, only works on real hardware."""
    ...
```

The `const()` fallback needs no `# pragma: no cover`: on CPython the `try` line runs and fails, and the `except` branch runs.

### When to use it

- **Runtime-only imports** (`import board`, `import neopixel`, etc.)
- **Hardware-specific branches** (`if sys.platform == "rp2":`)
- **Defensive guards** that only fire under conditions tests can't reproduce, such as a memory allocation failure on a 256 KB board

### When to write a test instead

- Business logic gets a test, never a pragma.
- Code a fake or stub can reach gets the fake: inject the dependency and test it.
- When unsure, leave the line uncovered and say so in the pull request, and a reviewer helps decide.

### Browsing coverage

After a test run, the HTML report shows which lines ran:

```bash
python -m coverage html
open htmlcov/index.html
```

Covered lines show green and missed lines red.  `htmlcov/` is gitignored.

## Lint

`python scripts/run.py lint` runs Ruff, then the `chumicro-checks` rules, and stops at the first tool that fails.

**Ruff** enforces:

| Rule set | What it catches |
|---|---|
| `E`: pycodestyle errors | Whitespace, indentation, line length, blank lines |
| `F`: pyflakes | Unused imports, undefined names, redefined variables |
| `I`: isort | Import ordering (stdlib → third-party → local, alphabetized) |
| `B`: bugbear | Common pitfalls like mutable default arguments, bare `except:`, unused loop variables |
| `UP`: pyupgrade | Modernization: replaces old syntax with newer Python equivalents |
| `TID252`: flake8-tidy-imports | Relative imports in device code, as [Imports](#imports) describes |

**`chumicro-checks`** holds the project's own `CHU` rules.  Each rule's module docstring in [`workbench/checks/src/chumicro_checks/rules/`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/checks/src/chumicro_checks/rules) documents it in full.  The rules a contributor meets most:

- **`CHU001`** enforces the [Naming](#naming) table.
- **`CHU002` to `CHU005`** catch whitespace that diffs noisily.  An editor's trim-on-save fixes all four.

  | Rule | What it catches |
  |---|---|
  | `CHU002` | File does not end with exactly one newline |
  | `CHU003` | More than two consecutive blank lines inside a file |
  | `CHU004` | Trailing whitespace on any line |
  | `CHU005` | Blank line immediately after a block opener (`def`, `class`, `if:`, `for:`, etc.) |

- **`CHU006`** flags mono-repo references in the publishable `src/` trees: `libraries/*/src/`, `workbench/*/src/`, and `support/*/src/`.  Those trees ship to PyPI and CircuitPython-bundle users, who have no `plans/` directory and no `scripts/run.py`.  It flags `Decision NNNN` and `ADR NNNN` pointers, `plans/...md` paths, `scripts/run.py`, *chumicro mono-repo* framing, and a bare `run.py`, the workbench template's command runner.  `chumicro_workspace` generates that `run.py` and may name it.  Everywhere else, name the installable CLI, such as `chumicro-deploy` or `chumicro-workspace`, and write the explanation inline instead of linking.  Suppress with `# noqa: CHU006`, or `<!-- noqa: CHU006 -->` in Markdown, only where the reference carries the meaning.
- **`CHU007`** keeps workbench packages from importing library packages ([Decision 0052](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0052-workbench-no-library-imports.md)).  It flags any `import chumicro_<libname>` under `workbench/*/src/` that names a `libraries/` package.  Workbench tools ship to laptops, and a library's CPython support exists for testing, so a workbench tool uses a PyPI equivalent such as `pyserial`, `msgpack`, or `ruamel.yaml`.  Device-side code embedded as bytes stays unscanned.
- **`CHU033`** bans `async`, as [Cooperative concurrency](#cooperative-concurrency) describes.
- **`CHU038`** keeps examples and demos running, as [Examples and demos](#examples-and-demos) describes.
- **`CHU039`** checks the `python` listings in the docs, as [Documentation tone](#documentation-tone) describes.

Each lint message names what to fix and why.
