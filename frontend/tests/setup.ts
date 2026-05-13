/**
 * Vitest setup - globalny dla wszystkich test files.
 *
 * - @testing-library/jest-dom: matchers .toBeInTheDocument, .toHaveTextContent itd.
 * - Mock window.matchMedia, IntersectionObserver - nie istnieja w jsdom domyslnie
 * - Mock next/navigation router hooks - strony uzywaja useRouter
 * - Mock localStorage czysci sie przed kazdym testem (auto-isolation)
 */
import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// Cleanup React po kazdym tescie
afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
});

// jsdom NIE ma matchMedia - polyfill (potrzebny dla niektorych UI libs)
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

// jsdom NIE ma IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = vi.fn(() => []);
  root = null;
  rootMargin = '';
  thresholds = [];
} as unknown as typeof IntersectionObserver;

// Mock next/navigation router - strony robia useRouter().push(...)
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));

// Mock useConfirm - w testach nie potrzebujemy faktycznego dialogu, tylko
// zeby hook nie rzucal blędu "must be used inside ConfirmProvider". Tests
// nie klikają destruktywnych akcji, wiec confirm() nigdy nie zostanie wywolany.
vi.mock('@/lib/confirm', () => ({
  useConfirm: () => async () => true,
  ConfirmProvider: ({ children }: { children: unknown }) => children,
}));

// Domyslny mock fetch - zwroty per-test override'owane.
beforeEach(() => {
  global.fetch = vi.fn();
});
