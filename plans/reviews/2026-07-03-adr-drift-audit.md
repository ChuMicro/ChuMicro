# ADR drift audit — 2026-07-03

Full audit of every architecture decision record in `plans/decisions/` against
the current state of the codebase. Read-only pass; nothing else touched.

**Corpus:** 93 ADRs on disk (`0001`–`0094`; `0050` is a numbering gap, no file).
**Verdict counts:** SOUND 81 · STALE 3 · CONSTRAINING 4 · DEAD-and-correctly-marked 5.
**Method:** every ADR read in full; the runner, sockets, mqtt, deploy/staging,
workspace, and `chumicro-checks` subsystems reality-checked against source with
file:line citations; `check_api.py` / `check_version.py` / git log cross-read.

Legend:
- **SOUND** — matches reality, still earning its keep.
- **STALE** — body no longer matches code or a later decision; needs an in-place edit.
- **CONSTRAINING** — the decision itself is now suspect; it governs but blocks a better design (deep-dive below).
- **DEAD** — inert or superseded; here all five are *correctly* marked per Decision 0076.

---

## 1. Full table

| # | Title | Verdict | One-line reason |
|---|-------|---------|-----------------|
| 0001 | Mono-workspace layout | SOUND | `libraries/`, `workbench/`, `support/` all present as described. |
| 0002 | Per-library version files | SOUND | Every lib/workbench pkg has a `VERSION`; `check_version.py` enforces with the 0.0.0 floor. |
| 0003 | Test & runtime boundaries | SOUND | pytest + unix-port + device-lane pyramid intact; rests on 0049. |
| 0004 | INERT sample library first slice | DEAD | Correctly `INERT`-marked; timing seam shipped, deferred seams all built. |
| 0005 | INERT windows/wsl2 unix-port | DEAD | Correctly `INERT`-marked; native-Windows deploy is now hard-refused. |
| 0006 | SUPERSEDED-BY-0016 smoke runner | DEAD | Correctly marked; `run_device_smoke.py` gone, `run_cross_runtime.py` is the heir. |
| 0007 | Cross-platform dependency strategy | SOUND | Re-implement-not-Blinka + three channels still the rule (ticks owned in-tree). |
| 0008 | SUPERSEDED-BY-0009 importlib isolation | DEAD | Correctly marked; per-library pytest runs replaced it. |
| 0009 | Per-library test runs | SOUND | `run.py test` fans out per-package; root importlib mode retained for workbench collisions. |
| 0010 | Library & workbench testability | SOUND | Constructor injection + per-lib `testing.py` fakes universal; root of the DI cluster (see C3). |
| 0011 | Per-library platform targeting | SOUND | `[tool.chumicro].platforms` read by pytest-device + release gates. |
| 0012 | IDE type stubs | SOUND | `circuitpython-stubs` + `micropython-esp32-stubs` pinned via `target-runtimes.toml`. |
| 0013 | Docs & examples standards | SOUND | README+docs+examples slot shape holds; `examples/helpers.py` still the pattern (0082 aims to replace, unbuilt). |
| 0014 | Runner pattern | **STALE** | Body + runner README still document `add(check_fn, handler=fn)` callable-registration; **code removed it** (`core.py:316-321` raises ValueError). |
| 0015 | Board architecture support tiers | SOUND | 256 KB / 2 MB floor cited across the corpus and `[heap]` budgets (0094). |
| 0016 | Cross-runtime unit tests | SOUND | Markers + plugin path intact; still cites `support/test_harness/` (correct until 0082's move lands, which it hasn't). |
| 0017 | CircuitPython RingIO workaround | SOUND | `prepare_circuitpython.py` still carries the self-removing flag. |
| 0018 | Distribution bundle repository | **CONSTRAINING** | Elaborate two-repo/dual-mpy release model, never once published; 0078 bolts on a *second* repo pair. See C4. |
| 0019 | Branching model | SOUND | Single-`main` + tags model accurate; release side unexercised but the branch policy stands. |
| 0020 | API breakage detection (griffe) | **CONSTRAINING** | `check_api.py:186` still FAILs (CI gate, `ci.yml:169`) on break+patch-bump — directly contradicts 0092's "never block a break." See C1. |
| 0021 | Docstring/type policy | SOUND | No `typing`, PEP 604/585 on signatures; enforced by griffe + review. |
| 0022 | Naming conventions (CHU001) | SOUND | CHU001 present and registered. |
| 0023 | Standalone promote workflow | SOUND | Accurate `promote.yml` description; part of unexercised release infra (see C4) but the mechanism decision holds. |
| 0024 | Mip/circup mpy folder serving | SOUND | Accurate `mpy6/` + `circuitpython-10.x-mpy/` description; unexercised (see C4). |
| 0025 | Dual coverage thresholds | SOUND | 85/94 split accurate; ADR is unusually honest about the post-pragma CPython-only scope. |
| 0026 | Editable installs | SOUND | `run.py setup` editable-installs libs + support packages. |
| 0027 | Device testing infrastructure | SOUND | mpremote/pyserial/pytest-device transport + `devices.yml` schema intact. |
| 0028 | Deploy modes RAM/flash | SOUND | Accurate; RAM-mode complexity is the C5 watch, not a body error. |
| 0029 | Project workspace shape | SOUND | §1 restored by 0038, §7 superseded by 0046 — both edited in place; rest holds. |
| 0030 | Config vs persisted state | SOUND | Read-only config pipeline + `chumicro-kvstore` split live. |
| 0031 | chumicro-sockets | SOUND | All factories present (`__init__.py:52-66`); §2 blocking-connect promise amended in place by 0081. |
| 0032 | Workbench folder | SOUND | `workbench/` = checks/deploy/pytest-device/repl/workspace, PyPI-only. |
| 0033 | macOS CIRCUITPY hardening | SOUND | FSKit detect + xattr/dot_clean/sync logic in `flash_drive.py`/`macos_fskit.py`. |
| 0034 | kvstore API & backends | SOUND | `KVStore` + `_backends/` shape live (kvstore 0.3.0). |
| 0035 | SUPERSEDED-BY-0036 runtime config | DEAD | Correctly marked; `chumicro-config` is the heir. |
| 0036 | chumicro-config library | SOUND | `RuntimeConfig`/`load_section`/`from_config` flat-key shape live. |
| 0037 | Runtime file marking | SOUND | `__chumicro_runtimes__` AST filter live; amended in place by 0044/0069. |
| 0038 | Workspace bootstrap via clone | SOUND | §3 partially superseded by 0075 (edited); clone-only + `update` accurate. |
| 0039 | Firmware version floor | SOUND | `firmware_support.py:21,24` = (1,27,0)/(10,1,0), warn-not-block. |
| 0040 | chumicro-requests | SOUND | Runner-shaped `HttpClient` (requests 0.16.2) + generator surface (0089). |
| 0041 | chumicro-http-server | SOUND | Runner-shaped server (http_server 0.16.0), TLS-listener carve-outs accurate. |
| 0042 | Library dependency policy | **CONSTRAINING** | Its hard-dep + factory-helper-submodule mandate spawned the 0062/0063/0093 patch chain; sub-rule was bench-disproved. See C3. |
| 0043 | chumicro-sockets UDP | SOUND | `udp_socket`/`FakeUDPSocket` present. |
| 0044 | Deploy-time runtime filtering | SOUND | `runtime_marker.py` filters at every host copy boundary. |
| 0045 | chumicro-websockets | SOUND | Client+server library (websockets 0.23.1) + `next_message` (0089). |
| 0046 | libs/→shared/, lazy libraries/ | SOUND | Workspace-template folder-shape decision (template-repo-facing; internally consistent). |
| 0047 | Deploy-mode flash default | SOUND | `DEFAULT_DEPLOY_MODE = "flash"` (`device.py:31`); §3 unified by 0068. |
| 0048 | Preflight phase-level parallelism | SOUND | §3 superseded by 0054 (edited); phase fan-out live. |
| 0049 | Three-runtime trinity | SOUND | Founding principle; CPython-as-test-seam holds everywhere. |
| 0051 | Runner-shaped as project policy | **CONSTRAINING** | The gate-based + no-async lock drove a from-scratch cooperative scheduler and two coexisting service shapes. See C2. |
| 0052 | Workbench no-library-imports | SOUND | CHU007 enforces; workbench src clean (only payload templates reference libs). |
| 0053 | Recovery-layer philosophy | SOUND | `DeployFailureKind` closed-set + coaching live. |
| 0054 | Streaming output & status modes | SOUND | Dispatchers live; body already notes 0092 retired its alias. |
| 0055 | Config pipeline unification | SOUND | `config_manifest.py` + `pipeline.compose_runtime_config` live. |
| 0056 | Transport extra_files staging | SOUND | `stage(extra_files=...)` binary-staging path present. |
| 0057 | Workspace-config file shape | SOUND | `workspace.yml`/`secrets.toml`/`project_config.toml` three-file split live (title still says "two-file"). |
| 0058 | Test skips must be loud | SOUND | CHU009/CHU010 present; `chumicro_test_harness.skip` primitive live. |
| 0059 | deploy-example front door | SOUND | `deploy-example` subcommand live; §1 collapsed onto one path by 0077 (edited). |
| 0060 | chumicro-checks package home | SOUND | `workbench/checks/` publishes the CHU family. |
| 0061 | WhenOversized cross-library contract | SOUND | `on_oversized(reported_length, topic)` confirmed (`mqtt/client.py:1627`). |
| 0062 | Entrypoint factory skip | SOUND | `__chumicro_skip_factories__` walker + typo/dead-skip diagnostics in `sources.py`. |
| 0063 | Duck-typed factory contract | SOUND | Duck-typed, no Protocol/ABC; examples still say `socket_factory` (mqtt uses `connector_factory` — see contradictions). |
| 0064 | mqtt three-tier + prefix sugar | **STALE** | `MQTTPublisher`/`publisher()` (§5) **absent** in code; `socket_factory` kwarg renamed to `connector_factory`. Three-tier itself is live. |
| 0065 | Device-library scaffolding cost | SOUND | No-`__slots__`/no-passthrough-`@property` policy; enforced by `/audit-library`. |
| 0066 | Agent-runnable CLIs | SOUND | TTY auto-detect + `--non-interactive` + distinct exit codes live across CLIs. |
| 0067 | MP TLS default trust | SOUND | `_ca_bundle.der` (17 roots, 16366 B) + secure-by-default MP path (`_adapters/mp.py:216`). |
| 0068 | Unified deploy-mode resolution | SOUND | Single `resolve_deploy_mode` shared by Deployer + pytest-device; `supports_ram_mode` schema present. |
| 0069 | Test-support module marker | SOUND | `is_test_support_module` + `__chumicro_test_support__` live. |
| 0070 | Host-only test marker | SOUND | `is_host_only_test` + `__chumicro_host_only__` live; three-marker inventory intact. |
| 0071 | Per-library soft-reset flash sweep | SOUND | `clear_entrypoints()` + per-library reset in pytest-device. |
| 0072 | Large test modules on constrained boards | SOUND | Chunked exec + `--per-file` reset; heap debt tracked (see 0094 payoff). |
| 0073 | msgpack decode trust boundary | SOUND | Trusting-decoder hardening decision (msgpack 0.2.1); CRC stays per-substrate. |
| 0074 | Lintable drift must be mechanized | SOUND | CHU014-017 shipped; policy in force. |
| 0075 | Retire init — clone-only | SOUND | No `init` subcommand exists; `template_apply` reduced to `update`/`materialize`. |
| 0076 | Archive dead decisions in filename | SOUND | CHU019 enforces status/marker/header agreement. |
| 0077 | One device-staging path | SOUND | `Deployer.deploy()` deleted; `deploy_diff` clean-slate default, keep-set = `{boot.py,boot_out.txt,_chu_kv.msgpack}` (`flash_drive.py:366`). |
| 0078 | Library acquisition is host-local | SOUND | `library add`/`browse`/`list` + `ChuMicro-Libraries` channel live (`cli/library.py`); adds a 2nd repo pair (feeds C4). |
| 0079 | Prose drift mechanization | SOUND | CHU020/024-028 shipped; CHU021/022/023 correctly absent per the ADR. |
| 0080 | Runner reactor / central wait | SOUND | `Runner.wait` + `io_socket`/`io_wants_*` reads (`core.py:549,762`). |
| 0081 | Library network I/O is non-blocking | SOUND | Connector factories live; 0031 §2 amended in place. |
| 0082 | Test-harness as infrastructure library | **STALE** | Claims test_harness "lives at `libraries/test_harness/`" & "`support/` dissolved" & browse filters `kind`; **none shipped** — `support/test_harness/` still exists, no `kind` field. |
| 0083 | Functional-test endpoint taxonomy | SOUND | Category-1 host fixtures under `chumicro_pytest_device.fixtures/` live. |
| 0084 | gc.collect() policy | SOUND | Three-context policy; lives in AGENTS.md. |
| 0085 | Board-to-host stdout markers | SOUND | Streaming transport landed (git `0069a96a`); `marker()` board helper. |
| 0086 | Programmatic deploy API | SOUND | `deploy_api.deploy_project`/`DeployedProject`/`markers`/`device_runner` present; demos consume them. |
| 0087 | Generators for sequential I/O | SOUND | `add_generator`/`GeneratorHandle` + CHU033 async-ban live. |
| 0088 | Periodic phase anchoring | SOUND | `preserve_phase` kw on `add`/`add_periodic`. |
| 0089 | Generator surfaces on networking libs | SOUND | `next_message`/`InboundPublish` in mqtt 0.20.x, requests, websockets. |
| 0090 | Deploy strips docstrings/comments | SOUND | `source_minify.py` called from all 4 staging sites. |
| 0091 | Event-wait tokens | SOUND | `Signal`/`wait_for` in `chumicro_runner.generators`. |
| 0092 | No backwards compat before publication | SOUND | Sweep executed (git `73568121`, `a6ddf8c7`); but its "check-api/version never block" claim is false in code (see C1). |
| 0093 | Transport-factory contract | SOUND | Side-effect-free construction confirmed (mqtt `client.py:361`); ntp 0.11.0 aligned. |
| 0094 | Board-shaped heap budgets | SOUND | `target-runtimes.toml [heap]` + `-X heapsize` in unix-port lanes. |

