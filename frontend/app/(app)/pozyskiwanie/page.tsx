/* Pozyskiwanie leadów - dwa tryby:
 *
 *  1) Praca ręczna (peek + select + bulk research)
 *     - /api/discovery/peek SYNC: pokazuje listę firm bez palenia tokenów
 *     - user wybiera które researchować
 *     - /api/research/bulk -> BULK_RESEARCH_LEADS job -> worker
 *     - frontend polluje /api/jobs/{id}, pokazuje progress
 *
 *  2) Wyślij agenta w teren (full async)
 *     - /api/discovery/search -> DISCOVERY_PIPELINE job (znajdź + research + draft)
 *     - frontend polluje, user moze zamknac przegladarke
 *     - agent leci do skutku
 */

'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

import { api, isAuthenticated } from '@/lib/api';

interface DiscoveredPlace {
  source: string;
  name: string;
  website: string | null;
  address: string | null;
  phone: string | null;
  rating: number | null;
  review_count: number | null;
  existing_lead_id: number | null;
  existing_lead_score: number | null;
  relevance: { score: number; reason: string } | null;
}

interface PeekResponse {
  places: DiscoveredPlace[];
  diagnostics: Array<{ source: string; places: unknown[]; error?: string; duration_s?: number }>;
  daily_used: number;
  daily_cap: number;
}

interface JobInfo {
  id: number;
  type: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
  progress: number;
  total: number;
  result: Record<string, unknown> | null;
  last_error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

const SEGMENTS = [
  'sklep_plastyczny',
  'sklep_papierniczy',
  'paint_and_sip',
  'warsztaty_dzieci',
  'animatorzy_eventy',
  'szkola_artystyczna',
  'marka_wlasna',
  'inne',
];

const SOURCES = [
  { key: 'google_places', label: 'Google Places' },
  { key: 'apify', label: 'Apify Google Maps' },
  { key: 'apify_allegro', label: 'Apify Allegro' },
  { key: 'apify_linkedin', label: 'Apify LinkedIn' },
];

type Mode = 'manual' | 'agent';

export default function PozyskiwaniePage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('manual');

  // Form
  const [segment, setSegment] = useState('sklep_papierniczy');
  const [location, setLocation] = useState('');
  const [customTarget, setCustomTarget] = useState('');
  const [maxPerSource, setMaxPerSource] = useState(50);
  const [selectedSources, setSelectedSources] = useState<string[]>(['google_places']);
  const [autoDraft, setAutoDraft] = useState(false);
  const [relevanceThreshold, setRelevanceThreshold] = useState(6);

