# Component and Layout Templates

These templates provide reusable UI components and layout files for the Next.js frontend scaffolded with ByteForge Aegis authentication.

## CRITICAL - Substitution Notes

- Replace `{ProjectName}` with the project's display name (e.g., "DevNotes", "TaskFlow")
- Replace `{project_description}` with the project's one-line description
- The `AuthCTA` and `LanguageSwitcher` components are identical across all projects; no substitution is needed
- The layout files require `{ProjectName}` and `{project_description}` substitution in metadata

---

## components/AuthCTA.tsx

Smart auth CTA button that shows a spinner while loading auth state, a "Go to Dashboard" link if authenticated, or a "Sign In" link if not authenticated. Uses the `useAuth` hook to read auth state from localStorage.

```typescript
'use client';

import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/navigation';
import { useAuth } from '@/lib/useAuth';

export default function AuthCTA() {
  const tLogin = useTranslations('Login');
  const tDashboard = useTranslations('Dashboard');
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="inline-flex items-center justify-center w-auto px-10 py-4 text-lg">
        <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
      </div>
    );
  }

  if (isAuthenticated) {
    return (
      <Link href="/dashboard" className="btn-primary inline-flex w-auto px-10 py-4 text-lg">
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
        </svg>
        {tDashboard('goToDashboard')}
      </Link>
    );
  }

  return (
    <Link href="/login" className="btn-primary inline-flex w-auto px-10 py-4 text-lg">
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
      </svg>
      {tLogin('signInButton')}
    </Link>
  );
}
```

---

## components/LanguageSwitcher.tsx

Dropdown language selector with globe icon. Closes on click outside and on Escape key press. Reads available locales from the routing config so it automatically scales to any number of languages. Start with just English in the `LANGUAGE_NAMES` map and add more entries as new locales are added to `i18n/routing.ts`.

```typescript
'use client';

import { useState, useRef, useEffect } from 'react';
import { useLocale } from 'next-intl';
import { usePathname, useRouter } from '@/i18n/navigation';
import { routing, Locale } from '@/i18n/routing';

const LANGUAGE_NAMES: Record<string, string> = {
  en: 'English',
  // Add more languages here as needed:
  // es: 'Espanol',
  // fr: 'Francais',
  // de: 'Deutsch',
  // pt: 'Portugues',
  // it: 'Italiano',
  // ja: '日本語',
  // zh: '中文',
  // ko: '한국어',
  // ar: 'العربية',
  // ru: 'Русский',
};

function GlobeIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
    </svg>
  );
}

function ChevronIcon({ isOpen }: { isOpen: boolean }) {
  return (
    <svg
      className={`w-3 h-3 transition-transform ${isOpen ? 'rotate-180' : ''}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  );
}

export default function LanguageSwitcher() {
  const locale = useLocale() as Locale;
  const pathname = usePathname();
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  function handleChange(newLocale: Locale) {
    router.replace(pathname, { locale: newLocale });
    setIsOpen(false);
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Close on escape key
  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    }

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, []);

  const currentLanguageName = LANGUAGE_NAMES[locale] || locale.toUpperCase();

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium text-[var(--foreground-muted)] hover:text-[var(--foreground)] transition-colors rounded-lg hover:bg-[var(--amber-glow)]/5"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
      >
        <GlobeIcon />
        <span>{currentLanguageName}</span>
        <ChevronIcon isOpen={isOpen} />
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-2 w-40 py-1 bg-[var(--card-bg)] border border-[var(--border)] rounded-lg shadow-lg z-50"
          role="listbox"
          aria-label="Select language"
        >
          {routing.locales.map((loc) => {
            const isSelected = locale === loc;
            const languageName = LANGUAGE_NAMES[loc] || loc.toUpperCase();

            return (
              <button
                key={loc}
                onClick={() => handleChange(loc)}
                className={`w-full px-4 py-2 text-left text-sm transition-colors ${
                  isSelected
                    ? 'bg-[var(--amber-glow)]/10 text-[var(--amber-glow)] font-medium'
                    : 'text-[var(--foreground-muted)] hover:bg-[var(--amber-glow)]/5 hover:text-[var(--foreground)]'
                }`}
                role="option"
                aria-selected={isSelected}
              >
                {languageName}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

---

## app/layout.tsx

Root layout. This is the top-level layout that wraps all pages. It returns `children` directly because the `<html>` and `<body>` tags are rendered in the locale layout below. This pattern is required by `next-intl` to support locale-aware `<html lang>` attributes.

```typescript
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '{ProjectName}',
  description: '{project_description}',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return children;
}
```

---

## app/[locale]/layout.tsx

Locale layout with `NextIntlClientProvider`. This layout wraps all pages within a specific locale. It validates the locale parameter, loads the correct messages, and provides them to all client components via the `NextIntlClientProvider`.

```typescript
import { NextIntlClientProvider } from 'next-intl';
import { getMessages } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { routing } from '@/i18n/routing';
import '../globals.css';

type Props = {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
};

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;

  if (!routing.locales.includes(locale as typeof routing.locales[number])) {
    notFound();
  }

  const messages = await getMessages();

  return (
    <html lang={locale}>
      <body>
        <NextIntlClientProvider messages={messages}>
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
```
