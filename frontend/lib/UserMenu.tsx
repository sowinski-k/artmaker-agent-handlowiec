'use client';

/**
 * UserMenu - avatar + dropdown w topbar.
 *
 * Klik na avatar -> dropdown z:
 *  - Email + nazwa workspace (kontekst)
 *  - Link do Ustawienia (/ustawienia)
 *  - Wyloguj (czerwone)
 *
 * Zamykany klikiem poza dropdownem (useEffect na document click).
 */
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

import { getCachedUser, getCachedWorkspace, logout } from './api';

export function UserMenu({ initials = 'EC' }: { initials?: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [user, setUser] = useState<ReturnType<typeof getCachedUser>>(null);
  const [ws, setWs] = useState<ReturnType<typeof getCachedWorkspace>>(null);

  useEffect(() => {
    setUser(getCachedUser());
    setWs(getCachedWorkspace());
  }, []);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  // Close on Esc
  useEffect(() => {
    if (!open) return;
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onEsc);
    return () => document.removeEventListener('keydown', onEsc);
  }, [open]);

  // Auto-derive initials from email/name jak nie podano explicit
  const computedInitials = (() => {
    if (initials !== 'EC') return initials;
    if (user?.name) {
      const parts = user.name.trim().split(/\s+/);
      return ((parts[0]?.[0] || '') + (parts[1]?.[0] || '')).toUpperCase() || 'EC';
    }
    if (user?.email) return user.email.slice(0, 2).toUpperCase();
    return 'EC';
  })();

  async function handleLogout() {
    setOpen(false);
    try { await logout(); } catch {}
    router.push('/login');
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: UM_CSS }} />
      <div className="user-menu-wrap" ref={ref}>
        <button
          className={`um-avatar ${open ? 'open' : ''}`}
          onClick={() => setOpen(!open)}
          title={user?.email || 'Konto'}
          type="button"
        >
          {computedInitials}
        </button>
        {open && (
          <div className="um-dropdown">
            <div className="um-head">
              <div className="um-avatar-big">{computedInitials}</div>
              <div className="um-head-text">
                <div className="um-name">{user?.name || user?.email || 'User'}</div>
                {ws && <div className="um-ws">Workspace: <strong>{ws.name}</strong></div>}
                {user?.email && <div className="um-email">{user.email}</div>}
              </div>
            </div>
            <div className="um-list">
              <button
                className="um-item"
                onClick={() => { setOpen(false); router.push('/ustawienia'); }}
                type="button"
              >
                <i className="ti ti-settings" />
                <span>Ustawienia konta</span>
              </button>
              <button
                className="um-item"
                onClick={() => { setOpen(false); router.push('/ustawienia#workspace'); }}
                type="button"
              >
                <i className="ti ti-building" />
                <span>Workspace</span>
              </button>
              <button
                className="um-item"
                onClick={() => { setOpen(false); router.push('/ustawienia#api-keys'); }}
                type="button"
              >
                <i className="ti ti-key" />
                <span>Klucze API</span>
              </button>
              <div className="um-divider" />
              <button
                className="um-item um-danger"
                onClick={handleLogout}
                type="button"
              >
                <i className="ti ti-logout" />
                <span>Wyloguj</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

const UM_CSS = `
.user-menu-wrap { position: relative; }
.um-avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: #1C1C1C; color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 600; font-size: 12px; font-family: inherit;
  border: 2px solid #D4212C;
  cursor: pointer;
}
.um-avatar:hover, .um-avatar.open {
  box-shadow: 0 0 0 3px rgba(212,33,44,0.18);
}

.um-dropdown {
  position: absolute; top: calc(100% + 8px); right: 0;
  width: 280px;
  background: var(--panel, #fff);
  border: 1px solid var(--border, #E5E7EB);
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.15);
  z-index: 100;
  animation: um-pop 0.12s ease-out;
}
@keyframes um-pop {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.um-head {
  display: flex; gap: 12px; align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border, #E5E7EB);
}
.um-avatar-big {
  width: 44px; height: 44px; border-radius: 50%;
  background: #1C1C1C; color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 600; font-size: 15px;
  border: 2px solid #D4212C;
  flex-shrink: 0;
}
.um-head-text { flex: 1; min-width: 0; }
.um-name { font-weight: 600; font-size: 13px; color: var(--ink, #111); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.um-ws { font-size: 11px; color: var(--muted, #6B7280); margin-top: 2px; }
.um-ws strong { color: var(--ink, #111); }
.um-email { font-size: 11px; color: var(--muted, #6B7280); font-family: 'JetBrains Mono', monospace; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.um-list { padding: 6px; }
.um-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 9px 12px;
  background: transparent; border: none; border-radius: 6px;
  color: var(--ink, #111); font-size: 13px; font-family: inherit;
  cursor: pointer; text-align: left;
}
.um-item i { font-size: 16px; color: var(--muted, #6B7280); }
.um-item:hover { background: var(--bg, #FAFAF7); }
.um-item:hover i { color: #D4212C; }

.um-divider {
  height: 1px; background: var(--border, #E5E7EB); margin: 6px 0;
}

.um-danger { color: #991B1B; }
.um-danger i { color: #991B1B; }
.um-danger:hover { background: #FEE2E2; }
.um-danger:hover i { color: #991B1B; }
`;
