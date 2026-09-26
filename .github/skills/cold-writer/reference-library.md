# Documentation reference library

## Contents

- [Choose by the page's job](#choose-by-the-pages-job)
- [Adafruit Learn](#adafruit-learn-physical-instruction-and-layout)
- [Raspberry Pi Projects](#raspberry-pi-projects-short-actions-and-physical-orientation)
- [Arduino](#arduino-teach-one-timing-mechanism-through-a-working-example)
- [MicroPython](#micropython-scannable-board-reference)
- [Adafruit Requests](#adafruit-requests-library-guide-and-api-navigation)
- [Django](#django-checkpoints-in-a-longer-setup-sequence)
- [Diátaxis](#diátaxis-give-each-page-a-clear-purpose)
- [Google developer style](#google-developer-style-a-check-on-voice)
- [Related skills](#related-skills)

Use these established documentation projects as concrete design references.
Selection reflects their relevance to embedded Python and developer education;
it is not a traffic ranking. Open the relevant page again before adopting a
version-dependent detail. External examples inform presentation. Verify ChuMicro
behavior independently.

## Choose by the page's job

| Need | Start with | Useful second reference |
|---|---|---|
| First successful board program | Raspberry Pi Projects | MicroPython quick reference for compact examples |
| Timers and cooperative work | Arduino's Blink Without Delay | MicroPython quick reference |
| Board wiring and physical setup | Raspberry Pi Projects | Arduino circuit and schematic |
| Library onboarding | Adafruit Requests | Adafruit Learn |
| Compact API or board lookup | MicroPython quick reference | Adafruit Requests API navigation |
| Multi-step software setup | Django tutorial | Raspberry Pi Projects |
| Documentation architecture | Diátaxis | Django's tutorial/reference separation |
| Professional, approachable wording | Google's developer style guide | ChuMicro audience and task requirements |

Choose a reference for a particular design decision. The second column offers
options, not a requirement to combine models or imitate their prose.

## Adafruit Learn: physical instruction and layout

[Creating and Editing Code](https://learn.adafruit.com/welcome-to-circuitpython/creating-and-editing-code)
walks from opening a file to running a program, then changing its timing. It
places code, editor images, expected LED behavior, and encouragement beside the
actions. Its guide navigation divides a larger subject into named pages.

**Apply to ChuMicro:** use a picture where recognizing a board or application
state matters. Place expected output beside actions when it helps a reader
recognize success. Borrow navigation or illustration choices as needed.

**Adaptation boundary:** choose commands and file locations from ChuMicro's actual
workflow. Its encouragement and playful voice are outside ChuMicro's default
editorial brief. Verify board-specific LED behavior. Use original illustrations or
properly licensed assets; the reference's photos and wording remain its own.

## Raspberry Pi Projects: short actions and physical orientation

[Getting started with Pico](https://projects.raspberrypi.org/en/projects/getting-started-with-the-pico)
has maintained sources for its [parts and goal](https://github.com/raspberrypilearning/getting-started-with-the-pico/blob/master/en/step_1.md),
[firmware setup](https://github.com/raspberrypilearning/getting-started-with-the-pico/blob/master/en/step_4.md),
and [package installation](https://github.com/raspberrypilearning/getting-started-with-the-pico/blob/master/en/step_5.md).
The firmware lesson pairs individual actions with images of BOOTSEL, USB wiring,
and the editor's interpreter selector. It names the drive the learner should see.

**Apply to ChuMicro:** separate physical setup from laptop commands. Show a
connector, button, or selector at the step that needs it. State the observable
result and keep optional hardware in a separate parts list.

**Adaptation boundary:** the lesson uses MicroPython and Thonny. ChuMicro's
workbench commands need their own verified sequence. The source files establish
content and image placement; inspect the rendered site before copying visual
components such as task cards or progress navigation.

## Arduino: teach one timing mechanism through a working example

[Blink Without Delay](https://docs.arduino.cc/built-in-examples/digital/BlinkWithoutDelay/)
introduces a practical need to do two things at once, then presents hardware,
a circuit drawing, a schematic, and code. Its
[maintained Markdown source](https://github.com/arduino/docs-content/blob/main/content/built-in-examples/02.digital/BlinkWithoutDelay/BlinkWithoutDelay.md)
makes the order and image roles inspectable.

**Apply to ChuMicro:** a timing lesson can begin with a visible activity such as
an LED and add one concurrent task. Use a wiring picture to show physical
connections and a schematic when electrical relationships need explanation.

**Adaptation boundary:** Arduino's C++ and `millis()` arithmetic do not establish
ChuMicro's Python APIs or wrapping-tick rules. Borrow the teaching sequence and
verify the replacement example. A short concrete demonstration can carry the
point without reproducing the reference's extended analogy.

## MicroPython: scannable board reference

[RP2 quick reference](https://docs.micropython.org/en/latest/rp2/quickref.html)
groups short code examples under hardware tasks and APIs such as pins, UART,
SPI, I2C, PWM, ADC, and timers. Board information and links sit alongside the
lookup material.

**Apply to ChuMicro:** use stable task headings and compact examples in reference
pages. Keep defaults, units, limits, and applicable runtimes beside the symbol
being looked up. Link to a tutorial for first-time setup.

**Adaptation boundary:** this is a lookup model for readers who already know the
basics. Its density would overwhelm an opening tutorial. The `latest` URL can
describe development behavior, so pin a version when using it as technical evidence.

## Adafruit Requests: library guide and API navigation

[Adafruit Requests documentation](https://docs.circuitpython.org/projects/requests/en/latest/)
places installation, usage, API, examples, and related project links in a library
documentation structure.

**Apply to ChuMicro:** give each library a short route from installation to one
complete example, with a separate API destination. Keep page labels predictable
across libraries. Link from a tutorial to a symbol's reference at the point where
readers are likely to customize it.

**Adaptation boundary:** its networking setup and runtime support belong to that
library. Re-derive ChuMicro imports, connection setup, memory limits, and security
behavior from ChuMicro sources.

## Django: checkpoints in a longer setup sequence

[Writing your first Django app, part 1](https://docs.djangoproject.com/en/5.2/intro/tutorial01/)
uses commands, generated directory listings, a development-server check, and
links to deeper documentation to guide a longer software setup.

**Apply to ChuMicro:** after scaffolding, show the file a learner will edit and
how to recognize successful creation. After execution, show relevant output.
Put useful recovery beside the relevant checkpoint and keep optional explanations linked.

**Adaptation boundary:** use this for sequencing and verification. Its web framework terminology and server
architecture add nothing to a board tutorial.

## Diátaxis: give each page a clear purpose

[Diátaxis](https://diataxis.fr/) distinguishes tutorials, how-to guides, reference,
and explanation. Its [tutorial guidance](https://diataxis.fr/tutorials/) emphasizes
meaningful action, achievable steps, visible results, and telling learners what
to expect.

**Apply to ChuMicro:** choose a page type before drafting. Put a learner's first
success on a tutorial page, repeated procedures in how-to guides, exact options
in reference, and architectural reasoning in explanation. Cross-link the pages
where that helps the reader continue.

**Adaptation boundary:** use the distinctions to make navigation useful. A page
can contain the small amount of explanation or reference needed to complete its
task. Preserve explicit user requirements when choosing its structure.

## Google developer style: a check on voice

[Voice and tone](https://developers.google.com/style/tone) favors conversational,
clear language that respects the reader.

**Apply to ChuMicro:** test whether an instruction sounds natural when spoken to
a colleague. Use direct address and familiar words. Explain unfamiliar project
concepts at first use and respect the reader's existing knowledge.

**Adaptation boundary:** ChuMicro's audience and task set the voice. Use this
guidance to catch patronizing, vague, or distracting prose; do not import a
reference's length or structure without a reader need.

## Related skills

- [mcollina/documentation](https://github.com/mcollina/skills/blob/main/skills/documentation/SKILL.md)
  supplies a compact Diátaxis decision table and outcome-based tutorial checks.
- [OpenFang technical-writer](https://github.com/RightNow-AI/openfang/blob/main/crates/openfang-skills/bundled/technical-writer/SKILL.md)
  suggests task headings, progressive introduction, and copy-paste verification.
- [Writers Room](https://github.com/JuJu78/writers-room/blob/main/SKILL.md) separates
  research, planning, writing, and review. Its SEO stages and repeated editorial
  passes serve an article workflow and are outside this skill's default process.

These are prior-art links, not dependencies or instructions to install a package.
The cold writer receives original, positive requirements distilled by the
researcher. Reviewers retain the source links and the rationale for each choice.
