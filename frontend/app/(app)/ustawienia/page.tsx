'use client';

/**
 * /ustawienia - panel konfiguracji konta + workspace + API keys + wyglądu.
 *
 * Sekcje (anchor links via #hash z UserMenu):
 *  - #account     - email, imię, change password
 *  - #workspace   - nazwa, plan, kredyty
 *  - #api-keys    - per-workspace klucze (placeholder, na razie tylko display
 *                   z global env settings - per-workspace UI w v2)
 *  - #appearance  - dark mode toggle (full controls)
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import {
  api, getCachedUser, getCachedWorkspace, isAuthenticated, refreshMe,
  type UserInfo, type WorkspaceInfo,
} from '@/lib/api';
import { ThemeToggle } from '@/lib/ThemeToggle';
import { UserMenu } from '@/lib/UserMenu';

type Flash = { kind: 'success' | 'error' | 'info'; text: string };

export default function UstawieniaPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState<Flash | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push('/login');
      return;
    }
    setUser(getCachedUser());
    setWorkspace(getCachedWorkspace());
    // Refresh from server zeby miec najsiwezsze credits/plan
    refreshMe()
      .then((res) => {
        setUser(res.user);
        setWorkspace(res.workspace);
      })
      .catch(() => {/* zostaw cache */})
      .finally(() => setLoading(false));
  }, [router]);

  // Auto-dismiss flash
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

  // Scroll do anchor po hydration (jak user kliknal np. /ustawienia#api-keys)
  useEffect(() => {
    if (loading) return;
    if (typeof window === 'undefined') return;
    const hash = window.location.hash;
    if (hash) {
      setTimeout(() => {
        const el = document.querySelector(hash);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 100);
    }
  }, [loading]);

  const credits = workspace
    ? { used: workspace.used_credits, total: workspace.credits, pct: workspace.credits > 0 ? Math.round((workspace.used_credits / workspace.credits) * 100) : 0 }
    : null;

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="topbar">
        <div className="crumb">
          Workspace <i className="ti ti-chevron-right" /> <strong>{workspace?.name || 'Ecombinat'}</strong>
          <i className="ti ti-chevron-right" /> Ustawienia
        </div>
        <div className="topbar-spacer" />
        <ThemeToggle compact />
        <UserMenu />
      </div>

      {flash && (
        <div className={`global-flash flash-${flash.kind}`}>
          {flash.kind === 'success' && <i className="ti ti-check" />}
          {flash.kind === 'error' && <i className="ti ti-alert-circle" />}
          {flash.kind === 'info' && <i className="ti ti-info-circle" />}
          <span style={{ flex: 1 }}>{flash.text}</span>
          <button className="flash-close" onClick={() => setFlash(null)}>
            <i className="ti ti-x" />
          </button>
        </div>
      )}

      <div className="content">
        <div className="page-head">
          <h1>Ustawienia</h1>
          <p>Twoje konto · workspace · klucze API · wygląd</p>
        </div>

        {loading ? (
          <div className="card" style={{ padding: 40, textAlign: 'center', color: 'var(--muted)' }}>
            Ładuję…
          </div>
        ) : (
          <>
            {/* MOJE KONTO */}
            <section id="account" className="card">
              <div className="card-head">
                <div className="card-title">
                  <i className="ti ti-user-circle" /> Moje konto
                </div>
              </div>
              <div className="card-body">
                <div className="kv">
                  <div className="k">Email</div>
                  <div className="v"><strong>{user?.email || '-'}</strong></div>
                  <div className="k">Imię</div>
                  <div className="v">{user?.name || <em style={{ color: 'var(--muted)' }}>(nie ustawione)</em>}</div>
                  <div className="k">Rola</div>
                  <div className="v">
                    {user?.is_admin ? (
                      <span className="badge badge-admin">Admin</span>
                    ) : (
                      <span className="badge badge-user">Użytkownik</span>
                    )}
                  </div>
                  <div className="k">ID konta</div>
                  <div className="v mono">{user?.id ?? '-'}</div>
                </div>
                <div className="muted-note">
                  <i className="ti ti-lock" /> Zmiana hasła i edycja danych konta
                  będzie dostępna w kolejnej wersji. Na razie skontaktuj się z adminem.
                </div>
              </div>
            </section>

            {/* WORKSPACE */}
            <section id="workspace" className="card">
              <div className="card-head">
                <div className="card-title">
                  <i className="ti ti-building" /> Workspace
                </div>
              </div>
              <div className="card-body">
                <div className="kv">
                  <div className="k">Nazwa</div>
                  <div className="v"><strong>{workspace?.name || '-'}</strong></div>
                  <div className="k">Slug</div>
                  <div className="v mono">{workspace?.slug || '-'}</div>
                  <div className="k">Plan</div>
                  <div className="v">
                    <span className={`plan-badge plan-${workspace?.plan || 'free'}`}>
                      {workspace?.plan || 'free'}
                    </span>
                  </div>
                  <div className="k">ID</div>
                  <div className="v mono">{workspace?.id ?? '-'}</div>
                </div>

                {credits && (
                  <div className="credits-block">
                    <div className="credits-head">
                      <span>Wykorzystanie kredytów</span>
                      <strong>{credits.used.toLocaleString('pl-PL')} / {credits.total.toLocaleString('pl-PL')}</strong>
                    </div>
                    <div className="credits-bar">
                      <div className="credits-fill" style={{ width: `${Math.min(100, credits.pct)}%` }} />
                    </div>
                    <div className="muted-note" style={{ marginTop: 8 }}>
                      <i className="ti ti-info-circle" /> Kredyty resetują się 1. dnia każdego miesiąca.
                      System rozliczania jeszcze w przygotowaniu — na razie traktuj jako informacyjne.
                    </div>
                  </div>
                )}
              </div>
            </section>

            {/* KLUCZE API */}
            <section id="api-keys" className="card">
              <div className="card-head">
                <div className="card-title">
                  <i className="ti ti-key" /> Klucze API
                </div>
              </div>
              <div className="card-body">
                <p className="section-desc">
                  Klucze do zewnętrznych usług których agent używa do pozyskiwania
                  i researchu leadów. <strong>Aktualnie używamy globalnych kluczy
                  workspace'u admina</strong> - per-workspace klucze będą w kolejnej
                  wersji (gdy uruchamiamy SaaS dla wielu klientów).
                </p>

                <div className="api-keys-grid">
                  <ApiKeyRow
                    name="Anthropic (Claude)"
                    desc="LLM do researchu leadów + generowania spersonalizowanych draftów"
                    setKey="ANTHROPIC_API_KEY"
                    docs="https://console.anthropic.com/settings/keys"
                  />
                  <ApiKeyRow
                    name="Google Gemini"
                    desc="Tańsza alternatywa LLM (filtr trafności, batch scoring)"
                    setKey="GEMINI_API_KEY"
                    docs="https://aistudio.google.com/apikey"
                  />
                  <ApiKeyRow
                    name="Apify"
                    desc="Scrapery: Google Maps, Allegro, LinkedIn"
                    setKey="APIFY_API_TOKEN"
                    docs="https://console.apify.com/settings/integrations"
                  />
                  <ApiKeyRow
                    name="Google Places API"
                    desc="Wyszukiwarka firm na mapie (najwyższa jakość, $25/1000)"
                    setKey="GOOGLE_PLACES_API_KEY"
                    docs="https://console.cloud.google.com/google/maps-apis/"
                  />
                  <ApiKeyRow
                    name="Woodpecker"
                    desc="Wysyłka cold-maili + sequence follow-upów + tracking"
                    setKey="WOODPECKER_API_KEY"
                    docs="https://app.woodpecker.co/settings/api"
                  />
                </div>
              </div>
            </section>

            {/* WYGLĄD */}
            <section id="appearance" className="card">
              <div className="card-head">
                <div className="card-title">
                  <i className="ti ti-palette" /> Wygląd
                </div>
              </div>
              <div className="card-body">
                <div className="appearance-row">
                  <div>
                    <div className="appearance-title">Motyw aplikacji</div>
                    <div className="appearance-desc">
                      <strong>Auto</strong> dopasowuje się do ustawień systemu (Windows, macOS, Linux).
                      <strong> Jasny</strong> / <strong>Ciemny</strong> wymusza na stałe.
                    </div>
                  </div>
                  <div className="appearance-toggle-wrap">
                    <ThemeToggle />
                  </div>
                </div>
              </div>
            </section>

            {/* INTEGRACJE info */}
            <section className="card">
              <div className="card-head">
                <div className="card-title">
                  <i className="ti ti-plug" /> Integracje
                </div>
              </div>
              <div className="card-body">
                <p className="section-desc">
                  <strong>Woodpecker</strong> — wysyłka i tracking cold-maili.
                  <strong> Apify</strong> — scrapery zewnętrznych źródeł.
                  Status połączeń widzisz na pulpicie Handlowca w karcie "System".
                </p>
              </div>
            </section>
          </>
        )}
      </div>
    </>
  );
}


