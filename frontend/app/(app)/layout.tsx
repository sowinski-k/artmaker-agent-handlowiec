'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { api, clearToken, isAuthenticated, logout } from '@/lib/api';

const HANDLOWIEC_PAGES = [
  { href: '/handlowiec/pulpit', icon: 'layout-dashboard', label: 'Pulpit' },
  { href: '/pozyskiwanie', icon: 'search', label: 'Pozyskiwanie' },
  { href: '/handlowiec/patrol', icon: 'radar-2', label: 'Patrol AI' },
  { href: '/leady', icon: 'users', label: 'Leady' },
  { href: '/drafty', icon: 'mail', label: 'Drafty' },
];

const HALA_PATH = '/pulpit';

const KUZNIA_TOOLS = [
  { icon: 'user-square', label: 'Wirtualny model / try-on', desc: 'ubrania na sylwetce' },
  { icon: 'ad-2', label: 'Generator reklam', desc: 'Meta / TikTok 1:1, 9:16, 4:5' },
  { icon: 'video', label: 'Animator packshotów', desc: 'foto -> loop 3-5s' },
  { icon: 'eraser', label: 'Usuń tło', desc: 'batch do 200 zdjęć' },
  { icon: 'arrows-maximize', label: 'Upscaler', desc: '2x / 4x' },
];

const KANCELARIA_TOOLS = [
  { icon: 'briefcase', label: 'Agent Celny', desc: 'cła, dokumenty' },
  { icon: 'shield-check', label: 'Asystent GPSR', desc: 'compliance UE' },
];

interface JobLite { id: number; status: string; type: string; progress: number; total: number }

interface MeResp {
  workspace: { credits: number; used_credits: number; name: string };
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [activeJobs, setActiveJobs] = useState<JobLite[]>([]);
  const [credits, setCredits] = useState<{ used: number; total: number } | null>(null);

  useEffect(() => {
    if (typeof window !== 'undefined' && !isAuthenticated()) {
      router.push('/login');
    }
  }, [router]);

  // Poll active jobs every 8s (workspace-wide widget)
  useEffect(() => {
    if (!isAuthenticated()) return;
    let cancelled = false;
    async function refresh() {
      try {
        const [jobs, me] = await Promise.all([
          api<JobLite[]>('/api/jobs?status=running&limit=10').catch(() => [] as JobLite[]),
          api<MeResp>('/api/auth/me').catch(() => null),
        ]);
        if (cancelled) return;
        // Backend filtruje status pojedynczo - pobierz tez pending
        const pending = await api<JobLite[]>('/api/jobs?status=pending&limit=10').catch(() => [] as JobLite[]);
        if (cancelled) return;
        setActiveJobs([...jobs, ...pending]);
        if (me?.workspace) setCredits({ used: me.workspace.used_credits, total: me.workspace.credits });
      } catch {}
    }
    refresh();
    const iv = setInterval(refresh, 8000);
    return () => { cancelled = true; clearInterval(iv); };
  }, [pathname]);

  const isHandlowiecActive = HANDLOWIEC_PAGES.some((p) => p.href === pathname);

  async function handleLogout() {
    try { await logout(); } catch {}
    clearToken();
    router.push('/login');
  }

  const creditsPct = credits && credits.total > 0
    ? Math.min(100, Math.round((credits.used / credits.total) * 100))
    : 0;

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
          <Link href={HALA_PATH} className={`sb-item ${pathname === HALA_PATH ? 'active' : ''}`}>
            <i className="ti ti-layout-dashboard"></i>
            <span className="sb-label">Pulpit</span>
          </Link>
          {/* Projekty / Biblioteka - ukryte do czasu implementacji.
              KUZNIA_TOOLS, KANCELARIA_TOOLS - tez ukryte. Roadmapa zostaje
              w pamieci (komentarze w kodzie + KUZNIA_TOOLS/KANCELARIA_TOOLS
              consts), wlaczamy gdy dany modul zacznie zylac. */}

          {/* ─── Agenci AI ─────────────────────────── */}
          <div className="sb-section">
            Agenci AI
            <span className="sb-section-sub">automatyzacja sprzedaży</span>
          </div>
          <div className={`sb-group ${isHandlowiecActive ? 'active' : ''}`}>
            <div className="sb-group-head">
              <i className="ti ti-robot"></i>
              <div className="sb-group-text">
                <div className="sb-group-name">Handlowiec</div>
                <div className="sb-group-meta">cold-email</div>
              </div>
              <span className="sb-badge live">live</span>
            </div>
          </div>
          <div className="sb-sub">
            {HANDLOWIEC_PAGES.map((p) => (
              <Link key={p.href} href={p.href}
                className={`sb-subitem ${pathname === p.href ? 'active' : ''}`}>
                <i className={`ti ti-${p.icon}`}></i>
                <span>{p.label}</span>
              </Link>
            ))}
          </div>

