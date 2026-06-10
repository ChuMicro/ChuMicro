#!/usr/bin/env python3
"""audit-code — voice registry access (shared shape with regen-comments' voices.json).

A voice tunes the REGISTER the findings are written in; it never changes the facts or the consequence. The
default is `plain` (voiceless) — clearest, no persona. The orchestrator prints the menu at the gate and looks
up the chosen persona to pass into the evaluation.

Usage:
  voices.py menu              # print the numbered voice menu (plain first, marked default)
  voices.py persona <key>     # print the persona string for <key> (empty for plain / unknown)
"""
import json
import os
import sys

REG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices.json")


def _voices():
    return json.load(open(REG)).get("voices", {})


def menu():
    voices = _voices()
    keys = ["plain"] + [k for k in voices if k != "plain"]
    print("Pick a voice for the findings (the register the traps are written in):\n")
    for i, k in enumerate(keys, 1):
        if k == "plain":
            print(f"  {i}. plain   (default, voiceless — clearest)")
        else:
            persona = voices.get(k, "")
            print(f"  {i}. {k}   — {persona[:96]}")
        print()
    print("type a number or key (Enter = 1, plain). The findings stay clear either way; a voice only adds bite.")


def persona(key):
    sys.stdout.write(_voices().get(key, "") or "")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "menu":
        menu()
    elif len(sys.argv) >= 3 and sys.argv[1] == "persona":
        persona(sys.argv[2])
    else:
        sys.exit("usage: voices.py menu | persona <key>")


if __name__ == "__main__":
    main()
