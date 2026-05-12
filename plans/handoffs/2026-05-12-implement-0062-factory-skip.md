# Handoff 2026-05-12 — Implement Decisions 0062 + 0063 (factory-skip + duck-typed contract)

## What this session was about

User asked for a DI audit across `libraries/`.  The premise was a felt sense that "the DI isn't real" — libraries take factory parameters but their `pyproject.toml` deps and module-level imports drag the default transport along anyway, leaving custom-transport users with no actual opt-out.

The session walked through three tiers: Tier 1 (the mqtt module-level `chumicro_sockets` import leak, fixed and shipped), Tier 2 (the larger workspace-library-curation question), and Tier 3 (the duck-typed factory contract).  Bench-validation along the way disproved Decision 0042's claim of a deploy-time opt-out — the AST walker uses `ast.walk` and follows function-body imports, so the "factory helper in its own submodule" placement saves nothing on the device.

Two ADRs (0062, 0063) and one workstream landed as the design output.  Implementation is the next session's job.

## What got done

- **Commit `1dc581cd`** — combined commit: WhenOversized contract convergence (mqtt + requests + websockets, paired with Decision 0061 from a parallel agent) + DI Tier-1 sockets_factory submodules for mqtt + http_server.  VERSION bumps: mqtt 0.7.0→0.8.0, http_server 0.3.2→0.4.0, requests 0.4.0→0.5.0, websockets 0.11.4→0.12.0, events 0.2.0→0.2.1.
- **Commit `d9994b65`** — plans-only commit: Decision 0062 (entrypoint factory-skip mechanism), Decision 0063 (duck-typed factory contract), workspace-library-curation workstream, 0042 sub-rule rewritten in place to reflect bench-validated reality, next-up.md updated with `## Now` punch lists for both ADRs.

Both pushed to `origin/main`.

## To re-research / verify next session

After implementing 0062's walker change, **re-run the bench fixtures** to confirm the opt-out fires.  Fixtures were under `.scratch/ast-walker-check/` (gitignored, not on disk after `/clear`).  Recreate with:

```python
# .scratch/ast-walker-check/app_custom.py
from chumicro_mqtt import MQTTClient
__chumicro_skip_factories__ = ("chumicro_mqtt.sockets_factory",)  # add after walker change lands
def my_factory():
    raise NotImplementedError
client = MQTTClient(socket_factory=my_factory, client_id="x")
```

```python
# .scratch/ast-walker-check/app_default.py
from chumicro_mqtt import MQTTClient
client = MQTTClient.from_config({"mqtt.broker.host": "h", "mqtt.broker.port": 1883})
```

The pre-implementation bench (just `app_custom.py` without the constant) produced this output, which is the "before" baseline both apps need to **diverge from** after the walker change:

```
app_custom.py:  chumicro_sockets shipped = True   # WRONG — should be False once 0062 lands
app_default.py: chumicro_sockets shipped = True   # correct — default factory is used
```

Driver script for the bench (full path-setup) is in this session's history; key snippet:

```python
from chumicro_deploy.sources import ImportGraphSource
src = ImportGraphSource(
    entrypoint=Path(".scratch/ast-walker-check/app_custom.py"),
    search_paths=[Path("libraries/mqtt/src"), Path("libraries/sockets/src"), ...],  # all 6 chumicro infra libs
)
files = src.files()
has_sockets = any("chumicro_sockets" in p for p in files)
```

The "after" target: `app_custom.py` ships exactly `chumicro_mqtt/{__init__,_wire,client}.py` — no `sockets_factory.py`, no `chumicro_sockets/*`.  `app_default.py` ships all of it (no skip constant, default factory path active).

## Implementation punch list (lifted from `plans/next-up.md` ## Now)

### Decision 0062

