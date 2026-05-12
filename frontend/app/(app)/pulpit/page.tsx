/* Pulpit Hala - ogólny widok workspace (cross-module).
 *
 * Pokazuje wszystkie aktywne moduły, kredyty, ostatnią aktywność.
 * Module-specific dashboardy są pod /handlowiec/pulpit itp.
 */

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { api, getToken } from '@/lib/api';

interface Module {
  slug: string;
  name: string;
  desc: string;
  icon: string;
  status: 'live' | 'soon' | 'beta';
  href: string | null;
  metrics?: Record<string, number>;
}

interface Shortcut {
  label: string;
  href: string;
  icon: string;
}

interface Overview {
  workspace: {
    id: number;
    name: string;
    plan: string;
    credits: number;
    used_credits: number;
  };
  leads_total: number;
  drafts_pending: number;
  running_jobs: number;
  modules: Module[];
  shortcuts: Shortcut[];
}

interface ActivityItem {
  icon: string;
  accent: boolean;
  text: string;
  time: string;
}

interface ActiveJob {
  id: number;
  type: string;
  status: string;
  progress: number;
  total: number;
  created_at: string;
  started_at: string | null;
  retries: number;
  last_error: string | null;
}

const JOB_LABELS: Record<string, string> = {
  discovery_pipeline: 'Pozyskiwanie + research',
  research_lead: 'Research leada',
  bulk_research_leads: 'Bulk research',
  enrich_lead: 'Uzupełnij kontakt',
  bulk_enrich_leads: 'Bulk enrichment',
  generate_draft: 'Generowanie draftu',
  bulk_generate_drafts: 'Bulk drafty',
  send_draft: 'Wysyłka',
  poll_woodpecker: 'Synchronizacja statusów',
};

