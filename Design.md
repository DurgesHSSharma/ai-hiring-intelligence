# Design — AI Hiring Intelligence Platform

**Version:** 1.0
**Status:** Reference specification.

The frontend is authored and owned by the project owner. This document records the visual system so that the product, the PDF shortlist export, and any future surface stay consistent. Nothing here is an instruction to generate UI code.

**Superseded for the web frontend (2026-09-06):** the project owner has adopted a different visual direction — the "HireIntel" reference (purple/indigo SaaS dashboard) — as final for the `frontend/` web application, explicitly superseding this document's colour (§2), and signature-element (§1) choices for that surface. See `Memory.md` decision 90. This document's other sections (accessibility, motion discipline, voice, spacing scale where compatible) and its authority over the **PDF shortlist export** (§10, a backend-rendered surface, unaffected by this frontend decision) remain in force unless the owner says otherwise.

---

## 1. Direction

The product is an instrument panel for hiring decisions. A recruiter reads a number, understands where it came from, and decides. Every visual choice serves that: numbers are the loudest thing on the page, explanation sits immediately beside them, and decoration does not compete with either.

Three principles:

**Numbers first.** A fit score is the headline of a candidate card, set in a monospaced face at display size. Everything around it is quieter than it is.

**Never a bare score.** A score is always shown with its parts. A number without its breakdown is a design failure, not a layout shortcut.

**Restraint everywhere except the meter.** One signature element carries the personality. The rest of the interface is disciplined greys, hairline rules, and generous space.

### Signature element — the composition meter

A horizontal segmented rail beneath every fit score, showing the four weighted components as proportional segments that visibly add up to the total. The recruiter sees at a glance not just that a candidate scored 84.8, but that skills carried them and experience held them back.

```text
Fit Score
84.8 / 100 · Good match

 resume 34.8      skills 26.3    exp 13.5  edu 10.0
├──────────────┤├───────────┤├──────┤├─────┤·············
 ●              ●            ●       ●
 87.0           75.0         90.0    100.0
```

This appears on the candidate detail page, in the comparison table, and in the PDF export. It appears nowhere else — its scarcity is what makes it read as a signature rather than a texture.

---

## 2. Colour

### 2.1 Palette

Cool neutral ground, deep teal for action, and a four-step evaluative scale that does the real work. The evaluative colours are the only saturated things on most screens.

| Token | Hex | Use |
|---|---|---|
| `--ink-900` | `#101519` | Primary text, headings, score numerals |
| `--ink-700` | `#2B343D` | Strong body text, table headers |
| `--ink-500` | `#5A6672` | Secondary text, labels, captions |
| `--ink-300` | `#8C97A3` | Placeholder, disabled, tertiary metadata |
| `--line` | `#E2E7EB` | Borders, dividers, table rules |
| `--line-strong` | `#C9D1D8` | Input borders, focused dividers |
| `--canvas` | `#F4F7F8` | Page background |
| `--surface` | `#FFFFFF` | Cards, tables, panels, modals |
| `--surface-sunken` | `#EDF1F3` | Table header row, inset wells, code blocks |
| `--brand-700` | `#0B4A45` | Primary button, active nav, logo mark |
| `--brand-500` | `#0E7C6B` | Hover state, links, active tab underline |
| `--brand-100` | `#DCEDE9` | Selected row, brand tint background |
| `--focus` | `#1E9E8A` | Focus ring only. Never used as a fill |

### 2.2 Evaluative scale

One scale, used identically for candidate quality and inverted for attrition risk. A recruiter learns four colours once.

| Band | Fit score | Attrition risk | Solid | Tint | Text on tint |
|---|---|---|---|---|---|
| Strong | ≥ 85 | Low (< 30%) | `#0E7C6B` | `#DCEDE9` | `#0B4A45` |
| Good | 70–84 | — | `#2F6BA8` | `#DEE9F4` | `#1E4970` |
| Moderate | 55–69 | Medium (30–60%) | `#C08A18` | `#F7EDD5` | `#7A5709` |
| Weak | < 55 | High (> 60%) | `#B24630` | `#F7E2DD` | `#7A2E1E` |

