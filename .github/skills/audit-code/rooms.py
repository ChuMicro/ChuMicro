#!/usr/bin/env python3
"""audit-code — run-room allocation.

Every evaluation gets its OWN fresh, unique room under /tmp/audit-cr, created with ``tempfile.mkdtemp`` so
the name is allocated atomically. This is the only safe way to mint a room: two parallel runs that hand-build
a name like ``<slug>-1`` both guess the same string and land in the SAME directory, and a leftover dir from
an earlier run silently poisons a new one with stale artifacts. NEVER construct a room path by hand -- call
``new_room`` (or ``rooms.py new <slug>``).

Usage: rooms.py new <slug>   # mkdtemp a fresh room under /tmp/audit-cr, print its absolute path
"""
import os
import sys
import tempfile

BASE = "/tmp/audit-cr"


def new_room(slug):
    """Create and return a fresh, unique run room under BASE (atomic; never collides, never reuses)."""
    os.makedirs(BASE, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in (slug or "run")) or "run"
    return tempfile.mkdtemp(prefix=f"{safe}-", dir=BASE)


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "new":
        print(new_room(sys.argv[2]))
    else:
        sys.exit("usage: rooms.py new <slug>")


if __name__ == "__main__":
    main()
