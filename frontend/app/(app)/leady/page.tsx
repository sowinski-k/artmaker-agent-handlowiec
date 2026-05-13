'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

import { api, isAuthenticated } from '@/lib/api';

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
  drafts_count: number;
  latest_draft_status: string | null;
}

interface DraftLite {
  id: number;
  subject: string | null;
  status: string;
  template_variant: string | null;
  edited_by_user: boolean;
  created_at: string | null;
  sent_at: string | null;
}

interface EventLite {
  id: number;
  type: string;
  level: string;
  source: string | null;
  message: string;
  created_at: string | null;
}

interface ActiveJobLite {
  id: number;
  type: string;
  status: string;
  progress: number;
  total: number;
  created_at: string | null;
}

interface LeadDetail extends LeadRow {
  instagram: string | null;
  country: string;
  research_data: Record<string, unknown> | null;
  notes: string | null;
  updated_at: string | null;
  drafts: DraftLite[];
  events: EventLite[];
  active_jobs: ActiveJobLite[];
}

interface LeadsResponse {
  total: number;
  items: LeadRow[];
}

const STATUSES = ['', 'new', 'researched', 'drafted', 'approved', 'sent', 'replied', 'bounced', 'blacklisted'];
const SEGMENTS = ['', 'sklep_plastyczny', 'sklep_papierniczy', 'paint_and_sip', 'warsztaty_dzieci',
  'animatorzy_eventy', 'szkola_artystyczna', 'marka_wlasna', 'inne'];

const SORTS: Array<{ value: string; label: string }> = [
  { value: 'score', label: 'Najwyższy score' },
  { value: 'newest', label: 'Najnowsze' },
  { value: 'oldest', label: 'Najstarsze' },
  { value: 'company', label: 'Alfabetycznie' },
];

type DraftFlash = { kind: 'success' | 'error' | 'info'; text: string; draftId?: number };
type GlobalFlash = { kind: 'success' | 'error' | 'info'; text: string };

