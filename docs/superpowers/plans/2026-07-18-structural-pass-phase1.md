# Structural Pass Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate the five copied transport-factory modules into `chumicro_sockets`, finish generator-first teaching in three guides, document the wait vocabulary and the runner service contract, and land the orphan truth-fixes, per spec `docs/superpowers/specs/2026-07-18-structural-pass-design.md` Phase 1.

**Architecture:** One new module `chumicro_sockets/sockets_factory.py` holds four generic factory builders (parametrized by host/port/TLS material, never by protocol config keys). Each protocol library's `from_config` keeps its own config-key extraction and lazily imports the generic builders. The module name ends in `_factory`, so the deploy walker's existing `__chumicro_skip_factories__` family matching (`workbench/deploy/src/chumicro_deploy/skip_factories.py`, `_FACTORY_STEM`) covers it with zero walker changes.

**Tech Stack:** Pure Python (CircuitPython/MicroPython/CPython compatible), pytest, the repo's preflight gate.

## Global Constraints

- Work happens in a git worktree created via superpowers:using-git-worktrees (user requirement).
- Before EVERY commit: `set -o pipefail; python scripts/run.py preflight --coverage-threshold 94 2>&1 | tail -5` must end with `Preflight passed.` Never fuse the gate and the commit in one `&&` chain.
- Commit via the repo's git-commit skill convention: single-quoted heredoc message, imperative subject under 70 chars, body says why, no Co-Authored-By trailer. Stage with explicit paths, never `git add -A`.
- All prose in docs/READMEs/guides follows the docs voice (CLAUDE.md): no em-dashes, plain words, measured claims only.
- No backwards-compatibility shims (Decision 0092): each rename is break-plus-migrate in one commit.
- The sockets package must not learn any protocol config namespace (spec 1.1 dependency-direction constraint).
- New decision records go through the repo's new-decision skill.
- Device-library code carries no type annotations in signatures where the surrounding file has none; match each file's existing idiom.

---

### Task 1: Generic factories module in chumicro_sockets

**Files:**
- Create: `libraries/sockets/src/chumicro_sockets/sockets_factory.py`
- Test: `libraries/sockets/tests/test_sockets_factory.py`
- Modify: `libraries/sockets/VERSION` (minor bump; read current value first)

