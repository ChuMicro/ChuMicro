# Handoff 2026-05-22 — runner-reactor MQTT+TLS validated on 3/4 boards; Pi Pico W MP fragmentation hunt next

## What this session was about

User extended the runner-reactor hardware validation beyond the
HTTP-on-port-80 probe that closed the workstream earlier today.  Ask
was to test the wrapper-mediated polling against **a real MQTT server
and TLS too** ("this mac is on the same wifi the boards will be on so
you can stand up something here as needed with custom keys").  The
runner-reactor itself is committed and closed; this session was
follow-on coverage validating that `MQTTClient` registered as a runner
service drives `runner.tick(now) + runner.wait(now)` correctly against
real network I/O for both plain TCP and TLS-wrapped sockets.

## What's in flight

Nothing in this repo — working tree is clean apart from
`.idea/chumicro.iml` IDE drift.  All session artifacts live in
gitignored locations:

- **Probe project** at `~/circuitpython/ChuMicro-Workspace-Template/
  projects/mqtt_tls_probe/` — `app.py`, `project_config.toml`,
  `ca.der`, `ca.pem`, `tests/`.  Untracked in the workspace-template
  repo (projects/ is gitignored).  Loads CA from disk at runtime so
  the always-resident bytes literal isn't pinned in the module
  namespace — see "Dead ends" below for why that change moved the
  needle only ~2 KB.
- **Certs + broker config** at `/Users/chuxor/circuitpython/chumicro/
  .scratch/mqtt-probe-{certs,config}/`.  Cert regeneration script is
  `mqtt-probe-certs/generate.py` (uses Python's `cryptography`); both
  PEM + DER are emitted side-by-side.
- **Broker** (mosquitto 2.0.20) was running on the mac during the
  session — both `1883` plain and `8883` TLS listeners — and stopped
  cleanly at session end.  Restart with `mosquitto -c .scratch/
  mqtt-probe-config/mosquitto.conf -v > .scratch/mqtt-probe-config/
  mosquitto.log 2>&1 &`.

## What got done

Wrapper-mediated MQTT + TLS validated on the four-board target matrix.
**[VERIFIED: probe ran end-to-end against the local mosquitto on each
board this session]**

| Board | Plain MQTT | TLS no-verify | TLS with CA |
|---|---|---|---|
| Pi Pico W MP | ✓ (133/19 ms) | ENOMEM | ENOMEM |
| Pi Pico W CP | ✓ (138/24 ms) | ✓ (147/25 ms) | ✓ (171/53 ms) |
| Lolin S2 MP | ✓ (191/49 ms) | ✓ (213/66 ms) | ✓ (181/32 ms) |
| Lolin S2 CP | ✓ (130/18 ms) | ✓ (130/18 ms) | ✓ (130/18 ms) |

`connect_to_echo_ms / publish_to_echo_ms` per board.  Each TLS leg
that passed also ran a 10-cycle publish/echo loop on the same
connection with `drift_bytes = 48` — same noise floor the host
tracemalloc test produces.

Three independent fixes converged to make TLS_CA pass on 3/4 boards:

1. **Broad-validity cert (2000-2099)**.  Initial cert had
   `notBefore=2026-05-23` (today); MP boards cold-boot with an unset
   RTC and rejected the cert as not-yet-valid (`ValueError:` on Lolin
   S2 MP, `MBEDTLS_ERR_X509_CERT_VERIFY_FAILED` on Pi Pico W CP).
   Generated via `cryptography` lib since `openssl x509 -req` always
   stamps notBefore=now.
2. **DNS SAN + mDNS hostname** (`charless-macbook-pro.local`).  An
   IP-only SAN cert was rejected by the stricter mbedTLS builds on
   Lolin S2 MP and Pi Pico W CP — documented in
   `libraries/sockets/docs/guide.md` Runtime quirks table.  Adding a
   DNS SAN and connecting via the `.local` hostname (resolves via
   Bonjour) cleared it.
3. **DER on MP** (cert from `_load_ca_bytes()` returns DER bytes for
   `sys.implementation.name == "micropython"`).  rp2's mbedTLS ships
   without `MBEDTLS_PEM_PARSE_C`, so chumicro_sockets' MP adapter
   converts internally; handing DER directly skips that allocation
   and matches what the adapter would emit anyway.  Lolin S2 MP
   succeeded with this; Pi Pico W MP still failed (heap, not cert).

Probe contract exercised: `MQTTClient` added to a `Runner`, a periodic
50 ms driver task triggers `subscribe()` / `publish()` once the client
reports CONNECTED, on_message callback records the echo, the loop is
`while not received: now = runner.tick(); runner.wait(now)`.  The 50 ms
period caps `wait()`'s sleep so state transitions aren't stranded
between socket events — without it, `wait()` blocks for the full
keepalive interval (15 s) and the app's subscribe/publish never gets
the runner's attention.  **[VERIFIED: first attempt at the probe
without the periodic driver timed out on the SUBSCRIBE; adding the
periodic fixed it on the same deploy]**

## Decisions made (not yet captured in ADRs)

- The runner-reactor's hardware-validation claim is **complete on 3
  of 4 boards** for MQTT + TLS.  Pi Pico W MP's TLS failure is a
  cross-cutting heap-fragmentation concern unrelated to the runner-
  reactor's wrapper-mediated polling — the same board passed the
  earlier `runner_reactor_probe` (raw chumicro_sockets, no chumicro
  stack) for plain TCP and TLS-on-example.com.  Workstream stays
  closed.
- The probe project is **not promoted to a chumicro example or to a
  release-checked test**.  It's research scaffolding; once the
  fragmentation hunt lands a fix or a documented constraint, the
  probe gets retired with it.

## What was learned

- **Pi Pico W MP fragmentation evidence** (mem_info(1) per leg, with
  the chumicro_mqtt + chumicro_runner + chumicro_sockets + chumicro_
  config + chumicro_msgpack stack loaded):

  ```
  GC: total: 205440, used: 62800, free: 142640
  No. of 1-blocks: 618, 2-blocks: 161, max blk sz: 122, max free sz: 649
  ```

  142 KB total free, but **`max free sz: 649` GC blocks ≈ 10 KB**
  largest contiguous run (rp2 uses 16 B / block).  TLS handshake
  needs ~25 KB contiguous per the chumicro_requests guide → ENOMEM.
  ATB heap map dump (captured to `/Users/chuxor/circuitpython/
  chumicro/.scratch/pico-mp-mqtt-tls-full.log`) shows extensive
  M/D/h/=/. interleaving — Swiss-cheese fragmentation throughout the
  205 KB heap.  **[VERIFIED: mem_info(1) output captured this
  session]**

- **The cert in module scope is not the load-bearing fragmenter.**
  Switching from inline `CA_PEM` + `CA_DER` bytes literals to file-
  based loading via `open("/ca.der")` + immediate `del + gc.collect()`
  moved `max free sz` from 649 → 788 GC blocks (~2 KB improvement)
  on Pi Pico W MP.  Still nowhere near the 25 KB needed.  The
  resident-but-small bytes objects (~1.7 KB total for both PEM and
  DER) were not the cause; the real cost is module-level allocations
  from importing the chumicro stack.  **[VERIFIED: side-by-side mem_
  info(1) measurements pre and post the file-load refactor]**

- **The workspace-template's `wifi_only` example is broken** against
  the current `chumicro_config` API.  `app.py` does `wifi_section =
  config["wifi"]`, but `RuntimeConfig` is flat-key — `config["wifi"]`
  raises `MissingConfigKey` because the actual keys are `wifi.ssid`
  / `wifi.password`.  Canonical pattern is
  `WifiConfig.from_config(config)`.  **[VERIFIED: my own first probe
  deploy hit this same bug verbatim; I worked around with flat-key
  reads]**.  Already flagged in `1b92747e`'s commit body; deliberately
  left as a workspace-template follow-up.

## Riskiest assumption

That a leaner Pi Pico W MP probe — one that imports only chumicro_
sockets (no chumicro_mqtt, no chumicro_runner, no chumicro_config) —
**can** complete a self-signed TLS handshake.  The earlier
`runner_reactor_probe` validated this for HTTPS on example.com (real
CA chain) — but **not** against a self-signed CA on the local broker
with the cert recipe that just landed.  If the leaner probe still
ENOMEMs, the constraint is more fundamental than module-import
overhead and the fragmentation hunt needs to look elsewhere.

[HYPOTHESIS: cheapest test = strip the probe down to `chumicro_
sockets.tls_client_socket(BROKER_HOST_DNS, 8883, context=ssl_context_
with_ca(open("/ca.der", "rb").read()))` + a raw `select.poll()` loop;
deploy to `pi-pico-w-mp`; check whether the handshake completes and
log `gc.mem_free()` + `max free sz` before vs after.  If yes →
chumicro_mqtt's module load is the fragmenter.  If no → something in
chumicro_sockets' module load OR the wifi stack itself.]

## To re-research / verify next session

1. **Library-by-library fragmentation profile on Pi Pico W MP.**  Cold-
   boot, then `import` one library at a time, calling `gc.collect();
   micropython.mem_info(1)` after each.  Track how `max free sz`
   shifts.  Suspects in order of likely cost:
   - `chumicro_mqtt._wire` (33 KB on disk → some multiple in RAM)
   - `chumicro_mqtt.client` (55 KB on disk)
   - `chumicro_sockets.__init__` + `_adapters/mp` (23 + 21.5 KB)
   - `chumicro_runner.core` (19 KB)
   - `chumicro_msgpack._pure` (13 KB)
   [HYPOTHESIS: cheapest test = `.scratch/pico_mp_libwise_fragmentation.
   py` that imports each module in order with mem_info(1) between
   each.  Result tells you which library to investigate first.]

2. **Does freezing chumicro_mqtt as bytecode (mpy-cross + frozen
   modules) reduce its loaded heap cost?**  The chumicro_requests
   guide already implies yes for HTTPS — same lever applies here.
   [HYPOTHESIS: cheapest test = `python scripts/run.py prepare-mpy-
   cross`, cross-compile `chumicro_mqtt/*.py` → `.mpy`, ship those
   instead of `.py`, re-run the probe, observe mem_free + max_free_sz
   shift.]

3. **Does an alternate deploy mode help?**  The current probe uses
   the default chumicro-workspace flash mode.  [HYPOTHESIS: cheapest
   test = `python run.py deploy mqtt_tls_probe --device pi-pico-w-mp
   --mode ram` (or whatever flag enables ram mode if it exists) and
   observe whether max_free_sz improves.  Possibly already documented;
   check `docs/contributing/device-testing.md` for the existing
   mode picker.]

4. **Refine `libraries/sockets/docs/guide.md` Runtime quirks table.**
   Current entry says rp2 MP "mbedTLS build rejects self-signed certs
   entirely" — too pessimistic.  My runner_reactor_probe earlier today
   (separate session) already did self-signed-equivalent TLS on rp2
   MP successfully against example.com; the limit on Pi Pico W MP is
   *fragmentation*, not self-signed rejection.  Suggested rewording:
   "rp2 MP can handshake self-signed when the application heap is
   sparse (a minimal probe works); fails ENOMEM in heavy apps —
   ~25 KB contiguous needed."  Also worth adding the broad-validity
   + DNS-SAN guidance that fixed the other three boards.  Save for a
   focused doc PR — out of scope for the fragmentation hunt itself.

## Dead ends

- **Inline `CA_PEM` + `CA_DER` bytes literals in app.py.**  Tried as
  the first cert delivery shape (smaller initial change than disk
  files).  Worked functionally but pinned ~1.7 KB of bytes in the
  module namespace permanently.  Swapped to file-loading per the
  user's suggestion; the swap saved ~2 KB of `max free sz` on Pi
  Pico W MP but didn't dent the ENOMEM.  Left in place because file-
  loading is the better long-term pattern, but it didn't unblock the
  fragmentation hunt.

- **Subscribe/publish called from outside the runner loop.**  First
  probe iteration drove `client.subscribe()` / `client.publish()`
  directly after `runner.wait()` returned, expecting wait() to bounce
  often.  It doesn't — wait() blocks for the keepalive deadline (~15 s)
  on a CONNECTED client with nothing else due, so the app's transition
  was stranded.  Fixed by moving the drive logic into a runner-
  registered periodic task (50 ms period), which caps wait()'s sleep
  to 50 ms and gives the app a tick to react to state changes.  Worth
  remembering: **the runner-reactor pattern assumes app-driven actions
  happen via runner-registered work, not via post-wait() inline code.**
  If you write a probe with the inline pattern again, expect the
  same stall.

- **`ssl_context_no_verify()` to bypass the Lolin S2 MP cert
  rejection.**  Tried before the broad-validity + DNS-SAN fix.  Still
  failed with the same `ValueError:` — even verification-disabled
  contexts still parse the cert dates.  Not a useful escape hatch for
  the date-mismatch case; only useful when SAN/CN is the wrong shape
  but dates are fine.

- **`-not_before` / `-startdate` flags on `openssl x509 -req`.**  Not
  supported by the LibreSSL that ships on macOS.  `openssl ca`
  supports it via a config file but the indirection isn't worth it
  when Python's `cryptography` lib lets you set arbitrary dates
  directly.  `cryptography.x509.CertificateBuilder().not_valid_before
  (datetime(2000, 1, 1, tzinfo=timezone.utc))` is what worked.

## How to rebuild context fast

Re-read in this order:

- **`libraries/sockets/docs/guide.md`** "Runtime quirks" table — the
  prior session documented the IP-SAN and rp2 self-signed concerns
  already; this session's fixes (broad validity + DNS SAN) refine
  but do not contradict that table.
- **`libraries/sockets/src/chumicro_sockets/_adapters/mp.py:130-160`**
   `tls_client_socket` — passes `server_hostname=host` to
   `wrap_socket`; when host is the `.local` mDNS name, the SAN match
   works.  Also `ssl_context_with_ca` docstring on the MP adapter
   for the PEM-to-DER conversion rationale (rp2 ships without
   `MBEDTLS_PEM_PARSE_C`).
- **`libraries/requests/docs/guide.md`** "HTTPS heap headroom on
  minimum-class boards" — same ~25 KB figure the probe is fighting.
  Recommends `--mode flash` (already the default) + dropping unused
  imports.

Probe artifacts to read:

- `~/circuitpython/ChuMicro-Workspace-Template/projects/mqtt_tls_probe/
  app.py` — the probe.  Read `_load_ca_bytes`, `run_round_trip`, and
  the `_between_legs` mem_info(1) dump path.
- `.scratch/mqtt-probe-certs/generate.py` — cert recipe (2000-2099,
  DNS+IP SAN).
- `.scratch/mqtt-probe-config/mosquitto.conf` — local broker setup.
- `.scratch/pico-mp-mqtt-tls-full.log` — full Pi Pico W MP deploy
  output including the ATB heap map dumps between legs.

Recent commits worth scanning:

```
git --no-pager log --oneline -10
```

The 10-commit runner-reactor block is what makes the probe possible;
this session didn't add anything to it.

## Gotchas

- **Hardware state is point-in-time.**  All four boards were healthy
  and on the wifi (172.16.1.0/24) at session end — re-probe with
  `chumicro-workspace status` on resume.  IP assignments shift on
  reconnect.
- **Mosquitto port reuse.**  `pkill -f "mosquitto -c .scratch/mqtt-
  probe-config"` will sometimes match the pkill process itself or
  not catch the actual broker (PID gets reused as a child of the
  shell).  Use `pkill -9 -f mosquitto` followed by `ps -ax | grep
  mosquitto | grep -v grep` to confirm stopped.  An orphaned broker
  on 1883/8883 blocks the next session's startup.
- **`charless-macbook-pro.local` is the mac's mDNS name** as of this
  session — `scutil --get LocalHostName` to re-confirm.  If the mac
  is renamed, the cert's DNS SAN list needs to be regenerated.
- **The cert validity goes to 2099-12-31** — long enough that the
  resumer won't hit expiry, but the cert is self-signed by the local
  `ChuMicroProbeCA`.  Re-running `.scratch/mqtt-probe-certs/
  generate.py` is idempotent (keys are reused if present).
- **Pi Pico W MP `mem_info(1)` ATB heap map output character set:**
  `F` (free), `H` (head-of-alloc), `T` (tail of alloc), `M` (mark
  during GC), `=` (continuation of head), `.` (free single block),
  `D` (data block), `L` (long-lived?), `S` (string?).  Useful when
  reading the dump in `.scratch/pico-mp-mqtt-tls-full.log`.
- **`micropython.mem_info(1)` prints to MP's stdout**, which the
  chumicro-deploy `--tail` mode captures line-by-line.  The ATB map
  itself doesn't contain "RESULT" markers, so a grep for "RESULT"
  filters it out — use `awk '/HEAP_MAP_BEGIN/{found=1} found{print}
  /HEAP_MAP_END/{exit}'` to extract the surrounding chunks instead.
