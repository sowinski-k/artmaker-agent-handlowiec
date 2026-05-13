/* Pulpit Handlowca - module-specific dashboard cold-mail.
 *
 * Leady, drafty, funnel cold-maila, scoring, segmenty.
 * Ogólny widok workspace (Hala) jest pod /pulpit.
 */

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { api, getToken } from '@/lib/api';
import Loading from './loading';

interface DashboardData {
  stats: {
    leads_total: number;
    leads_hot: number;
    drafts_pending: number;
    avg_score: number;
    researched: number;
    sent_today: number;
    replied: number;
    reply_rate: number;
    bounced: number;
  };
  sparklines: Record<string, number[]>;
  funnel: Array<{ label: string; value: number; percent: number; icon: string }>;
  system: Array<{ label: string; value: string; status: 'ok' | 'warn' | 'err' }>;
  segments: Array<{ name: string; count: number }>;
}

interface ActivityItem {
  icon: string;
  accent: boolean;
  text: string;
  time: string;
}

export default function PulpitPage() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [events, setEvents] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Auth gate - bez tokena redirect na login
    if (!getToken()) {
      router.push('/login');
      return;
    }

    Promise.all([
      api<DashboardData>('/api/dashboard'),
      api<ActivityItem[]>('/api/events?limit=8').catch(() => []),
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
  }, [router]);

  if (loading) {
    return <Loading />;
  }

  if (error || !data) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center', color: '#8F1018' }}>
        {error || 'Brak danych'}
      </div>
    );
  }

  const { stats, funnel, system, segments } = data;

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: PULPIT_CSS }} />

      {/* TOPBAR */}
      <div className="topbar">
        <div className="crumb">
          <strong>Handlowiec</strong>
          <i className="ti ti-chevron-right"></i>
          Pulpit
        </div>
        <div className="search">
          <i className="ti ti-search"></i>
          Szukaj leadów, kampanii, ustawień…
          <span className="kbd">⌘K</span>
        </div>
        <button className="topbtn" title="Nowy projekt"><i className="ti ti-plus"></i></button>
        <button className="topbtn" title="Powiadomienia"><i className="ti ti-bell"></i><span className="dot"></span></button>
        <button className="topbtn" title="Pomoc"><i className="ti ti-help"></i></button>
        <div className="avatar">EC</div>
      </div>

      <div className="content">
        {/* PAGE HEAD */}
        <div className="page-head">
          <div>
            <h1>Pulpit Handlowca</h1>
            <p>Cold-mail · leady · drafty <span className="mono">·</span> <span className="last-update">aktualizacja właśnie</span></p>
          </div>
          <div className="timerange">
            <button>24h</button>
            <button>7d</button>
            <button className="active">30d</button>
            <button>90d</button>
            <button>YTD</button>
          </div>
        </div>

        {/* STATS - 4 cards */}
        <div className="stats">
          <StatCard label="Leady w bazie" value={stats.leads_total} icon="database"
            delta={`${stats.researched} researched`} deltaDir="up"
            sparkline={data.sparklines.leads} sparkColor="#D4212C" />
          <StatCard label="Hot leady" value={stats.leads_hot} unit="≥ 7/10" icon="flame"
            delta={`${stats.leads_hot}/${stats.leads_total} ogółem`} deltaDir="up"
            sparkline={data.sparklines.leads} sparkColor="#D4212C" />
          <StatCard label="Drafty do review" value={stats.drafts_pending} icon="mail-forward"
            sparkline={data.sparklines.drafts} sparkColor="#1C1C1C" />
          <StatCard label="Średni score" value={stats.avg_score.toFixed(1)} unit="/ 10" icon="chart-bar"
            sparkline={data.sparklines.replies} sparkColor="#6B7280" />
        </div>

        {/* ROW 1: CHART + ACTIVITY */}
        <div className="grid">
          <div className="card">
            <div className="card-head">
              <div className="card-title"><i className="ti ti-funnel"></i> Pipeline cold-mail</div>
              <div className="card-actions">
                <span style={{ fontSize: '11.5px' }}>30 dni</span>
              </div>
            </div>
            <div className="card-body">
              <div className="funnel">
                {funnel.map((row, i) => (
                  <div className="funnel-row" key={row.label}>
                    <div className="funnel-label">
                      <i className={`ti ti-${row.icon}`}></i> {row.label}
                    </div>
                    <div className="funnel-bar">
                      <div className={`funnel-fill ${i < 2 ? 'red' : ''}`}
                        style={{ width: `${row.percent}%`, ...(i >= 2 ? { background: ['#2A2A2A', '#444', '#666'][i - 2] || '#666' } : {}) }}>
                        {row.value}
                      </div>
                    </div>
                    <div className="funnel-num">{row.percent.toFixed(1)}%</div>
                  </div>
                ))}
              </div>
              <div style={{ borderTop: '1px solid var(--border)', marginTop: '14px', paddingTop: '12px',
                fontSize: '12px', color: 'var(--muted)', display: 'flex', justifyContent: 'space-between' }}>
                <span>Reply rate vs sent</span>
                <strong className="mono" style={{ color: 'var(--ink)', fontWeight: 600 }}>
                  {stats.reply_rate.toFixed(1)}%
                </strong>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div className="card-title"><i className="ti ti-activity"></i> Ostatnia aktywność</div>
              <div className="card-actions"><a href="#" style={{ fontSize: '11.5px', color: 'var(--muted)' }}>Wszystkie →</a></div>
            </div>
            <div className="activity">
              {events.length === 0 ? (
                <div style={{ padding: '24px', color: 'var(--muted)', fontSize: '13px', textAlign: 'center' }}>
                  Brak zdarzeń. Odpal pozyskiwanie żeby zobaczyć aktywność.
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

        {/* ROW 2: SEGMENTS + SYSTEM + SHORTCUTS */}
        <div className="grid split">
          <div className="card">
            <div className="card-head">
              <div className="card-title"><i className="ti ti-layers-subtract"></i> Leady wg segmentu</div>
            </div>
            {segments.length === 0 ? (
              <div style={{ padding: '24px', color: 'var(--muted)', fontSize: '13px', textAlign: 'center' }}>
                Brak leadów.
              </div>
            ) : (
              <table className="tbl">
                <thead>
                  <tr><th>Segment</th><th className="num">Liczba</th></tr>
                </thead>
                <tbody>
                  {segments.map(s => (
                    <tr key={s.name}>
                      <td>{s.name}</td>
                      <td className="num">{s.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <div className="card-head">
              <div className="card-title"><i className="ti ti-server"></i> Stan systemu</div>
              <div className="card-actions">
                <span className="mono" style={{ fontSize: '11px' }}>
                  <span className="status-dot ok"></span>operational
                </span>
              </div>
            </div>
            <div>
              {system.map(row => (
                <div className="sys-row" key={row.label}>
                  <span className="sys-label">
                    <span className={`status-dot ${row.status}`}></span>{row.label}
                  </span>
                  <span className="sys-val">{row.value}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div className="card-title"><i className="ti ti-bookmark"></i> Skróty</div>
              <div className="card-actions"><span style={{ fontSize: '11.5px' }}>ulubione</span></div>
            </div>
            <div>
              <a className="sys-row" href="#" style={{ textDecoration: 'none', color: 'inherit' }}>
                <span className="sys-label" style={{ gap: '8px' }}>
                  <div className="tool-ico"><i className="ti ti-search"></i></div> Nowe pozyskiwanie
                </span>
                <i className="ti ti-arrow-right" style={{ color: 'var(--muted-2)', fontSize: '14px' }}></i>
              </a>
              <a className="sys-row" href="#" style={{ textDecoration: 'none', color: 'inherit' }}>
                <span className="sys-label" style={{ gap: '8px' }}>
                  <div className="tool-ico"><i className="ti ti-mail-forward"></i></div> Drafty do review
                </span>
                <i className="ti ti-arrow-right" style={{ color: 'var(--muted-2)', fontSize: '14px' }}></i>
              </a>
              <a className="sys-row" href="#" style={{ textDecoration: 'none', color: 'inherit' }}>
                <span className="sys-label" style={{ gap: '8px' }}>
                  <div className="tool-ico"><i className="ti ti-users"></i></div> Lista leadów
                </span>
                <i className="ti ti-arrow-right" style={{ color: 'var(--muted-2)', fontSize: '14px' }}></i>
              </a>
              <a className="sys-row" href="#" style={{ textDecoration: 'none', color: 'inherit' }}>
                <span className="sys-label" style={{ gap: '8px' }}>
                  <div className="tool-ico"><i className="ti ti-key"></i></div> Klucze API
                </span>
                <i className="ti ti-arrow-right" style={{ color: 'var(--muted-2)', fontSize: '14px' }}></i>
              </a>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

// Helper: sparkline SVG generator
function Sparkline({ points, color }: { points: number[]; color: string }) {
  if (points.length < 2) return null;
  const width = 80, height = 28;
  const min = Math.min(...points), max = Math.max(...points);
  const range = max - min || 1;
  const xs = points.map((_, i) => Math.round((i * width) / (points.length - 1)));
  const ys = points.map(p => height - Math.round(((p - min) / range) * (height - 4)) - 2);
  const polyPoints = xs.map((x, i) => `${x},${ys[i]}`).join(' ');
  return (
    <svg className="stat-spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={polyPoints} />
    </svg>
  );
}

// Stat card component
function StatCard({ label, value, unit, delta, deltaDir, icon, sparkline, sparkColor }: {
  label: string;
  value: string | number;
  unit?: string;
  delta?: string;
  deltaDir?: 'up' | 'down' | 'flat';
  icon: string;
  sparkline?: number[];
  sparkColor: string;
}) {
  return (
    <div className="stat">
      <div className="stat-label"><i className={`ti ti-${icon}`}></i> {label}</div>
      <div className="stat-value tabular">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {delta && (
        <div className={`stat-delta ${deltaDir || 'flat'}`}>
          {deltaDir === 'up' && <i className="ti ti-arrow-up-right"></i>}
          {delta}
        </div>
      )}
      {sparkline && <Sparkline points={sparkline} color={sparkColor} />}
    </div>
  );
}

const PULPIT_CSS = `
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
.search {
  margin-left: auto;
  display: flex; align-items: center; gap: 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  width: 280px;
  color: var(--muted);
  font-size: 13px;
}
.search i { font-size: 14px; }
.search .kbd {
  margin-left: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  background: var(--panel);
  border: 1px solid var(--border);
  padding: 1px 5px;
  border-radius: 3px;
  color: var(--muted);
}
.topbtn {
  width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 6px;
  color: var(--muted);
  border: 1px solid var(--border);
  background: var(--panel);
  position: relative;
  cursor: pointer;
}
.topbtn:hover { color: var(--ink); border-color: var(--border-strong); }
.topbtn .dot {
  position: absolute; top: 6px; right: 6px;
  width: 6px; height: 6px;
  background: var(--red);
  border-radius: 50%;
  border: 1.5px solid var(--panel);
}
.avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  background: var(--graphite);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 600; font-size: 12px;
  border: 2px solid var(--red);
}
.content { padding: 24px; }
.page-head {
  display: flex; align-items: flex-end; justify-content: space-between;
  margin-bottom: 24px;
  gap: 16px;
}
.page-head h1 {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.4px;
  margin-bottom: 4px;
}
.page-head p { color: var(--muted); font-size: 13.5px; }
.page-head p .mono { color: var(--ink); }
.last-update { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--muted-2); }
.timerange {
  display: flex; gap: 0;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}
.timerange button {
  padding: 6px 12px;
  font-size: 12.5px;
  font-family: inherit;
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  border-right: 1px solid var(--border);
}
.timerange button:last-child { border-right: none; }
.timerange button:hover { background: var(--bg); color: var(--ink); }
.timerange button.active { background: var(--graphite); color: #fff; }

.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
.stat {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  position: relative;
}
.stat-label {
  font-size: 11.5px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  font-weight: 500;
  margin-bottom: 8px;
  display: flex; align-items: center; gap: 6px;
}
.stat-label i { font-size: 13px; }
.stat-value {
  font-size: 26px;
  font-weight: 600;
  letter-spacing: -0.6px;
  line-height: 1.1;
  font-feature-settings: "tnum";
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.stat-value .unit { font-size: 13px; color: var(--muted); font-weight: 400; }
.stat-delta {
  margin-top: 6px;
  font-size: 11.5px;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
}
.stat-delta.up { color: var(--red-dark); }
.stat-spark { position: absolute; bottom: 12px; right: 12px; opacity: 0.55; }

.grid { display: grid; grid-template-columns: 2fr 1fr; gap: 12px; margin-bottom: 12px; }
.grid.split { grid-template-columns: 1fr 1fr 1fr; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; }
.card-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}
.card-title { font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.card-title i { color: var(--red); font-size: 15px; }
.card-actions { display: flex; gap: 6px; align-items: center; font-size: 12px; color: var(--muted); }
.card-body { padding: 16px; }

.funnel { display: flex; flex-direction: column; gap: 8px; padding: 4px 0; }
.funnel-row {
  display: grid;
  grid-template-columns: 130px 1fr 60px;
  align-items: center;
  gap: 12px;
  font-size: 12.5px;
}
.funnel-label { display: flex; align-items: center; gap: 8px; }
.funnel-label i { font-size: 14px; color: var(--muted); }
.funnel-bar { height: 18px; background: var(--bg); border-radius: 3px; position: relative; overflow: hidden; }
.funnel-fill {
  height: 100%;
  background: var(--graphite);
  display: flex; align-items: center;
  padding-left: 8px;
  color: #fff;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
}
.funnel-fill.red { background: var(--red); }
.funnel-num { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--muted); text-align: right; }

.activity { padding: 0; }
.act-item {
  padding: 11px 16px;
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
  border-radius: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  color: var(--muted);
  flex-shrink: 0;
}
.act-ico i { font-size: 13px; }
.act-ico.red { background: var(--red-tint); border-color: rgba(212,33,44,0.2); color: var(--red); }
.act-text { line-height: 1.4; color: var(--muted); }
.act-text strong { color: var(--ink); font-weight: 500; }
.act-time { color: var(--muted-2); font-family: 'JetBrains Mono', monospace; font-size: 11px; }

.sys-row {
  padding: 11px 16px;
  border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
  font-size: 12.5px;
}
.sys-row:last-child { border-bottom: none; }
.sys-row:hover { background: var(--bg); }
.sys-label { color: var(--ink); display: flex; align-items: center; gap: 6px; }
.sys-val { font-family: 'JetBrains Mono', monospace; color: var(--muted); font-size: 12px; }
.tool-ico {
  width: 24px; height: 24px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  display: flex; align-items: center; justify-content: center;
  color: var(--red);
}
.tool-ico i { font-size: 14px; }

.status-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; margin-right: 6px; }
.status-dot.ok { background: #10B981; box-shadow: 0 0 0 3px rgba(16,185,129,0.15); }
.status-dot.warn { background: #F59E0B; }
.status-dot.err { background: var(--red); }

table.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
table.tbl th {
  text-align: left;
  font-weight: 500;
  font-size: 11px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.8px;
  padding: 10px 16px;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
table.tbl th.num, table.tbl td.num { text-align: right; font-family: 'JetBrains Mono', monospace; }
table.tbl td { padding: 11px 16px; border-bottom: 1px solid var(--border); }
table.tbl tr:last-child td { border-bottom: none; }
table.tbl tr:hover td { background: var(--bg); }

@media (max-width: 1100px) {
  .stats { grid-template-columns: repeat(2, 1fr); }
  .grid, .grid.split { grid-template-columns: 1fr; }
}
`;
