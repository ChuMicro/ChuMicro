# Workspace-code hunt — marker-streaming stall + correctness audit

Scope: `workbench/workspace/src/chumicro_workspace/` (code, not docs), plus the
cross-package marker-streaming stall investigation reaching into
`workbench/deploy/src/chumicro_deploy/`.

Method: read every src file in the workspace package; traced each finding to a
concrete trigger and wrong outcome; reproduced the stall host-side with the real
parser / dispatcher / queue (no board touched). Repro scripts in `.scratch/`.

---

## Stall root cause (demo-driver marker-streaming stall)

**The reporter's hypothesis — a `timeout=10.0` serial-read default — is wrong.
The serial-read path streams live.** Neither streaming idle timeout is 10.0:
CircuitPython uses `_EXECUTE_IDLE_TIMEOUT = 60.0`
(`circuitpython_transport.py:86`) and MicroPython uses
`_EXECUTE_IDLE_TIMEOUT = 300.0` (`micropython_transport.py:54`). Both transports
dispatch each stdout line to `on_line` the instant it arrives
(`circuitpython_transport.py:1954-1961` polls `in_waiting` every 10 ms and feeds
the dispatcher live; MicroPython feeds mpremote's per-byte `data_consumer`,
`micropython_transport.py:558-570`). So every board line — including
`ECHO_RECEIVED` and `DEMO_COMPLETE` — physically reaches the host live, within
the board's <1 s run.

**The exact-10.0 s shape is the driver's own
`session.wait_for("ECHO_RECEIVED", timeout_s=10.0)`
(`demos/sockets_runner_connector/driver.py:110`) blocking its full budget because
the marker never lands on the queue.** It never lands because
`chumicro_workspace.markers.parse_marker` rejects the whole `ECHO_RECEIVED` line.
The board prints (`demos/sockets_runner_connector/app.py:37`):

```
print(f"ECHO_RECEIVED bytes={len(payload)} payload={payload!r}")
```

with `payload = b"hello chumicro"`, so the literal stdout line is:

```
ECHO_RECEIVED bytes=14 payload=b'hello chumicro'
```

`parse_marker` (`markers.py:82-88`) splits the remainder on whitespace and
requires every token to match `key=value`. The `payload=b'hello chumicro'` value
contains a space, so it splits into two tokens — `payload=b'hello` (matches
`key=value`) and `chumicro'` (no `=`, fails). The all-or-nothing rule
(`return None` on the first non-matching token, `markers.py:85-86`) discards the
**entire** marker. `on_line` never pushes it (`device_runner.py:191-194`), so the
driver waits the full 10.0 s and raises `MarkerTimeoutError`. Verified in
`.scratch/repro_stall.py`: `parse_marker(...) -> None` for that line, and the
simulated driver times out at `10.01s` on `ECHO_RECEIVED`.

The 10 s the reporter observed the markers "arrive" is the driver's
`MarkerTimeoutError` handler
(`driver.py:120-133`) dumping `wait_for_completion`'s captured stdout — the raw
`ECHO_RECEIVED` / `DEMO_COMPLETE` **text** was there live; only the parsed
markers were lost.

**Fix.** Two layers:

1. Immediate (demo, `demos/sockets_runner_connector/app.py:37`): the marker
   grammar forbids whitespace in a value (documented at `markers.py:18-21`), and
   a `bytes` repr with an embedded space violates it. Emit no whitespace in the
   value — e.g. drop the `payload=` field (`print(f"ECHO_RECEIVED bytes={len(payload)}")`)
   or encode it whitespace-free (`payload={payload.hex()}`). The sibling
   `sockets_runner_connector_explicit` demo likely has the same line.

2. Robustness (workspace, in scope) — see W1/W2: the marker layer converts a
   grammar violation into a silent 10 s stall with a misleading generic timeout.
   Harden so a marker-shaped line that fails token parsing is diagnosable rather
   than invisible.

---

### W1 · high · markers.py:82-88 (parse_marker) — a single whitespace-bearing value silently drops the whole marker, producing a misleading N-second stall

