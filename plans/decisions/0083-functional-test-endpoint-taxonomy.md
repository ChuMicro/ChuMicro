# Decision 0083: Functional tests use controlled endpoints by default

Status: `accepted`
Date: `2026-05-24`
Summary: Functional tests default to Category 1 (controlled endpoint = host fixture); Category 2 (public endpoint) is an exception for interop verification; self-loopback is not a category.
Related: Decision [0082](0082-test-harness-as-infrastructure-library.md) (the device-side `chumicro_test_harness.network` helper that brings wifi up for both sides), Decision [0043](0043-chumicro-sockets-udp.md) (already uses a host-side echo fixture — the original Category 1 instance), Decision [0058](0058-test-skips-must-be-loud.md) (skip semantics for when an endpoint is unreachable), `plans/workstreams/test-harness-promotion-and-network-helper.md` (the implementation roster that aligns existing tests).

## Context

Functional tests for networking libraries today follow a mix of patterns that were never deliberately chosen:

- `mqtt/test_real_broker.py` and `sockets/test_real_udp.py` use **host-side controlled endpoints** — Mosquitto and a UDP echo server spawned by the conftest.  Both sides of the protocol are observable; the test asserts on broker state and on what the client received.
- `requests/test_real_get.py` and `ntp/test_real_ntp.py` use **public endpoints** — `example.com` and `pool.ntp.org`.  Only the client side is observable; the test asserts on protocol-level interop.
- `http_server/test_real_serve.py` uses **self-loopback** — same board runs both server and client, traffic flows through the LAN's router back to the device's own IP.  This depends on router hairpinning, which most consumer routers refuse, and the test fails on the Pi Pico W defaults (2026-05-24 bake).

There is no documented default, no criterion for when each shape is right, and new networking libraries inherit whichever pattern the scaffold seeded most recently.  The self-loopback variant has now demonstrated a concrete failure mode (hairpinning).  The taxonomy needs to be named, with a default, before the test-harness-promotion workstream rewrites the test bodies.

## Decision

**Functional tests default to a controlled endpoint — Category 1.  Public endpoints (Category 2) are an exception, justified only when interop with a real public service is what the test verifies and a host fixture would be tautological.  Two-board orchestration (Category 3) is future work.**

### Category 1 — Controlled endpoint (default)

One side of the protocol is the board, the other is a fixture the test owns.  When the library is a client (`mqtt`, `requests`, `ntp`, `websockets`, `sockets`-as-client), the fixture is a host-side server: Mosquitto subprocess, stdlib `http.server`, in-process SNTP responder, UDP / TCP echo.  When the library is a server (`http_server`, future `websockets`-server tests), the fixture is a host-side client: stdlib `socket` + hand-rolled request bytes, or `httpx` / `websockets` from PyPI.

Both sides observable.  Test asserts on server-side state (what the broker received, which subscriptions were placed, which retain bits set) as well as client-side outcome.  Reproducible; no public network dependency; deterministic timing.

### Category 2 — Public endpoint (exception)

The board talks to a real public service.  Acceptable when:

1. **Interop is the point.**  The test verifies that the library's wire-format implementation interoperates with a deployed real service, not just with our own server fixture.  A controlled NTP responder is our own SNTP encoder talking to our own SNTP decoder — green doesn't prove interop with `pool.ntp.org`.
2. **The endpoint is stable and well-known.**  `example.com`, `pool.ntp.org`, `www.google.com`.  Not third-party staging environments.
3. **The assertion is bounded.**  "Status 200 and a non-empty body" rather than "the exact bytes we sent come back."  We don't control what the public endpoint returns.

Category 2 tests must use `chumicro_test_harness.skip(reason)` when the endpoint is unreachable (Decision 0058 — skips must be loud).  Network flakiness is a known cost; a flaky network test that doesn't skip cleanly is a real defect.

### Category 3 — Two-board orchestration (deferred)

Two boards run paired test code, both deployed by the same pytest session.  Full-duplex protocol verification with both ends as runtime-portable code we own.  Requires `chumicro-pytest-device` to deploy to N boards in parallel, route per-board stdout / serial back to pytest, and synchronize a start-handshake between the two sides.  This is real infrastructure we don't have; deferred until a specific test asks for it.  Until then, the `ChuMicro-Workspace-Template/examples/two_board_handshake/` example is the manual-deploy reference shape.