          {/* ─── Integracje ────────────────────────── */}
          <div className="sb-section">Integracje</div>
          <a className="sb-item">
            <i className="ti ti-mail"></i>
            <span className="sb-label">Woodpecker</span>
          </a>
          <a className="sb-item">
            <i className="ti ti-package"></i>
            <span className="sb-label">Apify</span>
          </a>

          {activeJobs.length > 0 && (
            <Link href="/pulpit" className="sb-jobs">
              <div className="sb-jobs-head">
                <i className="ti ti-loader-2 spin"></i>
                <span>Praca w tle</span>
                <span className="sb-jobs-count">{activeJobs.length}</span>
              </div>
              <div className="sb-jobs-list">
                {activeJobs.slice(0, 2).map((j) => (
                  <div className="sb-jobs-item" key={j.id}>
                    <span className="sb-jobs-type">{labelForJob(j.type)}</span>
                    {j.total > 0 && (
                      <span className="sb-jobs-prog mono">{j.progress}/{j.total}</span>
                    )}
                  </div>
                ))}
                {activeJobs.length > 2 && (
                  <div className="sb-jobs-more">+ {activeJobs.length - 2} więcej</div>
                )}
              </div>
            </Link>
          )}

          <div className="sb-foot">
            <div className="sb-foot-row">
              Kredyty
              <strong>{credits?.used ?? 0} / {credits?.total ?? 100}</strong>
            </div>
            <div className="sb-bar"><div style={{ width: `${creditsPct}%` }}></div></div>
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

function labelForJob(type: string): string {
  switch (type) {
    case 'discovery_pipeline': return 'Agent w terenie';
    case 'bulk_research_leads': return 'Research wybranych';
    case 'research_lead': return 'Research';
    case 'enrich_lead': return 'Uzupełnij kontakt';
    case 'bulk_enrich_leads': return 'Uzupełnianie kontaktów';
    case 'generate_draft': return 'Draft';
    case 'bulk_generate_drafts': return 'Drafty (batch)';
    case 'send_draft': return 'Wysyłka';
    case 'poll_woodpecker': return 'Sync Woodpecker';
    default: return type;
  }
}

const APP_CSS = `
.app { display: grid; grid-template-columns: 272px 1fr; min-height: 100vh; }

aside.sidebar {
  background: #1C1C1C;
  color: #fff;
  padding: 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255,255,255,0.15) transparent;
}
aside.sidebar::-webkit-scrollbar { width: 6px; }
aside.sidebar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }

.sb-logo {
  display: flex; align-items: center; gap: 10px;
  padding: 4px 6px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  margin-bottom: 10px;
}
.sb-logo-mark {
  width: 30px; height: 30px;
  background: #D4212C;
  border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  color: #fff;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}
.sb-logo-mark::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, transparent 50%, rgba(0,0,0,0.2) 100%);
}
.sb-logo-mark i { font-size: 17px; position: relative; z-index: 1; }
.sb-logo-text {
  font-weight: 700;
  font-size: 15px;
  letter-spacing: -0.3px;
  font-family: 'Space Grotesk', sans-serif;
}
.sb-logo-env {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
  color: rgba(255,255,255,0.55);
  padding: 2px 6px;
  background: rgba(255,255,255,0.08);
  border-radius: 3px;
  margin-left: auto;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.sb-section {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: rgba(255,255,255,0.42);
  padding: 14px 6px 4px;
  font-weight: 700;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.sb-section-sub {
  font-size: 9.5px;
  text-transform: none;
  letter-spacing: 0;
  color: rgba(255,255,255,0.32);
  font-weight: 500;
  margin-top: 2px;
}

/* Flat nav item */
.sb-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  color: #D1D5DB;
  font-size: 13px;
  cursor: pointer;
  text-decoration: none;
  position: relative;
  transition: background 0.12s, color 0.12s;
  min-height: 32px;
}
.sb-item:hover { background: rgba(255,255,255,0.05); color: #fff; }
.sb-item.active { background: rgba(212,33,44,0.14); color: #fff; }
.sb-item.active::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px; height: 20px;
  background: #D4212C;
  border-radius: 0 2px 2px 0;
}
.sb-item.disabled { opacity: 0.45; cursor: not-allowed; }
.sb-item.disabled:hover { background: transparent; color: #D1D5DB; }
.sb-item i { font-size: 17px; width: 18px; flex-shrink: 0; }

.sb-label { flex: 1; }

.sb-label-stack {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.sb-label-stack .sb-label {
  font-size: 12.5px;
  line-height: 1.2;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sb-desc {
  font-size: 10.5px;
  color: rgba(255,255,255,0.38);
  font-weight: 400;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sb-count {
  margin-left: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: rgba(255,255,255,0.4);
  padding: 1px 5px;
  background: rgba(255,255,255,0.04);
  border-radius: 3px;
  flex-shrink: 0;
}

.sb-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  flex-shrink: 0;
}
.sb-badge.live {
  background: rgba(212,33,44,0.2);
  color: #fff;
  border: 1px solid rgba(212,33,44,0.4);
}

/* Group header for Handlowiec (with submodules) */
.sb-group {
  border-radius: 6px;
  padding: 2px;
  position: relative;
  margin-bottom: 2px;
}
.sb-group.active::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px; height: 24px;
  background: #D4212C;
  border-radius: 0 2px 2px 0;
}
.sb-group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  border-radius: 6px;
  background: rgba(255,255,255,0.03);
}
.sb-group.active .sb-group-head {
  background: rgba(212,33,44,0.14);
}
.sb-group-head i { font-size: 17px; color: #fff; flex-shrink: 0; }
.sb-group-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0;
  min-width: 0;
}
.sb-group-name {
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  line-height: 1.2;
}
.sb-group-meta {
  font-size: 10.5px;
  color: rgba(255,255,255,0.5);
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.3px;
}

.sb-sub {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 4px 0 4px 20px;
  margin-bottom: 4px;
}
.sb-subitem {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px 6px 12px;
  border-radius: 5px;
  color: rgba(255,255,255,0.62);
  font-size: 12.5px;
  text-decoration: none;
  transition: all 0.12s;
  border-left: 2px solid rgba(255,255,255,0.08);
  font-weight: 500;
}
.sb-subitem:hover {
  color: #fff;
  background: rgba(255,255,255,0.04);
  border-left-color: rgba(212,33,44,0.5);
}
.sb-subitem.active {
  color: #fff;
  background: rgba(212,33,44,0.18);
  border-left-color: #D4212C;
  font-weight: 600;
}
.sb-subitem i { font-size: 13px; }

.sb-jobs {
  margin-bottom: 8px;
  padding: 10px 12px;
  background: rgba(212,33,44,0.1);
  border: 1px solid rgba(212,33,44,0.25);
  border-radius: 8px;
  text-decoration: none;
  color: #fff;
  display: block;
  transition: all 0.15s;
}
.sb-jobs:hover {
  background: rgba(212,33,44,0.18);
  border-color: rgba(212,33,44,0.4);
}
.sb-jobs-head {
  display: flex; align-items: center; gap: 8px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.2px;
  margin-bottom: 6px;
  color: #fff;
}
.sb-jobs-head i { font-size: 14px; color: #FCA5A5; }
.sb-jobs-count {
  margin-left: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: rgba(255,255,255,0.15);
  padding: 1px 6px;
  border-radius: 3px;
}
.sb-jobs-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sb-jobs-item {
  display: flex;
  justify-content: space-between;
  font-size: 10.5px;
  color: rgba(255,255,255,0.72);
}
.sb-jobs-type { font-weight: 500; }
.sb-jobs-prog { color: rgba(255,255,255,0.55); }
.sb-jobs-more {
  font-size: 10px;
  color: rgba(255,255,255,0.45);
  font-style: italic;
}
.spin { animation: spin 1.5s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.mono { font-family: 'JetBrains Mono', monospace; }

.sb-foot {
  margin-top: auto;
  margin-bottom: 4px;
  padding: 12px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 8px;
}
.sb-foot-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 11px;
  color: rgba(255,255,255,0.6);
  margin-bottom: 4px;
}
.sb-foot-row strong {
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
}
.sb-bar {
  height: 3px;
  background: rgba(255,255,255,0.08);
  border-radius: 2px;
  overflow: hidden;
  margin: 6px 0 10px;
}
.sb-bar > div { height: 100%; background: #D4212C; }

.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 8px;
  background: transparent;
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 5px;
  color: rgba(255,255,255,0.6);
  font-size: 11.5px;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.12s;
}
.logout-btn:hover {
  background: rgba(212,33,44,0.1);
  color: #fff;
  border-color: rgba(212,33,44,0.4);
}
.logout-btn i { font-size: 14px; }

main { min-width: 0; }
`;