What happens: `parse_marker` treats any line whose first word is an uppercase
identifier but whose remainder isn't perfectly `key=value key=value` as *not a
marker* and returns `None` — no log, no diagnostic. A line that is obviously a
marker (valid name + several valid `key=value` pairs) is discarded wholesale
because one value contained a space. The consumer (`on_line`,
`device_runner.py:191-194`; `device_orchestration.py:332-335`) then never pushes
it, and the driver's `wait_for(name, timeout_s=T)` blocks its full `T` and raises
a generic `MarkerTimeoutError` that names only the awaited marker — pointing the
operator at a serial-read timeout (exactly what happened here) rather than at the
dropped line. Trigger: any board/test/demo printing a marker whose value carries
whitespace — a `bytes`/`str` repr with a space, a filesystem path with a space, a
formatted `"1.5 s"`. Confirmed live in the shipped `sockets_runner_connector`
demo on both runtimes. Blast radius: every marker-driven demo and every
`chumicro_pytest_device` functional test that prints such a value silently loses
the checkpoint and stalls for the wait budget; the failure masquerades as a
transport/serial problem. Suggested fix: keep the strict grammar, but make the
drop observable — when a line's first token is a valid marker name and at least
one token parsed as `key=value` yet a later token didn't, surface a warning
(stderr or a logger) naming the offending line, so the stall's real cause is
visible. Alternatively, tolerate a quoted value containing whitespace in the
grammar. Do not silently return `None` for a line that clearly intends to be a
marker.

### W2 · high · markers.py:135-150 (MarkerQueue.wait_for) — non-matching markers are silently consumed and destroyed, so one dropped checkpoint poisons the rest of an ordered sequence

What happens: `wait_for(name)` pops markers off the queue and **discards** every
one whose name isn't `name` (the loop at `markers.py:149-150` returns only on a
match; all others fall through and are gone). For the demo's ordered driver
(`driver.py:107-117` waits SENT → ECHO_RECEIVED → DEMO_COMPLETE), once
`ECHO_RECEIVED` fails to parse (W1) the driver sits in
`wait_for("ECHO_RECEIVED")`; the well-formed `DEMO_COMPLETE` that the board
prints ~instantly after is pulled off the queue *inside that wait* and thrown
away. So even the correctly-formed terminal marker is lost, and it cannot be
recovered on a retry — the only place it survives is the captured-stdout dump.
Verified in `.scratch/repro_drop.py`: driver reports `ECHO_RECEIVED TIMEOUT` then
`DEMO_COMPLETE TIMEOUT`, and the queue is empty afterward (DEMO_COMPLETE was
consumed, not left pending). Trigger: any parse gap or out-of-order arrival
between two awaited markers in a sequential driver. Blast radius: an in-order
marker driver (all demos, functional tests) can't observe markers after any
hiccup; the drop-non-matching contract — reasonable for a single blocking
fixture — actively hides state for the sequential-driver use case this layer is
now used for (`deploy_api`, demos). Suggested fix: for the ordered-sequence use,
don't destroy markers the current `wait_for` isn't looking for — either leave
non-matching markers on the queue (peek/putback) or keep a side log of dropped
marker names so a subsequent `wait_for` / diagnostic can see them. At minimum,
warn when a marker is dropped so the loss isn't invisible.

### W3 · medium · boot_shim.py:149-158 (module_calls_hard_reset) — an aliased import defeats the anti-bricking deploy guard silently

What happens: the guard that refuses to deploy a boot entrypoint containing
`microcontroller.reset()` / `machine.reset()` (enforcing the AGENTS.md
"never deploy a hard reset in code.py/main.py" rule via
`cli/deploy.py:184-200`) only matches an `ast.Attribute` whose `.value` is an
`ast.Name` with id exactly `"microcontroller"` or `"machine"`. It therefore does
not catch `import microcontroller as mc; mc.reset()` (the `.value.id` is `"mc"`),
nor `import machine as m; m.reset()`. The docstring only warns about the
`from microcontroller import reset` form, not the alias form, so the alias gap is
undocumented. Trigger: a user (or generated code) writes `import machine as m`
then `m.reset()` at boot in `main.py`/`code.py`. Blast radius: the reset ships,
the board reboots on every boot, crash-loops, and bricks the deploy cycle until
wiped — the exact catastrophic outcome the guard exists to prevent, defeated by a
one-line alias with no warning. Suggested fix: resolve `import ... as` aliases
(walk `ast.Import`/`ast.ImportFrom` to map local names back to
`microcontroller`/`machine`) before matching the call, and match
`from machine import reset` too; or at least document the alias gap alongside the
existing `from import` caveat.

### W4 · low · library_channel.py:216 (_safe_member_path) — prefix-string traversal check admits sibling-directory escape

