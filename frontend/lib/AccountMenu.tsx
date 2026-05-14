'use client';

/* Avatar dropdown w prawym gornym rogu apki.
 *
 * Zastapuje statyczny <div className="avatar">EC</div> ktory wczesniej
 * pokazywal hardkodowane inicjaly i nic nie robil po kliknieciu.
 *
 * Klik avatar -> dropdown z opcjami:
 *   - User name + email + workspace
 *   - /konto (link)
 *   - Wyloguj (POST /api/auth/logout + redirect na /login)
 *
 * Inicjaly pochodza z user.name (lub email lokal-part).
 */

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { getCachedUser, getCachedWorkspace, logout, clearToken } from './api';

function initials(name: string | null, email: string): string {
  const src = (name || email).trim();
  if (!src) return '?';
  const parts = src.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  // Single token (np. email lokal-part "jan.kowalski") -> bierzemy 2 pierwsze litery
  const tok = parts[0].replace(/[^a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]/g, '');
  return (tok.slice(0, 2) || src.slice(0, 2)).toUpperCase();
}

export function AccountMenu() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<{ name: string | null; email: string } | null>(null);
  const [workspace, setWorkspace] = useState<{ name: string; plan: string } | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Czytaj cache LS przy mount - tania operacja, bez network round-trip
  useEffect(() => {
    const u = getCachedUser();
    const w = getCachedWorkspace();
    if (u) setUser({ name: u.name, email: u.email });
    if (w) setWorkspace({ name: w.name, plan: w.plan });
  }, []);

  // Klik poza menu = zamknij
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  async function handleLogout() {
    try { await logout(); } catch {/* ignore */}
    clearToken();
    router.push('/login');
  }

  const ini = user ? initials(user.name, user.email) : '?';

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: ACCOUNT_MENU_CSS }} />
      <div className="account-menu" ref={menuRef}>
        <button
          className="account-avatar"
          onClick={() => setOpen((v) => !v)}
          aria-label="Menu konta"
          aria-haspopup="menu"
          aria-expanded={open}
        >
          {ini}
        </button>
        {open && (
          <div className="account-dropdown" role="menu">
            <div className="account-head">
              <div className="account-name">{user?.name || user?.email || 'Użytkownik'}</div>
              {user?.name && <div className="account-email">{user.email}</div>}
              {workspace && (
                <div className="account-ws">
                  <i className="ti ti-building" />
                  {workspace.name}
                  <span className="account-plan">{workspace.plan}</span>
                </div>
              )}
            </div>
            <div className="account-divider" />
            <Link
              href="/konto"
              className="account-item"
              role="menuitem"
              onClick={() => setOpen(false)}
            >
              <i className="ti ti-user-cog" />
              <span>Moje konto</span>
            </Link>
            <Link
              href="/pulpit"
              className="account-item"
              role="menuitem"
              onClick={() => setOpen(false)}
            >
              <i className="ti ti-layout-dashboard" />
              <span>Hala (pulpit)</span>
            </Link>
            <div className="account-divider" />
            <button
              className="account-item account-logout"
              onClick={handleLogout}
              role="menuitem"
            >
              <i className="ti ti-logout" />
              <span>Wyloguj</span>
            </button>
          </div>
        )}
      </div>
    </>
  );
}

const ACCOUNT_MENU_CSS = `
.account-menu { position: relative; }
.account-avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: #1C1C1C; color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 600; font-size: 12px; letter-spacing: 0.5px;
  border: 2px solid #D4212C;
  cursor: pointer;
  transition: transform 0.12s, box-shadow 0.12s;
  font-family: inherit;
}
.account-avatar:hover { transform: scale(1.05); box-shadow: 0 2px 8px rgba(212,33,44,0.25); }
.account-avatar:focus-visible { outline: 2px solid #D4212C; outline-offset: 2px; }

.account-dropdown {
  position: absolute; top: calc(100% + 8px); right: 0;
  min-width: 260px;
  background: #fff;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  box-shadow: 0 12px 32px rgba(0,0,0,0.12), 0 2px 6px rgba(0,0,0,0.04);
  padding: 6px;
  z-index: 100;
  animation: accountPop 0.12s ease-out;
  font-family: inherit;
}
@keyframes accountPop {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.account-head {
  padding: 12px 12px 10px;
}
.account-name {
  font-size: 13.5px; font-weight: 600; color: #111;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.account-email {
  font-size: 12px; color: #6B7280; margin-top: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.account-ws {
  display: inline-flex; align-items: center; gap: 6px;
  margin-top: 8px;
  font-size: 11.5px; color: #4B5563;
  padding: 4px 8px; background: #F9FAFB; border-radius: 6px;
}
.account-ws i { font-size: 13px; color: #6B7280; }
.account-plan {
  text-transform: uppercase; letter-spacing: 0.5px;
  font-size: 10px; font-weight: 600; color: #8F1018;
  padding: 1px 6px; background: #FDECED; border-radius: 8px;
  margin-left: 4px;
}
.account-divider {
  height: 1px; background: #F3F4F6; margin: 4px 0;
}
.account-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%;
  padding: 9px 10px;
  font-size: 13px; color: #111;
  background: none; border: none; cursor: pointer;
  border-radius: 6px;
  text-decoration: none;
  font-family: inherit;
  text-align: left;
  transition: background 0.1s;
}
.account-item:hover { background: #F3F4F6; }
.account-item i { font-size: 16px; color: #6B7280; }
.account-item:hover i { color: #D4212C; }
.account-logout { color: #8F1018; }
.account-logout:hover { background: #FDECED; }
.account-logout:hover i { color: #D4212C; }
`;
