# Workstream: deploy-bundle bloat overflows the minimum-tier flash

Status: **steps 1+2 complete; step 3 folds into ship-channel-manifest-unification.**  Step 2's closing bake landed 2026-07-03: the Pico W CP demo deploy ran exit-0 through the reduced-closure path and the board's `/lib/chumicro_test_harness` holds exactly the bootstrap closure (`network.py` / `patching.py` absent).  Step 3 (CP deploys drop the MP-only CA `.der`) is a target-runtime policy cell of the ship-channel resolver — tracked in [ship-channel-manifest-unification](ship-channel-manifest-unification.md).

## Problem

A *basic* demo can no longer be deployed to the minimum-tier board. Deploying
`demos/requests_fetch` (a one-shot HTTP GET) to a Raspberry Pi Pico W on
CircuitPython failed with `rsync: No space left on device`. The board reports
**~500 KB capacity, 2 KB free** after the deploy attempt. The same demo deploys
and runs fine on an ESP32-S2 CP board (4 MB) and on the Pico W under MicroPython
(mpremote, which does not stage onto the FAT drive the same way).

The user's read, and it is hard to argue with: "so much code bloat now that we
can't do a basic test without running out of disk space — the dependency bloat
and the sheer amount of boilerplate seems out of this world."

This is a tier-contract problem. [Decision 0015](../decisions/0015-board-architecture-support.md)
names 256 KB RAM / 2 MB physical / ~800 KB usable flash as the minimum board.
If a one-request demo cannot be staged there, the ecosystem has outgrown its own
stated floor.

## Measured 2026-06-13 — on the board, not the source tree

Corrected after reading the actual CIRCUITPY drive (the source-sum was misleading).
The deploy is already selective: a CircuitPython board carries **only** the CP adapter —
no `mp.py`, no host `cpython.py`, no `testing.py`. So `chumicro_sockets` on the board is
**~74 KB**, not the ~118 KB the source-sum suggested. What actually landed:

| File on board | Bytes | docstring+comment |
|---|---:|---:|
| `__init__.py` | 22.1 KB | **85%** |
| `_adapters/cp.py` | 18.0 KB | 68% |
| `_ca_bundle.der` | 16.4 KB | — (binary, not strippable) |
| `generators.py` | 9.7 KB | 72% |
| `_connector.py` | 7.2 KB | 74% |
| `_adapters/__init__.py` | 0.4 KB | 99% |

The deployed `.py` is **57 KB, of which 76% (44 KB) is docstrings + comments**.

## The fix is essentially one lever

**Flash-mode deploys ship docstrings verbatim.** RAM-mode inlines source through
`circuitpython_bootstrap._strip_docstring_from_body`; flash-mode `rsync`/`shutil.copy2`
copies raw `.py`. Apply the existing strip to the flash-stage path and `chumicro_sockets`
drops from ~74 KB to **~30 KB** (saving ~44 KB), and every other library shrinks by its
own docstring share. This also reconciles the verbose-docstring AGENTS rules with the
embedded flash budget: rich docstrings for maintainers, stripped on the device path.

Secondary: the 16 KB CA bundle is unconditional (a non-TLS user still pays it); and the
test-harness staging on the *demo* deploy path is what actually overflowed the Pico W CP.

Not a lever (verified on the board): per-runtime adapter selection already works — the
non-target adapter and the host adapter do not ship. An earlier note claimed otherwise from
a source-sum; the board disproved it.

(The 0087 "generators are leaner than coroutines" claim is about *runtime* — CircuitPython
allocates a fresh generator per `await`, asyncio carries a module + Task heap — not source
bytes. The generators.py file is 72% docstrings; the code is ~2.7 KB. Same docstring-on-flash
issue, not the mechanism.)

## Next steps

1. **Strip docstrings/comments on every device-stage path. SHIPPED** ([Decision 0090](../decisions/0090-deploy-strips-docstrings-and-comments.md)).
   `chumicro_deploy.source_minify.strip_source` blanks docstrings and `#`
   comments in place — line-preserving, behind an AST-equivalence guard that
   ships a file verbatim if the scan would alter its code. Both transports call
   `minify_python_tree` over the staging tree before transfer; RAM mode keeps
   its `ast.unparse` path and shares only the docstring-stripping transformer.
   Blanking rather than deleting was required so the on-device test runner's
   host-computed chunk boundaries still line up.