Rules:

- These four are the only saturated colours on a data screen. Nothing else competes.
- Colour never carries meaning alone. Every band also shows its label — "Good match", "High risk" — because roughly one in twelve male users cannot separate the moderate and weak swatches reliably.
- The weak band is a muted clay red, not a warning red. A low-scoring candidate is not an error.
- High attrition risk uses the same clay. The system reports a probability; it does not alarm.

### 2.3 Skill states

| State | Marker | Fill | Border | Text |
|---|---|---|---|---|
| Matched (exact) | filled dot | `#DCEDE9` | `#0E7C6B` | `#0B4A45` |
| Matched (semantic) | hollow dot | `#DCEDE9` | dashed `#0E7C6B` | `#0B4A45` |
| Missing | dash | `#F7E2DD` | `#B24630` | `#7A2E1E` |
| Additional | none | `#EDF1F3` | `#C9D1D8` | `#5A6672` |

The dashed border on semantic matches is deliberate: the recruiter should be able to see, without reading a tooltip, which matches the system inferred rather than found.

### 2.4 Chart palette

Ordered sequence for Recharts. Categorical series in this order; never random assignment.

```text
1  #0E7C6B   teal
2  #2F6BA8   blue
3  #C08A18   ochre
4  #B24630   clay
5  #5F6CA8   slate violet
6  #4E7A4A   moss
```

Chart rules: grid lines `--line` at 1px, axes labelled in `--ink-500` at 12px, no gradients, no drop shadows, no 3D, no pie charts with more than four slices. Score distribution histograms colour each bucket by its band using §2.2, so the histogram and the candidate list agree visually.

### 2.5 Dark mode

Not in v1 scope. If added later: `--canvas` `#12171B`, `--surface` `#1A2026`, `--line` `#2B343D`, text ladder inverted, and every evaluative colour lifted roughly 12% in lightness to hold contrast on dark ground. The tints are replaced by 15% alpha overlays of their solids.

---

## 3. Typography

### 3.1 Faces

| Role | Family | Weights | Where |
|---|---|---|---|
| Display | Bricolage Grotesque | 500, 700 | Page titles, section headings, empty-state headlines |
| Body / UI | IBM Plex Sans | 400, 500, 600 | Everything else — body, labels, buttons, tables, nav |
| Data | IBM Plex Mono | 400, 500, 600 | Every number: scores, percentages, counts, dates, ids |

All three are open-licence and available from Google Fonts. Loaded as variable or subset WOFF2, `font-display: swap`, preloaded for the display and body faces only.

The reasoning: Plex Sans and Plex Mono are one family, so the interface and its data read as a single voice. Bricolage is the one outside voice, slightly odd and slightly narrow, and it appears only at heading sizes — enough to give the product a face, not enough to become a texture.

### 3.2 The mono rule

Every number in this product is set in IBM Plex Mono with `font-variant-numeric: tabular-nums`.

This is not stylistic. A ranked list of fit scores in a proportional face has digits of differing widths, so the decimal points do not align and the eye cannot scan the column. Tabular mono makes a fifty-row ranking readable in one pass. It also gives the score display an instrument quality that matches the direction.

Applies to: fit scores, sub-scores, percentages, probabilities, candidate and job counts, experience years, dates, ids, metric values. Does not apply to numbers inside running prose.

### 3.3 Scale

Base 16px, 1.25 ratio, rounded to whole pixels.

