/**
 * Dark mode theme management.
 *
 * Persistencja: localStorage 'ec_theme' = 'light' | 'dark' | 'system'.
 * Aplikacja: data-theme="dark" na <html>. globals.css ma overrides per
 * data-theme="dark".
 *
 * SSR safe: applyThemeFromStorage moze byc wolane przed React hydration,
 * eliminuje "flash of light theme".
 */

export type Theme = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'ec_theme';

export function getStoredTheme(): Theme {
  if (typeof window === 'undefined') return 'system';
  const v = localStorage.getItem(STORAGE_KEY);
  if (v === 'light' || v === 'dark' || v === 'system') return v;
  return 'system';
}

export function setStoredTheme(theme: Theme): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(STORAGE_KEY, theme);
  applyThemeToDocument(theme);
}

/** Resolves 'system' to actual 'light'/'dark' based on prefers-color-scheme. */
export function resolveTheme(theme: Theme): 'light' | 'dark' {
  if (theme === 'light' || theme === 'dark') return theme;
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyThemeToDocument(theme: Theme): void {
  if (typeof document === 'undefined') return;
  const resolved = resolveTheme(theme);
  document.documentElement.setAttribute('data-theme', resolved);
}

/** Inicjalizacja przy starcie aplikacji - czyta storage + nasluchuje na zmiane
 *  prefers-color-scheme (gdy theme='system' i user przelaczy w OS). */
export function initTheme(): () => void {
  if (typeof window === 'undefined') return () => {};
  applyThemeToDocument(getStoredTheme());

  // Listen na OS-level dark mode change (tylko gdy theme='system')
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const handler = () => {
    if (getStoredTheme() === 'system') {
      applyThemeToDocument('system');
    }
  };
  mq.addEventListener('change', handler);
  return () => mq.removeEventListener('change', handler);
}
