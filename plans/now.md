# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **HTTP-stack hardening pass** (post-beginner-onramp).  Closed three gaps the user flagged after the workstream landed: (1) `chumicro-http-server` was dragging all of `chumicro-requests` for ~125 lines of shared HTTP/1.1 primitives — decoupled, server-only deploy now ~half the size; (2) `chumicro-{requests,http_server,mqtt}` had empty `functional_tests/` directories — populated with real-network acceptance tests that auto-skip without `_test_creds`; (3) the two-thing examples hard-coded `WIFI_SSID`/`WIFI_PASSWORD` constants instead of using the standard `chumicro-config` pipeline — refactored to `runtime_config.msgpack`-first with constants as a fallback.  Plus two new second-step examples (`circuitpython_periodic_get.py` for requests, `circuitpython_telemetry.py` for mqtt) that match the same pattern.
- **Last shipped:** Decoupling commit `7fdab37` (drops `chumicro-requests` dep from `chumicro-http-server`; inlines `CaseInsensitiveDict` + `parse_charset` into `chumicro_http_server._wire`).  Functional tests + new examples + two-thing refactor pending in this same session — landing in a single follow-up commit after preflight.
- **In flight:** Functional tests + examples + two-thing refactor — preflight + commit are the next step.
- **Blocked on:** —
- **Last touched:** `libraries/http_server/{src,tests,README.md,pyproject.toml}` (decoupling commit), `libraries/{requests,http_server,mqtt}/functional_tests/{conftest.py,test_real_*.py}` (new), `libraries/{requests,mqtt}/examples/circuitpython_*.py` (new), `libraries/http_server/examples/circuitpython_two_thing_{server,sensor}.py` (refactored to chumicro-config pattern), `plans/decisions/0041-chumicro-http-server.md` §5 + Consequences (decoupling rationale).

---

## Architecture clarification (2026-04-27)

Question raised: should the transport libraries (`chumicro-{requests,http_server,mqtt}`) depend on `chumicro-config` so wifi creds are a "natural part of the test stack via chumicro-deploy"?

Answer: **no** — that would force them to also drag `chumicro-wifi`, breaking the layer purity (each transport library should work over any factory-supplied socket, including non-wifi transports).  Tests + examples that need creds use the standard application-layer wiring: `chumicro-config` + `chumicro-wifi` + `chumicro-{requests,http_server,mqtt}` together at the app boundary.  The libraries themselves stay transport-clean.

## What's actually committed-runnable now

* **Functional tests:** `libraries/{requests,http_server,mqtt}/functional_tests/test_real_*.py`.  Real network round-trips (HTTP GET against `example.com`, server bind + self-loopback, MQTT publish/subscribe round-trip against `test.mosquitto.org`).  Each test brings wifi up, drives a real socket, and verifies an LED-blink counter ticks during the in-flight operation (Decision 0014's runner-shape promise).  Skip silently when `_test_creds` is absent.  Conftest in each functional_tests/ materialises `_test_creds.py` from `.scratch/wifi-creds.toml` host-side; tests will run live once the deploy machinery picks the shim up alongside the test (open infra gap — see `plans/next-up.md`).
* **Examples that match the standard config pattern:** all four hardware-prefixed examples (`http_server/{two_thing_server,two_thing_sensor}`, `requests/periodic_get`, `mqtt/telemetry`) load wifi via `chumicro_config.load_runtime_config()` first, fall back to in-file constants for raw single-file deploys.  The natural workspace flow is `chumicro-workspace deploy --thing <name>` with secrets in `secrets.yml`; the constants path is the "I just want to copy this single file to /code.py" shortcut.

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
