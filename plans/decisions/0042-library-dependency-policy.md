# Decision 0042: Library dependency policy

Status: `accepted`
Date: `2026-04-27`
Related: [Decision 0010](0010-library-testability.md) (constructor injection + fakes), [Decision 0014](0014-runner-pattern.md) (runner pattern), [Decision 0031](0031-chumicro-sockets.md) (sockets), [Decision 0040](0040-chumicro-requests.md) (requests + factory helper pattern), `plans/workstreams/library-pipeline.md` §"Dependency policy".

## Context

Today every chumicro service takes its dependencies via constructor injection
(e.g. `MQTTClient(sockets=…)`, `HttpClient(connection_factory=…)`). Clean
for testing and substitution, but creates an onboarding cliff:

> *"What sockets lib? You mean I have to download chumicro-sockets too?
> Why didn't anyone tell me?"*

`chumicro-requests` (Decision 0040) already established a workable middle
path: declare `chumicro-sockets` as a hard dep in `pyproject.toml`, ship
a `chumicro_sockets_factory(radio=...)` one-liner that returns the
canonical factory, and keep the constructor parameter explicit. One
`pip install chumicro-requests` brings everything in; one line wires the
default; one parameter swaps it out.

Several Tier-A libraries are about to land (`chumicro-logging`,
`chumicro-events`, `chumicro-ntp`) plus a future device-feedback layer
(`chumicro-presence`). Three of those (logging, events, presence) have a
property that core infrastructure does not: they are **decoration** — the
library they decorate functions perfectly without them. We need to settle
the dep policy *before* the next batch lands so each new library starts
under the right rules and the `pyproject.toml` audit happens once.

## Decision

Two classes of dependency, each with its own rule.

### Class 1 — core infrastructure: hard dep + factory helper

A library is *core infrastructure* if a downstream library cannot function
without it. Today that is `chumicro-sockets`, `chumicro-runner`,
`chumicro-timing`. (`chumicro-compat` is also infrastructure but is empty
unless polyfills are needed.)

**Rule:**

1. The downstream library declares the core dep in `[project].dependencies`
   in its `pyproject.toml`. A single `pip install chumicro-<name>`
   installs the whole stack.
2. The downstream library exposes a factory helper alongside its main
   constructor — `chumicro_<infra>_factory(...)` — that returns the
   canonical wiring with sensible defaults. (Pattern established by
   `chumicro_requests.chumicro_sockets_factory`.)
3. The downstream library's constructor takes the dependency as an
   explicit keyword argument. **No auto-defaulting to `chumicro-sockets`
   inside the constructor.** Explicit > implicit; the helper is one
   line; the wiring is readable.
4. Tests inject fakes from the upstream library's `testing` submodule
   (Decision 0010). They never accidentally hit the real
   factory.

Example (the `chumicro-requests` shape, now the standard):

```python
from chumicro_requests import HttpClient, chumicro_sockets_factory
from chumicro_wifi import wifi

client = HttpClient(connection_factory=chumicro_sockets_factory(radio=wifi.adapter.radio))
```

Existing libraries that already match this pattern (and need no change):
`chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`. Audit on next
release-prep cycle to confirm.

#### Sub-rule — factory helpers live in a separate submodule

The hard dep is unavoidable at install-time (`pip install chumicro-mqtt`
brings `chumicro-sockets` into the host venv whether or not the user
calls the helper).  The dep **is** avoidable at *deploy-time* — what
ships to the board — if the helper is structured so the AST-walking
import-graph deploy (Decision 0029) doesn't follow it.

**Rule:** the `chumicro_<infra>_factory(...)` helper lives in its own submodule (e.g. `chumicro_requests/sockets_factory.py`).  The library's `__init__.py` and core implementation modules **must not import the helper**.  Users opt in to the default wiring by importing the submodule explicitly (`from chumicro_requests.sockets_factory import chumicro_sockets_factory`); users supplying a custom transport never reference the submodule.

The AST-walking import-graph deploy (Decision 0029) starts from the user's app.  If the app never imports `chumicro_requests.sockets_factory`, the walker never enters that module, so the `import chumicro_sockets` inside it is never observed, and `chumicro_sockets` is never shipped to the device.  Lazy imports inside `client.py` (or anything `__init__.py` pulls in) do NOT give the user this opt-out — the walker still sees them when it analyzes `client.py`.

#### What the rule does not solve