1. **Walker change** — `workbench/deploy/src/chumicro_deploy/sources.py`.  The walker is `ImportGraphSource` at lines 205-340 ish.
   - Add AST-scan of entrypoint for `__chumicro_skip_factories__` module-level constant.  Mirror the pattern used for `__chumicro_runtimes__` reading (search `file_targets_runtime` in `workbench/deploy/src/chumicro_deploy/runtime_marker.py` for the precedent).
   - Build a discovered-factory-modules list from the search paths: every file matching `chumicro_*/[a-z_]+_factory.py`.
   - When resolving the import queue, filter modules whose path matches a skip entry (exact form via `.`-containing entries, family form via no-dot entries matching the last path segment).
   - Three diagnostic paths: typo (unmatched skip entry → fail the walk with clear error), direct-import override (skip target also referenced in user-app file outside the skip — keep the direct import, warn), dead-skip (skip target's parent library never imported anywhere — info warning).

2. **Per-library `try/except` wraps** in `from_config` for 5 libraries.  Sites:
   - `libraries/mqtt/src/chumicro_mqtt/client.py` — the lazy import at the bottom of `MQTTClient.from_config` (current shape: `from chumicro_mqtt.sockets_factory import (chumicro_sockets_factory,)`).  Wrap in `try/except ImportError → RuntimeError` with the exact message shape from 0062's Decision section.
   - `libraries/requests/src/chumicro_requests/client.py` — same pattern, `HttpClient.from_config`.
   - `libraries/websockets/src/chumicro_websockets/client.py` (and `server.py` if it also has one) — same pattern.
   - `libraries/ntp/src/chumicro_ntp/core.py` — `NTPClient.from_config` lazy-imports `chumicro_ntp.sockets_factory`.
   - `libraries/http_server/src/chumicro_http_server/server.py` — `HttpServer.from_config`, lazy-imports `chumicro_http_server.sockets_factory`.

3. **Bench validation** with the recreated fixtures above.  Both pre- and post-implementation outputs documented in 0062.

4. **Docs** — new "Slimming your deploy" page.  Two reasonable homes: `docs/contributing/` (mono-repo guide) or the workspace-template repo (user-facing).  Pick based on audience.  Should show exact form, family form, and the dep-tree-deselect interaction with `chumicro-workspace library add` (forward-reference to the Tier 2 workstream).

### Decision 0063

Documentation-only — no code logic changes.  Per-library docstring rewrites on the constructor's `socket=` / `socket_factory=` / `connection_factory=` / `listener_factory=` parameter — replace `"TCPClientSocket"`-style type names with the structural contract (`.recv_into` / `.send` / `.close` shape).  Add a `## Bring your own transport` section to each library's `docs/guide.md` with a non-chumicro example.

0063 can land in parallel with 0062 — no dependency.

## After implementation

Both ADRs flip from `proposed` to `accepted` once the walker change lands and the bench validates.  Edit 0062's status header and 0063's status header in place.  Move both Now-section entries to `## Done (recent)` (drop the oldest two to stay at the 25 cap).

## Dead ends — paths considered, rejected, don't re-walk

- **`pip install --no-deps` as the deploy-time opt-out.**  Doesn't address `mip`/`circup` on-device install, and that's where the real audience is.  Documented honestly in 0042's amended "What the rule does not solve" section.
- **Removing chumicro deps from pyproject.toml + relying on user awareness.**  Onboarding cliff that 0042 explicitly chose to avoid; no reason to revisit.
- **`importlib.import_module("chumicro_mqtt.sockets_factory")` to hide the import from the AST walker.**  Ugly, fragile, and the explicit-skip mechanism is cleaner.
- **Interprocedural call-site analysis** (walker reads user-app for `Class.from_config(...)` and infers whether the default branch is dead).  Real engineering, partial coverage.  Documented as alternative-considered in 0062.  Revisit only if the explicit-skip approach hits real-world friction.
- **Global cross-project skip** (`~/.chumicro/skip-factories.yml` or env var).  Reproducibility footgun.  Deferred in 0062 with explicit "revisit if 3+ users independently ask" criterion.
- **`typing.Protocol` for the factory contract.**  `typing` unavailable on MicroPython per Decision 0021.  Rejected in 0063's alternatives.

## How to rebuild context fast

Warm-up sequence for the implementing session:

1. **`git --no-pager log --oneline -20`** — last two commits are `d9994b65` (the design) and `1dc581cd` (the prior session's Tier 1 + WhenOversized).
2. **Read [`plans/decisions/0062-entrypoint-factory-skip.md`](../decisions/0062-entrypoint-factory-skip.md)** — load-bearing.  The mechanism is fully specified.
3. **Read [`plans/decisions/0063-duck-typed-factory-contract.md`](../decisions/0063-duck-typed-factory-contract.md)** — independent; can land first or second.
4. **Skim [`plans/decisions/0042-library-dependency-policy.md`](../decisions/0042-library-dependency-policy.md)** — sub-rule was rewritten in place; the corrected version explains *why* 0062 exists.
5. **`plans/workstreams/workspace-library-curation.md`** — Tier 2 follow-up; NOT in this session's scope but relevant context for any docs that mention `chumicro-workspace library` commands.
6. **`workbench/deploy/src/chumicro_deploy/sources.py:283-329`** — the AST walker (`_walk` + `_imports_from_file` + `_resolve_module`).  The `ast.walk` call at line 312 is the load-bearing line that makes lazy imports visible to the walker.
7. **`workbench/deploy/src/chumicro_deploy/runtime_marker.py`** — read this file for the `__chumicro_runtimes__` precedent.  0062's `__chumicro_skip_factories__` should mirror this implementation shape (read constant via AST, no module execution).

Useful greps:

```bash
# Find every from_config that needs the try/except wrap:
grep -rn "from chumicro_.*\.sockets_factory import\|from chumicro_.*\..*_factory import" libraries/

# Find existing factory submodules (the discovered list):
find libraries/ -path '*/src/chumicro_*/*_factory.py'
```

## Open questions waiting on user

- **AGENTS.md addition** for `__chumicro_skip_factories__`.  User said "add later" — should land after 0062 implementation moves to `accepted` status.  One line under whichever section makes most sense; entrypoint-level constants aren't currently a documented topic in AGENTS.md (only library-level shape rules are).
- **"Slimming your deploy" docs home** — mono-repo `docs/contributing/` vs workspace-template repo.  Probably workspace-template (it's where users live) but mono-repo audience may also want it for contributors writing factory-injecting libraries.  Worth raising before writing the doc.

## Gotchas

- **`ast.walk` traverses function bodies** (sources.py:312).  This is the load-bearing reason 0042's original opt-out claim didn't work.  Don't introduce a fix that relies on "lazy imports won't be followed" — they will.
- **The walker probes both module and name forms** for `from foo.bar import baz` (sources.py:319-328).  When designing the skip-name matching, remember `_resolve_module` silently returns `None` for names that don't resolve to a file — typos won't be caught by resolution alone, which is why 0062's typo-guard diagnostic is a separate check before resolution.
- **CHU011 caps each top-level `next-up.md` bullet at 5 lines including sub-bullets.**  This bit me drafting the punch list — had to drop a meta sub-bullet.  When adding implementation entries to `## Now`, count carefully.
- **Workspace-template repo and chumicro mono-repo are separate.**  When the docs page or any user-facing prose mentions `__chumicro_skip_factories__`, remember the workspace template repo is at `~/circuitpython/ChuMicro-Workspace-Template` and has its own publishing path (per the memory note about two-repo layout).  Mono-repo refs like "Decision NNNN" or `plans/...md` paths shouldn't leak into the workspace-template starter — CHU006 enforces this.
- **`from_config` API contract under 0062's `try/except` wrap.**  The error message names the bypass kwarg.  Make sure each library's wrapper names the right kwarg — mqtt has `socket=` AND `socket_factory=`, http_server has `listener_factory=` only, requests has `connection_factory=`, etc.  Match the existing constructor surface.
