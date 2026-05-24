# Workstream: functional_tests/ conftest helper dedup

Status: **proposed.**  Surfaced 2026-05-23 by `/audit-workspace`.  Cross-library duplication of pytest fixtures across the networking-library functional-test conftests.

## Evidence

Five helpers, repeated near-verbatim across the seven `libraries/*/functional_tests/conftest.py` files:

| Helper                              | Files                                                                    | Drift            |
|-------------------------------------|--------------------------------------------------------------------------|------------------|
| `_merged_runtime_config`            | http_server, ntp, wifi, sockets, websockets, mqtt, requests              | minor wording    |
| `_merged_runtime_config_with_creds` | mqtt, sockets, websockets                                                | sockets injects `now_utc_tuple` for TLS; otherwise near-identical |
| `_detect_lan_ip`                    | mqtt, sockets, websockets                                                | byte-identical mqtt+websockets; sockets adds a comment block |
| `_find_free_port`                   | mqtt, websockets                                                         | byte-identical body; mqtt has a docstring |
| `_wait_until_listening`             | mqtt, websockets                                                         | byte-identical |

Per-library line counts (for context on what's library-specific vs shared):

```
 50 http_server  (small — most logic is per-library)
210 mqtt          (large — mosquitto-broker fixture)
 48 ntp           (small)
 69 requests      (medium)
164 sockets       (large — echo-server fixture + TLS time injection)
179 websockets    (large — echo-server fixture)
 73 wifi          (medium)
```

The five duplicated helpers add up to ~80–100 lines per conftest that could move to a shared module.  The library-specific bits (mosquitto launcher, echo-server fixture, TLS time injection) stay per-library.

## Decision space

(a) **Shared module under `support/test_harness/`.**  Add a new `support/test_harness/src/chumicro_test_harness/networking.py` (or similar) that exports the five helpers.  Each library's conftest imports them and adds library-specific extensions.  Library-specific divergence (sockets' TLS time inject) stays as a per-conftest hook.

(b) **Scaffold + sync.**  Pick a canonical body, place it in `scripts/templates/`, regenerate per-library on scaffold.  Wrong fit — conftests are not scaffold-emitted in steady state; each library actively edits them.

(c) **Documented contract.**  Wrong fit — these are concrete helpers, not a behavioural contract.

(d) **Accept the drift.**  Defensible — divergence is mostly comments, not semantics, and the helpers are test-only.

**Recommended:** (a) — `support/test_harness/` already exists, already houses cross-library test infra, and is gitignored from PyPI ship.  Lowest blast radius: one new module, seven conftest edits, no scaffold change, no lint.

## What "good" looks like

* `support/test_harness/src/chumicro_test_harness/networking.py` exports the five helpers.
* Each `libraries/*/functional_tests/conftest.py` replaces its inline copies with `from chumicro_test_harness.networking import _merged_runtime_config, ...`.
* sockets' TLS-time injection stays in its own conftest as a post-merge mutation hook (`merged = _merged_runtime_config_with_creds(); if merged is not None: merged["sockets.now_utc_tuple"] = ...`).
* mqtt's mosquitto-broker fixture and websockets'/sockets' echo-server fixtures stay per-library (they're library-specific, not duplicated).
* No drift lint needed — a shared module enforces convergence by construction.

## Estimated size

Small.  ~150 LOC consolidation across seven files, no public-API touch, no decision-level question.  Preflight + functional-test bake on at least one networking library to confirm fixtures resolve correctly.