`pip install chumicro-mqtt` still installs `chumicro-sockets` into the
host venv as a transitive dep.  That is install-time, not deploy-time.
For users who want to fully avoid the dep on disk too (rare — chumicro
libraries are tiny), the escape hatch is `pip install --no-deps
chumicro-mqtt`, which we deliberately do not document.  The
deploy-time opt-out covers the only audience that actually cares
(memory-constrained boards).

### Class 2 — decoration / observability: callbacks only, never imported

A library is *decoration* if the library it observes functions perfectly
when the decoration is absent. Today that is `chumicro-logging`,
`chumicro-events`, and the future `chumicro-presence`.

**Rule:**

1. **No chumicro library declares `chumicro-logging`, `chumicro-events`, or
   `chumicro-presence` in `[project].dependencies`.** Ever.
2. **No chumicro library `import`s any of them.** Not at module level,
   not inside functions, not behind `try`/`except ImportError`. The
   absence must be invisible at runtime.
3. Libraries expose hooks where decoration would naturally attach.  Two shapes are in use today:
   - **Registration method** — `wifi.on_state_change(callback)` appends to an internal list; every registered callback fires on every state transition as `callback(old_state, new_state)`.
   - **Replaceable attribute** — `mqtt.on_connect = callback` (and the rest of the `on_*` family on `MQTTClient`); the service invokes the single slotted callback with the arity that callback's docs specify.

   Plus an optional `logger=None` constructor parameter accepting any
   callable with the shape `logger(level: str, message: str) -> None`.
   Default: a no-op. The application bridges this to whatever logging
   backend it wants — `chumicro-logging`, stdlib `logging`, `print`.
4. The decoration libraries themselves consume those hooks — the
   *application* wires them up.  `bus.publisher(topic)` returns a `*args`-accepting closure that adapts to either shape without an inline adapter:

   ```python
   from chumicro_events import EventBus
   bus = EventBus()
   wifi.on_state_change(bus.publisher("wifi.state"))    # registration-method
   mqtt.on_connect = bus.publisher("mqtt.connected")    # replaceable-attribute
   ```

   This keeps the dep graph a strict DAG: `presence → events → (nothing
   chumicro)`; `logging → (nothing chumicro)`; everything else
   independent of these three.

### Naming convention for factory helpers

When library `A` declares `B` as a hard dep and ships a default-wiring
helper, the helper is named `chumicro_<B>_factory(...)` and lives in
`A`'s public exports. Example: `chumicro_requests.chumicro_sockets_factory`.

When `B` itself ships a "default everything" entry point (e.g. a
no-arg constructor that works on the current runtime with whatever
hardware is present), it is named `default_<thing>(...)` in `B`'s
public exports — e.g. `chumicro_wifi.default_adapter()`. This is
the upstream-side counterpart to the downstream-side factory helper.

## Consequences

### Positive

- **Single-command install.** `pip install chumicro-mqtt` brings the
  stack. No more "wait, what else?" surprise.
- **Decoration stays optional.** Apps that don't want events / logging
  / presence don't pay for them in flash, RAM, import time, or
  conceptual overhead. A user shipping a tiny sensor on a Pi Pico can
  ignore those three libraries entirely and nothing breaks.
- **Test isolation preserved.** Constructor injection still required;
  fakes still mandatory; the factory helper is bypassed in tests by
  construction.
- **Dep graph is a DAG.** No cycles possible — decoration is at the
  top, infrastructure at the bottom, services in the middle.

### Negative

- **Hard deps still install on the host venv.**  A user who wants
  `chumicro-mqtt` over a custom transport gets `chumicro-sockets`
  installed in their CPython venv even if they pass their own
  factory.  Acceptable cost — `chumicro-sockets` is small and
  harmless when unused.  The deploy-time opt-out (factory helper in
  a separate submodule, see sub-rule above) ensures it does **not**
  ship to the device when unused, which is the case that matters
  for memory-constrained boards.
- **The decoration libraries cannot ergonomically wire themselves
  in.** Apps must do the wiring. Mitigated by: (a) `chumicro-presence`
  ships a one-line `presence.bind(wifi=..., mqtt=...)` that does the
  callback wiring centrally; (b) example apps in
  `examples/` show the canonical wiring; (c) the workspace template
  bundles a "wired-up" starter so beginners don't write the
  boilerplate.

The implementation punch-list (auditing existing libraries' `pyproject.toml` deps and factory-helper submodule placement, plus the open `chumicro-requests` follow-up to move `chumicro_sockets_factory` from `client.py` into its own `sockets_factory.py`) lives in `plans/next-up.md`, not here.
