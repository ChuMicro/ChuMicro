# Page Templates

These templates provide the dashboard (protected) page and home page for the Next.js frontend scaffolded with ByteForge Aegis authentication.

## CRITICAL - Substitution Notes

- Replace `{ProjectName}` with the project's display name (e.g., "DevNotes", "TaskFlow")
- Replace `{ProjectBrandHtml}` with the project's branded HTML display. The convention is a split-color brand using CSS variables:
  ```tsx
  <span className="text-[var(--foreground)]">Dev</span>
  <span className="text-[var(--amber-glow)]">Notes</span>
  ```
  Replace both the header and footer brand elements in each page with the project's specific brand.
- The home page is **project-specific** and should be customized for each project's needs. The template provides the structure and auth-aware patterns but the hero content, feature cards, and descriptions should reflect the actual project.

---

## app/[locale]/dashboard/page.tsx

Protected dashboard page. Redirects to `/login` if the user is not authenticated. Includes a header with brand logo, site name display, language switcher, and logout button. The main content area shows a placeholder "Coming Soon" card. The footer displays the brand.

CRITICAL: This page uses `'use client'` because it depends on the `useAuth` hook which reads from localStorage.

CRITICAL: The redirect to `/login` happens in a `useEffect` after the auth state is resolved. While loading, a spinner is shown. If not authenticated after loading, `null` is returned to prevent flash of content.

```typescript
'use client';

import { useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter, Link } from '@/i18n/navigation';
import { useAuth, logout } from '@/lib/useAuth';
import LanguageSwitcher from '@/components/LanguageSwitcher';

export default function DashboardPage() {
  const router = useRouter();
  const t = useTranslations('Dashboard');
  const tCommon = useTranslations('Common');
  const { isAuthenticated, isLoading, siteName } = useAuth();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">{tCommon('loading')}</p>
        </div>
      </main>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <main className="min-h-screen mesh-gradient paper-texture">
      <div className="relative z-10 min-h-screen flex flex-col">
        {/* Header */}
        <header className="px-6 py-4 border-b border-[var(--border)]">
          <div className="max-w-6xl mx-auto flex items-center justify-between">
            <Link href="/dashboard" className="font-display text-xl font-bold">
              {ProjectBrandHtml}
            </Link>

            <div className="flex items-center gap-4">
              {siteName && (
                <span className="text-sm text-[var(--foreground-muted)]">
                  {siteName}
                </span>
              )}
              <LanguageSwitcher />
              <button
                onClick={logout}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-[var(--foreground-muted)] hover:text-[var(--foreground)] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
                {tCommon('logout')}
              </button>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <div className="flex-1 px-6 py-12">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-12 animate-fade-in-up">
              <h1 className="font-display text-3xl md:text-4xl font-bold mb-4">
                {t('title')}
              </h1>
              <p className="text-[var(--foreground-muted)] text-lg">
                {t('subtitle')}
              </p>
            </div>

            {/* Placeholder content - replace with actual dashboard content */}
            <div className="card p-12 text-center animate-fade-in-up delay-200">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--amber-glow)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
              </div>
              <h2 className="font-display text-xl font-bold mb-2">{t('emptyStateTitle')}</h2>
              <p className="text-[var(--foreground-muted)]">{t('emptyStateMessage')}</p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="px-6 py-8 border-t border-[var(--border)]">
          <div className="max-w-6xl mx-auto text-center text-sm text-[var(--foreground-muted)]">
            <p className="font-display">
              {ProjectBrandHtml}
            </p>
          </div>
        </footer>
      </div>
    </main>
  );
}
```

### Brand Substitution Example

Replace `{ProjectBrandHtml}` in both the header and footer with the project's branded HTML. For example, for a project called "DevNotes":

```tsx
<span className="text-[var(--foreground)]">Dev</span>
<span className="text-[var(--amber-glow)]">Notes</span>
```

For a project called "TaskFlow":

```tsx
<span className="text-[var(--foreground)]">Task</span>
<span className="text-[var(--amber-glow)]">Flow</span>
```

For a single-word brand like "Aegis":

```tsx
<span className="text-[var(--amber-glow)]">Aegis</span>
```

---

## app/[locale]/page.tsx

> **CUSTOMIZE FOR YOUR PROJECT**: This home page template provides the structural skeleton and auth-aware patterns (header with language switcher, hero section, feature cards grid, AuthCTA button, footer). The actual content -- hero text, feature card titles/descriptions, icons, and any project-specific decorative elements -- should be customized to reflect the specific project's purpose and branding.

Home page with header (brand + language switcher), hero section, feature cards grid, auth CTA button, and footer. This is a server component by default since it only uses `useTranslations` (which works on both server and client). The `AuthCTA` and `LanguageSwitcher` are client components imported as children.

CRITICAL: The `FeatureCard` helper component is defined in the same file for simplicity. If your project grows to need feature cards elsewhere, extract it into `components/FeatureCard.tsx`.

CRITICAL: The feature card content (titles, descriptions, icons) comes from translation keys. Add corresponding keys to `messages/en.json` under the `"Home"` section. The template uses generic feature names that must be replaced with project-specific features.