**Interfaces:**
- Consumes: `chumicro_sockets.connector(host, port, *, tls=..., context=..., radio=...)`, `chumicro_sockets.listener(host, port, *, tls=..., context=..., radio=...)`, `chumicro_sockets.udp_socket(radio=...)`, `chumicro_sockets.ssl_context_with_cert_and_key_paths(cert_path=..., key_path=...)` (all exist today in `chumicro_sockets/__init__.py`).
- Produces (later tasks rely on these exact names):
  - `connector_factory(*, radio=None, ssl_context=None)` returns `(host, port, use_tls) -> SocketConnector`
  - `fixed_connector_factory(host, port, *, radio=None, ssl_context=None)` returns `() -> SocketConnector`
  - `listener_factory(host, port, *, radio=None, ssl_context=None, cert_path=None, key_path=None)` returns `() -> ListeningSocket`
  - `udp_socket_factory(*, radio=None)` returns `() -> socket`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the generic transport factories."""

import chumicro_sockets
from chumicro_sockets import sockets_factory


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


def test_connector_factory_dispatches_host_port_tls(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(chumicro_sockets, "connector", recorder)
    factory = sockets_factory.connector_factory(radio="R", ssl_context="CTX")
    factory("example.com", 443, True)
    (args, kwargs), = recorder.calls
    assert args == ("example.com", 443)
    assert kwargs == {"tls": True, "context": "CTX", "radio": "R"}


def test_connector_factory_plain_call_drops_context(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(chumicro_sockets, "connector", recorder)
    factory = sockets_factory.connector_factory(ssl_context="CTX")
    factory("example.com", 80, False)
    (args, kwargs), = recorder.calls
    assert kwargs == {"tls": False, "context": None, "radio": None}


def test_fixed_connector_factory_closes_over_endpoint(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(chumicro_sockets, "connector", recorder)
    factory = sockets_factory.fixed_connector_factory("broker.local", 8883, ssl_context="CTX")
    factory()
    factory()
    assert len(recorder.calls) == 2
    args, kwargs = recorder.calls[0]
    assert args == ("broker.local", 8883)
    assert kwargs == {"tls": True, "context": "CTX", "radio": None}


def test_fixed_connector_factory_no_tls_without_context(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(chumicro_sockets, "connector", recorder)
    sockets_factory.fixed_connector_factory("broker.local", 1883)()
    (_, kwargs), = recorder.calls
    assert kwargs["tls"] is False and kwargs["context"] is None


def test_listener_factory_plain(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(chumicro_sockets, "listener", recorder)
    sockets_factory.listener_factory("0.0.0.0", 8080, radio="R")()
    (args, kwargs), = recorder.calls
    assert args == ("0.0.0.0", 8080)
    assert kwargs == {"radio": "R"}


def test_listener_factory_tls_from_paths(monkeypatch):
    listener_rec = _Recorder()
    context_rec = _Recorder()
    monkeypatch.setattr(chumicro_sockets, "listener", listener_rec)
    monkeypatch.setattr(
        chumicro_sockets, "ssl_context_with_cert_and_key_paths", context_rec,
    )
    sockets_factory.listener_factory(
        "0.0.0.0", 8443, cert_path="c.pem", key_path="k.pem",
    )()
    (_, ctx_kwargs), = context_rec.calls
    assert ctx_kwargs == {"cert_path": "c.pem", "key_path": "k.pem"}
    (args, kwargs), = listener_rec.calls
    assert args == ("0.0.0.0", 8443)
    assert kwargs["tls"] is True and kwargs["radio"] is None


def test_listener_factory_explicit_context_wins(monkeypatch):
    listener_rec = _Recorder()
    context_rec = _Recorder()
    monkeypatch.setattr(chumicro_sockets, "listener", listener_rec)
    monkeypatch.setattr(
        chumicro_sockets, "ssl_context_with_cert_and_key_paths", context_rec,
    )
    sockets_factory.listener_factory("h", 1, ssl_context="CTX")()
    assert context_rec.calls == []
    (_, kwargs), = listener_rec.calls
    assert kwargs["context"] == "CTX"


def test_udp_socket_factory_fresh_socket_per_call(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(chumicro_sockets, "udp_socket", recorder)
    factory = sockets_factory.udp_socket_factory(radio="R")
    factory()
    factory()
    assert len(recorder.calls) == 2
    assert recorder.calls[0][1] == {"radio": "R"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest libraries/sockets/tests/test_sockets_factory.py -v`
Expected: FAIL with `ImportError: cannot import name 'sockets_factory'`

- [ ] **Step 3: Write the module**

```python
"""Generic transport factories for the chumicro networking libraries.

Builders take hosts, ports, and TLS material as parameters.  Protocol
config namespaces (``mqtt.broker.host`` and friends) belong to each
protocol library's ``from_config``, never here.

