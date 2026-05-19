# Handoff 2026-05-18 — deploy-path unification Phase 0/1/2 (through delta 6)

## What this session was about

Started as next-up cleanup ("help clean up next-up"), expanded by user
direction into executing the whole **deploy-path-unification**
workstream. Drove it from a freshly-opened workstream to: Decision
0077 `accepted`, Phase 1 done, Phase 2 Commits 1a/1b/2a/2b + delta 6
done — all bench-verified on real hardware. ~14 commits this session
(`c419ad2a` … `1adfc045`).

## What's in flight

Nothing uncommitted — working tree clean as of write. The pickup is
**Phase 2 Commit 2c (entrypoint-as-payload, delta 5)**; everything
before it is committed + bench-verified.

## What got done (commit SHAs)

- `c419ad2a` preflight `_env` fix (Phase 1) + backlog-zombie cleanup
- `ddb5d51f` Decision 0077 written `proposed` (Phase 0)
- `de85343a` repl `chumicro_timing` regression root-caused
- `38046b19` Phase 2 scope + cross-workstream reconciliation
- `dbf62986` 1a: `repl <project>` retired → `deploy --tail`
- `09282b6d` 1b: CP empty-dir reaping
- `1b70e2d9` 2a: keep-set unification + `settings.toml` eviction
- `4706b59b` "the one X" AI-tic fix + CHU020 filed
- `3738c3e8` 2b: clean-slate default-flip + **0077 `accepted`** + 0059 §1 edited in place + AGENTS.md non-negotiable
- `1adfc045` delta 6: MP whole-device clean-slate

## Decisions made (captured — pointers, not re-explained here)

- Decision 0077 (`accepted`) is the invariant of record. 0059 §1 +
  its Rejected bullet were edited *in place* (partial supersession;
  0059 stays `accepted`).
- The repl reframe: user asked "why does repl deploy at all?" → fix
  by *elimination* not dedupe (`repl <project>` retired, deploy-watch
  moved to `deploy --tail`). Rationale in `dbf62986` + workstream.
- settings.toml evict + one-time warning, clean-slate default,
  seams-before-convergence sequencing — all user-decided, in
  workstream "Sequencing" + Phase 2 deltas.

## What was learned (routed; pointers only)

- MP `_clean_slate_device` must run via an mpremote `exec`
  *subprocess*, not the persistent serial — `deploy_files`
  `_close_serial()`s before it and the following `fs cp` is a
  subprocess; holding the serial fails that push "port in use".
  `[VERIFIED: bench Pi Pico W MP — first attempt failed exactly this
  way, fix re-benched green]`. Captured inline in
  `micropython_transport._clean_slate_device` + commit `1adfc045`.
- The "two protection sites" the user flagged were Site A (clean
  exclude tuple) + Site B (`_list_scope_on_drive` omission); now one
  `flash_drive.DEVICE_KEEP_SET`. Full reasoning in the workstream
  Phase 2 delta 2.

## Riskiest assumption

**MP delta 6 is bench-verified only on the `deploy(clean=True)` /
`deploy-example` path (`_clean_slate_device`), NOT on the MP CLI
*diff* path (`deploy <project>` → `list_files_in_scope(clean_slate=
True)` → `_LIST_ALL_SCRIPT`).** The diff path on MP is unit-tested
only `[HYPOTHESIS: cheapest test = register the MP Pico W in a
workspace's devices.yml, plant /settings.toml + /junk.txt + a stale
/lib pkg via mpremote, run `chumicro-workspace deploy <project>
--device <mp>` (NOT deploy-example), then mpremote-walk the fs:
settings.toml/junk gone, keep set + payload remain]`. CP diff path
*was* bench-verified (`3738c3e8`); MP diff path inference rests on
the two paths being structurally parallel — plausible but unproven
on MP silicon.

## To re-research / verify next session

- **MP CLI diff clean-slate** — see Riskiest assumption. Cheapest
  test stated there.
- **Functional-test path** — 2a changed `FUNCTIONAL_TEST_EXTRA_
  EXCLUDES` (dropped `settings.toml`, added `_chu_kv.msgpack`) and
  2c will deeply rework `_stage_to_flash`. None of the functional
  suites were *run* this session (hardware-gated, out of scope).
  `[HYPOTHESIS: cheapest test = `python scripts/run.py
  test-functional` scoped to one library on a connected board once
  2c lands; settings.toml-dependent network tests must still pass
  via runtime_config.msgpack, not a board settings.toml]`.