| Token | Size / line height | Face | Weight | Tracking | Use |
|---|---|---|---|---|---|
| `score-hero` | 56 / 56 | Mono | 500 | −0.02em | Candidate fit score |
| `score-lg` | 32 / 36 | Mono | 500 | −0.01em | Card score, attrition probability |
| `score-md` | 20 / 24 | Mono | 500 | 0 | Sub-scores, table score cells |
| `display-1` | 34 / 40 | Bricolage | 700 | −0.02em | Page title |
| `display-2` | 26 / 32 | Bricolage | 700 | −0.01em | Section heading |
| `display-3` | 20 / 28 | Bricolage | 500 | 0 | Card heading, modal title |
| `body-lg` | 17 / 28 | Plex Sans | 400 | 0 | Job description, long text |
| `body` | 15 / 24 | Plex Sans | 400 | 0 | Default |
| `body-strong` | 15 / 24 | Plex Sans | 600 | 0 | Emphasis, table headers |
| `label` | 13 / 18 | Plex Sans | 500 | 0.01em | Form labels, chips, buttons |
| `caption` | 12 / 16 | Plex Sans | 400 | 0.02em | Metadata, helper text, axis labels |
| `eyebrow` | 11 / 14 | Plex Sans | 600 | 0.09em, uppercase | Section eyebrows, table column keys |

### 3.4 Rules

- Sentence case everywhere except `eyebrow`. No title case in headings, buttons, or labels.
- Line length capped at 72 characters for body text.
- Never more than three type sizes in one card.
- The eyebrow is used only where a label genuinely classifies the block below it. It is not decoration and it never appears twice in one card.
- Numbers never carry units inside the numeral. `84.8` in `score-lg` with `/ 100` in `caption` beside it, not `84.8/100` in one run.

---

## 4. Layout and space

### 4.1 Spacing scale

4px base: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96`. No value outside this scale.

| Context | Value |
|---|---|
| Inside a chip or badge | 4 vertical, 8 horizontal |
| Inside a button | 10 vertical, 16 horizontal |
| Card padding | 24 |
| Between cards | 16 |
| Between sections | 48 |
| Page top padding | 32 |
| Table cell | 12 vertical, 16 horizontal |
| Form field gap | 16 |

### 4.2 Structure

- Fixed left navigation 240px on desktop, collapsing to a top bar under 1024px.
- Content max width 1280px, centred, 32px gutters.
- Twelve-column grid, 24px gap.
- Candidate detail is a two-column split: 7 columns for score, breakdown, and skills; 5 columns for the resume preview, which is sticky on scroll.
- Breakpoints: 640 · 768 · 1024 · 1280.

### 4.3 Radius and elevation

| Token | Value | Use |
|---|---|---|
| `--r-sm` | 4px | Chips, badges, meter segments |
| `--r-md` | 8px | Buttons, inputs, cards |
| `--r-lg` | 12px | Modals, side panels |

Elevation is used almost never. Cards are defined by a 1px `--line` border on `--surface` against `--canvas`, not by shadow.

| Token | Value | Use |
|---|---|---|
| `--shadow-sm` | `0 1px 2px rgba(16,21,25,0.05)` | Dropdown, popover |
| `--shadow-md` | `0 8px 24px rgba(16,21,25,0.10)` | Modal, command palette |

Nothing else casts a shadow. A dense data table under layered shadows becomes unreadable.

---

## 5. Components

### 5.1 Score display

```text
┌─────────────────────────────────────────────────────┐
│  FIT SCORE                              eyebrow     │
│                                                     │
│  84.8  / 100        ● Good match                    │
│  ↑ score-hero, mono   ↑ band pill, tint fill        │
│                                                     │
│  ├────────────┤├─────────┤├────┤├───┤·············   │
│   resume        skills     exp   edu                │
│   87.0 ×0.40    75.0 ×0.35 90×.15 100×.10           │
│   ↑ caption + mono                                  │
└─────────────────────────────────────────────────────┘
```

The meter rail is 8px tall with `--r-sm` ends. Segments are the four evaluative solids at their weighted widths; unearned remainder is `--surface-sunken`. Weights are shown, so the composition is auditable rather than mysterious.

### 5.2 Candidate row

Rank number in mono `--ink-300` · name in `body-strong` · fit score in `score-md` coloured by band · a 6px band-coloured bar · matched/missing counts as chips · status pill · action link. Row height 64px. Hover fills `--brand-100`. Selected rows show a 3px `--brand-500` left border.

### 5.3 Buttons

| Variant | Fill | Text | Border | Use |
|---|---|---|---|---|
| Primary | `--brand-700` | white | none | One per view: Create job, Upload, Generate |
| Secondary | `--surface` | `--ink-700` | `--line-strong` | Cancel, secondary actions |
| Quiet | transparent | `--ink-500` | none | Table row actions, tertiary |
| Destructive | `--surface` | `#B24630` | `#B24630` | Delete. Always behind a confirmation |

