'use client';

/**
 * ThemeToggle - 3-state segmented button (light / dark / system).
 *
 * Kompaktowy widget do wpiecia w sidebar lub topbar. Po klik
 * zapisuje do localStorage + aktualizuje data-theme na html.
 */
import { useEffect, useState } from 'react';

import { type Theme, getStoredTheme, setStoredTheme } from './theme';

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState<Theme>('system');

  // Hydrate from storage po mount (SSR safe)
  useEffect(() => {
    setTheme(getStoredTheme());
  }, []);

  function pick(t: Theme) {
    setTheme(t);
    setStoredTheme(t);
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: TT_CSS }} />
      <div className={`theme-toggle ${compact ? 'tt-compact' : ''}`} role="group" aria-label="Motyw">
        <button
          className={`tt-btn ${theme === 'light' ? 'on' : ''}`}
          onClick={() => pick('light')}
          title="Tryb jasny"
          type="button"
        >
          <i className="ti ti-sun" />
          {!compact && <span>Jasny</span>}
        </button>
        <button
          className={`tt-btn ${theme === 'system' ? 'on' : ''}`}
          onClick={() => pick('system')}
          title="Auto wg systemu"
          type="button"
        >
          <i className="ti ti-device-laptop" />
          {!compact && <span>Auto</span>}
        </button>
        <button
          className={`tt-btn ${theme === 'dark' ? 'on' : ''}`}
          onClick={() => pick('dark')}
          title="Tryb ciemny"
          type="button"
        >
          <i className="ti ti-moon" />
          {!compact && <span>Ciemny</span>}
        </button>
      </div>
    </>
  );
}

const TT_CSS = `
.theme-toggle {
  display: inline-flex;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 8px;
  padding: 2px;
  gap: 2px;
}
.tt-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 10px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: rgba(255,255,255,0.55);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.tt-btn i { font-size: 14px; }
.tt-btn:hover { color: rgba(255,255,255,0.85); }
.tt-btn.on {
  background: rgba(212,33,44,0.18);
  color: #FCA5A5;
}

/* Compact variant - tylko ikony, krotsze */
.tt-compact .tt-btn { padding: 6px 8px; }
.tt-compact .tt-btn i { font-size: 16px; }
`;
