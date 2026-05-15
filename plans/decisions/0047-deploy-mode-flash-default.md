# Decision 0047: Default deploy mode is `flash`; libraries can flag themselves as flash-only

Status: `accepted`
Date: `2026-05-02`
Related: Decision 0029 (workspace shape), Decision 0033 (macOS CIRCUITPY
deploy hardening), Decision 0046 (workspace folder shape)

## Context

`chumicro-deploy` shipped with `DEFAULT_DEPLOY_MODE = "ram"`.  RAM mode
is fast-iteration friendly (CP: inline-exec, MP: `mpremote mount`) and
keeps edits off the board's flash, which is right for single-library
unit-style tests.  But it became the default for *everything*: project
deploys via `chumicro-workspace`, hardware-gated functional tests via
`chumicro-pytest-device`, examples run by hand.  Real consequences:

* RAM mode isn't a reflection of how production code runs.  A project
  that works in RAM mode but OOMs when imported from flash teaches the
  user nothing about whether their deploy actually ships.
* On smaller boards (Pi Pico W ~150 KB free heap; ESP32-S2 ~80 KB),
  heavy libraries (`chumicro-mqtt`, `chumicro-requests`,
  `chumicro-http-server`, `chumicro-websockets`) often OOM during
  import in RAM mode but fit fine when frozen in flash.  Users hit
  these silently and blame the library.
* The 2026-05-02 multi-persona audit named "RAM is the default" as a
  foot-gun: a beginner deploys `example_sensor` (boot counter
  persisted via `chumicro-kvstore`) in default mode and hits "boot
  counter doesn't increment" because RAM mode doesn't persist state
  across resets — and they have to learn a deploy mode they didn't
  ask about.

## Decision

**Two changes, landing together.**

### 1. Default flips: `flash` everywhere except unit-test-shape paths

* `chumicro_deploy.device.DEFAULT_DEPLOY_MODE`: `"ram"` → `"flash"`.
* All downstream defaults (`chumicro_deploy.config.default`,
  `chumicro_pytest_device._test_runner`, `chumicro_pytest_device.plugin`,
  mono-repo `devices.yml`, workspace template `_templates/devices.yml`):
  flip in lockstep.
* RAM mode stays available as an explicit opt-in: per-device
  `deploy_mode: ram` in `devices.yml`, `--deploy-mode ram` CLI flag,
  `Device(deploy_mode="ram")` constructor argument.
* Functional-test fixtures that genuinely benefit from RAM-mode
  iteration (single-library coverage, no persistence, no multi-library
  composition) opt in explicitly per-device or per-suite.

### 2. New library-side schema: `[tool.chumicro] requires_flash`

Each library's `pyproject.toml` may declare:

```toml
[tool.chumicro]
requires_flash = true   # absent / false (default): RAM mode is fine
```

Marked initially: `chumicro-mqtt`, `chumicro-requests`,
`chumicro-http-server`, `chumicro-websockets` — all four ship multi-KB
parsers + state machines + recv buffers that often OOM on small-board
RAM mode.  Lighter libraries (timing, runner, sockets, msgpack, config,
kvstore, ntp, wifi, compat, logging, events) leave the flag absent.

### 3. Pre-flight check + auto-switch with explanation

A RAM-mode deploy auto-switches to flash, with a human-readable
explanation, when the deploy graph carries a `requires_flash` library.
The `requires_flash` schema (§2) is the library-side input to that
check; the check itself proceeds in flash mode (no error, no aborted
run) and mutates only the *effective* mode for the run — the user's
`Device` is untouched.  `force_deploy_mode='ram'` (CLI:
`--force-deploy-mode ram`) is the escape hatch that skips it
(debugging the failure mode; explicit RAM iteration on a high-RAM
board; one-off probes).

The *mechanism* — originally a chumicro-deploy-only pre-flight — is
now a single resolver shared by `chumicro-deploy` and
`chumicro-pytest-device`, with an additional non-`.py`-data-file
trigger and a `devices.yml` flash-only device capability, so the
functional/on-device test path applies the same policy instead of a
divergent copy.  See [Decision 0068](0068-unified-deploy-mode-resolution.md)
for the unified resolution order and the supported deploy-mode matrix.

The auto-switch is the right default per the user's framing during
plan review: forcing the user to debug-and-retry with a different
flag is less helpful than handling the situation and explaining what
happened — same ergonomic shape as the existing recovery layer
(`chumicro_deploy.recovery`) that classifies transport failures and
walks users through fixes.

## Consequences

* **Beginners deploying `example_sensor`**: get flash mode by default,
  boot counter persists across resets, the example walkthrough's
  promise ("Reset the board and the boot counter increments") works
  out of the box.
* **`chumicro-pytest-device`**: hardware-gated functional tests run in
  flash mode by default — closer to production behavior.  Suites that
  want RAM mode opt in via the existing per-device or per-fixture
  mechanism.
* **Users with `deploy_mode: ram` in their existing `devices.yml`**:
  pre-flight auto-switches when a flagged library is in the graph;
  no breakage, just an explanation line.  RAM-mode-compatible
  graphs continue to honor the user's choice silently.
* **Library authors**: opt-in flag.  Most won't need it; the four
  heavy networked libraries get it now.  Future authors can flag
  themselves if a new library proves OOM-prone in RAM mode.
* **VERSION bumps**: chumicro-deploy minor (CLI/API behavior change),
  chumicro-pytest-device minor (default flip), chumicro-workspace
  minor (caller-side default behavior change).

## Alternatives considered

* **Refuse RAM mode for flagged libraries instead of auto-switching.**
  User push-back during plan review: forcing a debug-and-retry
  cycle is worse UX than handling the situation and explaining.
  Same shape as the recovery layer — classify, do the safe thing,
  tell the user what happened.
* **Numeric memory-footprint declaration (`min_free_ram_bytes`)**.
  Earlier draft of this ADR proposed per-library byte budgets +
  per-board RAM caps + summed-graph pre-flight.  Rejected as
  over-engineered: byte numbers are hard to measure accurately,
  brittle (vary by runtime + optimization), need maintenance as
  code evolves.  A binary `requires_flash` flag is library-author-
  authoritative and easy to keep accurate.
* **Board-class gating of `requires_flash`**.  Earlier consideration:
  the flag only fires on "small" boards (Pi Pico W, ESP32-S2),
  letting larger boards (ESP32-S3, ESP32-C6) try RAM mode anyway.
  Rejected: keeps the flag boolean (no board-class registry to
  maintain).  Power users on high-RAM boards who want RAM-mode
  testing of flagged libraries pass `force_deploy_mode='ram'`
  explicitly — friction is the point.
* **Keep RAM the default; just document the foot-gun more visibly.**
  Rejected: docs don't change behavior.  The audit's framing was
  that RAM-mode-as-default isn't a reflection of reality
  deployments — flipping the default is the structural fix.

## Migration

* No deprecation period (pre-publish per Decision 0046's hard-cutover
  precedent).  Users with `deploy_mode: ram` in `devices.yml` keep
  that override; pre-flight auto-switches when a flagged library is
  in the graph.
* Existing functional-test suites assuming RAM mode by default need
  per-suite override audits — most pass through unchanged because
  pytest-device's `--deploy-mode` flag still works; only
  the *unflagged* default changes from `ram` to `flash`.
