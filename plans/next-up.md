# Next Up

> Work queue.  One bullet per item, no sub-bullets — anything needing more than a title goes to [`workstreams/<name>.md`](workstreams/) and surfaces here as a one-line pointer.  Tracks status, not research.  No `## Done` section — `git --no-pager log` carries history.

## Now

- [ ] **Validate Pi Pico W CP-side fragmentation behaviour on custom firmware.**  [handoffs/2026-05-23-pi-pico-w-cp-fragmentation-validation.md](handoffs/2026-05-23-pi-pico-w-cp-fragmentation-validation.md)

## Next

- [ ] **CI infrastructure workstream (unscoped — fires when CI is re-enabled).**  [workstreams/archive/audit-remediation-and-drift-mechanization.md](workstreams/archive/audit-remediation-and-drift-mechanization.md)
- [ ] **Workspace-template gap #4b — regular-mode README update.**  [workstreams/archive/workspace-template-dev-and-regular-mode-gaps.md](workstreams/archive/workspace-template-dev-and-regular-mode-gaps.md)
- [ ] **`websockets` oversize-frame length on Lolin S2.**  [workstreams/websockets-oversize-frame-lolin-s2.md](workstreams/websockets-oversize-frame-lolin-s2.md)
- [ ] **Expand the device test matrix beyond ESP32-S2.**
- [ ] **Performance + resource benchmarking infrastructure** — heap + CPU per library op, regression gates, on-schedule CI.
- [ ] **Deploy-path unification — one mechanism puts code on a board.**  [workstreams/deploy-path-unification.md](workstreams/deploy-path-unification.md)
- [ ] **`_load_fallback_device` — stash sessionstart error.**  [workstreams/load-fallback-device-stash-sessionstart.md](workstreams/load-fallback-device-stash-sessionstart.md)
- [ ] **Deploy walker fails on unresolved imports.**  [workstreams/walker-unresolved-import-failure.md](workstreams/walker-unresolved-import-failure.md)
- [ ] **Concurrent-agent commit scrambling — process / skill note.**  [workstreams/concurrent-agent-commit-scrambling.md](workstreams/concurrent-agent-commit-scrambling.md)
- [ ] **`/audit-library libraries/requests` — dedup test helpers (`make_factory` / `canned_response` / `drive_until_done` / `make_client` repeated near-verbatim across 4 `test_client_*.py` files).**
- [ ] **`examples/helpers.py` cross-library drift.**  [workstreams/examples-helpers-cross-library-drift.md](workstreams/examples-helpers-cross-library-drift.md)
- [ ] **`/audit-library libraries/timing` — `_sleep_ms` duplicated across `functional_tests/test_heartbeat.py` and `test_heartbeat_ticks.py` (latter uses tabs, former spaces).**
- [ ] **`/audit-library libraries/ntp` — `functional_tests/test_real_ntp.py:120` `print("NTP_SKIP no creds")` is dead and mislabeled (runs after a successful run, post-finally, past the wifi-cfg-None guard).**
- [ ] **`/audit-library libraries/http_server` — `DEFAULT_BODY_BUFFER_SIZE` is exported via `__init__.py` but has no in-tree consumer (only `test_http_server_e2e.py` uses it as a magnitude reference); reserved-for-keep-alive public API to confirm or retire.**
- [ ] **`/audit-library workbench/pytest-device` — 7 shape candidates surfaced during the comment audit Pass 2 (collection.py `_device_closure_source_dirs` / `_device_own_source_dirs` near-parallel loops, two inline `import warnings` at 322 and 958, `_ensure_batch_result` guard duplication across `DeviceTestItem.runtest` / `DeviceRunFileItem.runtest`; pr_summary.py `_format_markdown_table` growth; runtime_config.py validator-class candidate; session.py nine near-identical `_session_*` getters; test_runner.py CircuitPython-RAM coupling via cast + dynamic import).**
- [ ] **`/audit-workspace` — 12 unit-test `conftest.py` files (compat, logging, wifi, msgpack, kvstore, events, timing, http_server, mqtt, requests, ntp, websockets, sockets) carry an identical one-line `"""Test configuration for the chumicro-<name>.</name>"""` docstring on an otherwise-empty file; strip them all together or leave as a workspace convention.**
- [ ] **`/audit-workspace` — `# noqa: CODE` and `# pragma: no cover` inline-comment separator drift; most of `libraries/` uses ` - ` but msgpack / sockets / runner / compat (now fixed) used em-dash; normalize and add CHU lint rule.**
- [ ] **`/audit-library workbench/checks` — module-level docstrings in `chu027.py`'s `_extract_docstring_blocks` are not suppressible (the ClassDef/FunctionDef header check doesn't fire for `ast.Module`, leaving `suppressed = False`). Decide whether to add a header-line-1 check or document the gap as intentional.**
- [ ] **`/audit-library libraries/mqtt/tests` — five `test_canonical_*` method names (`test_canonical_values`, `test_canonical_shape`, `test_canonical_encodings`) in `test_state.py` / `test_packets.py` / `test_encoder.py` / `test_testing_helpers.py` use the banned "canonical X" framing as identifiers; rename to concrete asserts (e.g. `test_known_values`, `test_known_encodings`).**
