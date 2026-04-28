# Decision 0043: chumicro-sockets — UDP support

Status: `accepted`
Date: `2026-04-27`
Related: [Decision 0031](0031-chumicro-sockets.md) (chumicro-sockets scope), `plans/workstreams/library-pipeline.md` (Tier-A NTP requires UDP).

## Context

Decision 0031 scoped `chumicro-sockets` as TCP + TLS only.  The
chumicro-mqtt / requests / http-server stack only needed connection-
oriented sockets and the surface area was easier to reason about
without the datagram path.

Tier-A's `chumicro-ntp` (and any future SNTP / mDNS / SSDP / SNMP /
M-SEARCH consumer) needs UDP.  The two structural options are:

1. **Inline UDP in `chumicro-ntp`.**  Keep `chumicro-sockets` TCP-only;
   `chumicro-ntp` carries its own per-runtime UDP adapter.  Pragmatic
   for one consumer, but the second UDP user (mDNS, SSDP, ...) would
   either copy the adapter or require an extraction.
2. **Add UDP to `chumicro-sockets`.**  Single home for cross-runtime
   socket abstractions.  Slight scope creep on Decision 0031 but
   matches the library's name and the user's mental model.

A future split into `chumicro-sockets-udp` / `chumicro-sockets-tcp`
remains possible if the bundle size becomes a problem on the
smallest boards — keep it as a watchpoint, not a starting point.

## Decision

UDP support lives in `chumicro-sockets` alongside TCP + TLS.  The
public API gains:

- `chumicro_sockets.UDPSocket` — duck-typed protocol with
  `sendto(data, host, port)` (separated args, normalised across
  runtimes), `recvfrom_into(buffer, nbytes=0) -> (n, (host, port))`,
  `close`, `setblocking`, `settimeout`, `fileno`, `getsockname`.
- `chumicro_sockets.udp_socket(bind_host, bind_port, *, radio,
  broadcast)` — runtime-routed factory.  Default arguments
  (`"0.0.0.0"`, `0`) bind to an ephemeral port on every interface;
  pass `bind_port=N` for receivers / servers.
- `chumicro_sockets.testing.FakeUDPSocket` — in-memory fake mirroring
  the protocol; `enqueue_recv(data, host, port)` scripts inbound
  datagrams and `sock.sent` is a list of `(data, host, port)` tuples.

Per-runtime adapters under `_adapters/`:

- **CircuitPython** — `socketpool.SocketPool(radio).socket(AF_INET,
  SOCK_DGRAM)`, `bind`, `sendto((host, port))`, native
  `recvfrom_into(buffer)` (already returns `(n, address)`).
- **MicroPython** — `socket.socket(AF_INET, SOCK_DGRAM)`, `bind`,
  `sendto`, `recvfrom`-polyfilled `recvfrom_into` (most MP UDP
  builds expose `recvfrom`, not `recvfrom_into`).
- **CPython** — stdlib `socket.socket(AF_INET, SOCK_DGRAM)` with the
  same wrapper shape so `sendto(data, host, port)` separated-arg
  form is honoured.

Each adapter wraps the native socket so the public surface is
runtime-uniform — `_CPUDPWrapper`, `_MpUDPWrapper`,
`_CPythonUDPWrapper` follow the existing TCP `_MpSocketWrapper`
pattern.

`broadcast=True` enables `SO_BROADCAST` so `sendto` to
`"255.255.255.255"` or a LAN broadcast address succeeds.  Best-effort
on CP / MP — older firmware lacking `setsockopt` swallows the error
silently rather than failing the factory.

### What's explicitly NOT in v1

- **Multicast** (group join via `IP_ADD_MEMBERSHIP`).  Needed for
  full SSDP M-SEARCH and full mDNS — a substantial extension that
  warrants its own decision.  Today's broadcast support covers the
  unicast SSDP variant and any "send to LAN broadcast, listen for
  responses" pattern; that's enough for chumicro-ntp + a "super
  simple SSDP client" example.  Add when the first multicast
  consumer surfaces.
- **IPv6.**  Every adapter hard-codes `AF_INET`.  IPv6 is a
  larger lift — `getaddrinfo` + dual-stack bind logic + per-runtime
  port verification — and no current consumer needs it.
- **Connected UDP sockets** (`socket.connect` on a UDP socket so
  subsequent `send` / `recv` skip the address argument).  Saves a
  per-call address tuple but introduces an extra mode users must
  reason about.  Can be added when a consumer benefits.
- **A separate `chumicro-sockets-udp` package.**  Considered
  proactively, deferred until size or coupling becomes a concrete
  problem.  Watchpoint: monitor the on-device `chumicro-sockets`
  bundle size on the smallest-flash board (currently Pi Pico W's
  2 MB-equivalent partition); if a split becomes attractive,
  re-open this decision.

## Validation

The four-board CPU matrix (CP-S2, CP-RP2, MP-S2, MP-RP2) ran
`libraries/sockets/functional_tests/test_real_udp.py` against a
host-side echo server bound on the LAN (started by the functional-
test conftest fixture).  All four sent `chumicro-udp-echo`, received
the same payload back, verified the sender address, and confirmed
the recv loop yielded between ticks (no block-call regression):

| Device                         | Runtime                | Result |
| ------------------------------ | ---------------------- | ------ |
| `pi-pico-w-circuitpython-board`  | CircuitPython 10.2.0 | PASS   |
| `pi-pico-w-micropython-board`    | MicroPython 1.28.0   | PASS   |
| `lolin-s2-circuitpython-board`   | CircuitPython 10.2.0 | PASS   |
| `lolin-s2-micropython-board`    | MicroPython 1.28.0   | PASS   |

Host-side unit tests cover the CPython adapter against real loopback
sockets + the FakeUDPSocket protocol surface + the factory routing
across all three runtimes (mocked).  Coverage: 97 % of
`chumicro_sockets` after the addition (above the 94 % gate).

## Consequences

### Positive

- One library, one mental model.  Users who already know
  `tcp_client_socket(host, port)` reach for `udp_socket(...)` next
  to it.
- `chumicro-ntp` lands as a thin parsing + scheduling layer on top
  of `udp_socket`, with no per-runtime adapter chase inside the NTP
  library itself.
- Future UDP consumers (SSDP M-SEARCH, mDNS query, SNMP get,
  ad-hoc protocols) inherit the per-runtime adapter work.
- The validated 4-board matrix becomes the regression bed for any
  future UDP work.

### Negative

- `chumicro-sockets` ships ~250 lines + 1 protocol + 1 wrapper class
  more than under Decision 0031's original scope.  Negligible on
  flash — the per-runtime adapter is gated by `__chumicro_runtimes__`
  so only the relevant adapter ships per board.
- The "TCP-only" mental shorthand from Decision 0031 is now stale.
  This decision file supersedes that scope clause; downstream docs
  reference the broader factory list.

### Watchpoints (not rules)

- If the on-device bundle size on the smallest-flash board crosses
  a threshold that hurts users, revisit the
  `chumicro-sockets-udp` split.  No threshold is named yet; we will
  see real numbers from the boot-cost benchmark in
  `plans/open-questions.md` first.
- If a multicast consumer (full mDNS / SSDP / video / sensor mesh)
  surfaces, scope a follow-on decision rather than slipping it into
  this one — multicast group membership has its own portability
  surface.
