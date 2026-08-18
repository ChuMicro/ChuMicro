---
title: "ChuMicro guides: getting started, installing, and fixing CircuitPython and MicroPython boards"
---

# Guides

Start at the top if you have a board and nothing running on it yet.  The
rest of the pages are here for when you have a specific question or a
specific symptom.

- **[Start here](start-here.md)** goes from a board still in its
  packaging to your own code running on it, on your own wifi: putting a
  runtime on the board, registering it, making a project, and deploying.
- **[Installing libraries](install.md)** is the full matrix: circup and
  the bundle on CircuitPython, mip on MicroPython, pip on CPython, the
  pre-compiled `.mpy` packages, and switching between the stable and
  experimental channels.
- **[Questions people ask](faq.md)** covers why a board freezes on the
  network, whether any of this uses async, how the same code runs on
  CircuitPython and MicroPython, and what a library costs in flash.
- **[Troubleshooting](troubleshooting/README.md)** starts from the
  error text, the hang, or the missing drive: a board that will not
  show up, WiFi that will not connect, TLS that fails, a deploy that
  is refused, memory that runs out.
- **[Wiring WiFi credentials](wiring-wifi-credentials.md)** shows how a
  network name and password reach a board without living in your code
  or your git history.

The contributing pages further down the menu are for changing ChuMicro
itself rather than using it.

Library documentation lives on its own pages, one per library, from
[the documentation home](https://chumicro.com/ChuMicro/).
