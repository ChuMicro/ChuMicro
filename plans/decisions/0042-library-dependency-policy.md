# Decision 0042: Library dependency policy

Status: `proposed` — draft awaiting post-Tier-A review (see "Pending decision" note below)
Date: `2026-04-27`
Related: [Decision 0010](0010-injection-and-fakes.md) (constructor injection + fakes), [Decision 0014](0014-tick-based-runner.md) (runner pattern), [Decision 0031](0031-chumicro-sockets.md) (sockets), [Decision 0040](0040-chumicro-requests.md) (requests + factory helper pattern), `plans/workstreams/library-pipeline.md` §"Dependency policy".

> **Pending decision (2026-04-27).** This file captures the analysis and a
> proposed split, but the call will be made *after* the Tier-A libraries
> (`chumicro-logging`, `chumicro-events`, `chumicro-ntp`) land and we have
> experience operating under the proposed rules. Do not treat the rules
> below as binding for libraries shipping in the meantime — when in
> doubt for those three, mirror the existing `chumicro-requests` pattern
> (hard dep + factory helper + explicit constructor parameter) for any
> *core infrastructure* deps and skip declaring any *decoration* deps.

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
3. Libraries expose hooks where decoration would naturally attach:
   - `on_state_change=callback` keyword arguments (already the pattern in
     wifi, mqtt, requests).
   - An optional `logger=None` constructor parameter accepting any
     callable with the shape `logger(level: str, message: str) -> None`.
     Default: a no-op. The application bridges this to whatever logging
     backend it wants — `chumicro-logging`, stdlib `logging`, `print`.
4. The decoration libraries themselves consume those hooks — the
   *application* wires them up:

   ```python
   from chumicro_events import EventBus
   bus = EventBus()
   wifi.on_state_change = bus.publisher("wifi.state")
   mqtt.on_state_change = bus.publisher("mqtt.state")
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

- **Hard deps cannot be opted out of without forking.** A user who
  wants `chumicro-mqtt` over a custom transport still gets
  `chumicro-sockets` installed even if they pass their own factory.
  Acceptable cost — `chumicro-sockets` is small and harmless when
  unused.
- **The decoration libraries cannot ergonomically wire themselves
  in.** Apps must do the wiring. Mitigated by: (a) `chumicro-presence`
  ships a one-line `presence.bind(wifi=..., mqtt=...)` that does the
  callback wiring centrally; (b) example apps in
  `examples/` show the canonical wiring; (c) the workspace template
  bundles a "wired-up" starter so beginners don't write the
  boilerplate.

### Audit checklist (on next release-prep cycle)

- [ ] `chumicro-mqtt` `pyproject.toml`: hard deps on `chumicro-sockets`,
      `chumicro-timing`, `chumicro-runner`. Confirm no `chumicro-logging`
      / `chumicro-events` deps.
- [ ] `chumicro-requests`: same.
- [ ] `chumicro-http-server`: same.
- [ ] `chumicro-wifi`, `chumicro-kvstore`, `chumicro-config`: no
      decoration deps.
- [ ] `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`:
      each ships a `chumicro_sockets_factory(...)` helper or
      equivalent.
- [ ] All libraries expose an `on_state_change` callback or
      equivalent hook shape.
- [ ] `chumicro-logging` (when shipped): no chumicro deps.
- [ ] `chumicro-events` (when shipped): no chumicro deps.
- [ ] `chumicro-presence` (when shipped): hard deps on the *output*
      libraries it composes (`chumicro-pixels`, `chumicro-input`,
      `chumicro-tone` if any wired); **no** dep on `chumicro-events`
      (it accepts an event source via its constructor); **no** dep
      on `chumicro-logging`.
