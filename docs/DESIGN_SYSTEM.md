# Design system

The frontend (`web/`) implements these tokens in `web/src/app/globals.css` (Tailwind v4 `@theme`). Tailwind's default
color palette is switched off, so only these tokens exist. `web/src/test/design-tokens.test.ts` fails the build if a
component uses a hex/rgb/hsl color or an arbitrary color class.

## Direction

- White or very light neutral background, generous whitespace, clear hierarchy.
- Deep navy is the brand color. Emerald is used **only** for positive values (rewards, net value).
- Subtle borders and shadows; no gradients; motion only for state changes, and none under `prefers-reduced-motion`.
- Bank names in plain text, never logos. No dashboard clutter, no decorative illustrations, no "AI" styling.

## Color tokens

Contrast ratios are WCAG 2.1 relative-luminance ratios, computed from the hex values (AA needs ≥ 4.5:1 for
text and ≥ 3:1 for UI component boundaries and focus indicators).

| Token | Hex | Use | Contrast |
|---|---|---|---|
| `navy-900` | `#0B1F3A` | Brand: header, primary buttons, headings accent | 16.52:1 on white; white text on it 16.52:1 |
| `navy-700` | `#1D3A66` | Hover/active primary, links | 11.36:1 on white |
| `navy-50` | `#EEF2F8` | Selected tab/background tint | navy-900 text 14.70:1 |
| `ink-900` | `#0F172A` | Headings | 17.85:1 on white |
| `ink-700` | `#334155` | Body text | 10.35:1 on white |
| `ink-500` | `#64748B` | Secondary text, input borders | 4.76:1 on white; 4.55:1 on `surface-subtle` |
| `surface` | `#FFFFFF` | Page and card background | — |
| `surface-subtle` | `#F8FAFC` | Section bands, table headers | — |
| `border` | `#E2E8F0` | Decorative card/table dividers (not the only cue) | decorative |
| `border-strong` | `#64748B` | Form control borders | 4.76:1 (≥ 3:1) |
| `focus` | `#2563EB` | 2px focus ring + 2px offset on every interactive element | 5.17:1 on white |
| `positive` | `#047857` | Positive values only | 5.48:1 on white; 5.21:1 on `positive-bg` |
| `positive-bg` | `#ECFDF5` | Positive chip background | — |
| `warning` / `warning-bg` | `#92400E` / `#FFFBEB` | "Offer not recently verified", stale | 6.84:1 |
| `expired` / `expired-bg` | `#B91C1C` / `#FEF2F2` | "Expired offer" | 5.91:1 |
| `unverified` / `unverified-bg` | `#475569` / `#F1F5F9` | "Not verified", "Information missing" | 6.92:1 |
| `recheck` / `recheck-bg` | `#9A3412` / `#FFF7ED` | "Recheck pending" | 6.88:1 |
| `info` / `info-bg` | `#1E40AF` / `#EFF6FF` | "Up to" toggletips, notes | 8.01:1 |

Color is never the only signal: every status chip has a text label and an icon-free word.

## Typography

- Family: **Inter** (self-hosted via `@fontsource-variable/inter`, no external font requests), falling back to
  `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif`.
- **Tabular numerals** (`font-variant-numeric: tabular-nums`, utility `tabular-nums`) for every money, rate, and date
  value (component `Money`, `Rate`).
- Scale (rem/line-height): `xs` 0.75/1rem · `sm` 0.875/1.25rem · `base` 1/1.5rem · `lg` 1.125/1.75rem ·
  `xl` 1.25/1.75rem · `2xl` 1.5/2rem · `3xl` 1.875/2.25rem · `4xl` 2.25/2.5rem (home hero only).
- Weights: 400 body, 500 labels, 600 headings. Headings follow document order (`h1` once per page).

## Scales

