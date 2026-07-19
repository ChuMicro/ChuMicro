# Security Policy

## What this covers

This policy covers the published ChuMicro artifacts:

- The device libraries, the `chumicro_*` packages under `libraries/` that ship
  to PyPI and the CircuitPython bundle.
- The workbench tools, `chumicro-workspace`, `chumicro-deploy`, `chumicro-repl`,
  and `chumicro-pytest-device`.

Two areas are worth calling out because they carry more risk than a timer or a
key-value store.

TLS and networking code is in scope. Several libraries speak to the network:
`requests`, `http_server`, `mqtt`, `websockets`, `sockets`, and `ntp`. They
handle sockets, parse untrusted bytes off the wire, and set up TLS. A
certificate check that accepts what it should reject, a parser that can be
driven past its buffer, or a TLS context built without verification are all the
kind of thing this policy is for.

The deploy tooling runs on your host. The workbench tools flash firmware, push
files, and open serial ports from your laptop, not from the board. A bug there
touches your machine and the boards you connect to it, so host-side issues
(command injection through a device path, a checksum that does not actually
verify) are in scope too.

## Reporting a vulnerability

Report privately through GitHub's private vulnerability reporting on the
ChuMicro/ChuMicro repository:

**[Report a vulnerability](https://github.com/ChuMicro/ChuMicro/security/advisories/new)**

That keeps the report between you and the maintainer until a fix is ready.
Please do not open a public issue for a security bug, and please do not post the
details on social media or a mailing list before a fix is out.

A useful report says what you found, how to reproduce it, which library or tool
and version it affects, and the runtime (CircuitPython, MicroPython, or CPython)
when the bug is runtime-specific. A proof of concept helps, even a rough one.

## What to expect

ChuMicro is maintained by one person, so there is no formal service-level
agreement and no promised response time. Here is the honest version of what
happens after you report:

- You get an acknowledgment that the report arrived.
- The maintainer tries to reproduce it and confirms whether it is a real issue.
- A confirmed issue gets a fix, and a disputed one gets an explanation of why.
  Serious problems go to the front of the line.

Fixes land in the next release of the affected package. Versions you have pinned
are not back-patched one by one. If a report goes quiet for a while, a polite
follow-up on the advisory thread is welcome.