The module name ends in ``_factory`` so the deploy walker's
``__chumicro_skip_factories__`` family matching drops it from
bring-your-own-transport deploys, and with it the only reference that
would pull :mod:`chumicro_sockets` onto the board.
"""

import chumicro_sockets


def connector_factory(*, radio=None, ssl_context=None):
    """Build a ``(host, port, use_tls) -> SocketConnector`` factory."""
    def factory(host, port, use_tls):
        return chumicro_sockets.connector(
            host, port,
            tls=use_tls,
            context=ssl_context if use_tls else None,
            radio=radio,
        )

    return factory


def fixed_connector_factory(host, port, *, radio=None, ssl_context=None):
    """Build a ``() -> SocketConnector`` factory for one fixed endpoint."""
    def factory():
        return chumicro_sockets.connector(
            host, port,
            tls=ssl_context is not None,
            context=ssl_context,
            radio=radio,
        )

    return factory


def listener_factory(host, port, *, radio=None, ssl_context=None,
                     cert_path=None, key_path=None):
    """Build a ``() -> ListeningSocket`` factory, TLS when material is given.

    TLS engages when *ssl_context* or *cert_path* is set; an explicit
    *ssl_context* wins over paths.
    """
    use_tls = ssl_context is not None or cert_path is not None

    def factory():
        if not use_tls:
            return chumicro_sockets.listener(host, port, radio=radio)
        context = (
            ssl_context
            if ssl_context is not None
            else chumicro_sockets.ssl_context_with_cert_and_key_paths(
                cert_path=cert_path, key_path=key_path,
            )
        )
        return chumicro_sockets.listener(
            host, port, tls=True, context=context, radio=radio,
        )

    return factory


def udp_socket_factory(*, radio=None):
    """Build a ``() -> socket`` factory returning a fresh bound UDP socket."""
    def factory():
        return chumicro_sockets.udp_socket(radio=radio)

    return factory
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest libraries/sockets/tests/ -v`
Expected: all PASS (new file plus the existing sockets suite).

- [ ] **Step 5: Bump `libraries/sockets/VERSION`** (minor: new public module). Read the file, bump the middle number, reset patch to 0.

- [ ] **Step 6: Preflight, then commit**

```bash
git add libraries/sockets/src/chumicro_sockets/sockets_factory.py libraries/sockets/tests/test_sockets_factory.py libraries/sockets/VERSION
git commit -m "sockets: add generic transport factories module"
```
(Heredoc body: explain this is spec 1.1 landing the shared home; the five per-library copies migrate in the next commits.)

---

### Task 2: Migrate mqtt

**Files:**
- Delete: `libraries/mqtt/src/chumicro_mqtt/sockets_factory.py`
- Modify: `libraries/mqtt/src/chumicro_mqtt/client.py:196-215` (the `from_config` lazy-import block)
- Modify: `libraries/mqtt/tests/test_client_from_config_factory.py` (patch targets and import paths)
- Modify: `libraries/mqtt/docs/guide.md`, `libraries/mqtt/README.md`, `libraries/mqtt/examples/bench.py` (references; grep first)
- Modify: `libraries/mqtt/VERSION` (minor bump)

**Interfaces:**
- Consumes: `fixed_connector_factory` from Task 1.
- Produces: `MQTTClient.from_config(config, ...)` keeps its exact public signature and error behavior; only the internal wiring changes.

- [ ] **Step 1: Update the failing-path and wiring in `client.py`**

Replace the block currently at lines 199-215 with:

```python
            # Lazy import so callers who pass their own socket/transport_factory
            # never pull chumicro_sockets into the deploy graph.
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415 - lazy
                    fixed_connector_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board); pass transport_factory= or "
                    "socket= explicitly.",
                ) from exception

            from chumicro_config import MissingConfigKey  # noqa: PLC0415 - lazy

            for required_key in ("mqtt.broker.host", "mqtt.broker.port"):
                if required_key not in config:
                    raise MissingConfigKey(
                        f"required config key {required_key!r} is missing",
                    )
            transport_factory = fixed_connector_factory(
                config["mqtt.broker.host"], config["mqtt.broker.port"],
                radio=radio, ssl_context=ssl_context,
            )
```

- [ ] **Step 2: Delete the copy**

```bash
git rm libraries/mqtt/src/chumicro_mqtt/sockets_factory.py
```

- [ ] **Step 3: Update tests.** In `libraries/mqtt/tests/test_client_from_config_factory.py`, retarget every `chumicro_mqtt.sockets_factory` import/patch to `chumicro_sockets.sockets_factory.fixed_connector_factory` (patch on the `chumicro_sockets.sockets_factory` module object, imported as a module, not on `chumicro_mqtt`). The MissingConfigKey tests keep passing unchanged because the validation semantics moved verbatim into `from_config`; the skip-factories RuntimeError test needs its expected message updated to `chumicro_sockets.sockets_factory not available` and its ImportError simulation retargeted (simulate by monkeypatching `sys.modules` so the lazy import raises, e.g. `monkeypatch.setitem(sys.modules, "chumicro_sockets.sockets_factory", None)` if that is the existing test's technique; mirror whatever technique the file uses today).

- [ ] **Step 4: Run the library suite**

Run: `pytest libraries/mqtt/tests -v`
Expected: all PASS.

- [ ] **Step 5: Sweep remaining references**

Run: `grep -rn "sockets_factory" libraries/mqtt --include="*.py" --include="*.md" | grep -v site/`
Update `docs/guide.md`, `README.md`, `examples/bench.py` hits to the new import path and function name. Expected end state: zero hits mentioning `chumicro_mqtt.sockets_factory`.

- [ ] **Step 6: Bump `libraries/mqtt/VERSION` (minor), preflight, commit**

```bash
git add -u libraries/mqtt
git commit -m "mqtt: use the shared sockets factories, drop the local copy"
```

---

### Task 3: Migrate requests

**Files:**
- Delete: `libraries/requests/src/chumicro_requests/sockets_factory.py`
- Modify: `libraries/requests/src/chumicro_requests/client.py:265-280`
- Modify: `libraries/requests/tests/test_client_fromconfig.py`, `libraries/requests/tests/test_requests_pytest.py`, `libraries/requests/functional_tests/test_real_get.py`, `test_real_get_tls.py`, `test_real_large_stream.py`
- Modify: `libraries/requests/docs/guide.md`, `docs/index.md`, `README.md`, `examples/generator_fetch.py`
- Modify: `demos/requests_fetch/app.py`, root `README.md` (the generator example imports `chumicro_requests.sockets_factory`)
- Modify: `libraries/requests/VERSION` (minor bump)

**Interfaces:**
- Consumes: `connector_factory` from Task 1.
- Produces: `HttpClient.from_config(...)` signature unchanged. All user-facing examples now import `from chumicro_sockets.sockets_factory import connector_factory`.

- [ ] **Step 1: Rewire `from_config`.** Replace the lazy-import block (lines 266-280) analogously to Task 2, importing `connector_factory` and calling `connector_factory(radio=radio, ssl_context=ssl_context)` (this library's factory shape takes no host/port; the client dials per request). RuntimeError message becomes `chumicro_sockets.sockets_factory not available ...` with the same tail.

- [ ] **Step 2:** `git rm libraries/requests/src/chumicro_requests/sockets_factory.py`

- [ ] **Step 3: Retarget tests and functional tests.** Same patch-target rules as Task 2 Step 3. Functional tests build real factories; change their imports to `from chumicro_sockets.sockets_factory import connector_factory` and drop the old alias name `chumicro_sockets_connector_factory` everywhere.

- [ ] **Step 4:** Run `pytest libraries/requests/tests -v` — all PASS.

- [ ] **Step 5: Sweep references repo-wide for this library**

Run: `grep -rn "chumicro_requests.sockets_factory\|chumicro_sockets_connector_factory" --include="*.py" --include="*.md" . | grep -v ".tools\|site/\|dist/"`
Fix every hit (includes root `README.md` line ~88 and `demos/requests_fetch/app.py`). The root README example becomes:

```python
from chumicro_requests.generators import get
from chumicro_sockets.sockets_factory import connector_factory

transport_factory = connector_factory(radio=wifi.adapter.radio)
```

- [ ] **Step 6: Bump VERSION (minor), preflight, commit**

```bash
git add -u libraries/requests demos/requests_fetch README.md
git commit -m "requests: use the shared sockets factories, drop the local copy"
```

---

### Task 4: Migrate websockets

**Files:**
- Delete: `libraries/websockets/src/chumicro_websockets/sockets_factory.py`
- Modify: `libraries/websockets/src/chumicro_websockets/client.py:66-80`, `server.py:235-247`
- Modify: `libraries/websockets/tests/test_sockets_factory.py` (delete; its builder-behavior cases were generalized into Task 1's sockets tests; port any case not covered there into `libraries/sockets/tests/test_sockets_factory.py` first), `tests/test_client_ping_edges.py`, `functional_tests/test_real_client_against_host.py`
- Modify: `libraries/websockets/docs/guide.md`, `docs/index.md`, `README.md`
- Modify: `libraries/websockets/VERSION` (minor bump)

**Interfaces:**
- Consumes: `connector_factory`, `listener_factory` from Task 1.
- Produces: `WebSocketClient.from_config(...)` and `WebSocketServer.from_config(...)` signatures unchanged.

- [ ] **Step 1: Client rewire.** Same shape as Task 3 Step 1 (`connector_factory(radio=radio, ssl_context=ssl_context)`).

- [ ] **Step 2: Server rewire.** Replace the block at `server.py:236-247` with:

```python
        if listener is None:
            # Lazy import so a client-only deploy never pulls chumicro_sockets onto the board.
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415 - lazy
                    listener_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or not on "
                    "the board); pass listener= explicitly.",
                ) from exception
            listener = listener_factory(
                config.get("websockets.server.host", "0.0.0.0"),
                config.get("websockets.server.port", 8765),
                radio=radio,
            )()
```

(The immediate `()` call preserves today's behavior: `from_config` hands the server an already-open listening socket.)

- [ ] **Step 3:** `git rm libraries/websockets/src/chumicro_websockets/sockets_factory.py` and port/delete `tests/test_sockets_factory.py` per the Files note.

- [ ] **Step 4:** Retarget remaining test references; run `pytest libraries/websockets/tests -v` — all PASS.

- [ ] **Step 5:** Sweep: `grep -rn "chumicro_websockets.sockets_factory\|chumicro_sockets_listener" --include="*.py" --include="*.md" . | grep -v ".tools\|site/\|dist/"` — fix all hits.

- [ ] **Step 6: Bump VERSION (minor), preflight, commit**

```bash
git add -u libraries/websockets libraries/sockets
git commit -m "websockets: use the shared sockets factories, drop the local copy"
```

---

### Task 5: Migrate http_server

**Files:**
- Delete: `libraries/http_server/src/chumicro_http_server/sockets_factory.py`
- Modify: `libraries/http_server/src/chumicro_http_server/server.py:429-445`
- Modify: `libraries/http_server/tests/test_http_from_config.py`
- Modify: `libraries/http_server/docs/guide.md`
- Modify: `libraries/http_server/VERSION` (minor bump)

**Interfaces:**
- Consumes: `listener_factory` from Task 1.
- Produces: `HttpServer.from_config(...)` signature unchanged, including the MissingConfigKey behavior for a half-configured TLS pair.

- [ ] **Step 1: Rewire `from_config`.** Replace the block at lines 430-445 with:

```python
        if transport_factory is None:
            host = config.get("http_server.bind_host", "0.0.0.0")
            port = config.get("http_server.bind_port", 8080)
            cert_path = config.get("http_server.tls.cert_path")
            key_path = config.get("http_server.tls.key_path")
            if (cert_path is None) != (key_path is None):
                from chumicro_config import MissingConfigKey  # noqa: PLC0415 - lazy

                missing = (
                    "http_server.tls.cert_path" if cert_path is None
                    else "http_server.tls.key_path"
                )
                raise MissingConfigKey(
                    f"required config key {missing!r} is missing; TLS "
                    "requires both cert_path and key_path",
                )
            # Lazy import so a caller-supplied transport_factory doesn't pull in chumicro_sockets.
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415 - lazy
                    listener_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not "
                    "available (excluded via __chumicro_skip_factories__ "
                    "or not on the board); pass transport_factory= "
                    "explicitly.",
                ) from exception

            transport_factory = listener_factory(
                host, port,
                radio=radio, ssl_context=ssl_context,
                cert_path=cert_path, key_path=key_path,
            )
```

Note the ordering change: config validation now runs before the lazy import. Check `test_http_from_config.py` for a test that asserts RuntimeError when factories are skipped AND config is half-TLS at once; if one exists, update its expectation to MissingConfigKey (validation now wins). Otherwise behavior is identical.

- [ ] **Step 2:** `git rm libraries/http_server/src/chumicro_http_server/sockets_factory.py`

- [ ] **Step 3:** Retarget tests; run `pytest libraries/http_server/tests -v` — all PASS.

- [ ] **Step 4:** Sweep: `grep -rn "chumicro_http_server.sockets_factory" --include="*.py" --include="*.md" . | grep -v ".tools\|site/\|dist/"` — fix all hits.

- [ ] **Step 5: Bump VERSION (minor), preflight, commit**

```bash
git add -u libraries/http_server
git commit -m "http_server: use the shared sockets factories, drop the local copy"
```

---

### Task 6: Migrate ntp

**Files:**
- Delete: `libraries/ntp/src/chumicro_ntp/sockets_factory.py`
- Modify: `libraries/ntp/src/chumicro_ntp/core.py:117-133`
- Modify: `libraries/ntp/tests/test_ntp_from_config.py`, `tests/test_ntp_pytest.py`, `functional_tests/test_real_ntp.py`
- Modify: `libraries/ntp/docs/guide.md`, `docs/index.md`, `README.md`
- Modify: `libraries/ntp/VERSION` (minor bump)

**Interfaces:**
- Consumes: `udp_socket_factory` from Task 1.
- Produces: `NTPClient.from_config(...)` signature unchanged; the factory it builds still returns non-blocking sockets.

- [ ] **Step 1: Rewire `from_config`.** Replace the block at lines 118-133 with:

```python
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415
                    udp_socket_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board), pass socket= or "
                    "transport_factory= explicitly.",
                ) from exception

            base_factory = udp_socket_factory(radio=radio)

            def transport_factory():
                udp_socket = base_factory()
                udp_socket.setblocking(False)
                return udp_socket
```

- [ ] **Step 2:** `git rm libraries/ntp/src/chumicro_ntp/sockets_factory.py`

- [ ] **Step 3:** Retarget tests; run `pytest libraries/ntp/tests -v` — all PASS.

- [ ] **Step 4:** Sweep: `grep -rn "chumicro_ntp.sockets_factory\|chumicro_sockets_factory" --include="*.py" --include="*.md" . | grep -v ".tools\|site/\|dist/"` — fix all hits (this pattern also catches any stale http_server naming).

- [ ] **Step 5: Bump VERSION (minor), preflight, commit**

```bash
git add -u libraries/ntp
git commit -m "ntp: use the shared sockets factories, drop the local copy"
```

---

### Task 7: Repo-wide sweep, size budgets, deploy-tool prose

**Files:**
- Modify: `docs/contributing/slimming-your-deploy.md`, `workbench/deploy/src/chumicro_deploy/sources.py` (docstring references), `.github/skills/audit-embedded/field-reality.md`, `.github/skills/audit-integration/SKILL.md`
- Modify: `size-budgets.toml` (the `[sockets]` ceiling, only if the gate fails)
- Verify: `workbench/deploy/tests/test_skip_factories.py` still green (mechanism untouched)

- [ ] **Step 1: Final reference sweep**

Run: `grep -rn "sockets_factory" --include="*.py" --include="*.md" . | grep -v ".tools\|site/\|dist/\|plans/\|chumicro_sockets"`
Every remaining hit must be either the new import path or historical prose in `plans/` (leave plans history alone). Update the four prose files above so their examples name `chumicro_sockets.sockets_factory` and state that the `sockets_factory` family entry in `__chumicro_skip_factories__` now matches the one shared module.

- [ ] **Step 2: Deploy walker check**

Run: `pytest workbench/deploy/tests/test_skip_factories.py -v`
Expected: PASS with zero source changes. If any test hardcodes the five old per-library paths as fixtures, update fixtures only, not the mechanism.

- [ ] **Step 3: Size gate.** Run preflight. If the sockets budget fails, re-measure and raise `[sockets]` in `size-budgets.toml` by the measured delta (record the number for Task 9's decision record); the five migrated libraries shrank, leave their ceilings alone (headroom is fine).

- [ ] **Step 4: Preflight, commit**

```bash
git add -u docs workbench/deploy .github/skills size-budgets.toml
git commit -m "deploy docs + budgets: one shared sockets_factory module"
```

---

### Task 8: Workspace template migration (sister repo)

**Files (in the sibling `ChuMicro-Workspace-Template` checkout, NOT the worktree):**
- Any file matching `grep -rn "sockets_factory" --include="*.py" --include="*.md" .` in that repo.

- [ ] **Step 1:** Run the grep above in the template clone. If zero hits, record that in the Task 9 decision record and skip to Task 9.
- [ ] **Step 2:** For each hit, apply the same import-path migration as Tasks 2-6 (the template's starter app and skills reference library examples).
- [ ] **Step 3:** Run the template's own checks (`python3 run.py lint` and its tests per its README), then commit there with subject `Track the shared chumicro_sockets factories module` and push only if its remote is the user's (check `git remote -v`; if push is blocked, leave the commit local and note it in the final report).

---

### Task 9: Decision record superseding 0093, notes on 0087/0089

**Files:**
- Create: next decision number under `plans/decisions/` (via the new-decision skill; expect `0115-shared-sockets-factories.md`)
- Modify: `plans/decisions/0093-transport-factory-contract.md` (superseded marker per that file's existing conventions and `plans/decisions/README.md` rules)
- Modify: `plans/decisions/0087-generators-for-sequential-io.md`, `0089-generator-surfaces-on-networking-libraries.md` (one-line note each: teaching order is generator-first per user call 2026-07-18; contract unchanged)

- [ ] **Step 1:** Invoke the new-decision skill. Content: the five copies drifted once (M77), the shared module lives in `chumicro_sockets` because importers of the glue are sockets users by definition, the generic-parameters constraint (no protocol config namespaces in sockets), the `_factory` filename keeping the skip-family mechanism unchanged, and the measured flash delta from Task 7 Step 3.
- [ ] **Step 2:** Mark 0093 superseded by the new record, following the archive-in-filename convention (Decision 0076) if that is what the decisions README prescribes; read it first and match.
- [ ] **Step 3:** Preflight, commit: `plans: record shared sockets factories decision (supersedes 0093)`

---

### Task 10: Generator-first guides (spec 1.2)

**Files:**
- Modify: `libraries/requests/docs/guide.md`, `libraries/websockets/docs/guide.md`, `libraries/mqtt/docs/guide.md`

**Interfaces:**
- Consumes: each library's `generators` submodule (read `src/chumicro_<lib>/generators.py` for the exact public names before writing; requests exposes `get` used as `response = yield from get(transport_factory, url)`).

- [ ] **Step 1:** For each of the three guides, add a new first section after `## Overview` titled `## Getting started with generators` whose code comes from that library's existing runnable generator example (`libraries/requests/examples/generator_fetch.py` for requests; locate the equivalent example in websockets and mqtt `examples/`; if a library has no generator example, write the guide snippet against the actual `generators.py` API and add the missing example file in the same commit, deployed-example-tested only if a board is attached, otherwise unit-shaped). The existing `## Getting started` section stays, retitled `## Getting started with a service` and introduced as the service-author idiom.
- [ ] **Step 2:** Cross-check every snippet imports from `chumicro_sockets.sockets_factory` (not the deleted paths).
- [ ] **Step 3:** Render check: `python scripts/run.py preflight` covers doc-command parity lints; also run any docs-specific check the preflight output names as skipped.
- [ ] **Step 4:** Commit: `guides: lead requests, websockets, mqtt with the generator surface`

---

### Task 11: Wait-vocabulary page (spec 1.3)

**Files:**
- Modify: `libraries/timing/docs/guide.md` (new section `## Choosing a wait`), `libraries/runner/docs/guide.md` and `libraries/sockets/docs/guide.md` (one-paragraph pointer each)

- [ ] **Step 1:** Add to the timing guide (adjust the final column only if a name proves wrong against source):

```markdown
## Choosing a wait

Every ChuMicro wait answers one question.  Pick by the question, not the type.

| You want | Reach for | Lives in |
|---|---|---|
| "run this every N ms" | `Rate` | `chumicro_timing` |
| "give up after N ms" | `Deadline` | `chumicro_timing` |
| "a flag one place sets, another awaits" | `Signal` + `wait_for` | `chumicro_timing` |
| "pause this generator until the socket is readable/writable" | `ReadWait` / `WriteWait` | `chumicro_sockets` |
| "tell the runner when my service next needs the CPU" | `next_deadline` / `io_interest` on your service | the runner service contract |
| "block the loop until a task finishes, with a timeout" | `runner.run_until` | `chumicro_runner` |
```

Verify each row against the source module before committing; fix the table, not the code.
- [ ] **Step 2:** Pointer paragraphs in runner and sockets guides link to the timing guide section.
- [ ] **Step 3:** Preflight, commit: `docs: one page answers which wait primitive to reach for`

---

### Task 12: Service contract written down (spec 1.4)

**Files:**
- Modify: `libraries/runner/src/chumicro_runner/testing.py` (add `validate_service`)
- Test: `libraries/runner/tests/test_validate_service.py` (create)
- Modify: `libraries/runner/docs/guide.md` (new section `## The service contract`)
- Modify: `libraries/runner/VERSION` (minor bump)

- [ ] **Step 1:** Read `libraries/runner/src/chumicro_runner/core.py` and list where each of `check`, `handle`, `io_interest`, `io_socket`, `next_deadline`, `io_error` is dispatched. Derive the coherence rules FROM that reading; the starting hypothesis to verify is: `handle` requires `check`; `io_socket` and `io_interest` come as a pair; `io_error` requires `io_socket`; a service must expose at least one of `check`, `io_socket`, or `next_deadline`. Any rule the source contradicts gets corrected to what core.py actually does.

- [ ] **Step 2: Write failing tests** (shape; extend per the verified rules):

```python
from chumicro_runner.testing import validate_service


class _Good:
    def check(self, now_ms):
        return False

    def handle(self, now_ms):
        pass


def test_check_handle_service_passes():
    validate_service(_Good())


def test_handle_without_check_fails():
    class Bad:
        def handle(self, now_ms):
            pass

    try:
        validate_service(Bad())
    except ValueError as error:
        assert "check" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_io_socket_without_interest_fails():
    class Bad:
        def check(self, now_ms):
            return False

        def handle(self, now_ms):
            pass

        def io_socket(self):
            return object()

    try:
        validate_service(Bad())
    except ValueError as error:
        assert "io_interest" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_inert_object_fails():
    try:
        validate_service(object())
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 3:** Implement `validate_service(service)` in `testing.py`: collect which of the six names are present-and-callable via `getattr`, apply the verified rules, raise `ValueError` naming the missing/extra member and the rule, return `None` on success. Docstring states this validates shape only, never behavior.
- [ ] **Step 4:** `pytest libraries/runner/tests/test_validate_service.py -v` — PASS, then the full runner suite.
- [ ] **Step 5:** Guide section `## The service contract`: list the six members, required/optional, when each is called by the tick loop (from the Step 1 reading), and a closing paragraph pointing at `validate_service` for use in consumer test suites. State explicitly: two ways to run work exist (services and generators); this section documents the service side; nothing here adds a third.
- [ ] **Step 6:** Bump runner VERSION (minor), preflight, commit: `runner: document the service contract, add validate_service`

---

### Task 13: Orphan truth-fixes (spec 1.5)

**Files:**
- Modify: root `README.md` (remove the logging row, line ~179)
- Modify: `libraries/README.md` (remove the logging row at line 20, drop logging from the Primitives line 44 and the problem-index line 68)
- Modify: `libraries/README.md` Primitives line for compat if the check below proves it unused

- [ ] **Step 1:** Remove the logging rows/entries listed above. The library itself stays in-tree and parked; only the advertising goes.
- [ ] **Step 2:** Compat check: `grep -rln "chumicro_compat" libraries workbench support demos scripts "$WORKSPACE_TEMPLATE_ROOT" 2>/dev/null | grep -v "libraries/compat\|site/\|dist/\|__pycache__"`. Zero external hits were found in src trees during planning; this wider sweep is the confirmation. If still zero: edit the `libraries/README.md` line 44 claim ("Depended on by most others") so it no longer names compat or logging, and add one sentence to `libraries/compat/README.md` stating it is a standalone polyfill no chumicro library currently requires. If hits exist: leave everything and note the finding in the commit body.
- [ ] **Step 3:** Preflight, commit: `readme: stop advertising parked logging, true up compat claims`

---

### Task 14: Phase 1 close-out

- [ ] **Step 1:** Full preflight green.
- [ ] **Step 2:** Check spec success criteria 1 and 2 (zero copied factory code: `find libraries -name sockets_factory.py` returns only the sockets one; three guides lead with generators).
- [ ] **Step 3:** Run the task-checkpoint skill: refresh `plans/next-up.md` (Phase 1 done inside the structural-pass bullet, Phase 2 next), lift lessons if any, commit, push the worktree branch.
- [ ] **Step 4:** Report to the user: what merged, the measured flash delta, template-repo status, and that Phase 2 (run.py decomposition) planning is next.

---

## Self-review notes

- Spec 1.1 → Tasks 1-9. Spec 1.2 → Task 10. Spec 1.3 → Task 11. Spec 1.4 → Task 12. Spec 1.5 → Task 13. Testing/migration mechanics → per-task preflight plus Tasks 7-8; the four-board device sweep runs at the user's bench discretion before stable relaunch (Phase 3), not per commit.
- Function names are consistent across tasks: `connector_factory`, `fixed_connector_factory`, `listener_factory`, `udp_socket_factory`, module `chumicro_sockets.sockets_factory`.
- Known judgment points left to the executor on purpose, each with a stated default: test patch technique mirrors each existing file, guide prose follows existing voice, coherence rules verified against core.py.