2. **Demo/app deploys stage only the harness bootstrap closure. SHIPPED (code;
   real-board bake pending).** A demo's bootstrap imports only
   `chumicro_test_harness.runner` + `.discovery` (closure: `__init__`,
   `assertions`, `skip`). `deploy_project` now mirrors the harness into a temp
   directory minus `network.py` (functional-test real-I/O helpers) and
   `patching.py` (unit-test fakes) before staging, dropping **14.8 KB of source
   / 6.7 KB on-flash after the step-1 strip** from every demo. The gate lives at
   the `deploy_api` entry point, not behind `include_test_support`: functional
   tests `import chumicro_test_harness.network` and deploy with the same
   `include_test_support=False` a demo uses, so that flag cannot tell a demo from
   a functional run. Functional and device-unit deploys (through pytest-device)
   still stage the full harness. Closing check owed: a Pico W CP demo bake to
   confirm the on-board drop and that the reduced harness still bootstraps.
3. **The 16 KB CA bundle is MicroPython-only — drop it on CircuitPython deploys.**
   Verified: `_ca_bundle.der` is read only by `_ca_bundle.read_der`, called only
   from `_adapters/mp.py`; `cp.py` calls `load_verify_locations(cadata="")` or a
   user PEM and never touches the shipped bundle (CP validates against its
   firmware x509-crt-bundle). On a CP board the 16 KB `.der` is dead weight, so a
   deterministic runtime drop beats the original "opt-in for non-TLS" framing and
   targets the exact board that overflowed. Blocker: the runtime filter
   (`__chumicro_runtimes__`, [Decision 0037](../decisions/0037-runtime-file-marking.md))
   marks `.py` files only; excluding a *data file* by runtime needs a marking
   convention — a sidecar marker, a runtime-suffixed name
   (`_ca_bundle.micropython.der`), or a per-library deploy manifest. Route that
   choice through `new-decision` before implementing. The MP non-TLS opt-out (a
   BYO-context user still pays 16 KB) stays a later, separate lever.

Boilerplate (copied `examples/helpers.py`, the inline runtime_config msgpack
decoder, repeated wifi-up scaffolding) and per-library size (chumicro_mqtt ~2x
the reference; the queued `/audit-embedded` passes) are real but secondary to the
docstring-strip win above — re-measure each after step 1 lands.

## Validation history

- 2026-06-13 — Step 1 shipped and baked on real boards. `deploy-example sockets
  tcp_roundtrip` to s2mini-cp (CP, flash) ran a full TCP round-trip; the deployed
  `chumicro_sockets` `.py` measured ~12 KB on the drive with no docstrings, down
  from the ~57 KB recorded above. The on-device unit sweep that overflowed before
  (`test-unit-on-device --library sockets --deploy-mode flash`) now stages and
  runs on the Pico W CP (256 KB): 49/65 pass, and the Pico W MP runs 65/65. The
  16 `test_udp.py` failures on CircuitPython are pre-existing — they reproduce
  identically with stripping turned off (a no-op `strip_source`) and on both CP
  boards regardless of heap, so they are a separate `test_udp.py`-on-CP defect,
  not a strip regression.
- 2026-06-14 — Step 2 (demo harness-core reduction) shipped host-side.
  `deploy_project` mirrors the harness minus `network.py` + `patching.py`;
  measured 14.8 KB raw / 6.7 KB on-flash dropped per demo via `strip_source`.
  `test_deploy_api.py` `TestDemoHarnessCoreReduction` asserts the mirror is
  exactly the bootstrap closure; the full workspace + deploy suites stay green
  (1953 passed). A Pico W CP demo bake is still owed to confirm the on-board byte
  drop and that the reduced harness still bootstraps a demo to completion.

## Why it matters

The generator-networking-apis demos validated on s2mini-cp (CP, 4 MB) and the
Pico W MP (264 KB RAM) but could not be staged on the Pico W CP — not for a RAM
reason, purely a flash-bundle-size reason. The minimum-tier contract should hold
for a basic demo, or the contract (or the deploy bundle) needs to change.
