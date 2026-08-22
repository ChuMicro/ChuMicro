# Schematics for the buttons guide

Every SVG in this directory is generated. Editing the vector output by hand puts
it out of step with the script that drew it, so change the script and render
again.

The drawings belong to the wiring and debounce section of `docs/guide.md`, the
section that explains when `settle_ms=0` is the right setting and what hardware
earns it.

## Regenerating

`scripts/render_button_schematics.py`, at the root of the mono-repo, draws all
five with [schemdraw](https://schemdraw.readthedocs.io/). schemdraw is a
documentation tool that runs on your computer. It belongs in the workspace
virtualenv and in no library's `pyproject.toml`, because nothing it produces
reaches a device.

```console
$ uv pip install schemdraw
$ python scripts/render_button_schematics.py
```

That writes all five files. While you are working on one drawing, render just
that one:

```console
$ python scripts/render_button_schematics.py --figure debounce-rc
```

To see the result before you commit it, open the SVG in a browser, or turn it
into a PNG with `rsvg-convert -b white -w 800 debounce-rc.svg -o /tmp/check.png`.
Render it a second time over `-b '#1f2129'` to see what the documentation site
shows.

## The five figures

| File | `--figure` name | What it shows | Component values |
| --- | --- | --- | --- |
| `wiring-active-low.svg` | `wiring-active-low` | Momentary switch from the pin to GND, pull-up supplied by the pin itself | internal pull-up, tens of kΩ, no external part |
| `wiring-active-high.svg` | `wiring-active-high` | Momentary switch from the pin to 3V3, held low by an external resistor | R1 10 kΩ |
| `debounce-rc.svg` | `debounce-rc` | RC low-pass on its own, including the series resistor that keeps the discharge path finite | R1 10 kΩ, R2 2.2 kΩ, C1 2.2 µF |
| `debounce-rc-schmitt.svg` | `debounce-rc-schmitt` | An RC network squared up by a Schmitt-trigger inverter | R1 10 kΩ, R2 4.7 kΩ, C1 2.2 µF, C2 100 nF, 74HC14 |
| `debounce-spdt-latch.svg` | `debounce-spdt-latch` | SPDT switch into a cross-coupled NAND latch | R1 10 kΩ, R2 10 kΩ, 74HC00 |

## The RC values

The two RC figures share a pull-up and a capacitor and differ in the series
resistor, because they feed different things.

| | `debounce-rc` | `debounce-rc-schmitt` |
| --- | --- | --- |
| R1, pull-up | 10 kΩ | 10 kΩ |
| R2, series | 2.2 kΩ | 4.7 kΩ |
| C1 | 2.2 µF | 2.2 µF |
| Press, C1 empties through R2 alone | τ = 4.8 ms | τ = 10 ms |
| Release, C1 refills through R1 and R2 | τ = 27 ms | τ = 32 ms |
| Contacts, held down | 330 µA | 330 µA |
| Contacts, peak as C1 empties | 1.5 mA | 0.7 mA |
| What it earns | `settle_ms=5` | `settle_ms=0` |

C1 refills through R1 and R2 in line and empties through R2 on its own, so the
release edge is always the slower of the two. That lopsidedness is built into
the arrangement, and no choice of values takes it out.

On the bare-pin figure R2 also has to stay well under R1. The library turns the
pin's own pull-up on for every button, and R2 divides against it. Against the
13 kΩ pull-up an nRF52840 supplies, 2.2 kΩ holds the pressed pin near 0.5 V,
which is a solid low. At 10 kΩ it would sit near 1.4 V, which is not one.

That same internal pull-up sits in parallel with R1 while the capacitor refills,
so the release you measure comes in ahead of the 27 ms the printed parts give on
their own: nearer 14 ms on a board whose pull-up is 13 kΩ and nearer 22 ms on
one nearer 50 kΩ. The 27 ms on the drawing is the slow end, which is the one to
size a settle window against. The 74HC14 figure has no such help, and its 32 ms
is what it is.

The 74HC14 figure has no such divider, because a logic input supplies no pull-up
of its own and the pressed node reaches a true 0 V. That is why R2 moves up to
4.7 kΩ there. The larger value brings the two time constants closer together and
halves the peak the contacts carry.

Only the 74HC14 figure earns `settle_ms=0`. An RC network on its own hands the
pin a slow ramp across a single threshold, and a plain input has no hysteresis
you can count on, so that figure asks for `settle_ms=5`. The 74HC14 switches at
1.8 V on the way up and 1.05 V on the way down: C1 needs 12 ms to fall to the
lower point and 25 ms to climb to the upper one, so the contacts have long
stopped moving before either is crossed, and a gap in the bouncing would have to
last 13 ms to undo a crossing.

Buy a capacitor that still measures 2.2 µF with 3.3 V across it. A small ceramic
gives up a good part of its value under DC bias, so reach for a film part or an
X7R rated 25 V or better and these numbers hold.

Every value and every time constant printed on the two drawings comes from
`RC_PULL_UP_KOHM`, `RC_CAPACITOR_UF`, `RC_SERIES_PLAIN_KOHM` and
`RC_SERIES_SCHMITT_KOHM` at the top of the script, so changing one there moves
the component label and the arithmetic together.

## House style

One ink, `#7f8a96`, draws every line and every label, over a transparent
background. The documentation site renders these on a dark page and GitHub
renders the same files on a light one, and an embedded image takes its colors
from neither page, so a single mid-tone that holds roughly 4:1 contrast at both
ends is what stays readable in either place. Keep new artwork on that ink rather
than adding a second color.

The rest of the style lives in the constants at the top of the script: `UNIT`,
`LINE_WIDTH`, `LABEL_SIZE` for component labels, and `NOTE_SIZE` with
`NOTE_STEP` for the block of notes under each drawing. Change them there and
every figure moves together.

Two schemdraw habits are worth knowing before you edit a figure. A label on a
component drawn downward reads `loc="top"` for the left side and `loc="bot"` for
the right side, because the label frame turns with the component. And an element
placed with `.at()` still points the way the previous element left it, so a
`Rect` needs `.right()` after a vertical resistor or it arrives rotated a
quarter turn.
