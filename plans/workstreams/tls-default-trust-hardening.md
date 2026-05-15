# TLS default-trust hardening — follow-up to Decision 0067

Shape Y shipped (`4735ae4d`): `tls_client_socket(context=None)` verifies on
every runtime, MP via a 9-root curated PEM constant.  Post-ship review
surfaced a hard architectural constraint and several follow-ups.

## The load-bearing constraint (drives everything below)

MicroPython's `ssl` module (`extmod/modtls_mbedtls.c`) exposes **only**
`load_verify_locations(cadata)` → `mbedtls_x509_crt_parse(make_copy=1)`,
which `memcpy`s + parses **every** cert into heap for the SSLContext
lifetime.  MP exposes no `mbedtls_ssl_conf_verify` hook to Python.

CircuitPython's `lib/mbedtls_config/crt_bundle.c` (used on rp2 *and*
esp, generic port of ESP-IDF's algorithm) is C in firmware: a verify
callback that binary-searches a flash-resident compact bundle
(subject+pubkey, presorted) and parses one pubkey per handshake —
~600 B resident, certs never leave flash.

**Consequence:** a curated subset on MP is *permanent architecture*,
not a stopgap.  ~9 roots ≈ 12–18 KB resident heap; 151 ≈ 200–300 KB
(impossible on 256 KB boards).  DER-vs-PEM does not change this ceiling
(it helps the one-time parse transient + rp2 `MBEDTLS_PEM_PARSE_C`
absence only).  Decision 0067 body must be corrected to say this
plainly — it currently implies "9 now, more later."

## Items

1. **Full 4-board matrix test** — consolidated functional test covering
   {no-verify, default, real-HTTPS-with-validation} × {Lolin S2, Pi
   Pico W} × {CP, MP}.  Today only the default→reject-expired cell is
   hardware-covered.
2. **`sendall` test bug** — `test_real_tcp.py:91` + `test_real_tls.py:97`
   call `socket.sendall`, which the protocol never defined (only
   `send() -> int`, partial-write contract).  Added 2026-04-27
   (`4019e24a`), masked because CPython sockets have `sendall` and
   device TCP/TLS tests weren't run since.  Fix: tests loop on `send()`.
   No protocol change (a blocking `sendall` would stall the runner).
3. **PEM → file** — ship `chumicro_sockets/_ca_bundle.<ext>` as data,
   not a `.py` `PEM_BYTES` constant, so the ~11.5 KB source can be
   freed after parse instead of pinned in `sys.modules` forever.
4. **Files in RAM-mode deploy** — investigate whether the deploy /
   pytest-device transport can stage a non-`.py` data file in RAM
   mode.  If not: auto-detect real-file tests and force flash mode;
   document the override.
