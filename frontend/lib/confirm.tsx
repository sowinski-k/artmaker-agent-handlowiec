'use client';

/* Shared confirm dialog - zastapuje native window.confirm() (ten szary chromowy
 * popup nie pasuje do reszty UI).
 *
 * Uzycie:
 *   const confirm = useConfirm();
 *   const ok = await confirm({
 *     title: 'Usunac lead?',
 *     message: 'Lead trafi do kosza i bedzie tam 7 dni.',
 *     confirmLabel: 'Przeniesc do kosza',
 *     destructive: true,
 *   });
 *   if (ok) { ... }
 *
 * Aby dzialalo, root layout musi byc opakowany w <ConfirmProvider>.
 */

import {
  createContext, useCallback, useContext, useEffect, useState,
  type ReactNode,
} from 'react';

interface ConfirmOptions {
  title: string;
  message: string | ReactNode;
  confirmLabel?: string;     // default "Potwierdz"
  cancelLabel?: string;       // default "Anuluj"
  destructive?: boolean;      // czerwony confirm button (delete-style)
  icon?: string;              // Tabler icon name (bez 'ti ti-' prefix), np. 'trash'
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

interface PendingDialog extends ConfirmOptions {
  resolve: (value: boolean) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingDialog | null>(null);

  const confirm = useCallback<ConfirmFn>((opts) => {
    return new Promise<boolean>((resolve) => {
      setPending({ ...opts, resolve });
    });
  }, []);

  const close = useCallback((value: boolean) => {
    setPending((p) => {
      if (p) p.resolve(value);
      return null;
    });
  }, []);

  // Esc = cancel, Enter = confirm. Tylko gdy dialog otwarty.
  useEffect(() => {
    if (!pending) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(false);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        close(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [pending, close]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <>
          <style dangerouslySetInnerHTML={{ __html: CONFIRM_CSS }} />
          <div className="cf-backdrop" onClick={() => close(false)} role="presentation">
            <div
              className="cf-dialog"
              role="alertdialog"
              aria-labelledby="cf-title"
              aria-describedby="cf-msg"
              onClick={(e) => e.stopPropagation()}
            >
              <div className={`cf-icon ${pending.destructive ? 'destructive' : ''}`}>
                <i className={`ti ti-${pending.icon || (pending.destructive ? 'trash' : 'alert-circle')}`} />
              </div>
              <h3 id="cf-title" className="cf-title">{pending.title}</h3>
              <div id="cf-msg" className="cf-msg">{pending.message}</div>
              <div className="cf-actions">
                <button className="cf-btn cf-btn-cancel" onClick={() => close(false)} autoFocus>
                  {pending.cancelLabel || 'Anuluj'}
                </button>
                <button
                  className={`cf-btn ${pending.destructive ? 'cf-btn-destructive' : 'cf-btn-primary'}`}
                  onClick={() => close(true)}
                >
                  {pending.confirmLabel || 'Potwierdź'}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </ConfirmContext.Provider>
  );
}

/** Hook to open the confirm dialog. Returns a Promise<boolean>. */
export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    throw new Error('useConfirm() must be used inside <ConfirmProvider>');
  }
  return ctx;
}

const CONFIRM_CSS = `
.cf-backdrop {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(17, 17, 17, 0.55);
  display: flex; align-items: center; justify-content: center;
  padding: 16px;
  animation: cf-fade 0.12s ease-out;
  backdrop-filter: blur(2px);
}
@keyframes cf-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}
.cf-dialog {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0,0,0,0.25), 0 4px 12px rgba(0,0,0,0.1);
  width: 100%; max-width: 440px;
  padding: 28px 24px 20px;
  text-align: center;
  font-family: inherit;
  animation: cf-pop 0.16s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes cf-pop {
  from { opacity: 0; transform: scale(0.92) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
.cf-icon {
  width: 52px; height: 52px;
  margin: 0 auto 14px;
  border-radius: 50%;
  background: #F3F4F6;
  display: flex; align-items: center; justify-content: center;
  color: #6B7280;
}
.cf-icon.destructive {
  background: #FDECED;
  color: #D4212C;
}
.cf-icon i { font-size: 24px; }
.cf-title {
  font-size: 17px;
  font-weight: 600;
  color: #111;
  margin: 0 0 8px;
  letter-spacing: -0.2px;
}
.cf-msg {
  font-size: 13.5px;
  color: #4B5563;
  line-height: 1.5;
  margin-bottom: 20px;
  white-space: pre-line;
}
.cf-msg strong { color: #111; }
.cf-actions {
  display: flex; gap: 8px; justify-content: stretch;
}
.cf-btn {
  flex: 1;
  padding: 10px 16px;
  font-size: 13.5px;
  font-weight: 500;
  border-radius: 8px;
  border: 1px solid transparent;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.12s, border-color 0.12s;
}
.cf-btn-cancel {
  background: #fff;
  color: #4B5563;
  border-color: #E5E7EB;
}
.cf-btn-cancel:hover { background: #F9FAFB; border-color: #D1D5DB; color: #111; }
.cf-btn-primary {
  background: #D4212C;
  color: #fff;
  border-color: #D4212C;
}
.cf-btn-primary:hover { background: #8F1018; border-color: #8F1018; }
.cf-btn-destructive {
  background: #D4212C;
  color: #fff;
  border-color: #D4212C;
}
.cf-btn-destructive:hover { background: #8F1018; border-color: #8F1018; }
.cf-btn:focus-visible {
  outline: 2px solid #D4212C;
  outline-offset: 2px;
}
`;