```typescript
import { useTranslations } from 'next-intl';
import AuthCTA from '@/components/AuthCTA';
import LanguageSwitcher from '@/components/LanguageSwitcher';

// ---------------------------------------------------------------------------
// CUSTOMIZE: Replace this with a project-specific icon/logo component, or
// remove it entirely if the project does not need a decorative hero icon.
// ---------------------------------------------------------------------------
function HeroIcon() {
  return (
    <div className="w-16 h-16 mx-auto rounded-2xl bg-[var(--amber-glow)]/10 flex items-center justify-center">
      <svg className="w-8 h-8 text-[var(--amber-glow)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    </div>
  );
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="card p-6 text-left">
      <div className="w-10 h-10 rounded-lg bg-[var(--amber-glow)]/10 flex items-center justify-center text-[var(--amber-glow)] mb-4">
        {icon}
      </div>
      <h3 className="font-display text-lg font-bold mb-2">{title}</h3>
      <p className="text-[var(--foreground-muted)] text-sm leading-relaxed">{description}</p>
    </div>
  );
}

export default function HomePage() {
  const t = useTranslations('Home');

  return (
    <main className="min-h-screen mesh-gradient paper-texture">
      <div className="relative z-10 min-h-screen flex flex-col">
        {/* Header */}
        <header className="px-6 py-4">
          <div className="max-w-5xl mx-auto flex items-center justify-between">
            <div className="font-display text-xl font-bold">
              {ProjectBrandHtml}
            </div>
            <LanguageSwitcher />
          </div>
        </header>

        {/* Hero Section */}
        <section className="flex-1 flex flex-col items-center justify-center px-6 py-16 md:py-24">
          <div className="max-w-4xl mx-auto text-center">
            {/* Logo/Icon - CUSTOMIZE: replace HeroIcon with project-specific icon */}
            <div className="animate-fade-in-up mb-8">
              <HeroIcon />
            </div>

            {/* Title */}
            <h1 className="font-display text-4xl md:text-6xl lg:text-7xl font-bold tracking-tight mb-6 animate-fade-in-up delay-100">
              {ProjectBrandHtml}
            </h1>

            {/* Decorative line */}
            <div className="flex justify-center mb-6 animate-fade-in-up delay-200">
              <div className="decorative-line" />
            </div>

            {/* Subtitle */}
            <p className="font-display text-xl md:text-2xl text-[var(--foreground)] mb-4 animate-fade-in-up delay-200">
              {t('subtitle')}
            </p>

            {/* Description */}
            <p className="text-[var(--foreground-muted)] text-lg md:text-xl max-w-2xl mx-auto mb-10 animate-fade-in-up delay-300">
              {t('description')}
            </p>

            {/* CTA Button */}
            <div className="animate-fade-in-up delay-400">
              <AuthCTA />
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------------------------------
            CUSTOMIZE: Replace these feature cards with project-specific features.
            Add corresponding translation keys to messages/en.json under "Home":
              "feature1Title": "Your Feature",
              "feature1Description": "Description of the feature.",
              "feature2Title": "Another Feature",
              "feature2Description": "Description of another feature.",
              "feature3Title": "Third Feature",
              "feature3Description": "Description of the third feature."
            --------------------------------------------------------------------------- */}
        <section className="px-6 pb-16 md:pb-24">
          <div className="max-w-5xl mx-auto">
            <div className="grid md:grid-cols-3 gap-6">
              <div className="animate-fade-in-up delay-500">
                <FeatureCard
                  icon={
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                  }
                  title={t('feature1Title')}
                  description={t('feature1Description')}
                />
              </div>
              <div className="animate-fade-in-up delay-600">
                <FeatureCard
                  icon={
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  }
                  title={t('feature2Title')}
                  description={t('feature2Description')}
                />
              </div>
              <div className="animate-fade-in-up delay-600" style={{ animationDelay: '700ms' }}>
                <FeatureCard
                  icon={
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                  }
                  title={t('feature3Title')}
                  description={t('feature3Description')}
                />
              </div>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="px-6 py-8 border-t border-[var(--border)]">
          <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-[var(--foreground-muted)]">
            <p className="font-display">
              {ProjectBrandHtml}
            </p>
            <p>{t('footerTagline')}</p>
          </div>
        </footer>
      </div>
    </main>
  );
}
```

### Required Translation Keys for Home Page

Add these keys to `messages/en.json` under the `"Home"` section. Replace the placeholder values with project-specific content:

```json
{
  "Home": {
    "title": "{ProjectName}",
    "subtitle": "{project_description}",
    "description": "A longer description of what the project does and why users should care.",
    "feature1Title": "Feature One",
    "feature1Description": "Description of the first key feature of your project.",
    "feature2Title": "Feature Two",
    "feature2Description": "Description of the second key feature of your project.",
    "feature3Title": "Feature Three",
    "feature3Description": "Description of the third key feature of your project.",
    "footerTagline": "Built with care."
  }
}
```

### Customization Notes

The home page template provides the **structural skeleton** that every Aegis-powered frontend shares:

1. **Header** with brand display and language switcher
2. **Hero section** with brand, subtitle, description, and auth-aware CTA button
3. **Feature cards grid** (3-column on desktop, stacked on mobile)
4. **Footer** with brand and tagline

What should be customized per project:

- **`HeroIcon` component**: Replace with a project-specific SVG icon or logo, or remove entirely
- **Feature card icons**: Choose SVG icons that represent your project's actual features
- **Feature card content**: Update translation keys with real feature names and descriptions
- **Number of feature cards**: Add or remove cards as needed (adjust the grid classes accordingly)
- **Any project-specific sections**: Add testimonials, pricing, screenshots, etc. between the hero and features sections
- **Brand display**: Replace `{ProjectBrandHtml}` with the split-color brand pattern in header, hero title, and footer
