'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { api, getToken } from '@/lib/api';

interface LeadRow {
  id: number;
  segment: string;
  company_name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  website: string | null;
  city: string | null;
  status: string;
  score: number | null;
  created_at: string | null;
}

interface LeadDetail extends LeadRow {
  instagram: string | null;
  country: string;
  research_data: Record<string, unknown> | null;
  notes: string | null;
  updated_at: string | null;
}

interface LeadsResponse {
  total: number;
  items: LeadRow[];
}

const STATUSES = ['', 'new', 'researched', 'drafted', 'approved', 'sent', 'replied', 'bounced', 'blacklisted'];
const SEGMENTS = ['', 'sklep_plastyczny', 'sklep_papierniczy', 'paint_and_sip', 'warsztaty_dzieci',
  'animatorzy_eventy', 'szkola_artystyczna', 'marka_wlasna', 'inne'];

export default function LeadyPage() {
  const router = useRouter();
  const [leads, setLeads] = useState<LeadRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [segment, setSegment] = useState('');
  const [status, setStatus] = useState('');
  const [minScore, setMinScore] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (!getToken()) router.push('/login');
  }, [router]);

  async function load() {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '100' });
      if (segment) params.set('segment', segment);
      if (status) params.set('status', status);
      if (minScore > 0) params.set('min_score', String(minScore));
      const res = await api<LeadsResponse>(`/api/leads?${params}`);
      setLeads(res.items);
      setTotal(res.total);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); /* eslint-disable-next-line */ }, [segment, status, minScore]);

  async function openDetail(id: number) {
    setSelectedId(id);
    setDetail(null);
    try {
      const d = await api<LeadDetail>(`/api/leads/${id}`);
      setDetail(d);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd');
    }
  }

  async function generateDraft(leadId: number) {
    setGenerating(true);
    try {
      const res = await api<{ ok: boolean; job_id: number }>('/api/drafts', {
        method: 'POST',
        body: JSON.stringify({ lead_id: leadId }),
      });
      // Job utworzony - worker generuje draft async (~20-40s). Polluj az done.
      const jobId = res.job_id;
      const maxWaitMs = 90_000;  // 90s hard limit
      const start = Date.now();
      let lastStatus = 'pending';
      while (Date.now() - start < maxWaitMs) {
        await new Promise((r) => setTimeout(r, 2000));
        try {
          const job = await api<{ status: string; result: { draft_id?: number } | null; last_error?: string }>(
            `/api/jobs/${jobId}`
          );
          lastStatus = job.status;
          if (job.status === 'done') {
            const draftId = job.result?.draft_id;
            alert(`✅ Draft #${draftId ?? '?'} wygenerowany. Zobacz w Drafty.`);
            return;
          }
          if (job.status === 'failed' || job.status === 'cancelled') {
            alert(`❌ Draft NIE wygenerowany (status: ${job.status}). ${job.last_error || ''}`);
            return;
          }
        } catch {
          /* network glitch, poll again */
        }
      }
      alert(`⏳ Draft jeszcze sie generuje (job #${jobId}, status: ${lastStatus}). Sprawdz /drafty za chwile.`);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd');
    } finally {
      setGenerating(false);
    }
  }

  const scoreBadge = (s: number | null) => {
    if (s == null) return <span style={{ color: '#9CA3AF' }}>-</span>;
    const cls = s >= 7 ? 'hot' : s >= 5 ? 'warm' : 'cold';
    return <span className={`score-badge ${cls}`}>{s.toFixed(1)}</span>;
  };

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="topbar">
        <div className="crumb">
          Workspace <i className="ti ti-chevron-right" /> <strong>Ecombinat</strong>
          <i className="ti ti-chevron-right" /> Leady
        </div>
        <div className="avatar">EC</div>
      </div>

      <div className="content">
        <div className="page-head">
          <div>
            <h1>Leady</h1>
            <p>{total} firm w bazie · sortowane po score malejąco</p>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title"><i className="ti ti-filter" /> Filtry</div>
          </div>
          <div className="card-body" style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div className="field">
              <label>Segment</label>
              <select value={segment} onChange={(e) => setSegment(e.target.value)}>
                {SEGMENTS.map((s) => <option key={s} value={s}>{s || '- wszystkie -'}</option>)}
              </select>
            </div>
            <div className="field">
              <label>Status</label>
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUSES.map((s) => <option key={s} value={s}>{s || '- wszystkie -'}</option>)}
              </select>
            </div>
            <div className="field" style={{ maxWidth: 200 }}>
              <label>Min score: {minScore}</label>
              <input type="range" min={0} max={10} step={0.5} value={minScore}
                onChange={(e) => setMinScore(parseFloat(e.target.value))} />
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <div className="card-head">
            <div className="card-title">
              <i className="ti ti-users" /> Wyniki ({leads.length})
            </div>
          </div>
          {loading ? (
            <div style={{ padding: 40, textAlign: 'center', color: '#6B7280' }}>Ładowanie…</div>
          ) : leads.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: '#6B7280' }}>
              Brak leadów. Idź do <a href="/pozyskiwanie" style={{ color: '#D4212C' }}>Pozyskiwanie</a> żeby znaleźć pierwsze.
            </div>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th className="num">Score</th>
                  <th>Firma</th>
                  <th>Segment</th>
                  <th>Miasto</th>
                  <th>Email</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {leads.map((l) => (
                  <tr key={l.id} onClick={() => openDetail(l.id)} style={{ cursor: 'pointer' }}>
                    <td className="num">{scoreBadge(l.score)}</td>
                    <td><strong>{l.company_name}</strong>{l.contact_name && <div style={{ fontSize: 11, color: '#6B7280' }}>{l.contact_name}</div>}</td>
                    <td><span className="seg-badge">{l.segment}</span></td>
                    <td style={{ color: '#6B7280' }}>{l.city || '-'}</td>
                    <td style={{ color: '#6B7280', fontSize: 12 }}>{l.email || '-'}</td>
                    <td><span className={`status-badge status-${l.status}`}>{l.status}</span></td>
                    <td><i className="ti ti-chevron-right" style={{ color: '#9CA3AF' }} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {selectedId && (
        <div className="drawer-overlay" onClick={() => setSelectedId(null)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <h2>Lead #{selectedId}</h2>
              <button className="close-btn" onClick={() => setSelectedId(null)}>
                <i className="ti ti-x" />
              </button>
            </div>
            {!detail ? (
              <div style={{ padding: 40, textAlign: 'center', color: '#6B7280' }}>Ładowanie…</div>
            ) : (
              <div className="drawer-body">
                <div className="kv">
                  <div className="k">Firma</div><div className="v"><strong>{detail.company_name}</strong></div>
                  <div className="k">Segment</div><div className="v"><span className="seg-badge">{detail.segment}</span></div>
                  <div className="k">Score</div><div className="v">{scoreBadge(detail.score)}</div>
                  <div className="k">Status</div><div className="v"><span className={`status-badge status-${detail.status}`}>{detail.status}</span></div>
                  <div className="k">Email</div><div className="v">{detail.email || '-'}</div>
                  <div className="k">Telefon</div><div className="v">{detail.phone || '-'}</div>
                  <div className="k">Strona</div><div className="v">{detail.website ? <a href={detail.website} target="_blank" rel="noopener" style={{ color: '#D4212C' }}>{detail.website}</a> : '-'}</div>
                  <div className="k">Miasto</div><div className="v">{detail.city || '-'}</div>
                  <div className="k">Kontakt</div><div className="v">{detail.contact_name || '-'}</div>
                </div>

                {detail.research_data && (
                  <>
                    <h3 style={{ marginTop: 20, marginBottom: 8 }}>Research</h3>
                    {(detail.research_data as { rationale?: string }).rationale && (
                      <p style={{ fontSize: 13, color: '#374151', marginBottom: 12 }}>
                        {(detail.research_data as { rationale: string }).rationale}
                      </p>
                    )}
                    {Array.isArray((detail.research_data as { concrete_hooks?: { text: string; source: string }[] }).concrete_hooks) && (
                      <div style={{ marginBottom: 12 }}>
                        <strong style={{ fontSize: 12, color: '#6B7280', textTransform: 'uppercase', letterSpacing: 0.8 }}>Konkretne sygnały</strong>
                        <ul style={{ marginTop: 6, paddingLeft: 18, fontSize: 13 }}>
                          {(detail.research_data as { concrete_hooks: { text: string; source: string }[] }).concrete_hooks.map((h, i) => (
                            <li key={i}>{h.text} <span style={{ color: '#9CA3AF', fontSize: 11 }}>({h.source})</span></li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}

                <div className="drawer-actions">
                  {detail.status === 'researched' && detail.email && (
                    <button className="btn btn-primary" onClick={() => generateDraft(detail.id)} disabled={generating}>
                      {generating ? 'Generuję…' : '✉️ Generuj draft maila'}
                    </button>
                  )}
                  {!detail.email && (
                    <span style={{ fontSize: 13, color: '#8F1018' }}>
                      Brak emaila - nie można wysłać maila do tego leada.
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

const CSS = `
.topbar { background: #fff; border-bottom: 1px solid #E5E7EB; padding: 0 24px; display: flex; align-items: center; height: 52px; gap: 16px; position: sticky; top: 0; z-index: 10; }
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #6B7280; }
.crumb strong { color: #111; font-weight: 500; }
.crumb i { font-size: 12px; color: #9CA3AF; }
.avatar { margin-left: auto; width: 32px; height: 32px; border-radius: 50%; background: #1C1C1C; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 12px; border: 2px solid #D4212C; }
.content { padding: 24px; }
.page-head { margin-bottom: 20px; }
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-head p { color: #6B7280; font-size: 13.5px; margin: 0; }

.card { background: #fff; border: 1px solid #E5E7EB; border-radius: 8px; }
.card-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #E5E7EB; }
.card-title { font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.card-title i { color: #D4212C; font-size: 15px; }
.card-body { padding: 16px; }

.field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 180px; }
.field label { font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 500; }
.field select, .field input { padding: 8px 12px; border: 1px solid #E5E7EB; border-radius: 6px; font-family: inherit; font-size: 13.5px; background: #fff; color: #111; }
.field select:focus, .field input:focus { outline: none; border-color: #D4212C; box-shadow: 0 0 0 3px rgba(212,33,44,0.08); }

table.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
table.tbl th { text-align: left; font-weight: 500; font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; padding: 10px 16px; background: #FAFAF7; border-bottom: 1px solid #E5E7EB; }
table.tbl th.num, table.tbl td.num { text-align: right; font-family: 'JetBrains Mono', monospace; }
table.tbl td { padding: 11px 16px; border-bottom: 1px solid #E5E7EB; }
table.tbl tr:hover td { background: #FAFAF7; }

.score-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 36px; padding: 2px 8px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 11.5px; font-weight: 600; }
.score-badge.hot { background: #FDECED; color: #8F1018; }
.score-badge.warm { background: #FFF7ED; color: #C2410C; }
.score-badge.cold { background: #FAFAF7; color: #6B7280; border: 1px solid #E5E7EB; }

.seg-badge { display: inline-block; padding: 2px 8px; background: #FAFAF7; border: 1px solid #E5E7EB; border-radius: 4px; font-size: 11px; color: #6B7280; font-family: 'JetBrains Mono', monospace; }

.status-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; font-family: 'JetBrains Mono', monospace; }
.status-new { background: #FAFAF7; color: #6B7280; border: 1px solid #E5E7EB; }
.status-researched { background: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE; }
.status-drafted { background: #FEF3C7; color: #92400E; border: 1px solid #FCD34D; }
.status-approved { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
.status-sent { background: #E0E7FF; color: #4338CA; border: 1px solid #A5B4FC; }
.status-replied { background: #FDECED; color: #8F1018; border: 1px solid #FCA5A5; }
.status-bounced { background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }
.status-blacklisted { background: #1C1C1C; color: #fff; }

.drawer-overlay { position: fixed; inset: 0; background: rgba(17,17,17,0.4); z-index: 100; display: flex; justify-content: flex-end; }
.drawer { width: 520px; max-width: 90vw; background: #fff; height: 100vh; overflow-y: auto; }
.drawer-head { padding: 16px 24px; border-bottom: 1px solid #E5E7EB; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; background: #fff; }
.drawer-head h2 { font-size: 18px; margin: 0; }
.close-btn { background: none; border: none; cursor: pointer; color: #6B7280; font-size: 18px; padding: 4px; }
.close-btn:hover { color: #111; }
.drawer-body { padding: 20px 24px; }
.kv { display: grid; grid-template-columns: 100px 1fr; gap: 8px 16px; font-size: 13px; }
.kv .k { color: #6B7280; text-transform: uppercase; font-size: 11px; letter-spacing: 0.8px; font-weight: 500; padding-top: 2px; }
.kv .v { color: #111; }

.drawer-actions { margin-top: 24px; padding-top: 20px; border-top: 1px solid #E5E7EB; display: flex; gap: 8px; align-items: center; }
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; font-family: inherit; }
.btn-primary { background: #D4212C; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #8F1018; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
`;
