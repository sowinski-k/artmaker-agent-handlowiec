'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { clearToken, getToken, logout } from '@/lib/api';

const HANDLOWIEC_PAGES = [
  { href: '/pulpit', icon: 'layout-dashboard', label: 'Pulpit' },
  { href: '/pozyskiwanie', icon: 'search', label: 'Pozyskiwanie' },
  { href: '/leady', icon: 'users', label: 'Leady' },
  { href: '/drafty', icon: 'mail', label: 'Drafty' },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  // Auth guard - protected pages
  useEffect(() => {
    if (typeof window !== 'undefined' && !getToken()) {
      router.push('/login');
    }
  }, [router]);

  const isHandlowiecActive = HANDLOWIEC_PAGES.some((p) => p.href === pathname);

  async function handleLogout() {
    try { await logout(); } catch {}
    clearToken();
    router.push('/login');
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: APP_CSS }} />
      <div className="app">
        <aside className="sidebar">
          <div className="sb-logo">
            <div className="sb-logo-mark"><i className="ti ti-flame"></i></div>
            <div className="sb-logo-text">eCombinat</div>
            <span className="sb-logo-env">PROD</span>
          </div>

          <div className="sb-section">Hala</div>
          <Link href="/pulpit" className={`sb-item ${pathname === '/pulpit' ? 'active' : ''}`}>
            <i className="ti ti-layout-dashboard"></i> Pulpit
          </Link>
          <a className="sb-item disabled"><i className="ti ti-folder"></i> Projekty <span className="sb-count">—</span></a>
          <a className="sb-item disabled"><i className="ti ti-photo"></i> Biblioteka <span className="sb-count">—</span></a>

          <div className="sb-section">Kuźnia · Agenci AI</div>
          <div className={`sb-item sb-group ${isHandlowiecActive ? 'active' : ''}`}>
            <i className="ti ti-robot"></i> Handlowiec cold-email <span className="sb-count">live</span>
          </div>
          <div className="sb-sub">
            {HANDLOWIEC_PAGES.map((p) => (
              <Link key={p.href} href={p.href} className={`sb-subitem ${pathname === p.href ? 'active' : ''}`}>
                <i className={`ti ti-${p.icon}`}></i> {p.label}
              </Link>
            ))}
          </div>

          <a className="sb-item disabled"><i className="ti ti-photo"></i> Zdjęcia produktowe</a>
          <a className="sb-item disabled"><i className="ti ti-video"></i> Wideo</a>
          <a className="sb-item disabled"><i className="ti ti-wand"></i> Opisy AI</a>

          <div className="sb-section">Integracje</div>
          <a className="sb-item"><i className="ti ti-mail"></i> Woodpecker</a>
          <a className="sb-item"><i className="ti ti-package"></i> Apify</a>

          <div className="sb-foot">
            <div className="sb-foot-row">Kredyty <strong>0 / 100</strong></div>
            <div className="sb-bar"><div style={{ width: '0%' }}></div></div>
            <button onClick={handleLogout} className="logout-btn">
              <i className="ti ti-logout"></i> Wyloguj
            </button>
          </div>
        </aside>

        <main>
          {children}
        </main>
      </div>
    </>
  );
}

const APP_CSS = `
.app { display: grid; grid-template-columns: 224px 1fr; min-height: 100vh; }

aside.sidebar {
  background: #1C1C1C;
  color: #fff;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
}
.sb-logo { display: flex; align-items: center; gap: 10px; padding: 6px 8px 18px; border-bottom: 1px solid rgba(255,255,255,0.08); margin-bottom: 14px; }
.sb-logo-mark { width: 28px; height: 28px; background: #D4212C; border-radius: 6px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.sb-logo-mark i { font-size: 16px; }
.sb-logo-text { font-weight: 600; font-size: 14px; letter-spacing: -0.2px; }
.sb-logo-env { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #9CA3AF; padding: 1px 6px; background: rgba(255,255,255,0.06); border-radius: 3px; margin-left: auto; }
.sb-section { font-size: 10.5px; text-transform: uppercase; letter-spacing: 1.4px; color: rgba(255,255,255,0.4); padding: 12px 10px 4px; font-weight: 600; }
.sb-item {
  display: flex; align-items: center; gap: 10px;
  padding: 7px 10px; border-radius: 6px;
  color: #D1D5DB; font-size: 13px;
  cursor: pointer; text-decoration: none; position: relative;
  transition: background 0.12s;
}
.sb-item:hover { background: rgba(255,255,255,0.05); color: #fff; }
.sb-item.active, .sb-group.active { background: rgba(212,33,44,0.12); color: #fff; }
.sb-item.active::before, .sb-group.active::before {
  content: ''; position: absolute; left: -12px; top: 50%; transform: translateY(-50%);
  width: 3px; height: 18px; background: #D4212C; border-radius: 0 2px 2px 0;
}
.sb-item.disabled { opacity: 0.4; cursor: not-allowed; }
.sb-item i { font-size: 16px; width: 16px; }
.sb-count { margin-left: auto; font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: rgba(255,255,255,0.5); }
.sb-item.active .sb-count, .sb-group.active .sb-count { color: rgba(255,255,255,0.85); }

.sb-group { cursor: default; font-weight: 500; }

.sb-sub { display: flex; flex-direction: column; gap: 1px; padding-left: 12px; margin-bottom: 4px; }
.sb-subitem {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px 6px 14px; border-radius: 6px;
  color: rgba(255,255,255,0.65); font-size: 12.5px;
  text-decoration: none; transition: all 0.12s;
  border-left: 2px solid rgba(255,255,255,0.08);
}
.sb-subitem:hover { color: #fff; background: rgba(255,255,255,0.04); border-left-color: rgba(212,33,44,0.5); }
.sb-subitem.active { color: #fff; background: rgba(212,33,44,0.18); border-left-color: #D4212C; font-weight: 500; }
.sb-subitem i { font-size: 14px; }

.sb-foot { margin-top: auto; padding: 10px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; }
.sb-foot-row { display: flex; justify-content: space-between; align-items: baseline; font-size: 11px; color: rgba(255,255,255,0.6); margin-bottom: 4px; }
.sb-foot-row strong { color: #fff; font-family: 'JetBrains Mono', monospace; font-weight: 500; }
.sb-bar { height: 3px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden; margin: 6px 0 8px; }
.sb-bar > div { height: 100%; background: #D4212C; }

.logout-btn {
  display: flex; align-items: center; gap: 6px;
  width: 100%; padding: 8px; margin-top: 8px;
  background: transparent; border: 1px solid rgba(255,255,255,0.1);
  border-radius: 4px; color: rgba(255,255,255,0.6); font-size: 11.5px;
  cursor: pointer; font-family: inherit;
}
.logout-btn:hover { background: rgba(255,255,255,0.05); color: #fff; border-color: rgba(255,255,255,0.2); }
.logout-btn i { font-size: 14px; }

main { min-width: 0; }
`;