  // Peek state (manual)
  const [peeking, setPeeking] = useState(false);
  const [peekResults, setPeekResults] = useState<DiscoveredPlace[] | null>(null);
  const [peekDiag, setPeekDiag] = useState<PeekResponse['diagnostics']>([]);
  const [peekCap, setPeekCap] = useState<{ used: number; cap: number } | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Job tracking (manual bulk research + agent mode)
  const [activeJob, setActiveJob] = useState<JobInfo | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push('/login');
      return;
    }
    // Hydrate activeJob na load - jak user wraca/refreshuje strone, a backend
    // ma juz aktywny job discovery/bulk research, odzyskujemy go zeby nie
    // pozwolic na drugi rownolegly job.
    (async () => {
      try {
        const running = await api<JobInfo[]>(
          '/api/jobs?status=running&limit=5'
        ).catch(() => [] as JobInfo[]);
        const pending = await api<JobInfo[]>(
          '/api/jobs?status=pending&limit=5'
        ).catch(() => [] as JobInfo[]);
        const found = [...running, ...pending].find(
          (j) => j.type === 'discovery_pipeline' || j.type === 'bulk_research_leads'
        );
        if (found) {
          setActiveJob(found);
          startJobPolling(found.id);
        }
      } catch {
        /* nieaktywny user - olej */
      }
    })();
  }, [router]);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  function toggleSource(key: string) {
    setSelectedSources((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  }

  function buildQuery() {
    const phrase = customTarget.trim() || segment.replace(/_/g, ' ');
    return location.trim() ? `${phrase} ${location.trim()}` : phrase;
  }

  function startJobPolling(jobId: number) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const j = await api<JobInfo>(`/api/jobs/${jobId}`);
        setActiveJob(j);
        if (j.status === 'done' || j.status === 'failed' || j.status === 'cancelled') {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch (err) {
        console.error('Poll failed:', err);
      }
    }, 2000);
  }

  async function handlePeek(e: React.FormEvent) {
    e.preventDefault();
    if (selectedSources.length === 0) {
      alert('Wybierz przynajmniej jedno źródło.');
      return;
    }
    setPeeking(true);
    setPeekResults(null);
    setSelected(new Set());
    try {
      const res = await api<PeekResponse>('/api/discovery/peek', {
        method: 'POST',
        body: JSON.stringify({
          query: buildQuery(),
          sources: selectedSources,
          max_per_source: maxPerSource,
          segment,
          location: location.trim() || null,
          custom_description: customTarget.trim() || null,
          use_relevance_filter: true,
          relevance_threshold: relevanceThreshold,
        }),
      });
      setPeekResults(res.places);
      setPeekDiag(res.diagnostics);
      setPeekCap({ used: res.daily_used, cap: res.daily_cap });

      const auto = new Set<number>();
      res.places.forEach((p, i) => {
        if (
          p.website &&
          p.existing_lead_id == null &&
          p.relevance &&
          p.relevance.score >= relevanceThreshold
        ) {
          auto.add(i);
        }
      });
      setSelected(auto);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd wyszukiwania');
    } finally {
      setPeeking(false);
    }
  }

  async function handleResearchSelected() {
    if (!peekResults || selected.size === 0) return;
    const urls = Array.from(selected)
      .map((i) => peekResults[i]?.website)
      .filter((w): w is string => !!w);
    if (urls.length === 0) return;

    setSubmitting(true);
    try {
      const res = await api<{ job_id: number; total: number }>('/api/research/bulk', {
        method: 'POST',
        body: JSON.stringify({
          urls,
          segment_hint: segment,
          city_hint: location || null,
          auto_draft_threshold: autoDraft ? 7 : null,
        }),
      });
      setActiveJob({
        id: res.job_id, type: 'bulk_research_leads',
        status: 'pending', progress: 0, total: res.total,
        result: null, last_error: null,
        created_at: new Date().toISOString(),
        started_at: null, completed_at: null,
      });
      startJobPolling(res.job_id);
    } catch (err) {
      await handleJobConflict(err, 'Błąd uruchomienia researchu');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleJobConflict(err: unknown, fallbackMsg: string) {
    const e = err as Error & { status?: number; detail?: { active_job_id?: number; msg?: string } };
    if (e.status === 409 && e.detail?.active_job_id) {
      const msg = e.detail.msg || fallbackMsg;
      alert(`${msg}\n\nPokażę aktualnie pracującego agenta.`);
      try {
        const job = await api<JobInfo>(`/api/jobs/${e.detail.active_job_id}`);
        setActiveJob(job);
        if (job.status === 'pending' || job.status === 'running') {
          startJobPolling(job.id);
        }
      } catch {/* ignore */}
      return;
    }
    alert(e.message || fallbackMsg);
  }

  async function handleSendAgent(e: React.FormEvent) {
    e.preventDefault();
    if (selectedSources.length === 0) {
      alert('Wybierz przynajmniej jedno źródło.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await api<{ job_id: number; daily_used: number; daily_cap: number }>(
        '/api/discovery/search', {
        method: 'POST',
        body: JSON.stringify({
          query: buildQuery(),
          sources: selectedSources,
          max_per_source: maxPerSource,
          segment,
          location: location.trim() || null,
          custom_description: customTarget.trim() || null,
          use_relevance_filter: true,
          relevance_threshold: relevanceThreshold,
          auto_research: true,
          auto_draft_threshold: autoDraft ? 7 : null,
        }),
      });
      setActiveJob({
        id: res.job_id, type: 'discovery_pipeline',
        status: 'pending', progress: 0, total: 0,
        result: null, last_error: null,
        created_at: new Date().toISOString(),
        started_at: null, completed_at: null,
      });
      startJobPolling(res.job_id);
    } catch (err) {
      await handleJobConflict(err, 'Błąd uruchomienia agenta');
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelJob() {
    if (!activeJob) return;
    try {
      await api(`/api/jobs/${activeJob.id}/cancel`, { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
  }

  function clearJob() {
    setActiveJob(null);
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }

  const jobActive = activeJob && (activeJob.status === 'pending' || activeJob.status === 'running');

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="topbar">
        <div className="crumb">
          <strong>Handlowiec</strong>
          <i className="ti ti-chevron-right" /> Pozyskiwanie
        </div>
        {peekCap && (
          <div className="cap-pill">
            <i className="ti ti-bolt" /> {peekCap.used} / {peekCap.cap} dziś
          </div>
        )}
      </div>

      <div className="content">
        <div className="page-head">
          <div>
            <h1>Pozyskiwanie leadów</h1>
            <p>Wybierz tryb i zacznij szukać. Praca leci w tle - możesz wylogować się.</p>
          </div>
        </div>

        {/* MODE TOGGLE */}
        <div className="mode-tabs">
          <button
            className={`mode-tab ${mode === 'manual' ? 'active' : ''}`}
            onClick={() => setMode('manual')}>
            <div className="mode-tab-icon"><i className="ti ti-hand-click" /></div>
            <div className="mode-tab-text">
              <div className="mode-tab-name">Praca ręczna</div>
              <div className="mode-tab-desc">Zobacz listę, wybierz co researchować. Nie pali tokenów dopóki nie klikniesz.</div>
            </div>
          </button>
          <button
            className={`mode-tab ${mode === 'agent' ? 'active' : ''}`}
            onClick={() => setMode('agent')}>
            <div className="mode-tab-icon"><i className="ti ti-truck-delivery" /></div>
            <div className="mode-tab-text">
              <div className="mode-tab-name">Wyślij agenta w teren</div>
              <div className="mode-tab-desc">Agent sam znajdzie, zrobi research, wygeneruje drafty. Możesz wyjść.</div>
            </div>
          </button>
        </div>

        {/* JOB PROGRESS */}
        {activeJob && (
          <div className="job-card">
            <div className="job-head">
              <div className="job-title">
                <i className={`ti ti-${jobActive ? 'loader-2 spin' : activeJob.status === 'done' ? 'check' : 'x'}`} />
                {jobActive ? 'Agent pracuje...' :
                 activeJob.status === 'done' ? 'Gotowe!' :
                 activeJob.status === 'failed' ? 'Job padł' : 'Anulowano'}
              </div>
              <div className="job-actions">
                {jobActive ? (
                  <button className="btn-ghost" onClick={cancelJob}>
                    <i className="ti ti-x" /> Anuluj
                  </button>
                ) : (
                  <button className="btn-ghost" onClick={clearJob}>
                    <i className="ti ti-x" /> Zamknij
                  </button>
                )}
              </div>
            </div>
            {activeJob.total > 0 && (
              <>
                <div className="progress-bar">
                  <div style={{ width: `${(activeJob.progress / Math.max(activeJob.total, 1)) * 100}%` }} />
                </div>
                <div className="progress-meta">
                  <span>{activeJob.progress} / {activeJob.total} przerobione</span>
                  <span className="mono">job #{activeJob.id}</span>
                </div>
              </>
            )}
            {!activeJob.total && jobActive && (
              <div className="progress-meta">
                <span>Agent znajduje miejsca...</span>
                <span className="mono">job #{activeJob.id}</span>
              </div>
            )}
            {/* LIVE TICKER - lista ostatnio przetworzonych leadow */}
            {(() => {
              const recent = (activeJob.result as { recent?: Array<{
                name?: string; url?: string; status?: string; score?: number;
                lead_id?: number; drafted?: boolean; error?: string;
              }> } | null)?.recent;
              if (!recent || recent.length === 0) return null;
              return (
                <div className="live-ticker">
                  <div className="live-ticker-head">
                    <i className="ti ti-activity" /> Ostatnio przetworzone
                  </div>
                  <div className="live-ticker-list">
                    {[...recent].reverse().map((r, i) => (
                      <div className={`lt-row lt-${r.status || 'pending'}`} key={i}>
                        <span className="lt-icon">
                          {r.status === 'researched' && <i className="ti ti-check" />}
                          {r.status === 'duplicate' && <i className="ti ti-copy" />}
                          {r.status === 'failed' && <i className="ti ti-alert-triangle" />}
                        </span>
                        <span className="lt-name" title={r.url}>{r.name || r.url}</span>
                        {r.score != null && (
                          <span className="lt-score mono">{r.score}/10</span>
                        )}
                        {r.drafted && <span className="lt-tag">draft</span>}
                        {r.status === 'duplicate' && <span className="lt-tag muted">dup</span>}
                        {r.status === 'failed' && (
                          <span className="lt-tag err" title={r.error}>błąd</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
            {activeJob.status === 'done' && activeJob.result && (
              <div className="job-result">
                <JobResult result={activeJob.result} />
                <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                  <Link href="/leady" className="btn btn-primary">
                    <i className="ti ti-users" /> Zobacz leady
                  </Link>
                  <Link href="/drafty" className="btn btn-ghost">
                    <i className="ti ti-mail" /> Drafty
                  </Link>
                </div>
              </div>
            )}
            {activeJob.status === 'failed' && (
              <div className="job-error">
                <strong>Błąd:</strong> {activeJob.last_error || 'Nieznany błąd'}
              </div>
            )}
          </div>
        )}

        {/* SEARCH FORM */}
        <div className="card">
          <div className="card-head">
            <div className="card-title">
              <i className="ti ti-search" />
              {mode === 'manual' ? 'Zajrzyj na rynek' : 'Patrol agenta'}
            </div>
            <div className="card-actions">
              {peekCap && peekCap.used >= peekCap.cap && (
                <span style={{ color: '#8F1018' }}>
                  <i className="ti ti-alert-triangle" /> Dzienny limit wyczerpany
                </span>
              )}
            </div>
          </div>
          <form onSubmit={mode === 'manual' ? handlePeek : handleSendAgent} className="card-body">
            <div className="form-row">
              <div className="field">
                <label>Segment</label>
                <select value={segment} onChange={(e) => setSegment(e.target.value)}>
                  {SEGMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Lokalizacja (miasto / województwo)</label>
                <input type="text" value={location} onChange={(e) => setLocation(e.target.value)}
                  placeholder="np. Warszawa, Pomorskie" />
              </div>
              <div className="field" style={{ maxWidth: 200 }}>
                <label>Max / źródło (1-100)</label>
                <input type="number" value={maxPerSource} min={1} max={100}
                  onChange={(e) => setMaxPerSource(parseInt(e.target.value) || 50)} />
                <span style={{ fontSize: 11, color: '#6B7280', marginTop: 4, display: 'block' }}>
                  Twarde limity API: Google Places 60, Apify Maps 50, Allegro 100, LinkedIn 50. Włącz kilka źródeł żeby zwiększyć pulę.
                </span>
              </div>
            </div>

            <div className="field">
              <label>Własny opis targetu (opcjonalny, ma pierwszeństwo nad segmentem)</label>
              <textarea value={customTarget} onChange={(e) => setCustomTarget(e.target.value)}
                placeholder="np. 'producenci sztalug i ram do obrazów'"
                rows={2} />
            </div>

            <div className="field">
              <label>Źródła</label>
              <div className="checkbox-row">
                {SOURCES.map((s) => (
                  <label key={s.key} className="check">
                    <input type="checkbox" checked={selectedSources.includes(s.key)}
                      onChange={() => toggleSource(s.key)} />
                    <span>{s.label}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="form-row">
              <label className="check">
                <input type="checkbox" checked={autoDraft}
                  onChange={(e) => setAutoDraft(e.target.checked)} />
                <span><i className="ti ti-mail" /> Auto-draft jeśli score &ge; 7</span>
              </label>
              <div className="field" style={{ maxWidth: 240 }}>
                <label>Próg trafności LLM &ge; {relevanceThreshold}</label>
                <input type="range" min={0} max={10} value={relevanceThreshold}
                  onChange={(e) => setRelevanceThreshold(parseInt(e.target.value))} />
              </div>
            </div>

            <button type="submit" className="btn btn-primary"
              disabled={peeking || submitting || !!jobActive}>
              {mode === 'manual'
                ? (peeking ? 'Szukam...' : 'Zajrzyj na rynek')
                : (submitting ? 'Wysyłam agenta...' : 'Wyślij agenta w teren')}
            </button>
          </form>
        </div>

        {/* PEEK DIAGNOSTICS */}
        {peekDiag.length > 0 && mode === 'manual' && (
          <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            {peekDiag.map((d) => (
              <div key={d.source} className={`diag-pill ${d.error ? 'err' : ''}`}>
                <strong>{d.source}</strong>: {d.error || `${(d.places as unknown[]).length} firm · ${d.duration_s}s`}
              </div>
            ))}
          </div>
        )}

        {/* PEEK RESULTS TABLE */}
        {mode === 'manual' && peekResults && (
          <div className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <div className="card-title">
                <i className="ti ti-list" /> Wyniki ({peekResults.length})
                {peekResults.some((r) => r.existing_lead_id) && (
                  <span style={{ fontSize: 12, color: '#6B7280', marginLeft: 8 }}>
                    · {peekResults.filter((r) => r.existing_lead_id).length} już w bazie
                  </span>
                )}
              </div>
              <div className="card-actions">
                <span style={{ fontSize: 12 }}>Zaznaczonych: {selected.size}</span>
                <button className="btn btn-primary"
                  disabled={submitting || selected.size === 0 || !!jobActive}
                  onClick={handleResearchSelected}>
                  {submitting ? 'Tworzę job...' : `Researchuj ${selected.size} →`}
                </button>
              </div>
            </div>
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 30 }}></th>
                  <th>Firma</th>
                  <th>Adres</th>
                  <th className="num">Ocena</th>
                  <th className="num">Trafność</th>
                  <th>Powód</th>
                  <th>WWW</th>
                </tr>
              </thead>
              <tbody>
                {peekResults.map((p, i) => {
                  const dup = p.existing_lead_id != null;
                  const rel = p.relevance;
                  return (
                    <tr key={`${p.source}-${i}`} style={{ opacity: dup ? 0.5 : 1 }}>
                      <td>
                        <input type="checkbox" checked={selected.has(i)}
                          disabled={!p.website || dup}
                          onChange={() => {
                            const s = new Set(selected);
                            if (s.has(i)) s.delete(i); else s.add(i);
                            setSelected(s);
                          }} />
                      </td>
                      <td>
                        <strong>{p.name}</strong>
                        {dup && <span style={{ color: '#6B7280', fontSize: 11 }}> · w bazie #{p.existing_lead_id}</span>}
                      </td>
                      <td style={{ color: '#6B7280' }}>{p.address || '-'}</td>
                      <td className="num">{p.rating?.toFixed(1) || '-'}</td>
                      <td className="num">
                        {rel ? (
                          <span className={`rel-pill ${rel.score >= 7 ? 'hot' : rel.score >= 5 ? 'warm' : 'cold'}`}>
                            {rel.score}
                          </span>
                        ) : '-'}
                      </td>
                      <td style={{ color: '#6B7280', fontSize: 12 }}>{rel?.reason || ''}</td>
                      <td>
                        {p.website ? (
                          <a href={p.website} target="_blank" rel="noopener" style={{ color: '#D4212C', fontSize: 12 }}>
                            {p.website.replace(/^https?:\/\//, '').slice(0, 28)}...
                          </a>
                        ) : '-'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* AGENT MODE EXPLAINER (no results yet) */}
        {mode === 'agent' && !activeJob && (
          <div className="explainer">
            <div className="explainer-head">
              <i className="ti ti-info-circle" /> Jak działa patrol agenta
            </div>
            <ol className="explainer-list">
              <li>Klikasz "Wyślij agenta w teren" - powstaje zadanie w kolejce.</li>
              <li>Worker (osobny serwer) zaczyna pracę: znajduje firmy w wybranych źródłach.</li>
              <li>LLM filtruje trafność (próg &ge; {relevanceThreshold}) - odpada szum z Google Maps.</li>
              <li>Dla każdej trafnej firmy: scraping strony + research LLM + scoring 0-10.</li>
              <li>{autoDraft ? 'Score ≥ 7 → wygenerowany draft maila gotowy do approve.' : 'Drafty NIE są generowane (włącz checkbox jeśli chcesz).'}</li>
              <li>Możesz wylogować się / zamknąć przeglądarkę. Patrol leci do końca.</li>
            </ol>
          </div>
        )}
      </div>
    </>
  );
}

function JobResult({ result }: { result: Record<string, unknown> }) {
  const items: Array<[string, string | number]> = [];
  for (const [k, v] of Object.entries(result)) {
    if (typeof v === 'number' || typeof v === 'string') items.push([k, v]);
  }
  const labels: Record<string, string> = {
    places_found: 'Firm znalezionych',
    targets_matching: 'Trafnych',
    researched: 'Zresearchowanych',
    drafted: 'Draftów',
    duplicates: 'Już w bazie',
    failed: 'Błędów',
    total: 'Łącznie',
  };
  return (
    <div className="result-grid">
      {items.map(([k, v]) => (
        <div className="result-item" key={k}>
          <div className="result-value tabular">{v}</div>
          <div className="result-label">{labels[k] || k}</div>
        </div>
      ))}
    </div>
  );
}

const CSS = `
.topbar { background: #fff; border-bottom: 1px solid #E5E7EB; padding: 0 24px; display: flex; align-items: center; height: 52px; gap: 16px; position: sticky; top: 0; z-index: 10; }
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #6B7280; }
.crumb strong { color: #111; font-weight: 500; }
.crumb i { font-size: 12px; color: #9CA3AF; }
.cap-pill {
  margin-left: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11.5px;
  color: #6B7280;
  background: #FAFAF7;
  border: 1px solid #E5E7EB;
  padding: 5px 10px;
  border-radius: 6px;
  display: flex; align-items: center; gap: 6px;
}
.cap-pill i { color: #D4212C; font-size: 13px; }

.content { padding: 24px; max-width: 1320px; }
.page-head { margin-bottom: 20px; }
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-head p { color: #6B7280; font-size: 13.5px; margin: 0; }

.mode-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 20px;
}
.mode-tab {
  background: #fff;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  gap: 14px;
  align-items: flex-start;
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition: all 0.15s;
}
.mode-tab:hover { border-color: #D1D5DB; }
.mode-tab.active {
  border-color: rgba(212,33,44,0.5);
  background: rgba(212,33,44,0.03);
  box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}
.mode-tab-icon {
  width: 40px; height: 40px;
  background: #FAFAF7;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: #6B7280;
  flex-shrink: 0;
}
.mode-tab.active .mode-tab-icon {
  background: rgba(212,33,44,0.1);
  border-color: rgba(212,33,44,0.2);
  color: #D4212C;
}
.mode-tab-icon i { font-size: 20px; }
.mode-tab-text { flex: 1; }
.mode-tab-name { font-size: 14px; font-weight: 600; margin-bottom: 3px; color: #111; }
.mode-tab-desc { font-size: 12px; color: #6B7280; line-height: 1.4; }

.job-card {
  background: #fff;
  border: 1px solid rgba(212,33,44,0.3);
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 16px;
  box-shadow: 0 4px 16px -8px rgba(212,33,44,0.2);
}
.job-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.job-title {
  font-size: 14px;
  font-weight: 600;
  display: flex; align-items: center; gap: 8px;
  color: #111;
}
.job-title i { color: #D4212C; font-size: 18px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.job-actions { display: flex; gap: 8px; }

.progress-bar {
  height: 8px;
  background: #FAFAF7;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}
.progress-bar > div {
  height: 100%;
  background: linear-gradient(90deg, #D4212C, #8F1018);
  transition: width 0.3s;
}
.progress-meta {
  display: flex; justify-content: space-between;
  font-size: 12px; color: #6B7280;
}
.progress-meta .mono { font-family: 'JetBrains Mono', monospace; }

.live-ticker {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #E5E7EB;
}
.live-ticker-head {
  font-size: 11.5px;
  font-weight: 600;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.live-ticker-head i { color: #D4212C; font-size: 13px; }
.live-ticker-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 280px;
  overflow-y: auto;
}
.lt-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #FAFAF7;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  font-size: 12.5px;
  animation: lt-slidein 0.25s ease-out;
}
@keyframes lt-slidein {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.lt-row.lt-researched { border-left: 3px solid #16A34A; }
.lt-row.lt-duplicate { border-left: 3px solid #9CA3AF; opacity: 0.75; }
.lt-row.lt-failed { border-left: 3px solid #D4212C; }
.lt-icon { width: 16px; display: flex; align-items: center; }
.lt-row.lt-researched .lt-icon i { color: #16A34A; }
.lt-row.lt-duplicate .lt-icon i { color: #6B7280; }
.lt-row.lt-failed .lt-icon i { color: #D4212C; }
.lt-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #1F2937;
  font-weight: 500;
}
.lt-score {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #6B7280;
  background: white;
  border: 1px solid #E5E7EB;
  padding: 1px 6px;
  border-radius: 3px;
}
.lt-tag {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: 'JetBrains Mono', monospace;
  background: rgba(212,33,44,0.1);
  color: #8F1018;
  border: 1px solid rgba(212,33,44,0.2);
}
.lt-tag.muted { background: #F3F4F6; color: #6B7280; border-color: #E5E7EB; }
.lt-tag.err { background: rgba(212,33,44,0.15); color: #8F1018; }

.job-result { margin-top: 14px; padding-top: 14px; border-top: 1px solid #E5E7EB; }
.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: 12px;
}
.result-item {
  background: #FAFAF7;
  border: 1px solid #E5E7EB;
  border-radius: 6px;
  padding: 10px 12px;
  text-align: center;
}
.result-value {
  font-size: 20px;
  font-weight: 700;
  color: #111;
  letter-spacing: -0.3px;
}
.result-label {
  font-size: 10.5px;
  color: #6B7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 2px;
}
.tabular { font-feature-settings: "tnum"; font-variant-numeric: tabular-nums; }

.job-error {
  margin-top: 12px;
  padding: 10px 12px;
  background: #FDECED;
  border: 1px solid rgba(212,33,44,0.2);
  border-radius: 6px;
  font-size: 13px;
  color: #8F1018;
}

.card { background: #fff; border: 1px solid #E5E7EB; border-radius: 10px; margin-bottom: 12px; }
.card-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #E5E7EB; }
.card-title { font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.card-title i { color: #D4212C; font-size: 15px; }
.card-actions { display: flex; gap: 12px; align-items: center; font-size: 12px; color: #6B7280; }
.card-body { padding: 16px; }

.form-row { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; align-items: flex-end; }
.field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 200px; }
.field label { font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 500; }
.field input, .field select, .field textarea {
  padding: 8px 12px; border: 1px solid #E5E7EB; border-radius: 6px; font-family: inherit; font-size: 13.5px;
  background: #fff; color: #111;
}
.field input:focus, .field select:focus, .field textarea:focus {
  outline: none; border-color: #D4212C; box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}
.field textarea { resize: vertical; min-height: 50px; }
.field input[type=range] { padding: 0; height: 28px; }

.checkbox-row { display: flex; gap: 16px; flex-wrap: wrap; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #111; cursor: pointer; }
.check input { margin: 0; cursor: pointer; }
.check i { font-size: 14px; color: #6B7280; margin-right: 2px; }

.btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; font-family: inherit; text-decoration: none; }
.btn-primary { background: #D4212C; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #8F1018; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost {
  background: transparent;
  color: #6B7280;
  border: 1px solid #E5E7EB;
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  font-family: inherit;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn-ghost:hover { color: #111; border-color: #D1D5DB; }

.diag-pill {
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  background: #FDECED;
  color: #8F1018;
  border: 1px solid rgba(212,33,44,0.15);
}
.diag-pill.err { background: #fef2f2; border-color: #fecaca; }

table.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
table.tbl th { text-align: left; font-weight: 500; font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; padding: 10px 16px; background: #FAFAF7; border-bottom: 1px solid #E5E7EB; }
table.tbl th.num, table.tbl td.num { text-align: right; font-family: 'JetBrains Mono', monospace; }
table.tbl td { padding: 11px 16px; border-bottom: 1px solid #E5E7EB; }
table.tbl tr:last-child td { border-bottom: none; }
table.tbl tr:hover td { background: #FAFAF7; }

.rel-pill {
  display: inline-block;
  min-width: 26px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  text-align: center;
}
.rel-pill.hot { background: rgba(212,33,44,0.15); color: #8F1018; }
.rel-pill.warm { background: #FEF3C7; color: #92400E; }
.rel-pill.cold { background: #F3F4F6; color: #6B7280; }

.explainer {
  background: #fff;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 18px 20px;
}
.explainer-head {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 12px;
  color: #111;
  display: flex; align-items: center; gap: 8px;
}
.explainer-head i { color: #D4212C; font-size: 16px; }
.explainer-list {
  padding-left: 20px;
  font-size: 13px;
  color: #374151;
  line-height: 1.7;
}
.explainer-list li { margin-bottom: 4px; }
`;