export default function HalaPulpit() {
  const router = useRouter();
  const [data, setData] = useState<Overview | null>(null);
  const [events, setEvents] = useState<ActivityItem[]>([]);
  const [activeJobs, setActiveJobs] = useState<ActiveJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<number | null>(null);

  const fetchActiveJobs = async () => {
    try {
      const [running, pending] = await Promise.all([
        api<ActiveJob[]>('/api/jobs?status=running&limit=20').catch(() => []),
        api<ActiveJob[]>('/api/jobs?status=pending&limit=20').catch(() => []),
      ]);
      setActiveJobs([...running, ...pending]);
    } catch {
      setActiveJobs([]);
    }
  };

  const cancelJob = async (id: number) => {
    if (!confirm(`Anulować job #${id}? Już zrobione leady zostaną w bazie.`)) return;
    setCancellingId(id);
    try {
      await api(`/api/jobs/${id}/cancel`, { method: 'POST' });
      await fetchActiveJobs();
    } catch (err) {
      alert('Nie udało się anulować: ' + (err instanceof Error ? err.message : 'błąd'));
    } finally {
      setCancellingId(null);
    }
  };

  useEffect(() => {
    if (!getToken()) {
      router.push('/login');
      return;
    }
    Promise.all([
      api<Overview>('/api/workspace/overview'),
      api<ActivityItem[]>('/api/events?limit=8').catch(() => []),
      fetchActiveJobs(),
    ])
      .then(([d, e]) => {
        setData(d);
        setEvents(e);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Błąd pobierania danych');
        setLoading(false);
      });
    // Auto-refresh aktywnych jobów co 5s
    const iv = setInterval(fetchActiveJobs, 5000);
    return () => clearInterval(iv);
  }, [router]);

  if (loading) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center', color: '#6B7280' }}>
        Ładowanie pulpitu…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center', color: '#8F1018' }}>
        {error || 'Brak danych'}
      </div>
    );
  }

  const { workspace, modules, shortcuts } = data;
  const creditsPct = workspace.credits > 0
    ? Math.min(100, Math.round((workspace.used_credits / workspace.credits) * 100))
    : 0;

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: HALA_CSS }} />

      <div className="topbar">
        <div className="crumb">
          <strong>Hala</strong>
          <i className="ti ti-chevron-right"></i>
          Pulpit
        </div>
        <div className="ws-tag">
          <i className="ti ti-building-warehouse"></i>
          {workspace.name}
          <span className="plan-pill">{workspace.plan}</span>
        </div>
      </div>

      <div className="content">
        <div className="welcome">
          <h1>Twoja Hala</h1>
          <p>
            Centrum dowodzenia całym kombinatem. Wybierz agenta z prawej strony lub
            zacznij od skrótu. Praca leci w tle - możesz zamknąć przeglądarkę.
          </p>
        </div>

        {/* TOP STATS */}
        <div className="kpi-row">
          <div className="kpi">
            <div className="kpi-label"><i className="ti ti-bolt"></i> Kredyty</div>
            <div className="kpi-value tabular">
              {workspace.used_credits}<span className="kpi-unit"> / {workspace.credits}</span>
            </div>
            <div className="kpi-bar"><div style={{ width: `${creditsPct}%` }}></div></div>
            <div className="kpi-meta">{creditsPct}% wykorzystane</div>
          </div>

          <div className="kpi">
            <div className="kpi-label"><i className="ti ti-database"></i> Leady w bazie</div>
            <div className="kpi-value tabular">{data.leads_total}</div>
            <Link href="/leady" className="kpi-link">
              Zobacz wszystkie <i className="ti ti-arrow-right"></i>
            </Link>
          </div>

          <div className="kpi">
            <div className="kpi-label"><i className="ti ti-mail-forward"></i> Drafty do review</div>
            <div className="kpi-value tabular">{data.drafts_pending}</div>
            <Link href="/drafty" className="kpi-link">
              Sprawdź drafty <i className="ti ti-arrow-right"></i>
            </Link>
          </div>

          <div className="kpi">
            <div className="kpi-label"><i className="ti ti-loader"></i> Praca w tle</div>
            <div className="kpi-value tabular">{data.running_jobs}</div>
            <div className="kpi-meta">
              {data.running_jobs > 0
                ? 'agenci pracują, zamknij spokojnie'
                : 'cisza w fabryce'}
            </div>
          </div>
        </div>

        {/* AKTYWNE ZADANIA - tylko gdy jakies sa */}
        {activeJobs.length > 0 && (
          <div className="active-jobs-section">
            <div className="section-head">
              <h2><i className="ti ti-loader-2 spin"></i> Aktywne zadania</h2>
              <span className="section-sub">worker pracuje w tle ({activeJobs.length})</span>
            </div>
            <div className="active-jobs">
              {activeJobs.map((j) => {
                const pct = j.total > 0 ? Math.round((j.progress / j.total) * 100) : 0;
                const isRunning = j.status === 'running';
                return (
                  <div className={`aj-row ${j.status}`} key={j.id}>
                    <div className="aj-meta">
                      <div className="aj-type">
                        {JOB_LABELS[j.type] || j.type}
                        <span className="aj-id mono">#{j.id}</span>
                        {!isRunning && <span className="aj-status">w kolejce</span>}
                        {j.retries > 0 && <span className="aj-retry">retry {j.retries}</span>}
                      </div>
                      <div className="aj-prog-line">
                        {j.total > 0 ? (
                          <>
                            <div className="aj-bar"><div style={{ width: `${pct}%` }}></div></div>
                            <span className="aj-prog mono">{j.progress}/{j.total} ({pct}%)</span>
                          </>
                        ) : (
                          <span className="aj-prog mono">{isRunning ? 'pracuje…' : 'czeka na start'}</span>
                        )}
                      </div>
                      {j.last_error && (
                        <div className="aj-error">Ostatni błąd: {j.last_error}</div>
                      )}
                    </div>
                    <button
                      className="aj-cancel"
                      onClick={() => cancelJob(j.id)}
                      disabled={cancellingId === j.id}
                    >
                      <i className="ti ti-x"></i>
                      {cancellingId === j.id ? 'Anulowanie…' : 'Anuluj'}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="hala-grid">
          {/* MODUŁY */}
          <div>
            <div className="section-head">
              <h2><i className="ti ti-apps"></i> Twoi agenci</h2>
              <span className="section-sub">moduły AI w workspace</span>
            </div>

            <div className="modules">
              {modules.map((m) => (
                <ModuleCard key={m.slug} module={m} />
              ))}
            </div>
          </div>

          {/* RIGHT COLUMN */}
          <div>
            <div className="section-head">
              <h2><i className="ti ti-bookmark"></i> Skróty</h2>
              <span className="section-sub">najczęstsze akcje</span>
            </div>
            <div className="shortcuts">
              {shortcuts.map((s) => (
                <Link key={s.href} href={s.href} className="shortcut">
                  <div className="sc-icon"><i className={`ti ti-${s.icon}`}></i></div>
                  <span>{s.label}</span>
                  <i className="ti ti-arrow-right sc-arrow"></i>
                </Link>
              ))}
            </div>

            <div className="section-head" style={{ marginTop: '24px' }}>
              <h2><i className="ti ti-activity"></i> Ostatnia aktywność</h2>
              <span className="section-sub">zdarzenia w workspace</span>
            </div>
            <div className="activity">
              {events.length === 0 ? (
                <div className="empty">
                  Brak zdarzeń. Odpal pierwszego agenta żeby zobaczyć aktywność.
                </div>
              ) : events.map((e, i) => (
                <div className="act-item" key={i}>
                  <div className={`act-ico ${e.accent ? 'red' : ''}`}>
                    <i className={`ti ti-${e.icon}`}></i>
                  </div>
                  <div className="act-text" dangerouslySetInnerHTML={{ __html: e.text }} />
                  <span className="act-time">{e.time}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function ModuleCard({ module: m }: { module: Module }) {
  const live = m.status === 'live';
  const card = (
    <div className={`mod-card ${m.status}`}>
      <div className="mod-head">
        <div className={`mod-ico ${m.status}`}>
          <i className={`ti ti-${m.icon}`}></i>
        </div>
        <div className="mod-text">
          <div className="mod-name">
            {m.name}
            {live && <span className="mod-badge live">live</span>}
            {m.status === 'soon' && <span className="mod-badge soon">soon</span>}
          </div>
          <div className="mod-desc">{m.desc}</div>
        </div>
        {live && <i className="ti ti-arrow-right mod-arrow"></i>}
      </div>

      {live && m.metrics && (
        <div className="mod-metrics">
          {Object.entries(m.metrics).map(([k, v]) => (
            <div className="mod-metric" key={k}>
              <span className="mm-value">{v}</span>
              <span className="mm-label">{k === 'leads' ? 'leady' : k === 'drafts_pending' ? 'drafty' : k}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
  return live && m.href ? <Link href={m.href} className="mod-link">{card}</Link> : card;
}

const HALA_CSS = `
.topbar {
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  display: flex;
  align-items: center;
  height: 52px;
  gap: 16px;
  position: sticky;
  top: 0;
  z-index: 10;
}
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
.crumb strong { color: var(--ink); font-weight: 500; }
.crumb i { font-size: 12px; color: var(--muted-2); }
.ws-tag {
  margin-left: auto;
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--ink);
  background: var(--bg);
  border: 1px solid var(--border);
  padding: 6px 12px;
  border-radius: 6px;
}
.ws-tag i { font-size: 14px; color: var(--red); }
.plan-pill {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  background: rgba(212,33,44,0.12);
  color: var(--red-dark);
  padding: 2px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 700;
}

.content { padding: 24px; max-width: 1320px; }

.welcome { margin-bottom: 24px; max-width: 720px; }
.welcome h1 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.5px;
  margin: 0 0 6px 0;
  color: var(--ink);
}
.welcome p { color: var(--muted); font-size: 14px; line-height: 1.55; }

.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 28px;
}
.kpi {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
}
.kpi-label {
  font-size: 11.5px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  font-weight: 600;
  margin-bottom: 10px;
  display: flex; align-items: center; gap: 6px;
}
.kpi-label i { font-size: 13px; color: var(--red); }
.kpi-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.6px;
  line-height: 1.1;
  font-feature-settings: "tnum";
  color: var(--ink);
}
.kpi-unit { font-size: 14px; color: var(--muted); font-weight: 400; }
.kpi-bar {
  height: 4px;
  background: var(--bg);
  border-radius: 2px;
  overflow: hidden;
  margin: 10px 0 6px;
}
.kpi-bar > div { height: 100%; background: var(--red); transition: width 0.3s; }
.kpi-meta {
  font-size: 11.5px;
  color: var(--muted-2);
  font-family: 'JetBrains Mono', monospace;
}
.kpi-link {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; color: var(--red); text-decoration: none;
  margin-top: 8px; font-weight: 500;
}
.kpi-link:hover { text-decoration: underline; }
.kpi-link i { font-size: 13px; }

.active-jobs-section { margin-bottom: 28px; }
.active-jobs {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.aj-row {
  display: flex; align-items: center; gap: 16px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}
.aj-row:last-child { border-bottom: none; }
.aj-row.pending { opacity: 0.75; background: var(--bg); }
.aj-meta { flex: 1; min-width: 0; }
.aj-type {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  margin-bottom: 6px;
  display: flex; align-items: center; gap: 8px;
}
.aj-id {
  font-size: 11px;
  color: var(--muted-2);
  background: var(--bg);
  border: 1px solid var(--border);
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 500;
}
.aj-status {
  font-size: 10.5px;
  color: var(--muted-2);
  background: var(--bg);
  border: 1px solid var(--border);
  padding: 1px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.aj-retry {
  font-size: 10.5px;
  color: var(--red-dark);
  background: rgba(212,33,44,0.1);
  border: 1px solid rgba(212,33,44,0.25);
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'JetBrains Mono', monospace;
}
.aj-prog-line {
  display: flex; align-items: center; gap: 10px;
}
.aj-bar {
  flex: 1;
  height: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow: hidden;
  max-width: 360px;
}
.aj-bar > div { height: 100%; background: var(--red); transition: width 0.3s; }
.aj-prog {
  font-size: 11.5px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
}
.aj-error {
  margin-top: 6px;
  font-size: 11px;
  color: var(--red-dark);
  font-family: 'JetBrains Mono', monospace;
}
.aj-cancel {
  display: flex; align-items: center; gap: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--ink);
  font-size: 12px;
  font-weight: 500;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.12s;
  flex-shrink: 0;
}
.aj-cancel:hover:not(:disabled) {
  background: rgba(212,33,44,0.1);
  border-color: rgba(212,33,44,0.4);
  color: var(--red-dark);
}
.aj-cancel:disabled { opacity: 0.6; cursor: not-allowed; }
.aj-cancel i { font-size: 13px; }
.spin { animation: spin 1.4s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.hala-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 24px;
}

.section-head {
  display: flex; align-items: baseline; gap: 10px;
  margin-bottom: 14px;
}
.section-head h2 {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.2px;
  margin: 0;
  display: flex; align-items: center; gap: 8px;
  color: var(--ink);
}
.section-head h2 i { color: var(--red); font-size: 16px; }
.section-sub {
  font-size: 11.5px;
  color: var(--muted-2);
  font-family: 'JetBrains Mono', monospace;
}

.modules { display: flex; flex-direction: column; gap: 10px; }
.mod-link { text-decoration: none; color: inherit; }
.mod-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px;
  transition: all 0.15s;
}
.mod-card.live { cursor: pointer; }
.mod-card.live:hover {
  border-color: rgba(212,33,44,0.4);
  box-shadow: 0 4px 16px -8px rgba(212,33,44,0.2);
  transform: translateY(-1px);
}
.mod-card.soon { opacity: 0.62; }

.mod-head {
  display: flex; align-items: center; gap: 14px;
}
.mod-ico {
  width: 44px; height: 44px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  color: var(--muted);
  flex-shrink: 0;
}
.mod-ico.live { background: rgba(212,33,44,0.1); border-color: rgba(212,33,44,0.25); color: var(--red); }
.mod-ico i { font-size: 22px; }
.mod-text { flex: 1; min-width: 0; }
.mod-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.2px;
  color: var(--ink);
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 3px;
}
.mod-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.mod-badge.live { background: rgba(212,33,44,0.15); color: var(--red-dark); border: 1px solid rgba(212,33,44,0.25); }
.mod-badge.soon { background: var(--bg); color: var(--muted-2); border: 1px solid var(--border); }
.mod-desc { font-size: 12.5px; color: var(--muted); line-height: 1.4; }
.mod-arrow { color: var(--muted-2); font-size: 16px; }
.mod-card.live:hover .mod-arrow { color: var(--red); }

.mod-metrics {
  display: flex;
  gap: 18px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.mod-metric { display: flex; flex-direction: column; gap: 1px; }
.mm-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 18px;
  font-weight: 600;
  color: var(--ink);
  font-feature-settings: "tnum";
}
.mm-label {
  font-size: 10.5px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.shortcuts {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.shortcut {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--ink);
  text-decoration: none;
  transition: background 0.12s;
}
.shortcut:last-child { border-bottom: none; }
.shortcut:hover { background: var(--bg); }
.sc-icon {
  width: 28px; height: 28px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  color: var(--red);
  flex-shrink: 0;
}
.sc-icon i { font-size: 14px; }
.sc-arrow { margin-left: auto; color: var(--muted-2); font-size: 13px; }
.shortcut:hover .sc-arrow { color: var(--red); }

.activity {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}
.empty {
  padding: 20px;
  text-align: center;
  color: var(--muted-2);
  font-size: 12.5px;
}
.act-item {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: flex-start;
  font-size: 12.5px;
}
.act-item:last-child { border-bottom: none; }
.act-ico {
  width: 24px; height: 24px;
  border-radius: 5px;
  background: var(--bg);
  border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  color: var(--muted);
  flex-shrink: 0;
}
.act-ico i { font-size: 12px; }
.act-ico.red { background: rgba(212,33,44,0.1); border-color: rgba(212,33,44,0.2); color: var(--red); }
.act-text { line-height: 1.4; color: var(--muted); word-break: break-word; }
.act-text strong { color: var(--ink); font-weight: 500; }
.act-time {
  color: var(--muted-2);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
  flex-shrink: 0;
}

@media (max-width: 1100px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .hala-grid { grid-template-columns: 1fr; }
}
`;