Height 40px standard, 32px compact in table rows. Labels are verbs in sentence case: "Create job", never "Submit". The verb stays the same through the flow — a button that says "Generate questions" produces a toast that says "Questions generated".

### 5.4 Chips

Skill chips, 24px tall, `--r-sm`, `label` type, per §2.3. Matched chips lead with a filled dot, semantic with a hollow dot, missing with an en dash. Sorted alphabetically inside each group. Over twelve chips, show ten and a "+n more" quiet chip.

### 5.5 Tables

Header row `--surface-sunken`, `eyebrow` type, sticky on scroll. Rows separated by 1px `--line`. No zebra striping — the band colours already carry meaning and stripes fight them. Numeric columns right-aligned in mono. Sort indicator is a small caret in `--ink-500` on the active column only.

### 5.6 Forms

Labels above inputs in `label` type, `--ink-700`. Inputs 40px tall, 1px `--line-strong`, `--r-md`, 12px horizontal padding. Focus: 2px `--focus` ring at 2px offset, never a colour change alone. Helper text in `caption` `--ink-500` under the field. Errors replace helper text in `#B24630` and add a `#B24630` border. Required fields marked with an asterisk in `--ink-300`, with the convention stated once at the top of the form.

### 5.7 Status pills

| Status | Fill | Text |
|---|---|---|
| New | `#EDF1F3` | `--ink-500` |
| Shortlisted | `#DEE9F4` | `#1E4970` |
| Interviewed | `#F7EDD5` | `#7A5709` |
| Selected | `#DCEDE9` | `#0B4A45` |
| Rejected | `#F7E2DD` | `#7A2E1E` |

### 5.8 Empty, loading, and error states

**Empty** — a one-line Bricolage headline naming what is missing, one line of `body` `--ink-500` saying what to do, and the primary action. "No candidates yet. Upload resumes to this job to see a ranked shortlist." An empty screen is an invitation to act, not an apology.

**Loading** — skeletons matching the final layout in `--surface-sunken`, never spinners on full pages. Batch upload shows real per-file progress with filenames, because a 50-file parse takes long enough that a generic bar reads as a hang.

**Error** — states what happened and what to do, in the interface's voice. "This resume could not be read. It may be a scanned image. Try uploading a text-based PDF." No apologies, no vagueness, no error codes shown to the user unless there is a support path for them.

**Parse failure** — failed files stay visible in the upload result list with their reason. They are never silently dropped, because a recruiter who uploaded fifty resumes and sees forty-eight candidates needs to know which two are missing and why.

---

## 6. Motion

| Interaction | Duration | Easing |
|---|---|---|
| Hover, focus | 120ms | `ease-out` |
| Dropdown, tooltip | 150ms | `ease-out` |
| Modal, side panel | 200ms | `cubic-bezier(0.16, 1, 0.3, 1)` |
| Meter segments filling on load | 500ms, 60ms stagger | `cubic-bezier(0.16, 1, 0.3, 1)` |
| Chart series draw | 400ms | `ease-out` |

The meter fill is the only orchestrated moment in the product. Segments animate left to right in weight order, so the composition assembles itself in front of the recruiter. Everything else is functional feedback.

