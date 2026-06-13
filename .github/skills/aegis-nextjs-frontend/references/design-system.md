# Design System Reference

This file contains the complete `globals.css` template for the Aegis design system. It implements a warm, paper-and-ink aesthetic with amber accents, paper textures, and mesh gradient backgrounds.

## globals.css

```css
@import "tailwindcss";

/* ============================================================
   Google Fonts
   ============================================================ */
@import url('https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&display=swap');

/* ============================================================
   CSS Custom Properties - Light Mode (Default)
   ============================================================ */
:root {
  /* Ink palette - warm dark tones */
  --ink-deepest: #1a1612;
  --ink-deep: #2d2822;
  --ink-medium: #4a4238;
  --ink-light: #6b5f52;
  --ink-muted: #8a7e70;

  /* Paper palette - warm light tones */
  --paper-cream: #f4efe6;
  --paper-warm: #ede7db;
  --paper-cool: #f8f5ef;

  /* Amber accent palette */
  --amber-glow: #c8956c;
  --amber-bright: #d4a574;
  --amber-deep: #b8845c;

  /* Status colors */
  --success-green: #4a7c59;
  --error-red: #c75050;

  /* Semantic mappings */
  --foreground: var(--ink-deepest);
  --foreground-secondary: var(--ink-medium);
  --foreground-muted: var(--ink-muted);
  --background: var(--paper-cream);
  --background-secondary: var(--paper-warm);

  /* Component tokens */
  --card-bg: #ffffff;
  --card-border: #e8e0d4;
  --input-background: #faf8f4;
  --input-border: #d4cdc2;
  --input-focus-ring: rgba(200, 149, 108, 0.3);
  --border: #e0d8cc;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(26, 22, 18, 0.04);
  --shadow-md: 0 4px 12px rgba(26, 22, 18, 0.06);
  --shadow-lg: 0 8px 24px rgba(26, 22, 18, 0.08);
  --shadow-hover: 0 8px 24px rgba(26, 22, 18, 0.1);
}

/* ============================================================
   Dark Mode Overrides
   ============================================================ */
@media (prefers-color-scheme: dark) {
  :root {
    /* Ink palette inverted for dark mode */
    --ink-deepest: #f0ebe4;
    --ink-deep: #d8d0c6;
    --ink-medium: #b0a696;
    --ink-light: #8a7e70;
    --ink-muted: #6b5f52;

    /* Paper palette - dark warm tones */
    --paper-cream: #1a1612;
    --paper-warm: #221e19;
    --paper-cool: #2a2520;

    /* Amber accent palette - slightly brighter for dark backgrounds */
    --amber-glow: #d4a574;
    --amber-bright: #e0b688;
    --amber-deep: #c8956c;

    /* Status colors - adjusted for dark backgrounds */
    --success-green: #5a9c6e;
    --error-red: #e06060;

    /* Semantic mappings */
    --foreground: var(--ink-deepest);
    --foreground-secondary: var(--ink-medium);
    --foreground-muted: var(--ink-muted);
    --background: var(--paper-cream);
    --background-secondary: var(--paper-warm);

    /* Component tokens */
    --card-bg: #221e19;
    --card-border: #3a342c;
    --input-background: #2a2520;
    --input-border: #4a4238;
    --input-focus-ring: rgba(212, 165, 116, 0.3);
    --border: #3a342c;

    /* Shadows - more prominent on dark backgrounds */
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.2);
    --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.3);
    --shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.4);
    --shadow-hover: 0 8px 24px rgba(0, 0, 0, 0.5);
  }
}

/* ============================================================
   Base Styles
   ============================================================ */
body {
  font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
  color: var(--foreground);
  background-color: var(--background);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.font-display {
  font-family: 'Libre Baskerville', 'Georgia', serif;
}

/* ============================================================
   Paper Texture Overlay
   Uses an inline SVG with fractal noise for a subtle
   paper-like grain effect across the entire page.
   ============================================================ */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 9999;
  pointer-events: none;
  opacity: 0.03;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='400' height='400'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  background-repeat: repeat;
}

/* ============================================================
   Mesh Gradient Background
   Layered radial gradients that create a soft, warm
   ambient glow behind the page content.
   ============================================================ */
body::after {
  content: '';
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background:
    radial-gradient(ellipse 80% 60% at 10% 20%, rgba(200, 149, 108, 0.06) 0%, transparent 60%),
    radial-gradient(ellipse 60% 80% at 90% 80%, rgba(200, 149, 108, 0.04) 0%, transparent 60%),
    radial-gradient(ellipse 50% 50% at 50% 50%, rgba(244, 239, 230, 0.5) 0%, transparent 80%);
}

@media (prefers-color-scheme: dark) {
  body::before {
    opacity: 0.02;
  }

  body::after {
    background:
      radial-gradient(ellipse 80% 60% at 10% 20%, rgba(200, 149, 108, 0.03) 0%, transparent 60%),
      radial-gradient(ellipse 60% 80% at 90% 80%, rgba(200, 149, 108, 0.02) 0%, transparent 60%),
      radial-gradient(ellipse 50% 50% at 50% 50%, rgba(26, 22, 18, 0.5) 0%, transparent 80%);
  }
}

/* ============================================================
   Animation Keyframes
   ============================================================ */
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes scaleIn {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

@keyframes spark {
  0%, 100% {
    opacity: 0;
    transform: scale(0.8);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes pulse-ring {
  0% {
    transform: scale(1);
    opacity: 0.4;
  }
  100% {
    transform: scale(1.5);
    opacity: 0;
  }
}

/* ============================================================
   Animation Utilities
   ============================================================ */
.animate-fade-in-up {
  animation: fadeInUp 0.6s ease-out both;
}

.animate-fade-in {
  animation: fadeIn 0.5s ease-out both;
}

.animate-scale-in {
  animation: scaleIn 0.5s ease-out both;
}

.animate-shimmer {
  animation: shimmer 2s linear infinite;
}

.animate-spark {
  animation: spark 2s ease-in-out infinite;
}

.animate-pulse-ring {
  animation: pulse-ring 1.5s ease-out infinite;
}

/* Delay utility classes for staggered animations */
.delay-100 {
  animation-delay: 100ms;
}

.delay-200 {
  animation-delay: 200ms;
}

.delay-300 {
  animation-delay: 300ms;
}

.delay-400 {
  animation-delay: 400ms;
}

.delay-500 {
  animation-delay: 500ms;
}

.delay-600 {
  animation-delay: 600ms;
}

/* ============================================================
   Component: Card
   White card with subtle border, shadow, rounded corners,
   and a gentle lift effect on hover.
   ============================================================ */
.card {
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 0.75rem;
  box-shadow: var(--shadow-md);
  transition: box-shadow 0.3s ease, transform 0.3s ease;
}

.card:hover {
  box-shadow: var(--shadow-hover);
  transform: translateY(-2px);
}

/* ============================================================
   Component: Input Field
   Full-width input with warm background, smooth focus
   transition, and amber glow on focus.
   ============================================================ */
.input-field {
  width: 100%;
  padding: 0.75rem 1rem;
  background: var(--input-background);
  border: 1px solid var(--input-border);
  border-radius: 0.5rem;
  color: var(--foreground);
  font-family: 'DM Sans', system-ui, sans-serif;
  font-size: 0.95rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  outline: none;
}

.input-field::placeholder {
  color: var(--foreground-muted);
}

.input-field:focus {
  border-color: var(--amber-glow);
  box-shadow: 0 0 0 3px var(--input-focus-ring);
}

/* ============================================================
   Component: Primary Button
   Gradient amber button with icon support, lift on hover,
   and a disabled state that reduces opacity.
   ============================================================ */
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: linear-gradient(135deg, var(--amber-glow), var(--amber-deep));
  color: #ffffff;
  font-family: 'DM Sans', system-ui, sans-serif;
  font-weight: 600;
  font-size: 0.95rem;
  border: none;
  border-radius: 0.5rem;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--shadow-sm);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary svg,
.btn-primary .icon {
  width: 1.125rem;
  height: 1.125rem;
  flex-shrink: 0;
}

/* ============================================================
   Component: Secondary Button
   Transparent button with border, amber text highlight
   on hover.
   ============================================================ */
.btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: transparent;
  color: var(--foreground);
  font-family: 'DM Sans', system-ui, sans-serif;
  font-weight: 500;
  font-size: 0.95rem;
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background-color 0.2s ease;
}

.btn-secondary:hover {
  border-color: var(--amber-glow);
  color: var(--amber-deep);
  background-color: rgba(200, 149, 108, 0.05);
}

.btn-secondary:active {
  background-color: rgba(200, 149, 108, 0.1);
}

.btn-secondary svg,
.btn-secondary .icon {
  width: 1.125rem;
  height: 1.125rem;
  flex-shrink: 0;
}

/* ============================================================
   Component: Spinner
   Rotating border circle for loading states.
   ============================================================ */
.spinner {
  width: 1.5rem;
  height: 1.5rem;
  border: 2px solid var(--border);
  border-top-color: var(--amber-glow);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ============================================================
   Component: Status Feedback Bars
   Colored horizontal bars for success and error states.
   ============================================================ */
.status-success {
  background-color: var(--success-green);
  color: #ffffff;
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.9rem;
  font-weight: 500;
}

.status-error {
  background-color: var(--error-red);
  color: #ffffff;
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.9rem;
  font-weight: 500;
}

/* ============================================================
   Component: Decorative Line
   Centered amber gradient horizontal rule for visual
   separation between content sections.
   ============================================================ */
.decorative-line {
  width: 6rem;
  height: 2px;
  margin: 1.5rem auto;
  background: linear-gradient(
    90deg,
    transparent,
    var(--amber-glow),
    transparent
  );
  border: none;
  border-radius: 1px;
}
```

