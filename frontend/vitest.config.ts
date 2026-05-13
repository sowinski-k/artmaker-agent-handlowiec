import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Vitest config: smoke testy frontendu w jsdom env.
 *
 * - jsdom: DOM API w Node (window, document, localStorage) - nie wymaga browsera
 * - alias @/ -> source root (zgodnie z tsconfig paths Next.js)
 * - setupFiles: globalne mocki (fetch, localStorage) + @testing-library/jest-dom
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    css: false, // dangerouslySetInnerHTML CSS w stronach - ignorujemy w testach
    include: ['tests/**/*.test.{ts,tsx}'],
  },
});
