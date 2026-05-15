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
- [ ] #1 consolidated 4-board matrix test (needs `_seed_rtc` for the
  real-HTTPS leg).
- [ ] #9 RAM-mode data-file staging investigation (gates #10a).
- [ ] #10a shipped bundle as a DER **data file** + low-RAM loader
  (free source post-parse).  #10b/#10c (user-CA detect, converter)
  done above.
- [ ] #6 RAM instrumentation test + #7 final subset sizing + Decision
  0067 body correction (curated-subset-is-permanent).