## Design Tokens Quick Reference

| Token | Light | Dark | Usage |
|-------|-------|------|-------|
| `--ink-deepest` | `#1a1612` | `#f0ebe4` | Primary text |
| `--ink-deep` | `#2d2822` | `#d8d0c6` | Headings |
| `--ink-medium` | `#4a4238` | `#b0a696` | Secondary text |
| `--ink-light` | `#6b5f52` | `#8a7e70` | Tertiary text |
| `--ink-muted` | `#8a7e70` | `#6b5f52` | Placeholders, hints |
| `--paper-cream` | `#f4efe6` | `#1a1612` | Page background |
| `--paper-warm` | `#ede7db` | `#221e19` | Section backgrounds |
| `--paper-cool` | `#f8f5ef` | `#2a2520` | Subtle alternation |
| `--amber-glow` | `#c8956c` | `#d4a574` | Primary accent |
| `--amber-bright` | `#d4a574` | `#e0b688` | Hover accent |
| `--amber-deep` | `#b8845c` | `#c8956c` | Active/pressed accent |
| `--success-green` | `#4a7c59` | `#5a9c6e` | Success states |
| `--error-red` | `#c75050` | `#e06060` | Error states |
| `--border` | `#e0d8cc` | `#3a342c` | Borders, dividers |
| `--card-bg` | `#ffffff` | `#221e19` | Card backgrounds |

## Typography

- **Body**: DM Sans - clean, modern sans-serif for readability
- **Display**: Libre Baskerville - elegant serif for headings and hero text
- Apply `.font-display` class to any element that should use Libre Baskerville

## Animation Usage

Use the animation classes with delay utilities for staggered entrance effects:

```html
<div class="animate-fade-in-up">First item</div>
<div class="animate-fade-in-up delay-100">Second item</div>
<div class="animate-fade-in-up delay-200">Third item</div>
```

Available animations:
- `animate-fade-in-up` - Slides up 16px while fading in (0.6s)
- `animate-fade-in` - Simple opacity fade (0.5s)
- `animate-scale-in` - Scales from 95% while fading in (0.5s)
- `animate-shimmer` - Horizontal shimmer for skeleton loaders
- `animate-spark` - Pulsing scale for decorative elements
- `animate-pulse-ring` - Expanding ring for active indicators