---

## 2. CONSTRAINING deep-dives (ranked — the payload)

### C1 — Decision 0020 (SemVer breakage gate) now contradicts 0092 and blocks the "breaks are free" workflow

**What it optimized for.** 0020 (2026-04-05) wired `griffe check` into CI so a
breaking API change published as a *patch* release fails: "Breakages detected +
patch bump → FAIL … Once a library reaches 1.0.0, major bumps are required."
It exists to protect **downstream consumers** from silent breaking releases.

**What today's evidence says.** Nothing has ever been published — 0092
(2026-07-03) is explicit: "Nothing in this workspace has ever been published; it
has iterated privately for months," and declares breaking changes *free*:
"`check-version` and `check-api` remain as change-awareness gates (they describe
what changed), **not as compatibility contracts (they never block a break**)."

The code says otherwise. `scripts/check_api.py:184-190` still emits
`FAIL: … API breakages detected but VERSION bump is only '<patch>'`, returns
`False`, and the comment block above it cites "See Decision 0020." It is a live
CI gate (`.github/workflows/ci.yml:169`) and a `preflight` phase
(`scripts/run.py:1845`). So a 0092-style "break and migrate all consumers in one
commit" still reddens CI unless the same commit *also* carries a SemVer-correct
VERSION bump — the exact compatibility ceremony 0092 set out to abolish.
`check_version.py:99-105` is the sibling: release-relevant change without a bump
also exits 1 (softened only by the 0.0.0 floor).