What happens: the tar-extraction traversal guard tests
`str(target).startswith(str(into.resolve()))`. String-prefix matching treats a
sibling path as "inside": with `into` resolving to `/x/foo`, a member resolving
to `/x/foo-evil/payload` passes (`"/x/foo-evil/...".startswith("/x/foo")` is
True). A crafted snapshot member named `<repo-tag>/<short>/../../foo-evil/payload`
survives the check (member.name becomes `<short>/../../foo-evil/payload`,
`(into/that).resolve()` = `/x/foo-evil/payload`) and `extractall`
(`library_channel.py:257-259`) writes outside `into`. Straight `../` escapes to
an unrelated root are correctly rejected (they fail the prefix), so this is
sibling-directory only. Trigger: a malicious/compromised snapshot tarball from a
channel repo. Blast radius: low in practice — the source is a first-party GitHub
repo over HTTPS and this is host-side dev tooling — but the guard is
incorrectly implemented for its stated purpose. Suggested fix: compare on path
boundaries, e.g. `into_resolved == target or into_resolved in target.parents`
(or `os.path.commonpath`), not `str.startswith`.

### W5 · low · additive_apply.py:70 / managed_block.py:93 — user credential/config files are rewritten with a non-atomic in-place write

What happens: `additive_reapply` overwrites `secrets.toml` / `workspace.yml` via
`user_path.write_text(new_text)` (`additive_apply.py:70`), and
`sync_managed_block` overwrites `workspace.yml` via `write_text`
(`managed_block.py:93`). `write_text` truncates then writes; a crash / kill /
disk-full between truncate and full write leaves the file truncated or empty.
Trigger: process death mid-write during `setup`'s additive re-apply or a library
subcommand's managed-block sync. Blast radius: `secrets.toml` holds the user's
only copy of wifi/MQTT/API credentials (gitignored, not recoverable from VCS);
losing it is real data loss. Low because the window is small and the operation is
infrequent. Suggested fix: write to a temp file in the same directory and
`os.replace` onto the target (atomic rename) for these user-owned files.

### W6 · low · deploy_api.py:143-152 (DeployedProject.shutdown) — transport disconnect can race the still-running bootstrap read thread after a join timeout

What happens: `shutdown` calls `self.runner.shutdown(timeout_s=5.0)` then
`self.transport.disconnect()`. `runner.shutdown` joins the background thread with
that timeout and, on timeout, returns while the thread is still inside
`transport.execute(...)` reading the serial port (`device_runner.py:169-174`).
`transport.disconnect()` then closes the port from the main thread while the bg
thread is mid-`in_waiting`/`read` (CircuitPython `_read_until`,
`circuitpython_transport.py:1955-1957`) or mid-`exec_raw` (MicroPython) —
concurrent access to one serial handle from two threads. Trigger: `shutdown`
(e.g. context-manager exit or the `finally` in `driver.py:134-136`) while the
board bootstrap hasn't finished within 5 s — realistic on the abort/timeout path.
Blast radius: low — the bg thread's exception is caught and stashed
(`device_runner.py:209-217`), so it's a best-effort teardown, not a crash — but
it's an unsynchronized close of a resource another live thread is reading.
Suggested fix: give `shutdown` a way to signal the read loop to stop (or a longer
bounded join) before closing the port, so the port isn't closed out from under an
active reader.

---

## Checked and clear (no finding)

- `merge.py` / `pipeline.py` / `loaders.py` / `flatten.py` / `writer.py`: config
  merge is deep, deterministic, deep-copies (no aliasing), and last-write-wins as
  documented; `use_single_float=True` preserves the CP-float32 wire contract.
- `deploy_source.py` / `config_manifest.py` / `import_graph.py` /
  `example_source.py`: staging composition, manifest union (strictest wins), and
  search-path dedup are correct.
- `_set_nested` "replace non-mapping intermediate" (additive_apply.py:129-131)
  looked like a data-loss path but is unreachable via `additive_reapply`:
  `_diff_dotted_paths` (`template_drift.py:97-99`) reports a whole missing subtree
  by its parent key and never descends into a user key that's present-but-scalar,
  so `_set_nested` is never handed segments whose intermediate exists as a scalar.
- `device_orchestration.execute_device_bootstrap` marker dispatch and
  `_line_dispatcher.StreamingLineDispatcher` line framing are correct; the
  dispatcher emits complete lines live and flushes the partial tail.
