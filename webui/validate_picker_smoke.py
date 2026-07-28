#!/usr/bin/env python3
"""Drive a rendered picker page in headless chromium and assert the JS contract holds.

validate_picker.py proves the markup, CSS, and the three coupled namespaces stay in sync,
but every check there reads static HTML. None of it runs the page. This script renders the
same all-feature fixture, opens it in headless chromium, and exercises the live behavior the
static gates cannot see:

  - picking a non-default radio adds `.card.done` to that card (the decided-facet marker the
    CSS turns into a "✓" suffix on the card id);
  - typing in `.notes` and the radio pick both reach the readonly `#blob` textarea in the
    documented `<id> = <value>` / `note <id>: <text>` line format;
  - picking a candidate box in a `columns` card adds `.card.done` there too.

Playwright and the chromium browser binary are heavy host-only deps absent from a fresh
checkout. When either is missing this exits SKIP_EXIT (3) with a one-line reason naming the
install step, never a silent pass that would let a JS regression ship unobserved.

Usage: validate_picker_smoke.py [<output-dir>]   (default: a fresh temp dir)
Exit 0 all behavior assertions held; 2 a behavior assertion failed; 3 playwright or chromium
is unavailable (loud skip).
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_picker  # noqa: E402  reuse the same all-feature fixture

PASS_EXIT = 0
FAIL_EXIT = 2
SKIP_EXIT = 3


def _render_page(outdir):
    """Write the shared fixture spec and render it to picker.html; return the file path.

    Reuses validate_picker.FIXTURE so the smoke and the static gates assert against one page,
    never two that can drift apart.
    """
    os.makedirs(outdir, exist_ok=True)
    spec_path = os.path.join(outdir, "spec.json")
    with open(spec_path, "w") as handle:
        json.dump(validate_picker.FIXTURE, handle, indent=1, ensure_ascii=False)
    render = subprocess.run(
        [sys.executable, os.path.join(HERE, "render_picker.py"), spec_path, outdir],
        capture_output=True, text=True,
    )
    if render.returncode != 0:
        print(f"FAIL smoke: renderer exited {render.returncode}: {render.stderr.strip()}", flush=True)
        sys.exit(FAIL_EXIT)
    return os.path.join(outdir, "picker.html")


def main():
    outdir = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="picker-smoke-")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIPPED smoke (playwright not installed; `pip install playwright`)", flush=True)
        sys.exit(SKIP_EXIT)

    page_path = _render_page(outdir)
    page_url = "file://" + page_path

    problems = []
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as error:
                # A missing browser binary surfaces here, not at import, meaning `playwright install
                # chromium` has not been run. Skip loudly rather than fail the gate.
                print(f"SKIPPED smoke (chromium unavailable; `playwright install chromium`): "
                      f"{type(error).__name__}: {error}", flush=True)
                sys.exit(SKIP_EXIT)
            page = browser.new_page()
            page.goto(page_url)

            # item 4 is the plain decision card: page options [apply, discuss, skip], default skip,
            # a notes box, no edit box. Picking apply is a non-default, non-edit pick.
            card4 = page.locator('.card[data-id="4"]')
            card4.locator('input[type=radio][value="apply"]').check()

            # the pick marks the card decided; the decided-facet CSS hangs the "✓" off this class
            if "done" not in (card4.get_attribute("class") or ""):
                problems.append('picking a non-default radio did not add .done to card 4')

            # the pick must reach the readonly blob in the documented "<id> = <value>" form
            blob = page.locator("#blob")
            blob_text = blob.input_value()
            if "4 = apply" not in blob_text:
                problems.append(f'blob missing "4 = apply" after the pick; blob was:\n{blob_text}')

            # typing in notes reaches the blob as a "note <id>: <text>" line
            card4.locator(".notes").fill("smoke note text")
            blob_text = blob.input_value()
            if "note 4: smoke note text" not in blob_text:
                problems.append(f'blob missing the typed note line; blob was:\n{blob_text}')

            # item 2 is the columns pick_ui card; its default is "suggested". Pick a different
            # candidate ("alt") so the change actually fires: a non-default, non-edit pick that
            # also marks the card decided.
            card2 = page.locator('.card[data-id="2"]')
            card2.locator('input[type=radio][value="alt"]').check()
            if "done" not in (card2.get_attribute("class") or ""):
                problems.append('picking a candidate box did not add .done to columns card 2')
            blob_text = blob.input_value()
            if "2 = alt" not in blob_text:
                problems.append(f'blob missing "2 = alt" after the candidate pick; blob was:\n{blob_text}')

            browser.close()
    except SystemExit:
        raise
    except Exception as error:
        print(f"FAIL smoke: driving the page raised {type(error).__name__}: {error}", flush=True)
        sys.exit(FAIL_EXIT)

    if problems:
        for problem in problems:
            print(f"FAIL smoke: {problem}", flush=True)
        print(f"fixture page: {page_path}", flush=True)
        sys.exit(FAIL_EXIT)

    print("OK smoke (radio pick, notes, and candidate pick all reach the blob; "
          ".done marks decided cards)", flush=True)
    print(f"fixture page: {page_path}", flush=True)
    sys.exit(PASS_EXIT)


if __name__ == "__main__":
    main()