**Replacement decision.** Demote the *breakage-vs-bump* enforcement to
warn-only until first publication: print the griffe diff and the "you may want a
minor bump" nudge, but `return 0`. Keep VERSION bumps as informational
change-awareness (which is all 0092 asks). Re-arm the gate at first publication,
where 0092 self-retires and a real SemVer/deprecation policy replaces it.

**Blast radius.** Small and contained: `scripts/check_api.py` (turn the FAIL
branch into a non-fatal warning), the `check-api` CI job, and the preflight
phase list. Zero library code. The only thing lost is the "did you forget to
bump" nudge — preserved as printed output.

---

### C2 — Decisions 0051 + 0014 (gate-based `check/handle` + the async ban) locked a shape that forced a from-scratch cooperative scheduler and two coexisting service models

**What it optimized for.** 0014 (2026-04-02) made `check(now_ms) -> bool` +
`handle(now_ms)` *the* service contract; 0051 (2026-05-04) elevated it to
project policy and banned `time.sleep`, blocking `poll`, and async. The stated
wins: transparency ("a plain `while True:` the developer can read, breakpoint,
and single-step"), no hidden scheduler, MP/CP portability, and avoiding
asyncio's broken-on-CP stream layer + blocking `getaddrinfo`.

**What today's evidence says.** The project has since rebuilt, ADR by ADR,
exactly the machinery an event loop provides — just hand-rolled:

- 0080 (runner reactor): a central `ipoll`-based `wait()` and duck-typed
  `io_socket`/`io_wants_read`/`io_wants_write` interest reads.
- 0087 (generators for sequential I/O): `runner.add_generator()` + `yield from`
  coroutines + `chumicro_sockets.generators`, driven by `.send()` with bespoke
  wait-tokens — "the same architectural posture trio and curio take."
- 0091: `Signal`/`wait_for` completion tokens, a bare-`yield` next-tick token,
  and indefinite `ipoll(-1)` parking.
- 0089: `next_message()` receive-stream generators on three libraries.

0087 concedes the cost in its own words: "**Two service shapes is real
conceptual overhead.**" The runner (0.16.1) now carries *both* a reactive
`check/handle` model *and* a generator-coroutine model with its own wait-token
protocol — an event loop in all but name, with the maintenance surface of one.
The entire 2026-05→07 ADR run (0080/0087/0089/0091) is scheduler catch-up work
that the original gate-based framing deferred.

**Replacement decision (adversarial).** The asyncio *rejection* stands on real
evidence (Adafruit CP stream layer issue #4; MP's blocking `getaddrinfo`). What
is suspect is 0014's choice of `check/handle` as the *primary* contract. Had the
runner been generator/coroutine-first over its own scheduler (which 0087 proves
is viable on all three runtimes), the reactive gate could have been a thin
adapter instead of a co-equal model — collapsing two shapes to one and
pre-empting the 0080/0087/0089/0091 sequence. This is not "adopt asyncio"; it is
"the generator substrate, not `check/handle`, should arguably have been the base
contract."

**Blast radius.** Very large and mostly *historical*: `chumicro-runner` core,
every networking library's service shape, all demos, and 5+ ADRs. This is a
design-debt flag, not an actionable flip today. The near-term slice: 0014's body
is independently STALE (it still documents the removed callable registration),
and 0051/0014 should acknowledge the standing two-shape cost rather than present
`check/handle` as the single shape.

---

### C3 — Decision 0042 (constructor-injection + factory-helper mandate) spawned a five-ADR patch chain to make injection deploy cleanly

**What it optimized for.** 0042 (2026-04-27), building on 0010's
inject-everything testability stance, tried to soften the "onboarding cliff"
it names in its own Context ("*What sockets lib? You mean I have to download
chumicro-sockets too?*"). Its fix: declare the hard dep, ship a
`chumicro_<infra>_factory()` helper in a *separate submodule*, keep the
constructor parameter explicit, and **forbid** auto-defaulting inside the
constructor.

**What today's evidence says.** The factory-helper-in-a-submodule sub-rule was
supposed to give a *deploy-time* opt-out. 0062 (2026-05-12) records it
**bench-disproved**: "the opt-out does not fire … `ast.walk` traverses function
bodies, so `from_config`'s lazy import … is discovered statically and followed."
That required a whole new mechanism — the `__chumicro_skip_factories__`
entrypoint marker plus walker typo/dead-skip/override diagnostics
(`chumicro_deploy/sources.py:359-552`). Then 0063 added a duck-typed-contract
documentation ADR because docstrings hard-typed the factory as
`TCPClientSocket`. Then 0093 (2026-07-03) found the five networking libraries had
drifted into **three incompatible factory contracts** (M77) and re-aligned them —
while explicitly accepting "~65 lines/library" of duplicated factory plumbing
rather than a shared package. That is one testability decision (0010→0042) and
four follow-on ADRs plus a deploy-walker feature, and the naming *still* drifted:
0064/0042/0063 say `socket_factory`; the mqtt code says `connector_factory` /
`chumicro_sockets_connector_factory` (`mqtt/client.py:317`).

**Replacement decision.** Re-open 0042 §3's flat ban on constructor
auto-defaulting. A `default_transport()`-style secure default wired *inside* the
constructor (injection as the override) would let the common path need no factory
submodule, no skip-marker, and no per-library duplication. The deploy-slimming
that `__chumicro_skip_factories__` buys (dropping `chumicro_sockets` for a
custom-transport user) is real but serves a rare audience; weigh it against the
machinery it imposes on every library and every new-library scaffold.

**Blast radius.** Medium-large: five networking libraries' constructors +
`from_config` + `sockets_factory.py` submodules, the deploy walker's skip logic,
CHU/scaffolder support, and per-library docs. A genuine flip, but high-value to
at least re-cost now that 0092 makes the break free.

---

### C4 — Decision 0018 (two-repo dual-mpy bundle distribution) is elaborate release infrastructure that has never shipped a single artifact and is already duplicated

**What it optimized for.** 0018 (2026-04-04) + 0024 designed a full
three-channel (PyPI/mip/circup), stable+experimental release architecture:
separate `ChuMicro-Bundle` / `ChuMicro-Bundle-Experimental` repos, dual mpy
folders (`mpy6/` magic-`M` for mip, `circuitpython-10.x-mpy/` magic-`C` for
circup), date+sequence tags, OIDC promote pipeline (0023), per-channel
`package.json`.

**What today's evidence says.** 0092 states plainly the workspace "has never
been published … iterating privately for months" — so none of this machinery has
been exercised end-to-end. Worse, it is already *duplicating*: 0078
(2026-05-18) adds a **second** pair of repos (`ChuMicro/ChuMicro-Libraries` +
`-Experimental`, `library_channel.py:45-46`) because the bundle repos are
package-only and can't carry the source trees the workspace actually consumes
via `library add`. The one channel the codebase truly uses today is that 0078
source-snapshot channel; the bundle/mpy/circup half is design-only. The git log
shows an active `ship-channel-manifest-unification` workstream still converging
the channel model (`a00b9f75`) — i.e. the "settled" distribution architecture is
still moving, with zero publications validating any of it.

**Replacement decision.** Apply 0092's own spirit to release infra: mark the
bundle/mpy/circup ADRs (0018/0024, and the promote mechanics they anchor) as
*design, unbuilt* and treat the 0078 source-snapshot channel as the single
exercised path. Defer the mpy/circup/PyPI split — and the stable/experimental
doubling — until a real first publication forces the actual constraints, rather
than maintaining four repos' worth of unvalidated release design as if
load-bearing.

**Blast radius.** Distribution tooling + CI only:
`scripts/bundle_manager.py`, `libraries_channel.py`, `release.yml`,
`promote.yml`. No device or library code. The change is a posture shift — stop
treating the bundle channel as a committed contract — not a deletion.

---

### C5 — (watch, lower-ranked) the RAM-mode CircuitPython raw-REPL subsystem (0027/0028/0033/0068/0071/0072/0090)

Not a flip — 0068 (2026-05-15) already adjudicated it and kept it — but flagged
because the user's "some core designs are wrong" thesis fits here too. The
CP RAM-mode raw-REPL path drags an outsized complexity tail: class-as-module
injection (0027), the macOS FSKit-wedge detector (0033), live-heap-probed
chunking (0028), unified-resolver data-file exceptions (0068), per-library +
opt-in per-file soft-reset (0071/0072), and in-place source-minify (0090). 0068
records that "**rip RAM mode out entirely** … was seriously considered" and would
be "a relatively clean excision and a large code reduction," kept only because
"most libraries *are* RAM-capable" and "the subsystem is already written." That
"already written, so keep it" is the momentum reasoning 0092 targets elsewhere;
worth a scheduled re-cost against a flash-only on-device sweep. The ADR bodies
themselves are accurate (hence SOUND in the table); the *design* is the debt.

---

## 3. Cross-contradictions and missing ADRs

### 3a. Pairs that now disagree

1. **0020 ↔ 0092 (live, sharp).** 0092: "check-version and check-api … never
   block a break." Code: `check_api.py:186` returns FAIL/exit-1 on
   break+insufficient-bump, gated in `ci.yml:169` and preflight; the FAIL branch
   cites "Decision 0020." `check_version.py:99-105` blocks release-relevant
   change without a bump. The two ADRs cannot both be true of the current CI.
   (Deep-dive C1.)

2. **0014 ↔ runner code + 0092 (doc-vs-code).** 0014's "Three registration
   patterns" and `libraries/runner/README.md` (~L196-205) still teach
   `add(check_function, handler=function)`. `core.py:316-321` now raises
   `ValueError` ("the separate check-plus-handler shape was removed") — the
   removal 0092 seeds. The ADR body and README are the stale side.

3. **0064 / 0042 / 0063 ↔ mqtt code (naming).** These ADRs name the injected
   factory `socket_factory` / `chumicro_sockets_factory`. mqtt ships
   `connector_factory` (`client.py:317`) and `chumicro_sockets_connector_factory`
   (`sockets_factory.py:11`). 0093's "connector" reshaping landed in code but the
   older ADRs weren't edited to match.

4. **0064 §5 ↔ mqtt code (absent surface).** 0064 specifies a `MQTTPublisher`
   topic-binder and `MQTTClient.publisher(...)` factory. Neither exists anywhere
   in `libraries/mqtt/src/` (grep-confirmed absent). The three-tier decode,
   `root_topic`, `prefixed=`, and `remove_pattern_handler` from the same ADR *are*
   present — so 0064 is STALE on §5 only.

5. **0082 ↔ reality (unbuilt decision).** 0082's decision sentence — test_harness
   "lives at `libraries/test_harness/`", "`support/` is dissolved", and
   `library browse`/`list` "filter `kind == "infrastructure"`" — is false on all
   three counts: `support/test_harness/` still exists, there is no
   `libraries/test_harness/`, and `LibraryCatalogEntry` has no `kind` field. The
   AGENTS.md import-name rule it also states (`chumicro_test_harness`) *is* honored,
   so the invariant holds while the mechanism it prescribes never landed.

6. **Resolved-in-place (noted, not live):** 0031 §2 ↔ 0081 (blocking-connect
   promise) and 0042 sub-rule ↔ 0062 (deploy opt-out) were both corrected by
   in-place edits to the older ADR — the model the README prescribes. Left here
   only so a reader doesn't re-flag them.

### 3b. Load-bearing decisions with NO ADR (missing records)

1. **The `webui/` picker subsystem (~2,500 LOC).** `webui/server.py`,
   `session.py`, `render_picker.py`, `serve_picker.py`, `picker_edit_gate.py`,
   `kit.py`, `theme.py` — a full host-side web UI with a session model and an
   edit-gate. **No ADR mentions `webui` or `picker`** (grep of `plans/decisions/`
   is empty). A `repl-playground` workstream exists but there is no decision
   record for the picker/webui shape. This is the largest un-ADR'd subsystem.

2. **Ship-channel manifest/selection contract.** git log `a00b9f75`
   ("ship-channel selection: verified converged, contract pinned") and the
   `ship-channel-manifest-unification` workstream pin a distribution-selection
   contract with no ADR — a load-bearing release decision that sits between
   0018 and 0078 and should be recorded (especially given C4).

3. **`Runner.run_until(handle)`** (runner 0.16.0, git `0aa0a126` "demos lose
   their tail loops"). New public runner surface; neither 0014 nor 0080 mention
   it. Minor.

4. **Un-ADR'd CHU rules.** `CHU029` (ADR `Summary:` required), `CHU031`
   (noqa ` - ` separator), `CHU032` (no cross-reference pointer phrases in
   comments) are registered and active but appear in no ADR (0079 introduced the
   engines but not these codes). The whitespace family CHU002-005/018 and CHU013
   are also un-ADR'd but trace to existing policy (0021/0014). Minor.

5. **Corpus note — `0050` gap.** No ADR `0050` exists; the sequence jumps
   0049→0051. Harmless (CHU019 guards *duplicate* prefixes, not gaps), but worth
   a one-line note so a future reader doesn't hunt for it.

---

## Appendix — reality-check provenance

Verified against source (file:line in the deep-dives/contradictions above):
runner `0.16.1` (callable-registration removal, `add_generator`, `wait`,
`Signal`/`wait_for`, single `next_deadline`), sockets `0.15.1` (13 factories,
17-root DER bundle, secure-by-default MP TLS), mqtt `0.20.1` (three-tier decode
live, `next_message`/`InboundPublish`, `MQTTPublisher` absent,
`connector_factory` naming), chumicro-deploy `0.36.0` (`deploy()` deleted,
keep-set, `source_minify`, `resolve_deploy_mode`, recovery kinds,
`__chumicro_skip_factories__`), chumicro-workspace `0.44.0` (deploy_api, markers,
device_runner, library-add channel, init removed, firmware floor,
config_manifest; `kind`-filter absent), chumicro-checks `0.15.0` (30 rules;
CHU021/022/023 correctly absent, CHU033 present), and `check_api.py` /
`check_version.py` / `target-runtimes.toml [heap]` / `support/test_harness/` /
recent git log.