### Self-loopback is not a category

A board talking to its own LAN IP requires router hairpinning, which is firmware-dependent (Pi Pico W's lwIP stack routes the SYN out the radio; consumer APs typically don't reflect the packet back to the originating STA).  The reproducibility of the test depends on infrastructure we don't control.  When the library is a server, the right Category 1 shape is *host-driver-as-client* — the board runs the server, the host runs a stdlib socket client.  No loopback through the router; no hairpinning question.

### Host-side fixtures live with `chumicro_pytest_device`

The fixture machinery for Category 1 (start Mosquitto, start an HTTP server, start an SNTP responder) lives at `workbench/pytest-device/src/chumicro_pytest_device/fixtures/`.  The package already owns device-session orchestration, devices.yml, and transport — host-side fixtures fit the same mental model.  No new package; the new submodule is the home.

The board side of a Category 1 test imports `chumicro_test_harness.network` (Decision 0082) for wifi bring-up + runtime-config and the package under test from its own `src/`.  No `chumicro_<other-package>` imports in the test body.

## Rejected

- **Promote self-loopback as a documented category.**  Reproducibility on consumer routers is too variable.  Test infrastructure that fails ~half the time on a deployed test bed is worse than no test, because passes are uninformative ("did we test interop, or did we test the AP?").  When the library is a server, host-driver-as-client achieves the same coverage with deterministic behaviour.
- **Mock the network entirely.**  That is a unit test (and they already exist at `libraries/<name>/tests/`).  Functional tests must exercise real I/O — the whole point is to catch the bugs unit tests can't see.
- **One workstream per library to align tests.**  Five small workstreams duplicate the migration roster.  The existing `plans/workstreams/test-harness-promotion-and-network-helper.md` covers all five tests' Phase 2 rewrite — endpoint-taxonomy alignment folds into that phase rather than spinning up parallel workstreams.
- **A new top-level package for host fixtures.**  `workbench/pytest-device` already owns the test runner that consumes them; splitting fixtures into a sibling package multiplies release cycles for what is one mental model.
- **Mandate Category 1 for `requests` and `ntp`.**  A controlled NTP responder is our own encoder talking to our own decoder; green proves nothing about whether `chumicro_ntp` interoperates with the real SNTP universe.  Same shape for HTTP against `example.com`.  These two stay Category 2 with a clearly documented rationale per test.

## Consequences

- The `new-library` scaffold seeds a Category 1 conftest fixture for any new networking library — stdlib `http.server` for an HTTP-client library, in-process echo for a socket library, etc.  Scaffold templates carry the boilerplate so a fresh library starts with the right shape.
- `audit-library`'s §7 (project-policy compliance) gains a check: networking-library functional tests that match Category-2 shape (no host fixture, target string is a public hostname) earn a finding unless the file docstring opens with a `Category 2 — <reason>` declaration.  This is the mechanism that prevents future drift; the lint is the safety net for the rule.
- Each existing networking-library `functional_tests/test_real_*.py` opens with a one-line category declaration in its module docstring (`"""... Category 1 — host-side Mosquitto fixture."""`).  The declaration is what `audit-library`'s lint reads.
- The `test-harness-promotion-and-network-helper.md` workstream's Phase 2 absorbs the endpoint-taxonomy alignment for the five existing networking-library functional tests.  `http_server/test_real_serve.py` becomes Category 1 (host-driver-as-client), `requests` + `ntp` stay Category 2 with documented rationale, `mqtt` + `sockets` already match Category 1 and add the module-docstring declaration only.
- Two-board orchestration (Category 3) is a future workstream that lands when a real test asks for it.  Until then, the manual-deploy `two_board_handshake` example carries the shape.
- `workbench/pytest-device/src/chumicro_pytest_device/fixtures/` is the documented home for host-side endpoint fixtures.  The existing per-library `functional_tests/conftest.py` fixtures (Mosquitto in `mqtt/`, UDP echo in `sockets/`) move there as part of the workstream — one canonical Mosquitto fixture, one canonical echo fixture, imported by every conftest that needs them.