- **Commit 2c itself** — entrypoint-as-payload. Synthesize the shim
  for *every* context incl. functional test so `code.py` leaves
  `FUNCTIONAL_TEST_EXTRA_EXCLUDES` entirely and the rsync is
  byte-identical project/example/test. The post-stage step
  (soft-reboot+tail vs harness-exec+collect) is the *irreducible*
  axis-3 fork — extract it as an explicit strategy, do NOT try to
  collapse it. Workstream Phase 2 delta 5 + transport-audit section
  have the design.

## Dead ends (don't re-walk)

- repl regression ≠ partial tree, ≠ the deploy-walker silent-skip
  item. The `no module named 'chumicro_timing.ticks_add'` *submodule*
  string is just CircuitPython's phrasing for `from chumicro_timing
  import ticks_add` when the whole package is absent. Falsified
  on-device `[VERIFIED: bench]`; chased it as a walker-link first —
  it isn't.
- First empty-dir reaping (1b) scoped to "ancestors of this run's
  deletions" — too narrow, missed pre-existing husks; broadened to a
  whole-`/lib` bottom-up sweep. Don't reintroduce the scoped version.
- First `_clean_slate_device` used persistent serial → port bug
  (above). Don't.
- `deploy-example` from the **workspace-template repo** fails
  ("library not found under …/libraries") — template repo has no
  `libraries/`; mono-repo libs come via `library_sources`. Run
  `deploy-example` from the **mono-repo** instead. `deploy
  <project>` works from the template repo (the diff path).

## How to rebuild context fast

- Read `plans/workstreams/deploy-path-unification.md` end-to-end —
  it is the authoritative state (Phase status, all 6 deltas, the
  transport audit, sequencing, cross-workstream reconciliation).
- Decision 0077 (`accepted`) for the invariant; 0059 §1 for the
  superseded-in-place example path; AGENTS.md "Code shape
  (workbench)" for the in-force non-negotiable.
- Key code: `flash_drive.DEVICE_KEEP_SET` (the one constant);
  `circuitpy_drive._list_scope_on_drive(*, clean_slate=)`;
  `circuitpython_transport._notice_settings_toml_eviction` +
  `delete_files` (empty-dir reap + diff-path notice);
  `micropython_transport._clean_slate_device` + `_LIST_ALL_SCRIPT`;
  `deployer.deploy_diff(clean=True)`; `cli/deploy.py` `--no-wipe` +
  `resolve_project_deploy_source`.
- Commits `dbf62986`→`1adfc045` are the Phase 2 narrative in order.
- 2c entry point: `circuitpython_transport._stage_to_flash` +
  `_push_staging_to_drive`, and the pytest-device staging
  (`workbench/pytest-device/.../plugin.py` `_bulk_stage_for_device`)
  — the functional path that still excludes `code.py`.

## Gotchas

- **Board state — point-in-time, re-probe on resume.** As of write:
  Pi Pico W CP @ `/dev/cu.usbmodem112301` (CircuitPython 10.2.0,
  hello_world deployed, clean); Pi Pico W MP @
  `/dev/cu.usbmodem112401` (MicroPython 1.28.0, micropython_blink,
  clean); Lolin S2 MP @ `/dev/cu.usbmodem11101` (1.27.0, untouched
  this session); a 4th port `…84722E7490C31` (Lolin S2 CP, unused).
  Ports renumber across replug — re-probe, don't trust these.
- macOS shows **two** CIRCUITPY mounts when both a CP board is up;
  the Pico W CP was `/Volumes/CIRCUITPY 1` this session (the bare
  `/Volumes/CIRCUITPY` was the other board). FAT directory-listing
  is **stale until remount** — `ls` after a deploy can show
  deleted-on-device files still present. Trust on-device REPL /
  mpremote walks over host `ls` for verification. (Documented in
  `example-sweep-stability` workstream.)
- MP has no host mount — plant/inspect fs via `mpremote connect
  <port> exec` or `fs`.
- Don't `printf >` files for content (AGENTS.md) — slipped twice
  this session on 1-line VERSION files; use the file tools. (Also
  used `printf` to plant board test fixtures on the CIRCUITPY drive
  — that's bench setup, not repo file content, acceptable.)
- `--no-wipe` (additive opt-out) vs default clean-slate vs `--wipe`
  (full erase incl. keep set) — three levels; the `--wipe` flag name
  predates 0077 and reads slightly oddly next to `--no-wipe`. Left
  as-is per 0077's chosen term; don't "fix" the naming without an
  ADR.
