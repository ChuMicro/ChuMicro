#!/usr/bin/env python3
"""Generate per-voice preview samples for the pick menu (one-time, and on each voice add).

Renders every voice against a FIXED neutral subject (a FIFO buffer) in free prose — no code — so the
sample exposes the true voice. Runs the preview workflow as one clean-room `claude -p`, then merges the
samples into voices.json under "previews". Re-run after adding a voice; by default it fills only the missing
previews (`--all` regenerates every voice).

Usage: gen_voice_previews.py [--all]
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from preflight import require_claude  # noqa: E402


def main():
    require_claude()
    regen_all = "--all" in sys.argv
    vpath = os.path.join(SKILL, "voices.json")
    data = json.load(open(vpath))
    voices = data["voices"]
    previews = data.get("previews", {})
    need = [k for k in voices if regen_all or k not in previews]
    if not need:
        print("all voices already have previews; nothing to do (use --all to regenerate)")
        return

    room = tempfile.mkdtemp(prefix="regen-vp-")
    os.makedirs(os.path.join(room, "previews"), exist_ok=True)
    vjson = json.dumps([{"key": k, "para": voices[k]} for k in need])
    src = open(os.path.join(SKILL, "voice_preview_wf.js")).read()
    src = src.replace("__RUNDIR__", room).replace("__VOICES_JSON__", vjson)
    open(os.path.join(room, "voice_preview_wf.js"), "w").write(src)

    print(f"generating previews for: {', '.join(need)}")
    subprocess.run(
        ["claude", "-p",
         "Use the Workflow tool to run ./voice_preview_wf.js (call Workflow with scriptPath "
         "./voice_preview_wf.js). Wait for full completion, then reply DONE.",
         "--allowedTools", "Workflow", "Task", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=room, capture_output=True, text=True,
    )

    got = 0
    for k in need:
        p = os.path.join(room, "previews", k + ".txt")
        if os.path.exists(p):
            previews[k] = open(p).read().strip()
            got += 1
        else:
            print(f"  WARN: no preview produced for {k}")
    data["previews"] = previews
    json.dump(data, open(vpath, "w"), indent=2, ensure_ascii=False)
    print(f"=== merged {got}/{len(need)} preview(s) into voices.json ===")
    shutil.rmtree(room, ignore_errors=True)


if __name__ == "__main__":
    main()