No parallax, no scroll-triggered reveals, no ambient animation, no page transitions. Under `prefers-reduced-motion: reduce`, all of the above collapse to instant state changes.

---

## 7. Accessibility

- Body text meets WCAG AA 4.5:1 against its background; large text and UI borders meet 3:1. Every pairing in §2.2 was chosen against its tint to clear these.
- Colour is never the sole carrier of meaning. Bands carry labels, skill states carry markers.
- Visible focus on every interactive element: 2px `--focus` at 2px offset. Focus outlines are never removed.
- Full keyboard operation, logical tab order, skip-to-content link.
- Charts have a table equivalent reachable from the same card.
- Score meters carry `aria-label` text spelling out the composition in words.
- Touch targets at least 44×44px on mobile.
- Live regions announce upload progress and scoring completion.

---

## 8. Voice

Words are design material, not decoration.

- Name things as the recruiter names them. "Candidates", "shortlist", "fit score" — never "records", "entities", "inference output".
- Say what the number means. "84.8 / 100 · Good match" rather than a naked figure.
- Attrition copy is probabilistic and never accusatory. "78% attrition probability · High risk" — never "will leave", never "flight risk", never "disloyal".
- Never imply the system decided. Column headers say "Fit score", not "Recommendation". No screen says "rejected by the system".
- The candidate detail page carries a single quiet line under the score: "Scores are assistive. Review the resume before deciding." It appears once, in `caption` `--ink-500`, and is not dismissible.
- Errors explain and instruct. They do not apologise and they are never vague about what happened.
- A label labels, an example demonstrates, and nothing quietly does double duty.

---

## 9. Tokens

```css
:root {
  /* neutral */
  --ink-900:#101519; --ink-700:#2B343D; --ink-500:#5A6672; --ink-300:#8C97A3;
  --line:#E2E7EB;    --line-strong:#C9D1D8;
  --canvas:#F4F7F8;  --surface:#FFFFFF; --surface-sunken:#EDF1F3;

  /* brand */
  --brand-700:#0B4A45; --brand-500:#0E7C6B; --brand-100:#DCEDE9; --focus:#1E9E8A;

  /* evaluative */
  --strong:#0E7C6B;   --strong-tint:#DCEDE9;   --strong-text:#0B4A45;
  --good:#2F6BA8;     --good-tint:#DEE9F4;     --good-text:#1E4970;
  --moderate:#C08A18; --moderate-tint:#F7EDD5; --moderate-text:#7A5709;
  --weak:#B24630;     --weak-tint:#F7E2DD;     --weak-text:#7A2E1E;

  /* chart */
  --c1:#0E7C6B; --c2:#2F6BA8; --c3:#C08A18; --c4:#B24630; --c5:#5F6CA8; --c6:#4E7A4A;

  /* type */
  --font-display:'Bricolage Grotesque', ui-sans-serif, system-ui, sans-serif;
  --font-body:'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif;
  --font-mono:'IBM Plex Mono', ui-monospace, 'SF Mono', monospace;

  /* space */
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px;
  --s6:32px; --s7:48px; --s8:64px; --s9:96px;

  /* radius, shadow */
  --r-sm:4px; --r-md:8px; --r-lg:12px;
  --shadow-sm:0 1px 2px rgba(16,21,25,0.05);
  --shadow-md:0 8px 24px rgba(16,21,25,0.10);
}
```

---

## 10. Backend-rendered output

The PDF shortlist export follows this system, since it is generated server-side and is the one surface the backend renders directly.

- A4 portrait, 18mm margins.
- Header: job title in Bricolage 700 at 20pt, generation date and candidate count in Plex Mono 9pt `--ink-500`.
- One block per candidate: rank and name, fit score in Plex Mono 24pt coloured by band, the composition meter, matched and missing skills as text lists.
- Footer on every page: "Assistive scoring. Review resumes before deciding." in 8pt `--ink-500`.
- Greyscale-safe: the composition meter uses distinct segment fills that survive black-and-white printing, and every band prints its label.