5. **Ship DER, not PEM** — DER loads on every MP port (rp2 + esp);
   only PEM breaks rp2 (no `MBEDTLS_PEM_PARSE_C`).  So always ship
   pre-converted DER for the *default bundle we control* — no board
   probe needed, the "detect" fork dissolves.  Drops the `_pem_to_der`
   runtime cost + transient peak.

   **User-provided CAs are different** (not uniform across runtimes):
   MP needs DER on rp2 / auto-converts PEM via `_pem_to_der`; CP's
   binding wants an ASCII PEM `str` (DER isn't ASCII-decodable);
   CPython takes either.  `ssl_context_with_ca` must accept PEM **or**
   DER and detect by first byte (`0x2D` `-----` PEM, `0x30` ASN.1
   DER): MP detect (PEM→convert, DER→passthrough), CPython passthrough,
   CP PEM-or-clear-error (today DER → silent empty-trust, verified).
   `_pem_to_der` stays for the MP user-PEM path.  No new CLI: guide
   documents DER-preferred + `openssl x509 -outform DER` + a ~6-line
   bundle snippet.
6. **Stable low-RAM loader + RAM instrumentation** — preserved
   functional test that measures resident + transient heap on each
   board for the bundle load, so subset size is set from data, and
   regressions are caught.  Free everything freeable post-parse.
7. **Subset coverage** — 9 roots misses Sectigo/USERTrust (largest CA
   by cert count) + GoDaddy/Starfield.  Expand to ~13–15, ceiling set
   by #6's on-device numbers.  Do **not** pursue native/firmware
   (violates pure-Python cross-runtime constraint).

## Clock dependency (surfaced 2026-05-15 fixing #2)

Shape Y default validation requires a correct device clock.  Boot RTC
on most MP ports is epoch/2021 → a valid cert's `notBefore` looks
future-dated → `ValueError: certificate validity starts in the
future`.  Expired-cert *rejection* is unaffected (rejection regardless
of skew — why the first 4-board acceptance passed).  But every
happy-path / real-HTTPS leg must seed the RTC first.  Established
pattern: `requests/functional_tests/test_real_get_tls.py::_seed_rtc`
(host clock via conftest runtime-config; MP `machine.RTC().datetime`,
CP `rtc.RTC().datetime`).  `sockets/test_real_tls.py` + the #1 matrix
test must adopt it; sockets conftest must publish `now_utc_tuple`.
Real apps NTP-sync instead — document the requirement in the guide.

## Sequence

2 → 1 (sendall unblocks the real-HTTPS leg) → 4 (RAM-mode files
investigation gates the file approach) → 5+3 (DER file) → 6 (RAM
instrumentation) → 7 (final subset from data) → Decision 0067 body
correction.

## Status

Opened 2026-05-15.

- [x] **#2 sendall** + brittle `led_counter` assertion — fixed
  (`7497ac32`).  Surfaced the clock dependency (recorded above).
- [x] **#5 / user-CA detection + streamed `_pem_to_der`** (`96959951`)
  — `ssl_context_with_ca` PEM-or-DER: MP detect + unconditional
  PEM→DER (no `sys.platform` branch), CP PEM-only-clear-error,
  CPython PEM-or-DER.  Streaming converter (no split / no GC storm).
  Strict RFC 7468 `CERTIFICATE` boundary; alternate armors → clear
  ValueError, documented.  sockets 0.5.0 → 0.6.0.
- [x] **#1 consolidated 4-board matrix test** (`eeb4994b`) — three
  legs (no-verify accepts / default rejects / default accepts a real
  ISRG-X1 host) green on Lolin S2 + Pi Pico W × CP/MP.  `_seed_rtc`
  from host clock (conftest publishes `sockets.now_utc_tuple`).
  Surfaced concrete #7 evidence: example.com → AAA Certificate
  Services / Sectigo, *not* in the 9-root MP bundle (CP firmware
  has it) — Sectigo/AAA is a must-add for the final subset.
- [x] **#9 RAM-mode data-file staging** (`<this commit>`) — finding:
  CP RAM-mode (raw-REPL exec, no FS) silently drops non-`.py` files
  (`circuitpython_bootstrap.py:119-121`); MP mount-mode + all flash
  modes carry them.  Resolution: `Deployer._resolve_effective_device`
  now auto-switches the *whole* deploy to flash when the staged set
  has any non-`.py` file (all-or-nothing, after the `force_deploy_mode`
  escape hatch, same contract as `requires_flash`).  workbench/deploy
  0.21.1 → 0.22.0.  Decision: **DER ships as a data file** (not a
  `.py` constant) — the file's tight read→parse→free *lifetime*
  beats the constant's fragmentation (evict-after-parse strands an
  ~8 KB hole among long-lived TLS objects; non-compacting GC).
- [x] **#10a shipped bundle as a DER data file + loader** (`<this
  commit>`) — `_ca_bundle.der` (7996 B, 9 roots) ships as package
  data; `_ca_bundle.py` is now a tiny co-located loader shim
  (`read_der()` resolves the sibling via its own `__file__`, falls
  back to `/lib/chumicro_sockets/_ca_bundle.der`).  `mp._default_context`
  feeds `read_der()` straight into `ssl_context_with_ca` as an unbound
  temporary → freed before socket/handshake allocs.  Wheel-verified
  (.der in the artifact); 4-board matrix 10/10 with the file loader;
  155 unit tests.  sockets 0.6.0 → 0.6.1.  #10b/#10c done earlier.
  Note: `--deploy-mode ram` + CP also can't stage
  `/runtime_config.msgpack` (pre-existing pytest-device limitation,
  orthogonal); auto-switch is bypassed by the explicit-force hatch
  by design — unit-tested in test_deployer.py.
- [x] **#6 RAM instrumentation** (`d2e5588d`) —
  `test_ca_bundle_ram_cost.py` (MP-only, warm-up-then-measure):
  ~500 B parsed-chain RAM/root, ~187 KB free baseline (Pi Pico W
  MP), retained < 2 KB on release.  Regression trip-wire + the
  measured basis for sizing.
- [x] **#7 final subset sizing** (`c464ba39`) — 9 → 17 roots
  (added Sectigo AAA + USERTrust RSA/ECC [the demonstrated
  example.com gap], GoDaddy/Starfield G2, Entrust G2, Microsoft
  RSA/ECC 2017).  ~16 KB DER, well within budget; RAM not the
  constraint.  4-board matrix 20/20.
- [x] **rename** `_resolve_effective_device` →
  `_effective_device_for_source` (`4de8f6f6`) — name now signals
  the deploy-mode decision depends on the source.
- [x] **Decision 0067 body corrected** (`<this commit>`) — DER
  data-file (not PEM constant), `read_der()` lifetime rationale,
  17-root permanent-subset constraint, real measured numbers, the
  `ssl_context_with_ca` PEM-or-DER change moved out of "what does
  not change", clock-dependency consequence, no `regen` script.

**Workstream complete.**