- Spacing: Tailwind's 4px base (`1` = 4px). Page gutter 16px (mobile) / 24px (≥768px); max content width 1200px.
- Radius: `sm` 4px (chips), `md` 8px (inputs, buttons), `lg` 12px (cards).
- Shadow: `card` = `0 1px 2px rgb(15 23 42 / 0.06), 0 1px 3px rgb(15 23 42 / 0.04)`; `raised` (popovers) =
  `0 4px 12px rgb(15 23 42 / 0.10)`. Defined once in the theme.
- Breakpoints verified: 375px, 768px, 1280px.

## Components

| Component | Spec |
|---|---|
| **Product card** (`ProductCard`) | White card, `border`, radius `lg`, shadow `card`, padding 20px. Order: bank name (`ink-500`, sm), product name (`h3`, lg/600), verification badge, key facts list (fee, rate/APY, rewards, using `Money`/`Rate`), offer chip, "Checked X hours ago · Changed on <date>", actions: "Details" link and "Compare" checkbox. |
| **Verification badge** (`VerificationBadge`) | Pill, radius `sm`, xs/500. *Verified* = navy-50 bg + navy-900 text. *Partially verified* = `unverified` colors, with a "What's missing" disclosure listing the reasons. |
| **Offer chip** (`OfferChip` + `OfferAmount`) | *Exact*: `positive-bg`/`positive` "60,000 points". *Up to*: `info-bg`/`info` "**Up to** 80,000 points" + info toggletip button (`aria-expanded`, Esc closes): "The bank says this offer can vary. The amount you're offered is shown during your application and may be lower than this maximum." Never a dollar conversion next to an up-to amount. *At least* the same, with "At least". |
| **Status labels** (`StatusLabel`) | `expired` "Expired offer", `stale` "Offer not recently verified", `recheck` "Recheck pending", `missing` "Information missing", `unverified` "Not verified". Colors from the table. |
| **Filter bar** (`FilterBar`) | Labeled controls in a wrapping row (stacked at 375px). Bank select, max annual fee, reward category, "Has bonus", min APY, "Verified since", segment, card flags (checkboxes). GET form, so it works without JavaScript; "Clear filters" link. |
| **Comparison table** (`CompareTable`) | Semantic `<table>` with `<caption>`, row headers `th scope=row`; first column sticky on small screens with horizontal scroll inside the table only. Missing value shows "Information missing". |
| **Score breakdown** (`ScoreBreakdown`) | Total score `xl` tabular; list of components as labeled bars (`<meter>`-like div with `role="img"` + text "12.3 of 30 points"). |
| **Value split** (`ValueSplit`) | Four rows: Ongoing annual, Promotional, First-year, Non-monetized (names). Positive values in `positive`, negative in `ink-900` with a minus sign. **Multi-year view**: Year 1 / Year 2 / Year 3 / 3-year total. Break-even sentence below. |
| **Credit checkboxes** (`CreditCheckboxes`) | Fieldset with legend "Statement credits you would actually use"; all unchecked by default; each shows amount and period. |
| **Buttons** | Primary: navy-900 bg, white text, hover navy-700. Secondary: white bg, `border-strong`, ink-900 text. Min height 44px. Focus: 2px `focus` ring, 2px offset. |
| **Form inputs** (`Field`) | Visible `<label>`, helper text `ink-500`, error text `expired` color with `aria-describedby` and `aria-invalid`; border `border-strong`. |
| **Loading skeleton** | `surface-subtle` blocks, no shimmer under reduced motion; `aria-busy="true"` on the region. |
| **Empty state** | Short headline + one sentence + next step link (e.g. "No verified products yet for this bank. See Data Sources for status."). |
| **Error state** | Headline "Something went wrong", plain-language cause, "Try again" button; never stack traces. |
| **Disclaimer** | Footer and results page: not financial advice; confirm on the bank's site; data checked on a schedule and not real-time; no affiliate relationships. |
| **Source link** | "Official page ↗" opens in a new tab with `rel="noopener noreferrer"` and visually hidden "(opens in a new tab)". |