export default function LeadyPage() {
  const router = useRouter();
  const [leads, setLeads] = useState<LeadRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [segment, setSegment] = useState('');
  const [status, setStatus] = useState('');
  const [minScore, setMinScore] = useState(0);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [sort, setSort] = useState('score');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  // Bulk selection
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  // Globalny flash (toast) - zamiast alert
  const [flash, setFlash] = useState<GlobalFlash | null>(null);
  // Draft generation state - w drawerze, nie native alert
  const [draftJobId, setDraftJobId] = useState<number | null>(null);
  const [draftJobStatus, setDraftJobStatus] = useState<string | null>(null);
  const [draftFlash, setDraftFlash] = useState<DraftFlash | null>(null);
  // Ref do anulowania pollingu jak user zmienia drawer / unmount
  const pollAbortRef = useRef<{ cancelled: boolean } | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) router.push('/login');
  }, [router]);

  // Debounce searchInput -> search (300ms) zeby nie spamowac backendu
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Auto-dismiss flash po 5s
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

  async function load() {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '100', sort });
      if (segment) params.set('segment', segment);
      if (status) params.set('status', status);
      if (minScore > 0) params.set('min_score', String(minScore));
      if (search.trim()) params.set('q', search.trim());
      const res = await api<LeadsResponse>(`/api/leads?${params}`);
      setLeads(res.items);
      setTotal(res.total);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); /* eslint-disable-next-line */ }, [segment, status, minScore, search, sort]);

  // Bulk selection helpers
  const eligibleForBulk = leads.filter(
    (l) => l.status === 'researched' && l.email && (l.drafts_count === 0 || l.latest_draft_status === 'rejected')
  );
  const allEligibleSelected = eligibleForBulk.length > 0
    && eligibleForBulk.every((l) => selectedIds.has(l.id));

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }
  function toggleSelectAll() {
    if (allEligibleSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(eligibleForBulk.map((l) => l.id)));
    }
  }
  function clearSelection() {
    setSelectedIds(new Set());
  }

  async function bulkGenerateDrafts() {
    if (selectedIds.size === 0) return;
    const ids = Array.from(selectedIds);
    setBulkSubmitting(true);
    try {
      const res = await api<{
        ok: boolean; requested: number; queued: number;
        skipped_not_researched: number; skipped_already_has_draft: number;
        job_ids: number[];
      }>('/api/drafts/bulk', {
        method: 'POST',
        body: JSON.stringify({ lead_ids: ids }),
      });
      setFlash({
        kind: 'success',
        text: `Zlecone: ${res.queued} draftów. Pominięte: ${res.skipped_already_has_draft} z istniejącym draftem, ${res.skipped_not_researched} nie-researched. Worker generuje w tle.`,
      });
      clearSelection();
      // Refresh listy po 1.5s zeby zlapac nowe draft counts
      setTimeout(() => void load(), 1500);
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd' });
    } finally {
      setBulkSubmitting(false);
    }
  }

  async function refreshDetail(id: number) {
    try {
      const d = await api<LeadDetail>(`/api/leads/${id}`);
      setDetail(d);
      // Wykryj aktywny generate_draft job - jak jest, polluj dla statusu
      const activeDraftJob = d.active_jobs.find((j) => j.type === 'generate_draft');
      if (activeDraftJob && draftJobId !== activeDraftJob.id) {
        setDraftJobId(activeDraftJob.id);
        setDraftJobStatus(activeDraftJob.status);
        void pollDraftJob(activeDraftJob.id, id);
      }
    } catch (err) {
      console.error(err);
    }
  }

  async function openDetail(id: number) {
    // Reset draft state przy zmianie leada
    if (pollAbortRef.current) pollAbortRef.current.cancelled = true;
    setDraftFlash(null);
    setDraftJobId(null);
    setDraftJobStatus(null);
    setSelectedId(id);
    setDetail(null);
    await refreshDetail(id);
  }

  /**
   * Polling job statusu w tle. Aktualizuje drawer (refreshDetail) gdy
   * job zmienia state. User moze zamknac okno - polling zostanie anulowany,
   * ale BACKEND nadal pracuje (Worker process). Po powrocie userowi
   * drawer od nowa wykryje active_job albo gotowy draft.
   */
  async function pollDraftJob(jobId: number, leadId: number) {
    const ctrl = { cancelled: false };
    pollAbortRef.current = ctrl;
    const maxWaitMs = 120_000;
    const start = Date.now();
    while (!ctrl.cancelled && Date.now() - start < maxWaitMs) {
      await new Promise((r) => setTimeout(r, 2000));
      if (ctrl.cancelled) return;
      try {
        const job = await api<{ status: string; result: { draft_id?: number } | null; last_error?: string }>(
          `/api/jobs/${jobId}`
        );
        setDraftJobStatus(job.status);
        if (job.status === 'done') {
          const draftId = job.result?.draft_id;
          setDraftFlash({
            kind: 'success',
            text: 'Draft wygenerowany - kliknij zeby otworzyc.',
            draftId,
          });
          setDraftJobId(null);
          // Auto-refresh: drawer + tabela
          await refreshDetail(leadId);
          await load();
          return;
        }
        if (job.status === 'failed' || job.status === 'cancelled') {
          setDraftFlash({
            kind: 'error',
            text: `Generacja nieudana (${job.status}): ${job.last_error || 'unknown'}`,
          });
          setDraftJobId(null);
          return;
        }
      } catch {
        /* network glitch - probuj dalej */
      }
    }
  }

  async function generateDraft(leadId: number) {
    setDraftFlash(null);
    try {
      const res = await api<{ ok: boolean; job_id: number }>('/api/drafts', {
        method: 'POST',
        body: JSON.stringify({ lead_id: leadId }),
      });
      setDraftJobId(res.job_id);
      setDraftJobStatus('pending');
      setDraftFlash({ kind: 'info', text: 'Draft zlecony - agent pracuje w tle. Mozesz zamknac okno.' });
      void pollDraftJob(res.job_id, leadId);
    } catch (err) {
      setDraftFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udalo sie zlecic generacji',
      });
    }
  }

  // Cleanup polling przy odmontowaniu komponentu (np. nawigacja)
  useEffect(() => {
    return () => {
      if (pollAbortRef.current) pollAbortRef.current.cancelled = true;
    };
  }, []);

  function formatTimeAgo(iso: string): string {
    const t = new Date(iso).getTime();
    const diff = Math.max(0, Date.now() - t);
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return `${sec}s temu`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min} min temu`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h temu`;
    const day = Math.floor(hr / 24);
    if (day < 30) return `${day} dni temu`;
    return new Date(iso).toLocaleDateString('pl-PL');
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

      {/* Globalny flash */}
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
          <div>
            <h1>Leady</h1>
            <p>
              {total} {total === 1 ? 'firma' : total < 5 ? 'firmy' : 'firm'} w bazie
              {search.trim() && ` · filtr: "${search.trim()}"`}
            </p>
          </div>
          <a href="/pozyskiwanie" className="btn btn-secondary">
            <i className="ti ti-search" /> Znajdź nowe leady
          </a>
        </div>

        {/* Toolbar: search + filtry + sort - wszystko w jednym pasku */}
        <div className="toolbar">
          <div className="search-box">
            <i className="ti ti-search" />
            <input
              type="search"
              placeholder="Szukaj po nazwie firmy, kontakcie lub emailu..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
            {searchInput && (
              <button className="search-clear" onClick={() => setSearchInput('')} title="Wyczyść">
                <i className="ti ti-x" />
              </button>
            )}
          </div>

          <div className="toolbar-filters">
            <select className="tb-select" value={segment} onChange={(e) => setSegment(e.target.value)}>
              {SEGMENTS.map((s) => <option key={s} value={s}>{s ? `Segment: ${s}` : 'Wszystkie segmenty'}</option>)}
            </select>
            <select className="tb-select" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => <option key={s} value={s}>{s ? `Status: ${s}` : 'Wszystkie statusy'}</option>)}
            </select>
            <select className="tb-select" value={sort} onChange={(e) => setSort(e.target.value)}>
              {SORTS.map((s) => <option key={s.value} value={s.value}>Sortuj: {s.label}</option>)}
            </select>
            <div className="tb-score">
              <label>Min score: <strong>{minScore.toFixed(1)}</strong></label>
              <input type="range" min={0} max={10} step={0.5} value={minScore}
                onChange={(e) => setMinScore(parseFloat(e.target.value))} />
            </div>
          </div>
        </div>

        {/* Bulk action bar - widoczny tylko gdy cos zaznaczone */}
        {selectedIds.size > 0 && (
          <div className="bulk-bar">
            <div className="bulk-info">
              <i className="ti ti-checkbox" />
              <strong>{selectedIds.size}</strong> zaznaczone
            </div>
            <button className="btn btn-ghost btn-sm" onClick={clearSelection}>
              Wyczyść
            </button>
            <button
              className="btn btn-primary btn-sm"
              onClick={bulkGenerateDrafts}
              disabled={bulkSubmitting}
            >
              <i className="ti ti-mail-plus" />
              {bulkSubmitting ? 'Zlecam...' : `Generuj drafty (${selectedIds.size})`}
            </button>
          </div>
        )}

        <div className="card" style={{ marginTop: 12 }}>
          <div className="card-head">
            <div className="card-title">
              <i className="ti ti-users" /> Wyniki ({leads.length}{total > leads.length ? ` z ${total}` : ''})
            </div>
            {eligibleForBulk.length > 0 && (
              <button
                className="btn-link-sm"
                onClick={toggleSelectAll}
                title="Zaznacz wszystkie researched z emailem bez aktywnego draftu"
              >
                {allEligibleSelected ? 'Odznacz wszystkie' : `Zaznacz wszystkie researched (${eligibleForBulk.length})`}
              </button>
            )}
          </div>
          {loading ? (
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 40 }}></th>
                  <th className="num">Score</th>
                  <th>Firma</th>
                  <th>Segment</th>
                  <th>Miasto</th>
                  <th>Email</th>
                  <th>Status</th>
                  <th>Drafty</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td><span className="skel" style={{ width: 16, height: 16, borderRadius: 3 }} /></td>
                    <td className="num"><span className="skel skel-pill" /></td>
                    <td><span className="skel skel-line skel-w-140" /></td>
                    <td><span className="skel skel-pill" /></td>
                    <td><span className="skel skel-line skel-w-60" /></td>
                    <td><span className="skel skel-line skel-w-200" /></td>
                    <td><span className="skel skel-pill" /></td>
                    <td><span className="skel skel-line skel-w-30" /></td>
                    <td><span className="skel skel-line skel-w-30" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : leads.length === 0 ? (
            <div className="empty-state">
              <i className="ti ti-users-off" />
              <h3>{search.trim() ? 'Nic nie znaleziono' : 'Brak leadów'}</h3>
              <p>
                {search.trim()
                  ? `Spróbuj innego zapytania albo zresetuj filtry.`
                  : <>Idź do <a href="/pozyskiwanie">Pozyskiwanie</a> żeby znaleźć pierwsze leady, albo poczekaj na Patrol AI.</>
                }
              </p>
            </div>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 40 }}>
                    {eligibleForBulk.length > 0 && (
                      <input
                        type="checkbox"
                        checked={allEligibleSelected}
                        onChange={toggleSelectAll}
                        title="Zaznacz wszystkie kwalifikujące się"
                      />
                    )}
                  </th>
                  <th className="num">Score</th>
                  <th>Firma</th>
                  <th>Segment</th>
                  <th>Miasto</th>
                  <th>Email</th>
                  <th>Status</th>
                  <th>Drafty</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {leads.map((l) => {
                  const isHot = l.score != null && l.score >= 8;
                  const isEligible = l.status === 'researched' && l.email
                    && (l.drafts_count === 0 || l.latest_draft_status === 'rejected');
                  const isSelected = selectedIds.has(l.id);
                  return (
                    <tr
                      key={l.id}
                      className={`${isHot ? 'row-hot' : ''} ${isSelected ? 'row-selected' : ''}`}
                      onClick={(e) => {
                        // Klik w checkbox = toggle. Klik gdzie indziej = open drawer.
                        const target = e.target as HTMLElement;
                        if (target.tagName === 'INPUT' || target.closest('.row-check')) return;
                        openDetail(l.id);
                      }}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className="row-check">
                        {isEligible ? (
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(l.id)}
                          />
                        ) : (
                          <span title="Tylko researched z emailem (bez aktywnego draftu)" style={{ opacity: 0.3 }}>
                            <i className="ti ti-square" />
                          </span>
                        )}
                      </td>
                      <td className="num">{scoreBadge(l.score)}</td>
                      <td>
                        <strong>{l.company_name}</strong>
                        {l.contact_name && <div className="contact-sub">{l.contact_name}</div>}
                      </td>
                      <td><span className="seg-badge">{l.segment}</span></td>
                      <td className="muted">{l.city || '-'}</td>
                      <td className="email-cell">{l.email || <span className="muted">brak</span>}</td>
                      <td><span className={`status-badge status-${l.status}`}>{l.status}</span></td>
                      <td>
                        {l.drafts_count > 0 ? (
                          <span className="drafts-cell" title={`Najnowszy: ${l.latest_draft_status}`}>
                            <i className="ti ti-mail" />
                            <strong>{l.drafts_count}</strong>
                            {l.latest_draft_status && (
                              <span className={`status-mini status-${l.latest_draft_status}`}>
                                {l.latest_draft_status}
                              </span>
                            )}
                          </span>
                        ) : (
                          <span className="muted">-</span>
                        )}
                      </td>
                      <td><i className="ti ti-chevron-right" style={{ color: '#9CA3AF' }} /></td>
                    </tr>
                  );
                })}
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
                    <h3 className="section-h">Research</h3>
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
                    {(detail.research_data as { estimated_monthly_volume?: string }).estimated_monthly_volume && (
                      <div style={{ fontSize: 12, color: '#6B7280', marginBottom: 4 }}>
                        <strong>Szac. wolumen B2B:</strong>{' '}
                        <span style={{ color: '#111' }}>
                          {(detail.research_data as { estimated_monthly_volume: string }).estimated_monthly_volume}
                        </span>
                      </div>
                    )}
                    {Array.isArray((detail.research_data as { warning_flags?: string[] }).warning_flags) &&
                      (detail.research_data as { warning_flags: string[] }).warning_flags.length > 0 && (
                      <div className="warn-box">
                        <strong>Czerwone flagi:</strong>
                        <ul style={{ marginTop: 4, paddingLeft: 16 }}>
                          {(detail.research_data as { warning_flags: string[] }).warning_flags.map((w, i) => (
                            <li key={i}>{w}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}

                {/* DRAFTY tego leada - klikalne, prowadza do /drafty z highlightem */}
                <h3 className="section-h">
                  Drafty <span style={{ color: '#9CA3AF', fontWeight: 400 }}>({detail.drafts.length})</span>
                </h3>
                {detail.drafts.length === 0 ? (
                  <div className="empty-mini">Brak draftow. Wygeneruj ponizej.</div>
                ) : (
                  <div className="draft-list">
                    {detail.drafts.map((d) => {
                      const isRejected = d.status === 'rejected';
                      // Rejected drafty: nieklikalne, wizualnie przekreslone -
                      // /drafty domyslnie filtruje status=draft, klik prowadzilby
                      // do pustej strony "brak draftow" - mylace.
                      if (isRejected) {
                        return (
                          <div
                            key={d.id}
                            className="draft-chip status-rejected"
                            title="Draft odrzucony - nie wysyla sie. Mozesz wygenerowac nowy nizej."
                          >
                            <span className="dc-id">#{d.id}</span>
                            <span className="dc-subject dc-strikethrough">
                              {d.subject || '(bez tematu)'}
                            </span>
                            <span className="status-badge status-rejected">rejected</span>
                            {d.edited_by_user && <span className="dc-edited">edytowany</span>}
                          </div>
                        );
                      }
                      return (
                        <a
                          key={d.id}
                          href={`/drafty?open=${d.id}`}
                          className={`draft-chip status-${d.status}`}
                          onClick={(e) => {
                            if (!e.metaKey && !e.ctrlKey) {
                              e.preventDefault();
                              router.push(`/drafty?open=${d.id}`);
                            }
                          }}
                        >
                          <span className="dc-id">#{d.id}</span>
                          <span className="dc-subject">{d.subject || '(bez tematu)'}</span>
                          <span className={`status-badge status-${d.status}`}>{d.status}</span>
                          {d.edited_by_user && <span className="dc-edited" title="Edytowany ręcznie">edytowany</span>}
                        </a>
                      );
                    })}
                  </div>
                )}

                {/* TIMELINE aktywnosci - z Event table per lead_id */}
                {detail.events.length > 0 && (
                  <>
                    <h3 className="section-h">Historia</h3>
                    <ol className="timeline">
                      {detail.events.map((e) => (
                        <li key={e.id} className={`tl-item level-${e.level.toLowerCase()}`}>
                          <span className="tl-dot" />
                          <div className="tl-body">
                            <div className="tl-msg">{e.message}</div>
                            <div className="tl-meta">
                              <span className="tl-type">{e.type}</span>
                              {e.created_at && (
                                <span className="tl-time">{formatTimeAgo(e.created_at)}</span>
                              )}
                            </div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </>
                )}

                <div className="drawer-actions">
                  {/* Inline flash zamiast native alert */}
                  {draftFlash && (
                    <div className={`flash flash-${draftFlash.kind}`}>
                      {draftFlash.kind === 'success' && <span>✅</span>}
                      {draftFlash.kind === 'error' && <span>❌</span>}
                      {draftFlash.kind === 'info' && <span>⏳</span>}
                      <span style={{ flex: 1 }}>{draftFlash.text}</span>
                      {draftFlash.draftId && (
                        <button
                          className="btn btn-link"
                          onClick={() => router.push(`/drafty?open=${draftFlash.draftId}`)}
                        >
                          Otworz
                        </button>
                      )}
                    </div>
                  )}

                  {/* Pracuje w tle - widac progress + status, mozna zamknac okno */}
                  {draftJobId !== null && (
                    <div className="job-progress active">
                      <div className="jp-spinner" />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>
                          <span className="jp-dot" />
                          Agent generuje draft<span className="working-dots" />{' '}
                          <span className="mono" style={{ color: '#6B7280' }}>#{draftJobId}</span>
                        </div>
                        <div style={{ fontSize: 11, color: '#6B7280', marginTop: 2 }}>
                          Status: <strong>{draftJobStatus || 'pending'}</strong>. Pracuje w tle - mozesz zamknac okno, status pojawi sie w Drafty.
                        </div>
                        {/* Indeterminate progress bar - 'agent zyje' visual */}
                        <div className="jp-progress">
                          <div className="jp-progress-fill" />
                        </div>
                      </div>
                    </div>
                  )}

                  {detail.status !== 'sent' && detail.status !== 'replied' && detail.email && draftJobId === null && (
                    <button
                      className="btn btn-primary"
                      onClick={() => generateDraft(detail.id)}
                    >
                      <i className="ti ti-mail-plus" />{' '}
                      {detail.drafts.length > 0 ? 'Generuj kolejny draft' : 'Generuj draft maila'}
                    </button>
                  )}
                  {!detail.email && (
                    <span style={{ fontSize: 13, color: '#8F1018' }}>
                      Brak emaila - nie mozna wyslac maila do tego leada.
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
.page-head { margin-bottom: 16px; display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-head p { color: #6B7280; font-size: 13.5px; margin: 0; }

.btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 500; border: 1px solid transparent; cursor: pointer; font-family: inherit; text-decoration: none; transition: background 0.15s, border-color 0.15s; }
.btn i { font-size: 14px; }
.btn-sm { padding: 6px 12px; font-size: 12.5px; }
.btn-primary { background: #D4212C; color: #fff; border-color: #D4212C; }
.btn-primary:hover:not(:disabled) { background: #8F1018; border-color: #8F1018; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-secondary { background: #fff; color: #111; border-color: #E5E7EB; }
.btn-secondary:hover { background: #FAFAF7; border-color: #D1D5DB; }
.btn-ghost { background: #fff; color: #6B7280; border-color: #E5E7EB; }
.btn-ghost:hover { background: #F9FAFB; color: #111; }
.btn-link-sm { background: none; border: none; color: #D4212C; font-size: 12px; font-weight: 500; cursor: pointer; font-family: inherit; padding: 4px 8px; border-radius: 4px; }
.btn-link-sm:hover { background: #FDECED; }

/* TOOLBAR (search + filters + sort) - STICKY przy scroll w dol */
/* top: 52px = wysokosc topbar (sticky nad nim) */
.toolbar {
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  background: #fff; border: 1px solid #E5E7EB; border-radius: 8px;
  padding: 10px 12px; margin-bottom: 12px;
  position: sticky; top: 52px; z-index: 9;
  /* Subtle shadow gdy scroll - pokazuje ze element jest "nad" listing'iem */
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
.search-box {
  position: relative; flex: 1; min-width: 280px;
  display: flex; align-items: center;
}
.search-box > i {
  position: absolute; left: 12px; color: #9CA3AF; font-size: 16px; pointer-events: none;
}
.search-box input {
  flex: 1; width: 100%;
  padding: 8px 32px 8px 36px;
  border: 1px solid #E5E7EB; border-radius: 6px;
  font-family: inherit; font-size: 13.5px; color: #111;
  background: #FAFAF7;
}
.search-box input:focus {
  outline: none; border-color: #D4212C; background: #fff;
  box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}
.search-clear {
  position: absolute; right: 8px;
  background: none; border: none; cursor: pointer; color: #9CA3AF;
  padding: 4px; display: flex; border-radius: 4px;
}
.search-clear:hover { color: #111; background: #F3F4F6; }

.toolbar-filters { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.tb-select {
  padding: 7px 10px; border: 1px solid #E5E7EB; border-radius: 6px;
  font-family: inherit; font-size: 12.5px; color: #111; background: #fff;
  cursor: pointer; max-width: 220px;
}
.tb-select:hover { border-color: #D1D5DB; }
.tb-select:focus { outline: none; border-color: #D4212C; }
.tb-score {
  display: flex; flex-direction: column; gap: 2px;
  padding: 4px 10px; background: #FAFAF7; border-radius: 6px; min-width: 160px;
}
.tb-score label { font-size: 10.5px; color: #6B7280; }
.tb-score label strong { color: #111; }
.tb-score input[type="range"] { width: 100%; height: 4px; }

/* BULK ACTIONS bar */
/* BULK BAR - sticky tuz pod toolbar gdy zaznaczone */
.bulk-bar {
  display: flex; gap: 12px; align-items: center;
  background: #FDECED; border: 1px solid #FCA5A5; border-radius: 8px;
  padding: 10px 14px; margin-bottom: 12px;
  animation: slideDown 0.2s ease-out;
  /* top dopasowane do toolbar height + margin */
  position: sticky; top: 124px; z-index: 8;
  box-shadow: 0 2px 8px rgba(212,33,44,0.08);
}
.bulk-info {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: #8F1018;
}
.bulk-info i { font-size: 18px; }
.bulk-info strong { font-weight: 700; }

@keyframes slideDown {
  from { transform: translateY(-6px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

/* GLOBAL FLASH */
.global-flash {
  position: fixed; top: 64px; left: 50%; transform: translateX(-50%);
  z-index: 200; min-width: 320px; max-width: 600px;
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; border-radius: 8px;
  font-size: 13.5px; font-weight: 500;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  animation: slideDown 0.2s ease-out;
}
.global-flash i { font-size: 18px; flex-shrink: 0; }
.global-flash.flash-success { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
.global-flash.flash-error { background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }
.global-flash.flash-info { background: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE; }
.flash-close {
  background: none; border: none; cursor: pointer; color: inherit;
  opacity: 0.7; padding: 4px; display: flex; font-size: 16px;
}
.flash-close:hover { opacity: 1; }

/* Empty state */
.empty-state { text-align: center; padding: 60px 24px; }
.empty-state i { font-size: 40px; color: #D1D5DB; display: block; margin-bottom: 12px; }
.empty-state h3 { font-size: 16px; font-weight: 600; color: #111; margin: 0 0 8px; }
.empty-state p { color: #6B7280; font-size: 13.5px; margin: 0; }
.empty-state a { color: #D4212C; text-decoration: underline; }

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
table.tbl td { padding: 11px 16px; border-bottom: 1px solid #E5E7EB; vertical-align: middle; }
table.tbl tr:hover td { background: #FAFAF7; }
table.tbl tr.row-hot td { background: linear-gradient(90deg, rgba(212,33,44,0.05) 0%, transparent 30%); }
table.tbl tr.row-hot:hover td { background: linear-gradient(90deg, rgba(212,33,44,0.10) 0%, rgba(250,250,247,1) 50%); }
table.tbl tr.row-selected td { background: #FDECED; }
table.tbl tr.row-selected:hover td { background: #FDD8DB; }
table.tbl .row-check { width: 40px; text-align: center; padding: 11px 0 11px 16px; }
table.tbl .row-check input[type="checkbox"] {
  width: 16px; height: 16px; cursor: pointer; accent-color: #D4212C;
}
.contact-sub { font-size: 11.5px; color: #6B7280; margin-top: 1px; }
.muted { color: #9CA3AF; }
.email-cell { color: #4B5563; font-size: 12px; font-family: 'JetBrains Mono', monospace; }

.drafts-cell {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: #111;
}
.drafts-cell i { font-size: 13px; color: #D4212C; }
.drafts-cell strong { font-weight: 600; }
.status-mini {
  font-size: 9.5px; font-weight: 600;
  padding: 1px 5px; border-radius: 3px;
  font-family: 'JetBrains Mono', monospace;
  text-transform: uppercase; letter-spacing: 0.3px;
}
.status-mini.status-draft { background: #FEF3C7; color: #92400E; }
.status-mini.status-approved { background: #DCFCE7; color: #166534; }
.status-mini.status-sent { background: #E0E7FF; color: #4338CA; }
.status-mini.status-rejected { background: #FEE2E2; color: #991B1B; }

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

.drawer-actions { margin-top: 24px; padding-top: 20px; border-top: 1px solid #E5E7EB; display: flex; flex-direction: column; gap: 12px; }
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; font-family: inherit; }
.btn-primary { background: #D4212C; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #8F1018; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-link { background: none; color: #D4212C; border: 1px solid #D4212C; padding: 4px 10px; font-size: 12px; font-weight: 500; border-radius: 6px; }
.btn-link:hover { background: #FDECED; }

/* Section headers inside drawer */
.section-h { font-size: 13px; font-weight: 600; color: #111; margin: 24px 0 10px; padding-top: 16px; border-top: 1px solid #F3F4F6; text-transform: uppercase; letter-spacing: 0.6px; }
.empty-mini { font-size: 12px; color: #9CA3AF; padding: 8px 12px; background: #FAFAF7; border-radius: 6px; }

/* Drafty chip list */
.draft-list { display: flex; flex-direction: column; gap: 6px; }
.draft-chip { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid #E5E7EB; border-radius: 8px; text-decoration: none; color: #111; transition: border-color 0.15s, background 0.15s; cursor: pointer; }
.draft-chip:not(.status-rejected):hover { border-color: #D4212C; background: #FDECED; }
.draft-chip.status-rejected {
  cursor: default;
  background: #FAFAF7;
  border-color: #F3F4F6;
  opacity: 0.7;
}
.draft-chip.status-rejected:hover { background: #FAFAF7; border-color: #F3F4F6; }
.dc-strikethrough {
  text-decoration: line-through;
  color: #6B7280;
}
.dc-id { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #9CA3AF; font-weight: 600; min-width: 30px; }
.dc-subject { flex: 1; font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dc-edited { font-size: 12px; opacity: 0.7; }

/* Timeline (Event historia) */
.timeline { list-style: none; padding: 0; margin: 0; position: relative; }
.timeline::before { content: ''; position: absolute; left: 6px; top: 4px; bottom: 4px; width: 2px; background: #E5E7EB; }
.tl-item { display: flex; gap: 12px; padding: 6px 0; position: relative; }
.tl-dot { width: 14px; height: 14px; border-radius: 50%; background: #fff; border: 2px solid #9CA3AF; flex-shrink: 0; margin-top: 4px; position: relative; z-index: 1; }
.tl-item.level-info .tl-dot { border-color: #4338CA; }
.tl-item.level-warning .tl-dot { border-color: #C2410C; background: #FFF7ED; }
.tl-item.level-error .tl-dot { border-color: #8F1018; background: #FDECED; }
.tl-body { flex: 1; min-width: 0; }
.tl-msg { font-size: 13px; color: #111; line-height: 1.4; }
.tl-meta { font-size: 11px; color: #9CA3AF; display: flex; gap: 8px; margin-top: 2px; }
.tl-type { font-family: 'JetBrains Mono', monospace; }
.tl-time { font-family: 'JetBrains Mono', monospace; }

/* Inline flash (zamiast alert) */
.flash { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-radius: 8px; font-size: 13px; line-height: 1.4; }
.flash-success { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
.flash-error { background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }
.flash-info { background: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE; }

/* Background job progress widget */
.job-progress {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 14px; background: #FAFAF7;
  border: 1px solid #E5E7EB; border-radius: 8px;
}
.job-progress.active {
  border-color: #FCA5A5;
  background: linear-gradient(135deg, #FDECED 0%, #FAFAF7 100%);
  animation: pulse-bg 2.5s ease-in-out infinite;
}
@keyframes pulse-bg {
  0%, 100% { box-shadow: 0 0 0 0 rgba(212,33,44,0.0); }
  50%      { box-shadow: 0 0 0 4px rgba(212,33,44,0.08); }
}

.jp-spinner {
  width: 22px; height: 22px;
  border: 3px solid #E5E7EB; border-top-color: #D4212C;
  border-radius: 50%; animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

/* Pulsujaca kropka przed "Agent generuje" - dodatkowy 'zyje' signal */
.jp-dot {
  display: inline-block;
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #D4212C;
  margin-right: 6px;
  vertical-align: middle;
  animation: dot-pulse 1.4s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { transform: scale(1);   opacity: 1;   }
  50%      { transform: scale(1.5); opacity: 0.55; }
}

/* Indeterminate progress bar - generacja drafta nie ma znanej dlugosci,
   wiec animujemy 'sliding' fragment od lewej do prawej w nieskonczonosc */
.jp-progress {
  margin-top: 8px;
  height: 4px;
  background: #fff;
  border-radius: 2px;
  overflow: hidden;
  border: 1px solid #FCD8DB;
}
.jp-progress-fill {
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, transparent, #D4212C 50%, transparent);
  animation: jp-indeterminate 1.4s ease-in-out infinite;
}
@keyframes jp-indeterminate {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(250%); }
}

/* Working dots ellipsis - "Agent generuje..." z animacja kropek */
.working-dots::after {
  content: '';
  animation: dots-ellipsis 1.5s steps(4, end) infinite;
}
@keyframes dots-ellipsis {
  0%   { content: ''; }
  25%  { content: '.'; }
  50%  { content: '..'; }
  75%  { content: '...'; }
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Warning box dla research warning_flags */
.warn-box { background: #FFF7ED; border: 1px solid #FED7AA; border-radius: 6px; padding: 10px 12px; font-size: 12px; color: #9A3412; margin-bottom: 12px; }

.mono { font-family: 'JetBrains Mono', monospace; }
`;
