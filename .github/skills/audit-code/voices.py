#!/usr/bin/env python3
"""audit-code — voice registry access (reads the shared registry at `_shared/voices/voices.json`).

A voice tunes the REGISTER the findings are written in; it never changes the facts or the consequence. The
default is `plain` (voiceless) — clearest, no persona. The orchestrator prints the menu at the gate and looks
up the chosen persona to pass into the evaluation.

Usage:
  voices.py menu              # print the numbered voice menu (plain first, marked default,
                              # one preview-sentence taste per voice so the pick isn't blind)
  voices.py persona <key>     # print the persona string for <key> (empty for plain / unknown)
"""
import json
import os
import sys

REG = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "_shared", "voices", "voices.json"))


def _voices():
    return json.load(open(REG)).get("voices", {})


def _first_sentence(text):
    """The first sentence of a cached preview, flattened to one line (empty when no preview exists)."""
    text = " ".join(text.split())
    if not text:
        return ""
    end = text.find(". ")
    sentence = text if end == -1 else text[: end + 1]
    if len(sentence) > 160:
        sentence = sentence[:160].rsplit(" ", 1)[0] + " …"
    return sentence


def menu():
    registry = json.load(open(REG))
    voices = registry.get("voices", {})
    previews = registry.get("previews", {})
    keys = ["plain"] + [k for k in voices if k != "plain"]
    print("Pick a voice for the findings (the register the traps are written in):\n")
    for i, k in enumerate(keys, 1):
        if k == "plain":
            print(f"  {i}. plain   (default, voiceless — clearest)")
        else:
            persona = voices.get(k, "")
            print(f"  {i}. {k}   — {persona[:96]}")
        taste = _first_sentence(previews.get(k, ""))
        if taste:
            print(f"       e.g. {taste}")
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
