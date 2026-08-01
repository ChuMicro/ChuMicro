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
install step: never a silent pass that would let a JS regression ship unobserved.

This is a FIXTURE-ONLY lane: every assertion below names a card the fixture defines (ids 2 and
4), so there is nothing to point at a real page. It therefore renders only into a directory it
owns, exactly like validate_picker.py: no argument = a fresh temp dir, `--fixture-out DIR` names
one and REFUSES loud when DIR already holds files. A validator never overwrites its subject.

Usage: validate_picker_smoke.py [--fixture-out DIR]   (default: a fresh temp dir)
Exit 0 all behavior assertions held; 2 a behavior assertion failed; 3 playwright or chromium
is unavailable (loud skip).
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate_picker  # noqa: E402  reuse the same all-feature fixture + its render/ownership rules

PASS_EXIT = 0
FAIL_EXIT = 2
SKIP_EXIT = 3


def _render_page(outdir):
    """Render the shared fixture into our own `outdir`; return the page path.

    Delegates to validate_picker.render_fixture so the smoke and the static gates assert against
    ONE page built one way, never two that can drift apart (WS17 E1).
    """
    try:
        return validate_picker.render_fixture(outdir)
    except RuntimeError as error:
        print(f"FAIL smoke: {error}", flush=True)
        sys.exit(FAIL_EXIT)


def _parse_argv(argv):
    """-> the fixture output dir. Only `--fixture-out DIR` is accepted; anything else exits loud."""
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: validate_picker_smoke.py [--fixture-out DIR]", flush=True)
        sys.exit(0)
    if argv and argv[0] == "--fixture-out":
        if len(argv) != 2:
            sys.exit("--fixture-out takes exactly one directory")
        return validate_picker.own_fixture_dir(argv[1])
    if argv:
        sys.exit(f"unexpected argument {argv[0]!r}: this lane only drives the built-in fixture.\n"
                 f"Usage: validate_picker_smoke.py [--fixture-out DIR]")
    return tempfile.mkdtemp(prefix="picker-smoke-")


def main():
    outdir = _parse_argv(sys.argv[1:])

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIPPED smoke (playwright not installed: `pip install playwright`)", flush=True)
        sys.exit(SKIP_EXIT)

    page_path = _render_page(outdir)
    page_url = "file://" + page_path

    problems = []
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as error:
                # A missing browser binary surfaces here, not at import: `playwright install
                # chromium` has not been run. Skip loudly rather than fail the gate.
                print(f"SKIPPED smoke (chromium unavailable: `playwright install chromium`): "
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

            # a prose answer rides as its own "prose <item>.<id>: <text>" line, newline-escaped
            card4.locator(".prose").fill("first paragraph.\nsecond paragraph.")
            blob_text = blob.input_value()
            if "prose 4.context: first paragraph.\\nsecond paragraph." not in blob_text:
                problems.append(f'blob missing the prose line; blob was:\n{blob_text}')


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

            # item 7 carries every structured field kind. The empty required text field must
            # mark Submit blocked AND light itself up; answering it clears both.
            if not page.evaluate("document.getElementById('submitbtn').classList.contains('blocked')"):
                problems.append("Submit is not marked blocked while the required text field is empty")
            if page.locator(".ffield.missing").count() != 1:
                problems.append("the unanswered required field does not carry the .missing highlight")
            card7 = page.locator('.card[data-id="7"]')
            card7.locator(".fld-text").fill("PMA-1234")
            if page.evaluate("document.getElementById('submitbtn').classList.contains('blocked')"):
                problems.append("Submit stayed blocked after the required text field was filled")
            if page.locator(".ffield.missing").count() != 0:
                problems.append("the .missing highlight did not clear after answering")
            blob_text = blob.input_value()
            if "field 7.key: PMA-1234" not in blob_text:
                problems.append(f'blob missing the text field line; blob was:\n{blob_text}')

            # multi: checking a second box joins the default in one comma-joined line
            card7.locator('.fld-multi[value="setup flow"]').check()
            blob_text = blob.input_value()
            if "multi 7.areas = playback, setup flow" not in blob_text:
                problems.append(f'blob missing the multi line; blob was:\n{blob_text}')

            # scale: moving the range updates the live value chip and the always-riding line
            page.eval_on_selector(
                ".fld-scale",
                "el => { el.value = 4; el.dispatchEvent(new Event('input', {bubbles: true})); }")
            blob_text = blob.input_value()
            if "scale 7.confidence = 4/5" not in blob_text:
                problems.append(f'blob missing the scale line; blob was:\n{blob_text}')
            if page.locator(".scaleval").text_content() != "4/5":
                problems.append("the scale's live value chip did not follow the slider")

            # menu: a picked option rides; the empty (unanswered) default rides nothing
            card7.locator(".fld-menu").select_option("ui shell")
            blob_text = blob.input_value()
            if "menu 7.component = ui shell" not in blob_text:
                problems.append(f'blob missing the menu line; blob was:\n{blob_text}')

            # the upload zone is inert from file:// and says so (the hub lane is check_kit's job)
            drop_class = page.locator(".fld-drop").get_attribute("class") or ""
            if "off" not in drop_class:
                problems.append("the upload drop zone is not marked .off on a file:// page")
            if "served through the hub" not in (page.locator(".upmsg").text_content() or ""):
                problems.append("the upload zone does not explain why it is inert from file://")

            # allow_other on item 4: typing in the write-in box selects its radio and the text
            # rides as an `other 4:` line (this deliberately overrides the earlier apply pick)
            card4.locator(".otherbox").fill("hold it for the next release train")
            blob_text = blob.input_value()
            if "4 = other" not in blob_text:
                problems.append(f'typing in the write-in box did not select the other seat; blob was:\n{blob_text}')
            if "other 4: hold it for the next release train" not in blob_text:
                problems.append(f'blob missing the write-in line; blob was:\n{blob_text}')

            # the gallery lightbox: a click opens the overlay, Escape closes it
            page.locator("a.lbimg").first.click()
            if page.evaluate("document.getElementById('lightbox').hidden"):
                problems.append("clicking a gallery image did not open the lightbox")
            page.keyboard.press("Escape")
            if not page.evaluate("document.getElementById('lightbox').hidden"):
                problems.append("Escape did not close the lightbox")

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

    print("OK smoke (radio pick, notes, candidate pick, text/multi/scale/menu fields, the "
          "write-in seat, required gating, the lightbox, and the inert file:// upload zone "
          "all behave; .done marks decided cards)", flush=True)
    print(f"fixture page: {page_path}", flush=True)
    sys.exit(PASS_EXIT)


if __name__ == "__main__":
    main()