function ApiKeyRow({
  name, desc, setKey, docs,
}: {
  name: string; desc: string; setKey: string; docs: string;
}) {
  return (
    <div className="api-key-row">
      <div className="akr-info">
        <div className="akr-name">{name}</div>
        <div className="akr-desc">{desc}</div>
        <div className="akr-meta">
          <span className="akr-env">{setKey}</span>
          <a href={docs} target="_blank" rel="noopener" className="akr-docs">
            <i className="ti ti-external-link" /> Skąd wziąć klucz
          </a>
        </div>
      </div>
      <div className="akr-status">
        <span className="akr-status-pill akr-pill-system">system</span>
      </div>
    </div>
  );
}


const CSS = `
.topbar {
  background: var(--panel); border-bottom: 1px solid var(--border);
  padding: 0 24px; display: flex; align-items: center; height: 52px;
  gap: 16px; position: sticky; top: 0; z-index: 10;
}
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
.crumb strong { color: var(--ink); font-weight: 500; }
.crumb i { font-size: 12px; color: var(--muted-2); }
.topbar-spacer { flex: 1; }

.global-flash {
  position: fixed; top: 64px; left: 50%; transform: translateX(-50%);
  z-index: 200; min-width: 320px; max-width: 600px;
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; border-radius: 8px;
  font-size: 13.5px; font-weight: 500;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
}
.global-flash i { font-size: 18px; flex-shrink: 0; }
.global-flash.flash-success { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
.global-flash.flash-error { background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }
.global-flash.flash-info { background: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE; }
.flash-close { background: none; border: none; cursor: pointer; color: inherit; opacity: 0.7; padding: 4px; display: flex; font-size: 16px; }
.flash-close:hover { opacity: 1; }

.content {
  padding: 24px;
  max-width: 900px;
  margin: 0 auto;
}
.page-head { margin-bottom: 20px; }
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; color: var(--ink); }
.page-head p { color: var(--muted); font-size: 13.5px; margin: 0; }

.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 16px;
  overflow: hidden;
}
.card-head {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  background: var(--panel-2);
}
.card-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; color: var(--ink);
}
.card-title i { color: #D4212C; font-size: 16px; }
.card-body { padding: 18px; }

.kv {
  display: grid;
  grid-template-columns: 130px 1fr;
  gap: 10px 16px;
  font-size: 13px;
}
.kv .k {
  color: var(--muted); text-transform: uppercase;
  font-size: 11px; letter-spacing: 0.6px; font-weight: 600;
  padding-top: 2px;
}
.kv .v { color: var(--ink); }
.kv .v.mono { font-family: 'JetBrains Mono', monospace; font-size: 12px; }

.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px; font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.badge-admin { background: #1C1C1C; color: #fff; }
.badge-user { background: var(--panel-2); color: var(--ink); border: 1px solid var(--border); }

.plan-badge {
  display: inline-block; padding: 3px 10px; border-radius: 12px;
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.5px; font-family: 'JetBrains Mono', monospace;
}
.plan-free { background: var(--panel-2); color: var(--muted); border: 1px solid var(--border); }
.plan-enterprise { background: #1C1C1C; color: #FCA5A5; }
.plan-pro, .plan-paid { background: #FDECED; color: #8F1018; }

.muted-note {
  margin-top: 14px;
  padding: 10px 12px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12px;
  color: var(--muted);
  display: flex; align-items: flex-start; gap: 8px; line-height: 1.5;
}
.muted-note i { color: var(--muted-2); flex-shrink: 0; margin-top: 2px; font-size: 14px; }

.section-desc {
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.6;
  margin-bottom: 16px;
}
.section-desc strong { color: var(--ink); }

/* Credits */
.credits-block { margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--border); }
.credits-head {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 12px; color: var(--muted); margin-bottom: 8px;
}
.credits-head strong {
  color: var(--ink); font-family: 'JetBrains Mono', monospace; font-size: 14px;
}
.credits-bar {
  height: 8px;
  background: var(--panel-2);
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid var(--border);
}
.credits-fill {
  height: 100%;
  background: linear-gradient(90deg, #D4212C, #8F1018);
  transition: width 0.3s;
}

/* API keys */
.api-keys-grid {
  display: flex; flex-direction: column; gap: 10px;
}
.api-key-row {
  display: flex; gap: 14px; align-items: flex-start;
  padding: 12px 14px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.akr-info { flex: 1; min-width: 0; }
.akr-name { font-size: 13.5px; font-weight: 600; color: var(--ink); margin-bottom: 2px; }
.akr-desc { font-size: 11.5px; color: var(--muted); line-height: 1.4; margin-bottom: 6px; }
.akr-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.akr-env {
  font-family: 'JetBrains Mono', monospace; font-size: 10.5px;
  color: var(--muted-2);
  padding: 2px 6px; background: var(--panel); border-radius: 4px;
  border: 1px solid var(--border);
}
.akr-docs {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11.5px; color: #D4212C; text-decoration: none;
}
.akr-docs:hover { text-decoration: underline; }
.akr-docs i { font-size: 11px; }
.akr-status { flex-shrink: 0; }
.akr-status-pill {
  display: inline-block; padding: 3px 8px; border-radius: 11px;
  font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.5px; font-family: 'JetBrains Mono', monospace;
}
.akr-pill-system { background: var(--panel); color: var(--muted); border: 1px solid var(--border); }

/* Appearance */
.appearance-row {
  display: flex; gap: 16px; align-items: center; justify-content: space-between;
  flex-wrap: wrap;
}
.appearance-title { font-size: 14px; font-weight: 600; color: var(--ink); margin-bottom: 4px; }
.appearance-desc { font-size: 12px; color: var(--muted); line-height: 1.5; max-width: 500px; }
.appearance-desc strong { color: var(--ink); }
.appearance-toggle-wrap { background: #1C1C1C; padding: 4px; border-radius: 10px; }
`;
