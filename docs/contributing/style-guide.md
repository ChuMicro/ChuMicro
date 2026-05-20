# Style Guide

<img src="../../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

This is the definitive reference for code style in the ChuMicro workspace.  All code — library, infrastructure, and tests — follows these conventions unless explicitly noted.

<br clear="left">

The linter (`python scripts/run.py lint`) enforces most of these automatically. If lint passes, you're almost certainly fine. This guide explains what the rules are, why they exist, and what to do when the linter flags something.

## Baseline

We follow [PEP 8](https://peps.python.org/pep-0008/), the standard Python style guide, with a **100-character line limit** (configured in `pyproject.toml`). This is enforced automatically by [Ruff](https://docs.astral.sh/ruff/), a fast Python linter. You don't need to memorize PEP 8 — Ruff tells you when something is off.

## Naming

We use descriptive names so everyone can read the code without extra context. The linter catches common abbreviations and suggests the descriptive name for you.

| Rule | Example | Enforced by |
|---|---|---|
| No single-letter variables (except `_` and for-loop targets) | `index`, not `i` in assignments; `for i in range(10)` is fine | `CHU001` linter |
| Abbreviations to expand | `env` → `environment`; `buf` → `buffer`; `src` → `source`; `cmd` → `command`; `msg` → `message`; `err` → `error`; `ref` → `reference`; `addr` → `address`; `exc` → `exception`; `exec` → `execute` | `CHU001` linter |
| Same expansions apply as suffixes | `base_ref` → `base_reference`; `build_env` → `build_environment` | `CHU001` linter |
| Short-but-complete words are fine | `dir`, `key`, `tag`, `raw`, `pin`, `led`, `ok`, `end`, `args`, `config` | — |
| For-loop targets are exempt | `for i in range(10)`, `for k, v in items()` | — |
| Suppress with `# noqa: CHU001` | Only when matching an upstream API that you cannot rename | — |

**Why:** We optimize for readability across experience levels — full words over abbreviations. Python's common abbreviations (`msg`, `err`, `exc`, `buf`) are instantly familiar to experienced developers but not self-explanatory to everyone. Newcomers, multilingual developers working across multiple languages, and non-native English speakers don't share that background — `exc` isn't obviously "exception" if you haven't seen it before. The full words save every future reader a mental lookup. The linter handles this automatically, so it doesn't cost you time. We know it feels different from other Python projects — that's intentional. ([Decision 0022](../../plans/decisions/0022-naming-conventions.md))

## Type annotations

Python type annotations tell readers (and tools) what types a function accepts and returns. We use them on all function and method signatures. They cost zero runtime overhead on embedded boards — both CircuitPython and MicroPython parse annotations but strip them at compile time.

Do not import `typing` in library code — the module doesn't exist on CircuitPython or MicroPython. Use the modern built-in syntax instead:

```python
# ✅ Works on all runtimes — PEP 604 / PEP 585 syntax
def read(self, timeout: int | None = None) -> bytes | None: ...
def process(self, items: list[int]) -> dict[str, int]: ...

# ❌ Requires typing module — fails on embedded runtimes
from typing import Optional, List
def read(self, timeout: Optional[int] = None) -> Optional[bytes]: ...
```

Infrastructure code (`scripts/`) may use `typing` imports since it runs only on CPython. Most of `support/` is also CPython-only, **except `support/test_harness/`** which runs on all three runtimes — treat it like library code.

([Decision 0021](../../plans/decisions/0021-docstring-type-policy.md))

## Imports

Code that runs on a device — `libraries/*/src/`, `support/test_harness/` — must use **absolute imports only**. Relative imports break CircuitPython RAM-mode deploys.

```python
# ✅ Works on all runtimes
from chumicro_timing.ticks import ticks_ms, ticks_diff
from chumicro_timing.heartbeat import Heartbeat

# ❌ Breaks CircuitPython RAM-mode
from .ticks import ticks_ms, ticks_diff
from .heartbeat import Heartbeat
```

**Why:** CircuitPython RAM mode assembles library modules as class-as-module stubs and `exec()`'s them inside the raw REPL. The namespace passed to `exec()` has no `__package__` attribute, so Python can't resolve a leading `.` — `from .foo import bar` raises `ImportError`. Flash mode works fine because files land on the device filesystem and get a real `__package__` when imported, but any module whose RAM-mode path is exercised (which includes every published library) has to work in both modes.

Host-only code can use either style:

- **`workbench/*/src/`** — relative imports are fine. These packages run on CPython only and are never `exec()`'d through the raw REPL. `chumicro-deploy` uses relative intra-package imports throughout.
- **`scripts/`** — either style; not device-bound.
- **Tests** — either style; [Decision 0009](../../plans/decisions/0009-per-library-test-runs.md) lifted the earlier absolute-only restriction.

Cross-package imports between publishable libraries stay absolute regardless of where they live — `from chumicro_timing import ticks` inside `chumicro_runner` is correct and expected.

**Enforcement.** The rule is wired to ruff TID252 (`flake8-tidy-imports.ban-relative-imports`) in `pyproject.toml`. The `[tool.ruff.lint.per-file-ignores]` table relaxes it for `workbench/**`, `scripts/**`, `**/tests/**`, `**/functional_tests/**`, and `**/examples/**` — those trees run on CPython or stand alone outside any package, so relative imports either work fine or are syntactically impossible. A regression scenario in `scripts/audit_gates.py` confirms the gate fires for `libraries/*/src/` + `support/test_harness/src/` and stays silent in the relaxed trees.

## Docstrings

Every public function, method, and class needs a docstring. We use [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings): types go on annotations, descriptions go in docstrings. This avoids writing the type twice.

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

- **`Args:`** — `name: description` (no type in parens — it's already on the signature)
- **`Returns:`** — description only (no `type:` prefix)
- **`Raises:`** — `ExceptionType: description`

The docs build fails on [griffe](https://mkdocstrings.github.io/griffe/) warnings about missing or malformed sections, so you'll know right away if something needs fixing.

([Decision 0021](../../plans/decisions/0021-docstring-type-policy.md))

## Documentation tone

Style for READMEs, library guides, and contributing docs (not docstrings — those are above). These rules apply to the root README, every library's README and `docs/guide.md`, every workbench README, and contributing pages.

- **Anchor on a concrete user-visible promise, not an abstract design principle.** *"Keep a status LED blinking through a slow network call"* beats *"transparent state matters more than syntactic concurrency."* First-time readers don't share the vocabulary; they share the LED. Design philosophy belongs in ADRs, not in the project's top-level README.
- **No second-person ("you" / "your") in third-person documentation.** *"A microcontroller running anything beyond blink has to handle slow operations without freezing"* beats *"you're building something on a CircuitPython board."* Second-person presumes the reader's situation. READMEs land on PyPI homepages, GitHub search results, and blog links — they need to be welcoming without narrating at the reader. (Code-block comments and step-by-step tutorials are different — imperative is fine: *"install the package."*) Quick check: grep the draft for `\byou\b` / `\byour\b` / `\bwe\b`.
- **Don't bury the substantive matrix behind a folder-README link.** The library matrix and workbench matrix belong on the root README, not as a one-line `[Libraries](libraries/)` link. Most visitors only see one URL — the root. Folder-READMEs reinforce with deeper context (dependency graph, problem-driven selection); they're not the *only* home for the matrix.
- **Code, prose, and any visual must tell the same story.** If the hero promises an LED, the code shows `led.value = not led.value`, not `print()`. If the hero promises composition, the code shows multiple services on one runner. If a visual is added, it depicts what the prose says. When in doubt, skip the visual — prose + code can carry the load alone.
- **Don't redirect to sibling packages from a published package's docs.** A publishable package's public surface (README, guide, module docstrings) should describe what THIS package does, not what it doesn't do. Phrasings like *"This package doesn't do X — use `other-package` for X instead"* / *"For X, lives one level up in Y"* leak mono-repo awareness into a PyPI-facing artefact, and relative paths like `../workspace/` only resolve in the mono-repo docs site — they break PyPI README rendering. Cross-tool positioning that describes in-scope relationships is fine; redirecting readers to a sibling to fill a gap isn't.
- **Feature bullets are consumer-first and concrete.** Lead with what the user can DO (*"Bring your own socket, your own clock"*), not the implementation pattern (*"Constructor-injected duck-typed I/O dependencies"*). Name concrete things — actual library class names, stdlib alternatives, production scenarios — not abstractions like *"valid producer"* / *"any object that satisfies the contract"*. Acknowledge defaults first, then the swap-out path. No type-system jargon (`duck-typed`, `Protocol`, `structural typing`), no method-name lists in the pitch, no test-fake framing (production swap-ins belong; test fakes don't).

## Phrase bans

These bans apply to all writing in the repo: code comments, docstrings, markdown docs, and ADR bodies.  Tone guidance, not lints (except where noted at the end).

Write in sentences. Don't use em-dashes, semicolons, or arrows as shortcuts that paper over missing connective tissue. If two ideas are linked, write them as two sentences or join with a comma and a connector.

Cut AI-tic phrases. They sound non-human, drop information, and make prose harder to skim. The fix is usually structural, not vocabulary. When you write "the X promise" or "the X pattern", name X concretely in the same sentence. When you catch yourself writing one, rewrite the sentence to demonstrate the property concretely instead of asserting it abstractly.

**Degraded prose is rewritten, not trimmed again.** A passage rotted by repeated subtractive edits is not fixed by removing another word. That only makes it shorter and no clearer. Discard it and rewrite from a fresh read of what the thing is and why it exists. Several skills apply this rule in their scope: [`audit-comments`](../../.github/skills/audit-comments/SKILL.md) for code comments, [`audit-docs`](../../.github/skills/audit-docs/SKILL.md) for user-facing markdown, [`audit-skill`](../../.github/skills/audit-skill/SKILL.md) for SKILL.md bodies, and the in-place-edit rule in [`../../plans/decisions/README.md`](../../plans/decisions/README.md) for ADR bodies.

### Specific phrase bans

- Avoid "the canonical X" framing. Often "the X" or "the standard X" works as well, and frequently the bare phrase reads better still. Keep canonical encoding, canonical form, and canonical path. These are real technical terms with no fluff substitute.
- Avoid "the one / single / sole X that…" as a definition opener. It is the same tic as canonical X. Say plainly what X does. Legitimate invariant prose like "the single owner of the staging path" stays. Tone guidance, not a lint.
- Use "the X" only when X is an established singular referent the reader already has. Use "a X" or "an X" for forward references or categories the reader has not acquired yet. Use bare X for systems and brand names where the article is decoration. For example, write "ESP32-S2 firmware" rather than "the ESP32-S2 firmware". Two nouns in one sentence often need different articles. Indefinite articles are not clinical. Reaching for "the" everywhere to sound terse is a frequent miss.
- Don't open sentences with "this is the" or "this is a" to point back at what was just said. Restate the subject directly, or drop the meta sentence entirely. For example, instead of "Run preflight before every commit. This is the rule the recovery skill enforces", write "The recovery skill enforces preflight before every commit".
- Drop adjectives that don't carry information: comprehensive, robust, seamlessly, cutting-edge, best-in-class. If you'd reach for "comprehensive", list what it covers. If you'd reach for "robust", name what it survives.
- Don't open sentences with filler like "It is worth noting that", "It should be noted that", "Note that", "Let's dive into", "Let's explore", or "In this section, we will". Start with the content.
- In publishable trees, don't cite CHU lint codes in prose. Name the rule's intent instead. For example, write "silent test skips" rather than "CHU009". Enforced by `CHU006`. The `# noqa: CHUNNN` directive is exempt.

## String formatting

Use f-strings for all string formatting. They're the most readable option and work identically across all three runtimes.

```python
# ✅
print(f"Found {count} items in {directory}")

# ❌
print("Found %d items in %s" % (count, directory))
print("Found {} items in {}".format(count, directory))
```

## Error handling

Do not silently swallow exceptions in host-side infrastructure (`scripts/`, `workbench/*/src/`, `support/` outside `test_harness`).  Every `except:` branch that chooses not to re-raise must log a visible message — a WARNING at minimum — so problems are noticed instead of hidden.

```python
# ✅ visible
try:
    subprocess.run(["xattr", "-cr", str(path)], check=True)
except FileNotFoundError:
    print("WARNING: xattr not found — skipping extended attribute removal")
except subprocess.CalledProcessError as exc:
    print(f"WARNING: xattr failed: {exc}")

# ❌ silent
try:
    subprocess.run(["xattr", "-cr", str(path)], check=True)
except Exception:
    pass
```

Library code (`libraries/*/src/`, `support/test_harness/`) is held to the same bar, with an added constraint: `print()` costs RAM and I/O time on devices, so prefer raising a specific exception type the caller can react to, or (where the library exposes a logging seam) emit through that.  Still never `except: pass`.

Catching an exception and re-raising a different one is fine — the chained `__cause__` preserves the origin.  Catching to translate errno strings into classifier-friendly message shapes (e.g. the transport's `CIRCUITPY drive not found or not writable` re-raise) is the pattern, not the exception.

## Subprocess binary resolution (host tools)

When a host-side tool shells out to an installable CLI binary (`mpremote`, `esptool`, `rshell`), resolve the binary relative to the running interpreter first, not by a bare name on `PATH`:

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

**Why:** PyCharm and VS Code launch test runs via the interpreter path without activating a shell, so `.venv/bin` is not on `PATH` even on a freshly-prepared workspace.  Resolving next to `sys.executable` makes `.venv/bin/<name>` the primary candidate; `shutil.which` handles system-wide installs and Windows `Scripts/<name>.exe`; the bare-name fallback preserves the subprocess-level error when nothing resolves.

Only the first element of the argv list changes — the rest of the command stays identical.  See `plans/patterns.md` "Subprocess binary resolution" for the worked example and rationale.

## Memory patterns (library code only)

Microcontrollers have limited RAM and no virtual memory. These patterns help library code run efficiently on constrained devices. **You don't need to apply these patterns from day one** — they matter most in performance-sensitive code. If you're writing your first library, focus on correctness first and optimize later.

They apply to **publishable library code under `libraries/`** and **`support/test_harness/`** — other infrastructure code (`scripts/`, rest of `support/`) runs on CPython and should use standard Python conventions.

| Pattern | Why |
|---|---|
| Pre-allocate `bytearray` in constructor, reuse with `readinto()` | Avoid repeated allocation |
| `memoryview` for slicing | Avoid copies |
| `const()` for numeric constants (import from `micropython`) | Compiler optimization |
| Cache frequently used attributes in local variables | Reduce attribute lookups in hot paths |
| Avoid dynamic string building in loops | GC pressure |

<details>
<summary>Examples (expand when you're ready to optimize)</summary>

### `const()` — compile-time constants

On MicroPython and CircuitPython, `const()` inlines the value at compile time instead of creating a runtime object. On CPython it doesn't exist, so every library that uses it needs a fallback:

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

Prefix internal constants with `_` (module-private). See `libraries/timing/src/chumicro_timing/ticks.py` for a real example.

### `memoryview` — zero-copy slicing

Normal `bytearray` slicing creates a copy every time. `memoryview` gives you a slice that points to the original data:

```python
# ❌ Each slice copies data
header = data[0:4]       # new bytearray allocated
payload = data[4:20]     # another new bytearray allocated

# ✅ Zero-copy — slices share the original buffer
view = memoryview(data)
header = view[0:4]       # no copy
payload = view[4:20]     # no copy
```

Combine with pre-allocated buffers for the full pattern:

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


## Coverage exclusions

Every library must meet the **85 %** coverage threshold configured in `pyproject.toml` (`fail_under = 85`). Sometimes code genuinely can't be exercised in CPython tests — runtime-specific branches, hardware fallbacks, or defensive guards that only fire on a real board. Mark those lines so they don't drag down your coverage.

### `# pragma: no cover` — exclude a line or block

Add the comment to any line, `if` branch, or function that can't be tested on CPython:

```python
# Single line
x = board.D5  # pragma: no cover

# Entire branch
if sys.implementation.name == "circuitpython":  # pragma: no cover
    import neopixel
else:
    from chumicro_compat.stubs import neopixel

# Entire function (put it on the def line)
def _reset_hardware() -> None:  # pragma: no cover
    """Hard-reset the I2C bus — only works on real hardware."""
    ...
```

### Common patterns that already work

The `const()` fallback pattern used across libraries is already fully covered (both the `try` and `except` branches run on CPython). You usually don't need `# pragma: no cover` for it.

### When to use it

- **Runtime-only imports** (`import board`, `import neopixel`, etc.)
- **Hardware-specific branches** (`if sys.platform == "rp2":`)
- **Defensive guards** that only fire under conditions impossible to reproduce in tests (e.g., memory allocation failure on a 256 KB MCU)

### When NOT to use it

- Don't use it to hide untested business logic — write a test instead.
- Don't use it on code that *could* be tested with a fake or stub. If you can inject the dependency and test it, do that.
- If you're unsure, leave it uncovered and note it in your PR. A reviewer can help decide.

### Browsing coverage

After running tests, you can see exactly which lines are covered:

```bash
python -m coverage html
open htmlcov/index.html
```

Covered lines show in green, missed lines in red. Much easier than reading line numbers from the terminal output. (`htmlcov/` is gitignored.)


## Lint

`python scripts/run.py lint` runs three tools back to back. If all three pass, your code is style-correct.

**Ruff** — a fast Python linter that enforces:

| Rule set | What it catches |
|---|---|
| `E` — pycodestyle errors | Whitespace, indentation, line length, blank lines |
| `F` — pyflakes | Unused imports, undefined names, redefined variables |
| `I` — isort | Import ordering (stdlib → third-party → local, alphabetized) |
| `B` — bugbear | Common pitfalls like mutable default arguments, bare `except:`, unused loop variables |
| `UP` — pyupgrade | Modernization — replaces old syntax with newer Python equivalents |

**`CHU001`** (in the [`chumicro-checks`](../../workbench/checks/) package) catches:

- Single-letter variable names in assignments, parameters, and function names (`x` → use a descriptive name, `e` → `error`)
- For-loop targets are exempt — `for i in range(10)` is fine
- Abbreviated names we prefer spelled out (`env` → `environment`, `buf` → `buffer`)
- Those same abbreviations as suffixes (`base_ref` → `base_reference`, `build_env` → `build_environment`)

**`CHU002`–`CHU005`** (same package) catch whitespace bugs that diff noisily and are easy to miss in review:

| Rule | What it catches |
|---|---|
| `CHU002` | File does not end with exactly one newline |
| `CHU003` | More than two consecutive blank lines inside a file |
| `CHU004` | Trailing whitespace on any line |
| `CHU005` | Blank line immediately after a block opener (`def`, `class`, `if:`, `for:`, etc.) |

**`CHU006`** (same package) catches mono-repo references that have leaked into publishable `src/` trees (`libraries/*/src/`, `workbench/*/src/`, `support/*/src/`).  Those trees ship to PyPI / CircuitPython-bundle consumers who have no `plans/` directory and no `scripts/run.py`.  Flagged shapes:

- `Decision NNNN` / `ADR NNNN` — ADR pointers; ADRs live in `plans/decisions/` and aren't shipped.
- `plans/...md` paths — the mono-repo planning tree.
- `scripts/run.py` — the mono-repo's developer command runner.
- Bare `run.py` (without the `scripts/` prefix) — the workspace-template's command-runner shim.  Only `chumicro_workspace` legitimately knows about it (the package generates the shim); everywhere else, name the installable CLI (`chumicro-deploy`, `chumicro-workspace`, etc.) instead.
- `chumicro mono-repo` / `chumicro monorepo` framing.

Inline the prose instead of cross-linking.  Suppress with `# noqa: CHU006` (or `<!-- noqa: CHU006 -->` in Markdown) only when the reference is genuinely load-bearing.

**`CHU007`** (same package) enforces Decision 0052: workbench packages do not import library packages.  Walks `workbench/*/src/` and flags any `import chumicro_<libname>` or `from chumicro_<libname>` where `<libname>` matches a `libraries/` package.  Workbench is host-only and ships to laptops; libraries target devices and their CPython compatibility exists for testing/dev, not as a production runtime.  Use third-party PyPI equivalents (`pyserial`, `msgpack`, `ruamel.yaml`, etc.).  Templates / on-device payloads embedded as bytes are not scanned — those run on the device and legitimately import library packages.  Suppress with `# noqa: CHU007` only on legitimate payload-style imports (rare).

If lint passes, your style is correct. You don't need to memorize any of this — the error messages tell you exactly what to fix and why.
