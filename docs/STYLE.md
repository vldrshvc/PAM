# PAM — visual style

A warm, well-kept paper notebook. The notebook is a **skin**: grain, tape,
spiral and ruled lines all sit behind the content and never cost legibility or
tap comfort. Every rule below lives in `app/static/styles.css` as a token or a
single component block, so changing the look means changing values, not markup.

## Principles

1. **Handwriting is decoration, never data.** Caveat is used for page titles,
   section labels, status pills, buttons and empty states. Every figure, every
   row title and every secondary amount is Inter with tabular figures, because
   handwritten digits are ambiguous and money must not be.
2. **One dominant number per card.** The balance is 42px; the four supporting
   figures are 20px; row amounts are 16px. The eye should land once.
3. **Columns, not guesses.** Amounts sit in a fixed 104px right-aligned column,
   so every amount and every progress bar starts and ends on the same pixel.
4. **Nothing decorative may move layout.** The overspend circle, the tape and
   the grain are overlays drawn outside the flow.

## Colour

Semantic tokens only; no component hardcodes a hex value. Dark mode is the same
notebook bound in leather, switched by `prefers-color-scheme`.

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--desk` | `#f2ebdb` | `#17130f` | Page behind the paper |
| `--page` | `#fffcf5` | `#241e18` | Card / paper |
| `--page-edge` | `#e9e0cc` | `#3a3129` | Paper border |
| `--cover` / `--cover-hi` | `#1b3557` / `#24456e` | `#14263d` / `#1c3454` | Header cover |
| `--ink` | `#2a2724` | `#f1e7d7` | Body text (warm grey, never pure black) |
| `--ink-blue` | `#1f3a5f` | `#9dbce0` | Accent **text**, bar fill |
| `--pencil` | `#6b665e` | `#a79d8e` | Secondary text |
| `--green` | `#2f6b4f` | `#86bb9c` | Income, on track |
| `--brick` | `#a6402f` | `#e0897c` | Overspent, destructive (red pencil, never pure red) |
| `--accent-bg` / `--accent-fg` | `#1f3a5f` / `#fdfaf2` | `#2f5480` / `#f3ece0` | Filled controls |
| `--green-bg` / `--green-fg` | `#2f6b4f` / `#f4fbf7` | `#2f6048` / `#eaf6ef` | Achieved pill |
| `--rule` | `#cfdce9` | `#3b332a` | Ruled divider between rows |
| `--margin-rule` | `#e6b0aa` | `#6b423c` | The red margin down the left |
| `--track` | `#ece2cf` | `#322a22` | Progress track (bare paper) |
| `--field` / `--field-line` | `#ffffff` / `#c3b9a4` | `#2c251e` / `#4b4036` | Inputs |

An accent that reads well **as text on paper** is not the one that reads well
**behind text**, which is why `--ink-blue` and `--accent-bg` are separate.

### Measured contrast

Checked in the browser against the actual composited background, both themes:

| Element | Light | Dark | Required |
|---|---|---|---|
| Balance, row title, heading | 14.5 | 13.5 | 3.0 |
| Labels, row subtitle, amount, note | 5.6 | 6.2 | 4.5 |
| Primary button, active segment | 11.0 | 6.6 | 3.0 |
| Active / inactive tab | 11.2 / 8.9 | 8.4 / 11.0 | 3.0 / 4.5 |
| Account chip | 5.7 | 5.7 | 4.5 |

## Type

| Role | Font | Size / weight | Notes |
|---|---|---|---|
| Brand | Caveat | 27 / 700 | Header only |
| Page & section title | Caveat | 28 / 700 | Squiggle underline |
| Section label (`.label`) | Caveat | 17 / 500 | "Spent", "Budget left" |
| Status pill, buttons, empty state | Caveat | 16–20 / 700 | No digits ever |
| Balance | Inter | 42 / 700 | `letter-spacing: -.025em` |
| Supporting figures | Inter | 20 / 600 | |
| Row amount | Inter | 16 / 700 | Fixed 104px column |
| Row title | Inter | 15 / 600 | Truncates with ellipsis |
| Row subtitle, note, per-day | Inter | 13 / 400 | Carries money, so never handwriting |

`font-variant-numeric: tabular-nums` is set on `body`, so digits never shuffle
as values change. Both families are subsetted and embedded as base64 in
`app/static/fonts.css` (184 KB): no third-party request, works offline.

## Spacing

An 8px grid: `--s1: 4`, `--s2: 8`, `--s3: 12`, `--s4: 16`, `--s5: 24`, `--s6: 32`.
Page padding is 16px; cards are 16px apart; card padding is 24px top, 16px right
and bottom, 24px left to clear the margin rule. Minimum touch target is 44px
(`--tap`) and it is enforced on buttons, inputs, selects, nav tabs and row
delete targets.

## Components

- **Cover (`.topbar`)** — deep ink-blue gradient, grain overlay, and a spiral
  strip along the bottom edge drawn as two stacked radial gradients: a dark
  punched hole plus a lit lower lip.
- **Tab (`.tabs button`)** — Caveat, 44px tall. The active one is a divider
  pulled out of the pages: paper-coloured, top corners rounded, lifted shadow.
- **Page (`.card`)** — paper colour with the red margin rule ruled straight into
  the background, a grain layer behind the text, and a strip of washi tape on
  top. Tape angle and colour rotate across three variants by `nth-of-type`.
- **Row (`.list li`)** — 44px minimum, divided by a ruled line, never a plain
  border. Title, then subtitle; amount in the fixed column; a 44px delete target
  drawn as a pen stroke cross.
- **Amount** — right-aligned, tabular. Income is green with a leading `+`.
  Overspent is brick red and gets a hand-drawn circle around it, drawn as a
  masked SVG overlay so the column stays aligned.
- **Progress (`.bar`)** — 7px, paper-coloured track with an inset shadow, fill
  as an ink stroke that darkens left to right and turns brick when over budget.
- **Status pill** — Caveat on a 16% tint of its own colour; `achieved` is solid
  green and gains a checkmark doodle.
- **Field** — a ruled blank: no box, a 1.5px baseline that turns ink-blue on
  focus. Selects keep a full border because they carry a chevron.

## Motion

All under 250ms, and all disabled under `prefers-reduced-motion: reduce`.

| Where | What |
|---|---|
| View change | `page-turn`: 220ms, a 3.5° Y-rotation with a 6px lift, so switching months feels like turning a page |
| Progress bars | `ink-fill`: 240ms `scaleX` from the left, like a stroke being drawn |
| Buttons | 120ms press: 1px down plus an inset shadow, as if pressing into paper |
| Toast | 180ms lift from below |

## Hand-drawn assets

Three inline SVGs, held as tokens so any element can mask them: `--squiggle`
(title underline), `--circle-doodle` (overspent amount), `--tick-doodle`
(achieved), plus `--cross-doodle` for delete. They are masks, not images, so
they inherit the current colour and adapt to both themes.
