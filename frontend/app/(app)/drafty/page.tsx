'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

import { api, isAuthenticated } from '@/lib/api';
import { AccountMenu } from '@/lib/AccountMenu';
import { useConfirm } from '@/lib/confirm';

interface Draft {
  id: number;
  lead_id: number;
  company: string;
  lead_contact_name: string | null;
  lead_email: string | null;
  lead_segment: string | null;
  lead_city: string | null;
  lead_score: number | null;
  subject: string;
  snippet1: string;
  snippet2: string;
  snippet3: string;
  snippet5: string;
  full_preview: string;
  status: string;
  template_variant: string | null;
  edited_by_user: boolean;
  generated_by_model: string | null;
  created_at: string | null;
  sent_at: string | null;
  woodpecker_prospect_id: string | null;
  send_in_progress: boolean;
  last_send_error: string | null;
}

interface Campaign {
  id: number;
  name: string;
  status: string | null;
}

type Flash = { kind: 'success' | 'error' | 'info'; text: string };
type StatusFilter = 'draft' | 'approved' | 'sent' | 'rejected' | 'all';

const STATUS_TABS: { key: StatusFilter; label: string; icon: string }[] = [
  { key: 'draft', label: 'Do review', icon: 'mail' },
  { key: 'approved', label: 'Zatwierdzone', icon: 'check' },
  { key: 'sent', label: 'Wysłane', icon: 'send' },
  { key: 'rejected', label: 'Odrzucone', icon: 'x' },
  { key: 'all', label: 'Wszystkie', icon: 'list' },
];

const FIELD_LABELS: Record<string, string> = {
  subject: 'Temat',
  snippet1: 'Otwarcie',
  snippet2: 'Most do oferty',
  snippet3: 'Propozycja wartości',
  snippet5: 'CTA',
};

const FIELD_HINTS: Record<string, string> = {
  subject: 'Max 50 znaków. Bez "Oferta:" / "Propozycja".',
  snippet1: 'Musi nawiązać do konkretnego haka z researchu.',
  snippet2: 'Kim jesteś + dlaczego piszesz akurat do nich.',
  snippet3: 'Konkretna oferta: Chiny / private label + opcjonalnie panel B2B.',
  snippet5: 'Pytanie z niskim wysiłkiem (wycena? rozmowa? zainteresowanie?).',
};

function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const sec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 60) return `${Math.floor(sec)}s temu`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min temu`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h temu`;
  return new Date(iso).toLocaleDateString('pl-PL');
}

function scoreBadge(score: number | null) {
  if (score == null) return null;
  const cls = score >= 7 ? 'hot' : score >= 5 ? 'warm' : 'cold';
  return <span className={`score-pill ${cls}`} title={`Score ${score.toFixed(1)}`}>{score.toFixed(1)}</span>;
}

function statusPill(status: string, queued: boolean) {
  if (queued) {
    return <span className="status-pill status-queued"><i className="ti ti-loader" /> wysyłka</span>;
  }
  const labelMap: Record<string, string> = {
    draft: 'do review',
    approved: 'zatwierdzony',
    sent: 'wysłany',
    rejected: 'odrzucony',
  };
  return <span className={`status-pill status-${status}`}>{labelMap[status] || status}</span>;
}

function trackBadge(variant: string | null) {
  if (!variant) return null;
  if (variant.includes('private_label')) return <span className="track-badge track-a">Private Label</span>;
  if (variant.includes('both')) return <span className="track-badge track-both">Obie ścieżki</span>;
  if (variant.includes('b2b_panel')) return <span className="track-badge track-b">Panel B2B</span>;
  return null;
}

export default function DraftyPage() {
  const router = useRouter();
  const confirm = useConfirm();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selectedCampaign, setSelectedCampaign] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [regenerating, setRegenerating] = useState<string | null>(null);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('draft');
  const [search, setSearch] = useState('');
  // Mnoga selekcja - id draftow zaznaczonych w liscie. Tylko draftow ktore
  // mozna wyslac (draft/approved bez queued/sent). Czyszczone przy zmianie tabu.
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  // Otwarte (rozwiniete inline) drafty - klik wiersza otwiera pelen mail
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  // Deep-link: ?open=42 z drawera leada
  const [highlightId, setHighlightId] = useState<number | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) router.push('/login');
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const openId = params.get('open');
      if (openId) {
        const id = Number(openId);
        setHighlightId(id);
        setExpanded((p) => new Set(p).add(id));
      }
    }
  }, [router]);

  async function load() {
    setLoading(true);
    try {
      const [d, c] = await Promise.all([
        api<Draft[]>(`/api/drafts?status_filter=${statusFilter}`),
        api<Campaign[]>('/api/woodpecker/campaigns').catch(() => []),
      ]);
      setDrafts(d);
      setCampaigns(c);
      if (c.length > 0 && selectedCampaign == null) setSelectedCampaign(c[0].id);
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd ładowania' });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    setSelectedIds(new Set());
    /* eslint-disable-next-line */
  }, [statusFilter]);

  useEffect(() => {
    if (!loading && highlightId !== null) {
      const el = document.getElementById(`draft-${highlightId}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setTimeout(() => setHighlightId(null), 4000);
      }
    }
  }, [loading, highlightId]);

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

  // Filtered drafts po szukajce (po firmie/emailu/subjectu, lokalnie)
  const filteredDrafts = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return drafts;
    return drafts.filter((d) =>
      (d.company || '').toLowerCase().includes(q)
      || (d.lead_email || '').toLowerCase().includes(q)
      || (d.subject || '').toLowerCase().includes(q)
      || (d.lead_contact_name || '').toLowerCase().includes(q),
    );
  }, [drafts, search]);

  // Drafty ktore mozna zaznaczyc do bulk action (draft/approved, bez aktywnego joba)
  const selectableIds = useMemo(() => {
    return new Set(
      filteredDrafts
        .filter((d) => (d.status === 'draft' || d.status === 'approved') && !d.send_in_progress)
        .map((d) => d.id),
    );
  }, [filteredDrafts]);

  const allSelected = selectableIds.size > 0
    && Array.from(selectableIds).every((id) => selectedIds.has(id));
  const someSelected = selectedIds.size > 0 && !allSelected;

  function toggleSelect(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(selectableIds));
    }
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  function toggleExpand(id: number) {
    if (editing === id) return; // nie zwijaj w trakcie edycji
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function startEdit(d: Draft) {
    setEditing(d.id);
    setExpanded((p) => new Set(p).add(d.id));
    setEditValues({
      subject: d.subject || '',
      snippet1: d.snippet1 || '',
      snippet2: d.snippet2 || '',
      snippet3: d.snippet3 || '',
      snippet5: d.snippet5 || '',
    });
  }

  function cancelEdit() {
    setEditing(null);
    setEditValues({});
  }

  async function saveEdit(draftId: number) {
    try {
      await api(`/api/drafts/${draftId}`, {
        method: 'PATCH',
        body: JSON.stringify(editValues),
      });
      setEditing(null);
      setFlash({ kind: 'success', text: `Draft #${draftId} zapisany.` });
      await load();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd zapisu' });
    }
  }

  async function regenerateField(draftId: number, fieldName: string) {
    setRegenerating(`${draftId}-${fieldName}`);
    try {
      const res = await api<{ text: string }>(`/api/drafts/${draftId}/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ snippet_name: fieldName }),
      });
      setEditValues((prev) => ({ ...prev, [fieldName]: res.text }));
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd regeneracji' });
    } finally {
      setRegenerating(null);
    }
  }

  async function approve(draftId: number) {
    try {
      await api(`/api/drafts/${draftId}/approve`, { method: 'POST' });
      setFlash({ kind: 'success', text: `Draft #${draftId} zaakceptowany.` });
      await load();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd' });
    }
  }

  async function reject(draftId: number) {
    const ok = await confirm({
      title: 'Odrzucić draft?',
      message: 'Draft zostanie oznaczony jako odrzucony i nie wyślemy go. Nie da się tego cofnąć.',
      confirmLabel: 'Odrzuć draft',
      destructive: true,
      icon: 'x',
    });
    if (!ok) return;
    try {
      await api(`/api/drafts/${draftId}/reject`, { method: 'POST' });
      setFlash({ kind: 'info', text: `Draft #${draftId} odrzucony.` });
      await load();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd' });
    }
  }

  async function send(draftId: number) {
    if (!selectedCampaign) {
      setFlash({ kind: 'error', text: 'Wybierz najpierw kampanię Woodpecker u góry strony.' });
      return;
    }
    const draft = drafts.find((d) => d.id === draftId);
    const campaign = campaigns.find((c) => c.id === selectedCampaign);
    const ok = await confirm({
      title: 'Wysłać draft do Woodpeckera?',
      message: (
        <>
          Wyślemy <strong>Draft #{draftId}</strong>
          {draft?.lead_email && <> do <strong>{draft.lead_email}</strong></>}
          {campaign && <> w kampanii <strong>{campaign.name}</strong></>}.
          {'\n'}Lead trafi do sekwencji follow-upów Woodpeckera.
        </>
      ),
      confirmLabel: 'Wyślij',
      icon: 'send',
    });
    if (!ok) return;
    try {
      const res = await api<{ job_id: number }>(`/api/drafts/${draftId}/send`, {
        method: 'POST',
        body: JSON.stringify({ campaign_id: selectedCampaign }),
      });
      setFlash({
        kind: 'success',
        text: `Draft #${draftId} w kolejce do wysyłki (job #${res.job_id}).`,
      });
      await load();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd wysyłki' });
    }
  }

  // ─── Bulk actions ────────────────────────────────────────────────────

  async function bulkApprove() {
    const ids = Array.from(selectedIds).filter((id) => {
      const d = drafts.find((x) => x.id === id);
      return d?.status === 'draft';
    });
    if (ids.length === 0) {
      setFlash({ kind: 'info', text: 'Zaznaczone drafty nie są w statusie "do review".' });
      return;
    }
    setBulkSubmitting(true);
    let ok = 0, fail = 0;
    for (const id of ids) {
      try {
        await api(`/api/drafts/${id}/approve`, { method: 'POST' });
        ok++;
      } catch { fail++; }
    }
    setBulkSubmitting(false);
    setFlash({
      kind: fail === 0 ? 'success' : 'info',
      text: `Zatwierdzono ${ok}${fail > 0 ? `, ${fail} nieudane` : ''}.`,
    });
    clearSelection();
    await load();
  }

  async function bulkReject() {
    const ids = Array.from(selectedIds);
    const confirmed = await confirm({
      title: `Odrzucić ${ids.length} draftów?`,
      message: 'Wszystkie zaznaczone drafty zostaną oznaczone jako odrzucone. Nie da się tego cofnąć.',
      confirmLabel: `Odrzuć ${ids.length}`,
      destructive: true,
      icon: 'x',
    });
    if (!confirmed) return;
    setBulkSubmitting(true);
    let ok = 0, fail = 0;
    for (const id of ids) {
      try {
        await api(`/api/drafts/${id}/reject`, { method: 'POST' });
        ok++;
      } catch { fail++; }
    }
    setBulkSubmitting(false);
    setFlash({
      kind: 'info',
      text: `Odrzucono ${ok}${fail > 0 ? `, ${fail} nieudane` : ''}.`,
    });
    clearSelection();
    await load();
  }

  async function bulkSend() {
    if (!selectedCampaign) {
      setFlash({ kind: 'error', text: 'Wybierz najpierw kampanię Woodpecker u góry strony.' });
      return;
    }
    const ids = Array.from(selectedIds);
    const campaign = campaigns.find((c) => c.id === selectedCampaign);
    const confirmed = await confirm({
      title: `Wysłać ${ids.length} draftów do Woodpeckera?`,
      message: (
        <>
          Zakolejkujemy <strong>{ids.length}</strong> draftów do kampanii
          {campaign && <> <strong>{campaign.name}</strong></>}.
          {'\n'}Worker wysyła pojedynczo z rate-limitem Woodpeckera (~1.2s/draft).
          {'\n'}Drafty już wysłane / odrzucone / bez emaila zostaną pominięte.
        </>
      ),
      confirmLabel: `Wyślij ${ids.length}`,
      icon: 'send',
    });
    if (!confirmed) return;
    setBulkSubmitting(true);
    try {
      type BulkResp = {
        queued: number;
        requested: number;
        skipped: { draft_id: number; reason: string }[];
      };
      const res = await api<BulkResp>('/api/drafts/bulk-send', {
        method: 'POST',
        body: JSON.stringify({ draft_ids: ids, campaign_id: selectedCampaign }),
      });
      const msg = res.skipped.length > 0
        ? `${res.queued}/${res.requested} w kolejce. Pominięto ${res.skipped.length}: ${res.skipped.slice(0, 3).map((s) => `#${s.draft_id} (${s.reason})`).join(', ')}${res.skipped.length > 3 ? '...' : ''}`
        : `${res.queued} draftów w kolejce. Worker dorzuca do Woodpeckera w tle.`;
      setFlash({ kind: res.queued > 0 ? 'success' : 'error', text: msg });
      clearSelection();
      await load();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd zbiorczej wysyłki' });
    } finally {
      setBulkSubmitting(false);
    }
  }

  // ─── Render ──────────────────────────────────────────────────────────

  const noCampaignWarning = campaigns.length === 0;
  const bulkCount = selectedIds.size;

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="topbar">
        <div className="crumb">
          Workspace <i className="ti ti-chevron-right" /> <strong>Ecombinat</strong>
          <i className="ti ti-chevron-right" /> Drafty
        </div>
        {campaigns.length > 0 ? (
          <div className="topbar-campaign">
            <i className="ti ti-send" />
            <span className="tc-label">Kampania:</span>
            <select
              value={selectedCampaign || ''}
              onChange={(e) => setSelectedCampaign(Number(e.target.value))}
              title="Kampania Woodpecker do wysyłki"
            >
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}{c.status ? ` (${c.status})` : ''}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="topbar-warning" title="Skonfiguruj kampanię w Woodpecker">
            <i className="ti ti-alert-triangle" /> Brak kampanii
          </div>
        )}
        <AccountMenu />
      </div>

      {flash && (
        <div className={`global-flash flash-${flash.kind}`}>
          {flash.kind === 'success' && <i className="ti ti-check" />}
          {flash.kind === 'error' && <i className="ti ti-alert-circle" />}
          {flash.kind === 'info' && <i className="ti ti-info-circle" />}
          <span style={{ flex: 1 }}>{flash.text}</span>
          <button className="flash-close" onClick={() => setFlash(null)} aria-label="Zamknij">
            <i className="ti ti-x" />
          </button>
        </div>
      )}

      <div className="content">
        <div className="page-head">
          <div>
            <h1>Drafty cold-email</h1>
            <p className="page-sub">
              Przejrzyj, zatwierdź, wyślij. Bulk-actions po zaznaczeniu draftów.
            </p>
          </div>
          <button className="btn btn-ghost" onClick={() => load()} title="Odśwież listę">
            <i className="ti ti-refresh" /> Odśwież
          </button>
        </div>

        {/* Tabki statusów */}
        <div className="status-tabs">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              className={`status-tab ${statusFilter === tab.key ? 'active' : ''}`}
              onClick={() => setStatusFilter(tab.key)}
            >
              <i className={`ti ti-${tab.icon}`} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Toolbar: search + counter */}
        <div className="toolbar">
          <div className="search-box">
            <i className="ti ti-search" />
            <input
              type="search"
              placeholder="Szukaj: firma, email, temat, kontakt..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button className="search-clear" onClick={() => setSearch('')} aria-label="Wyczyść">
                <i className="ti ti-x" />
              </button>
            )}
          </div>
          <div className="counter">
            {loading
              ? 'Ładuję…'
              : filteredDrafts.length === drafts.length
                ? `${filteredDrafts.length} ${filteredDrafts.length === 1 ? 'draft' : 'draftów'}`
                : `${filteredDrafts.length} z ${drafts.length}`}
          </div>
        </div>

        {/* Bulk-bar: sticky pod toolbar gdy zaznaczone */}
        {bulkCount > 0 && (
          <div className="bulk-bar">
            <div className="bulk-info">
              <i className="ti ti-checks" />
              <strong>{bulkCount}</strong> zaznaczonych
              <button className="bulk-clear" onClick={clearSelection}>
                <i className="ti ti-x" /> Wyczyść
              </button>
            </div>
            <div className="bulk-actions">
              {statusFilter === 'draft' && (
                <button
                  className="btn btn-ghost btn-success"
                  onClick={bulkApprove}
                  disabled={bulkSubmitting}
                  title="Zatwierdź zaznaczone (tylko ze statusu draft)"
                >
                  <i className="ti ti-check" /> Zatwierdź
                </button>
              )}
              <button
                className="btn btn-ghost btn-danger"
                onClick={bulkReject}
                disabled={bulkSubmitting}
              >
                <i className="ti ti-x" /> Odrzuć
              </button>
              <button
                className="btn btn-primary"
                onClick={bulkSend}
                disabled={bulkSubmitting || noCampaignWarning}
                title={noCampaignWarning ? 'Brak kampanii' : `Wyślij ${bulkCount} draftów do Woodpeckera`}
              >
                {bulkSubmitting ? (
                  <><i className="ti ti-loader" /> Wysyłam…</>
                ) : (
                  <><i className="ti ti-send" /> Wyślij {bulkCount} →</>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Master checkbox + sort header */}
        {!loading && filteredDrafts.length > 0 && (
          <div className="list-header">
            <label className="row-check master-check" title={allSelected ? 'Odznacz wszystkie' : 'Zaznacz wszystkie'}>
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => { if (el) el.indeterminate = someSelected; }}
                onChange={toggleSelectAll}
                disabled={selectableIds.size === 0}
              />
              <span className="row-check-label">
                {selectableIds.size === 0
                  ? 'Brak draftów do zaznaczenia'
                  : allSelected
                    ? `Wszystkie ${selectableIds.size} zaznaczone`
                    : `Zaznacz wszystkie (${selectableIds.size})`}
              </span>
            </label>
          </div>
        )}

        {/* Lista draftów */}
        {loading ? (
          <div className="list">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="row skeleton-row">
                <span className="skel skel-check" />
                <span className="skel skel-id" />
                <span className="skel skel-text" />
              </div>
            ))}
          </div>
        ) : filteredDrafts.length === 0 ? (
          <div className="empty-state">
            <i className="ti ti-mail-off" />
            <h3>
              {search
                ? 'Brak draftów pasujących do filtra'
                : statusFilter === 'sent'
                  ? 'Nic jeszcze nie wysłałeś'
                  : statusFilter === 'rejected'
                    ? 'Nic odrzuconego'
                    : 'Brak draftów'}
            </h3>
            <p>
              {search ? (
                <>Zmień filtr lub <button className="inline-btn" onClick={() => setSearch('')}>wyczyść wyszukiwanie</button>.</>
              ) : (
                <>Wygeneruj drafty z poziomu <a href="/leady">/leady</a> lub <a href="/pozyskiwanie">/pozyskiwanie</a>.</>
              )}
            </p>
          </div>
        ) : (
          <div className="list">
            {filteredDrafts.map((d) => {
              const isExpanded = expanded.has(d.id);
              const isEditing = editing === d.id;
              const isHighlighted = highlightId === d.id;
              const isSelected = selectedIds.has(d.id);
              const canSelect = selectableIds.has(d.id);
              const canSend = (d.status === 'draft' || d.status === 'approved')
                && !d.send_in_progress
                && selectedCampaign != null;

              return (
                <div
                  key={d.id}
                  id={`draft-${d.id}`}
                  className={`row ${isExpanded ? 'expanded' : ''} ${isHighlighted ? 'highlighted' : ''} ${isSelected ? 'selected' : ''}`}
                >
                  {/* Compact row - zawsze widoczny */}
                  <div className="row-compact" onClick={() => toggleExpand(d.id)}>
                    <label className="row-check" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(d.id)}
                        disabled={!canSelect}
                        title={canSelect ? 'Zaznacz do bulk-action' : 'Już wysłany / odrzucony / w kolejce'}
                      />
                    </label>
                    <div className="row-meta">
                      <div className="row-line-1">
                        <span className="row-id">#{d.id}</span>
                        {scoreBadge(d.lead_score)}
                        <span className="row-company" title={d.company}>{d.company}</span>
                        {d.lead_email && <span className="row-email">{d.lead_email}</span>}
                        <span className="row-spacer" />
                        {statusPill(d.status, d.send_in_progress)}
                      </div>
                      <div className="row-line-2">
                        <span className="row-subject" title={d.subject}>{d.subject || <em>(brak tematu)</em>}</span>
                      </div>
                      <div className="row-line-3">
                        {d.lead_contact_name && <span className="meta-mini">{d.lead_contact_name}</span>}
                        {d.lead_city && <span className="meta-mini"><i className="ti ti-map-pin" />{d.lead_city}</span>}
                        {d.lead_segment && <span className="seg-mini">{d.lead_segment}</span>}
                        {trackBadge(d.template_variant)}
                        {d.edited_by_user && <span className="edited-mini" title="Edytowany ręcznie"><i className="ti ti-pencil" /> edytowany</span>}
                        <span className="row-spacer" />
                        {d.created_at && <span className="time-mini" title={new Date(d.created_at).toLocaleString('pl-PL')}>{timeAgo(d.created_at)}</span>}
                      </div>
                    </div>
                    <button
                      className="row-expand-btn"
                      onClick={(e) => { e.stopPropagation(); toggleExpand(d.id); }}
                      aria-label={isExpanded ? 'Zwiń' : 'Rozwiń'}
                    >
                      <i className={`ti ti-${isExpanded ? 'chevron-up' : 'chevron-down'}`} />
                    </button>
                  </div>

                  {/* Banery statusu wysyłki */}
                  {isExpanded && d.status === 'sent' && (
                    <div className="send-banner send-banner-success">
                      <i className="ti ti-circle-check" />
                      <div>
                        <strong>Wysłano do Woodpeckera</strong>
                        {d.sent_at && <> · {timeAgo(d.sent_at)}</>}
                        {d.woodpecker_prospect_id && <> · prospect <code>#{d.woodpecker_prospect_id}</code></>}
                        <div className="send-banner-sub">Ten lead nie zostanie zaspamowany powtórnie.</div>
                      </div>
                    </div>
                  )}
                  {isExpanded && d.last_send_error && d.status !== 'sent' && (
                    <div className="send-banner send-banner-error">
                      <i className="ti ti-alert-triangle" />
                      <div>
                        <strong>Ostatnia próba wysyłki nie powiodła się</strong>
                        <div className="send-banner-sub">{d.last_send_error}</div>
                      </div>
                    </div>
                  )}

                  {/* Expanded - mail content lub editor */}
                  {isExpanded && (
                    <div className="row-body">
                      {isEditing ? (
                        <div className="edit-form">
                          {(['subject', 'snippet1', 'snippet2', 'snippet3', 'snippet5'] as const).map((field) => (
                            <div className="edit-field" key={field}>
                              <div className="edit-field-head">
                                <label>{FIELD_LABELS[field]}</label>
                                <span className="edit-hint">{FIELD_HINTS[field]}</span>
                                <button
                                  className="regen-btn"
                                  onClick={() => regenerateField(d.id, field)}
                                  disabled={regenerating === `${d.id}-${field}`}
                                  title="Wygeneruj alternatywną wersję"
                                >
                                  <i className="ti ti-refresh" />
                                  {regenerating === `${d.id}-${field}` ? '…' : 'Inna wersja'}
                                </button>
                              </div>
                              {field === 'subject' ? (
                                <input
                                  type="text"
                                  value={editValues[field] || ''}
                                  onChange={(e) => setEditValues({ ...editValues, [field]: e.target.value })}
                                  maxLength={60}
                                />
                              ) : (
                                <textarea
                                  value={editValues[field] || ''}
                                  onChange={(e) => setEditValues({ ...editValues, [field]: e.target.value })}
                                  rows={field === 'snippet3' ? 4 : 3}
                                />
                              )}
                            </div>
                          ))}
                          <div className="row-actions">
                            <button className="btn btn-primary" onClick={() => saveEdit(d.id)}>
                              <i className="ti ti-device-floppy" /> Zapisz
                            </button>
                            <button className="btn btn-ghost" onClick={cancelEdit}>Anuluj</button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="mail-preview">
                            <div className="mail-subject-row">
                              <span className="mail-k">Temat</span>
                              <span className="mail-v">{d.subject || <em>(brak tematu)</em>}</span>
                            </div>
                            <div className="mail-body">
                              {[d.snippet1, d.snippet2, d.snippet3, d.snippet5]
                                .filter(Boolean)
                                .map((p, i) => <p key={i}>{p}</p>)}
                              <p className="mail-signature">
                                Pozdrawiam,<br />
                                <em>{'<sygnatura z Woodpeckera>'}</em>
                              </p>
                            </div>
                          </div>
                          <div className="row-actions">
                            <button
                              className="btn btn-ghost"
                              onClick={() => router.push(`/leady?open=${d.lead_id}`)}
                              title="Otwórz lead w nowym widoku"
                            >
                              <i className="ti ti-external-link" /> Lead
                            </button>
                            <button className="btn btn-ghost" onClick={() => startEdit(d)}>
                              <i className="ti ti-edit" /> Edytuj
                            </button>
                            <button className="btn btn-ghost btn-danger" onClick={() => reject(d.id)}>
                              <i className="ti ti-x" /> Odrzuć
                            </button>
                            {d.status === 'draft' && (
                              <button className="btn btn-ghost btn-success" onClick={() => approve(d.id)}>
                                <i className="ti ti-check" /> Zatwierdź
                              </button>
                            )}
                            {(() => {
                              const alreadySent = d.status === 'sent';
                              const isRejected = d.status === 'rejected';
                              const queued = d.send_in_progress;
                              if (alreadySent) {
                                return (
                                  <button className="btn btn-primary" disabled title="Już wysłany - nie wysyłamy drugi raz">
                                    <i className="ti ti-circle-check" /> Wysłano
                                  </button>
                                );
                              }
                              if (queued) {
                                return (
                                  <button className="btn btn-primary" disabled>
                                    <i className="ti ti-loader" /> W kolejce…
                                  </button>
                                );
                              }
                              if (isRejected) {
                                return (
                                  <button className="btn btn-primary" disabled title="Draft odrzucony">
                                    <i className="ti ti-send" /> Wyślij
                                  </button>
                                );
                              }
                              return (
                                <button
                                  className="btn btn-primary"
                                  disabled={!canSend}
                                  onClick={() => send(d.id)}
                                  title={selectedCampaign ? 'Wyślij teraz do Woodpeckera' : 'Wybierz kampanię u góry'}
                                >
                                  <i className="ti ti-send" /> Wyślij
                                </button>
                              );
                            })()}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}

const CSS = `
.topbar { background: #fff; border-bottom: 1px solid #E5E7EB; padding: 0 24px; display: flex; align-items: center; height: 52px; gap: 16px; position: sticky; top: 0; z-index: 20; }
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #6B7280; }
.crumb strong { color: #111; font-weight: 500; }
.crumb i { font-size: 12px; color: #9CA3AF; }
.topbar-campaign {
  margin-left: auto; display: flex; align-items: center; gap: 8px;
  padding: 4px 10px; background: #FAFAF7; border: 1px solid #E5E7EB; border-radius: 6px;
}
.topbar-campaign i { color: #D4212C; font-size: 14px; }
.tc-label { font-size: 12px; color: #6B7280; font-weight: 500; }
.topbar-campaign select {
  border: none; background: transparent; font-size: 13px; color: #111;
  padding: 2px 4px; cursor: pointer; outline: none; font-family: inherit; max-width: 220px;
}
.topbar-warning {
  margin-left: auto; display: flex; align-items: center; gap: 6px;
  padding: 4px 10px; background: #FEF3C7; color: #92400E; border-radius: 6px; font-size: 12px;
}

.global-flash {
  position: fixed; top: 60px; left: 50%; transform: translateX(-50%); z-index: 200;
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; min-width: 320px; max-width: 600px;
  background: #fff; border-radius: 8px; border: 1px solid #E5E7EB;
  box-shadow: 0 8px 20px rgba(0,0,0,0.12); font-size: 13.5px;
  animation: flash-in 0.2s ease-out;
}
@keyframes flash-in { from { opacity: 0; transform: translate(-50%, -8px); } to { opacity: 1; transform: translate(-50%, 0); } }
.flash-success { border-left: 3px solid #10B981; }
.flash-success i { color: #10B981; }
.flash-error { border-left: 3px solid #DC2626; }
.flash-error i { color: #DC2626; }
.flash-info { border-left: 3px solid #3B82F6; }
.flash-info i { color: #3B82F6; }
.flash-close { background: none; border: none; cursor: pointer; color: #9CA3AF; padding: 2px; }
.flash-close:hover { color: #111; }

.content { padding: 24px; max-width: 1200px; margin: 0 auto; }

.page-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
  margin-bottom: 16px;
}
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-sub { color: #6B7280; font-size: 13.5px; margin: 0; }

.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 13px; border-radius: 7px;
  border: 1px solid transparent; cursor: pointer;
  font-size: 13px; font-weight: 500; font-family: inherit;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
  white-space: nowrap;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn i { font-size: 14px; }
.btn-primary { background: #D4212C; color: #fff; border-color: #D4212C; }
.btn-primary:hover:not(:disabled) { background: #8F1018; border-color: #8F1018; }
.btn-secondary { background: #fff; color: #111; border-color: #E5E7EB; }
.btn-secondary:hover:not(:disabled) { background: #FAFAF7; border-color: #D1D5DB; }
.btn-ghost { background: transparent; color: #4B5563; border-color: #E5E7EB; }
.btn-ghost:hover:not(:disabled) { background: #F9FAFB; color: #111; border-color: #D1D5DB; }
.btn-success { color: #166534; }
.btn-success:hover:not(:disabled) { background: #F0FDF4; border-color: #BBF7D0; }
.btn-danger { color: #991B1B; }
.btn-danger:hover:not(:disabled) { background: #FEF2F2; border-color: #FECACA; }
.btn .ti-loader { animation: spin 1.2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Tabki statusów */
.status-tabs {
  display: flex; gap: 2px; margin-bottom: 14px;
  background: #F3F4F6; padding: 4px; border-radius: 10px; width: fit-content;
}
.status-tab {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: 7px;
  background: transparent; border: none; cursor: pointer;
  font-size: 13px; font-weight: 500; color: #6B7280; font-family: inherit;
  transition: background 0.12s, color 0.12s;
}
.status-tab i { font-size: 14px; }
.status-tab:hover { color: #111; }
.status-tab.active { background: #fff; color: #111; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }

/* Toolbar */
.toolbar {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 12px;
}
.search-box {
  flex: 1; max-width: 480px; position: relative;
  display: flex; align-items: center;
}
.search-box > i {
  position: absolute; left: 11px; color: #9CA3AF; font-size: 14px;
}
.search-box input {
  width: 100%; padding: 8px 10px 8px 32px;
  border: 1px solid #E5E7EB; border-radius: 7px;
  font-size: 13.5px; font-family: inherit;
  background: #fff;
}
.search-box input:focus {
  outline: none; border-color: #D4212C;
  box-shadow: 0 0 0 3px rgba(212, 33, 44, 0.1);
}
.search-clear {
  position: absolute; right: 6px; background: none; border: none; cursor: pointer;
  color: #9CA3AF; padding: 4px; display: flex; border-radius: 4px;
}
.search-clear:hover { background: #F3F4F6; color: #111; }
.counter { font-size: 12.5px; color: #6B7280; margin-left: auto; font-variant-numeric: tabular-nums; }

/* Bulk-bar */
.bulk-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px; margin-bottom: 12px;
  background: linear-gradient(135deg, #1C1C1C 0%, #2A2A2A 100%);
  border-radius: 9px; color: #fff;
  position: sticky; top: 60px; z-index: 15;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  animation: bulk-in 0.18s ease-out;
}
@keyframes bulk-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
.bulk-info {
  display: flex; align-items: center; gap: 10px;
  flex: 1; font-size: 13.5px;
}
.bulk-info > i { color: #FBBF24; font-size: 18px; }
.bulk-info strong { font-size: 15px; font-weight: 600; }
.bulk-clear {
  display: inline-flex; align-items: center; gap: 4px;
  background: rgba(255,255,255,0.1); color: #fff; border: none; cursor: pointer;
  padding: 4px 10px; border-radius: 6px; font-size: 12px; font-family: inherit;
}
.bulk-clear:hover { background: rgba(255,255,255,0.18); }
.bulk-actions { display: flex; gap: 8px; }
.bulk-actions .btn-ghost {
  background: rgba(255,255,255,0.1); color: #fff; border-color: rgba(255,255,255,0.2);
}
.bulk-actions .btn-ghost:hover:not(:disabled) {
  background: rgba(255,255,255,0.18); border-color: rgba(255,255,255,0.3); color: #fff;
}
.bulk-actions .btn-ghost.btn-success { color: #6EE7B7; }
.bulk-actions .btn-ghost.btn-danger { color: #FCA5A5; }
.bulk-actions .btn-primary { background: #D4212C; }

/* Lista */
.list-header {
  display: flex; align-items: center;
  padding: 8px 14px; margin-bottom: 6px;
  border-bottom: 1px solid #E5E7EB;
  font-size: 12px; color: #6B7280;
}
.row-check { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }
.row-check input[type="checkbox"] {
  width: 16px; height: 16px; cursor: pointer; accent-color: #D4212C;
}
.row-check input[type="checkbox"]:disabled { cursor: not-allowed; opacity: 0.4; }
.row-check-label { font-size: 12px; }
.master-check .row-check-label { font-weight: 500; }

.list { display: flex; flex-direction: column; gap: 6px; }

.row {
  background: #fff; border: 1px solid #E5E7EB; border-radius: 9px;
  transition: border-color 0.12s, box-shadow 0.12s;
}
.row.expanded { box-shadow: 0 4px 16px rgba(0,0,0,0.06); border-color: #D1D5DB; }
.row.highlighted { border-color: #D4212C; box-shadow: 0 0 0 3px rgba(212, 33, 44, 0.12); }
.row.selected { background: #FEF7F7; border-color: #FECACA; }
.row.selected.expanded { background: #FFF; }

.row-compact {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 12px 14px; cursor: pointer;
}
.row-compact:hover { background: rgba(0,0,0,0.015); }
.row.expanded .row-compact:hover { background: transparent; }

.row-meta { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.row-line-1 {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 13px;
}
.row-id {
  font-family: 'JetBrains Mono', monospace; font-size: 12px;
  color: #6B7280; font-weight: 500;
}
.row-company {
  font-weight: 600; color: #111;
  max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.row-email {
  font-family: 'JetBrains Mono', monospace; font-size: 11.5px;
  color: #6B7280;
  max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.row-spacer { flex: 1; }
.row-line-2 {
  font-size: 13.5px; color: #1F2937;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-weight: 500;
}
.row-subject em { color: #9CA3AF; font-style: italic; font-weight: 400; }
.row-line-3 {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  font-size: 11.5px; color: #6B7280;
}
.meta-mini { display: inline-flex; align-items: center; gap: 3px; }
.meta-mini i { font-size: 11px; color: #9CA3AF; }
.seg-mini {
  font-size: 10.5px; color: #6B7280; background: #FAFAF7;
  border: 1px solid #E5E7EB; border-radius: 4px; padding: 1px 6px;
  font-family: 'JetBrains Mono', monospace;
}
.edited-mini {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 10.5px; color: #92400E; background: #FEF3C7;
  border-radius: 3px; padding: 1px 5px;
}
.edited-mini i { font-size: 10px; }
.time-mini { font-size: 11px; color: #9CA3AF; }

.row-expand-btn {
  background: none; border: none; cursor: pointer;
  color: #9CA3AF; padding: 4px; border-radius: 4px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.row-expand-btn:hover { background: #F3F4F6; color: #111; }
.row-expand-btn i { font-size: 16px; }

.status-pill {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 12px;
  font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.5px; font-family: 'JetBrains Mono', monospace;
  white-space: nowrap;
}
.status-draft { background: #FEF3C7; color: #92400E; }
.status-approved { background: #DCFCE7; color: #166534; }
.status-sent { background: #E0E7FF; color: #4338CA; }
.status-rejected { background: #FEE2E2; color: #991B1B; }
.status-queued { background: #FEF3C7; color: #92400E; }
.status-queued i { animation: spin 1.2s linear infinite; font-size: 10px; }

.score-pill {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 30px; padding: 1px 7px; border-radius: 4px;
  font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600;
}
.score-pill.hot { background: #FDECED; color: #8F1018; }
.score-pill.warm { background: #FFF7ED; color: #C2410C; }
.score-pill.cold { background: #FAFAF7; color: #6B7280; border: 1px solid #E5E7EB; }

.track-badge {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 1px 6px; border-radius: 3px;
  font-size: 10px; font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
}
.track-badge.track-a { background: #1C1C1C; color: #fff; }
.track-badge.track-b { background: #FDECED; color: #8F1018; }
.track-badge.track-both { background: linear-gradient(135deg, #1C1C1C, #8F1018); color: #fff; }

/* Banery wysyłki w expanded */
.send-banner {
  display: flex; gap: 12px; align-items: flex-start;
  padding: 11px 14px; border-top: 1px solid #F3F4F6;
  font-size: 13px; line-height: 1.5;
}
.send-banner i { font-size: 17px; flex-shrink: 0; margin-top: 1px; }
.send-banner strong { color: #111; }
.send-banner code {
  font-family: 'JetBrains Mono', monospace; font-size: 12px;
  background: rgba(0,0,0,0.05); padding: 1px 5px; border-radius: 3px;
}
.send-banner-sub { font-size: 12px; color: #6B7280; margin-top: 3px; }
.send-banner-success { background: #ECFDF5; color: #065F46; border-left: 3px solid #10B981; }
.send-banner-success i { color: #10B981; }
.send-banner-error { background: #FEF2F2; color: #991B1B; border-left: 3px solid #DC2626; }
.send-banner-error i { color: #DC2626; }

/* Row body - mail preview lub edit form */
.row-body {
  border-top: 1px solid #F3F4F6;
  padding: 16px 18px;
}

.mail-preview { margin-bottom: 14px; }
.mail-subject-row {
  display: flex; gap: 12px; padding: 6px 0;
  border-bottom: 1px solid #F3F4F6; margin-bottom: 10px;
  font-size: 13.5px;
}
.mail-k {
  flex-shrink: 0; width: 52px;
  font-size: 11px; color: #9CA3AF; text-transform: uppercase;
  letter-spacing: 0.6px; font-weight: 600; padding-top: 2px;
}
.mail-v { color: #111; font-weight: 500; }
.mail-body {
  padding: 6px 0; font-size: 13.5px; color: #1F2937; line-height: 1.6;
}
.mail-body p { margin: 0 0 12px; }
.mail-body p:last-child { margin-bottom: 0; }
.mail-signature { color: #6B7280; padding-top: 8px; border-top: 1px dashed #E5E7EB; }
.mail-signature em { color: #9CA3AF; font-style: italic; font-size: 11.5px; }

.row-actions {
  display: flex; gap: 6px; flex-wrap: wrap;
  padding-top: 12px; border-top: 1px solid #F3F4F6;
  margin-top: 4px;
}

/* Edit form */
.edit-form { display: flex; flex-direction: column; gap: 14px; }
.edit-field { display: flex; flex-direction: column; gap: 5px; }
.edit-field-head {
  display: flex; align-items: center; gap: 10px;
  font-size: 12px;
}
.edit-field-head label {
  font-size: 11px; font-weight: 600;
  color: #4B5563; text-transform: uppercase; letter-spacing: 0.6px;
}
.edit-hint { color: #9CA3AF; font-size: 11px; flex: 1; }
.regen-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: #FAFAF7; color: #4B5563; border: 1px solid #E5E7EB;
  padding: 3px 8px; border-radius: 5px; font-size: 11px; cursor: pointer;
  font-family: inherit;
}
.regen-btn:hover:not(:disabled) { background: #F3F4F6; color: #111; }
.regen-btn:disabled { opacity: 0.5; cursor: wait; }
.regen-btn i { font-size: 11px; }
.edit-form input, .edit-form textarea {
  padding: 8px 10px; border: 1px solid #E5E7EB; border-radius: 6px;
  font-size: 13.5px; font-family: inherit; color: #111;
}
.edit-form input:focus, .edit-form textarea:focus {
  outline: none; border-color: #D4212C; box-shadow: 0 0 0 3px rgba(212, 33, 44, 0.1);
}
.edit-form textarea { resize: vertical; line-height: 1.5; }

/* Empty state */
.empty-state {
  text-align: center; padding: 60px 24px;
  background: #fff; border: 1px dashed #E5E7EB; border-radius: 10px;
}
.empty-state > i { font-size: 38px; color: #D1D5DB; margin-bottom: 12px; }
.empty-state h3 { font-size: 16px; color: #4B5563; margin: 0 0 6px; font-weight: 500; }
.empty-state p { color: #9CA3AF; font-size: 13.5px; margin: 0; }
.empty-state a { color: #D4212C; text-decoration: underline; }
.inline-btn {
  background: none; border: none; color: #D4212C; cursor: pointer;
  font-family: inherit; font-size: inherit; padding: 0; text-decoration: underline;
}

/* Skeleton */
.skeleton-row {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 14px;
}
.skel {
  display: inline-block; background: linear-gradient(90deg, #F3F4F6 0%, #E5E7EB 50%, #F3F4F6 100%);
  background-size: 200% 100%;
  border-radius: 4px;
  animation: skel-shimmer 1.4s ease-in-out infinite;
}
@keyframes skel-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
.skel-check { width: 16px; height: 16px; flex-shrink: 0; }
.skel-id { width: 30px; height: 14px; }
.skel-text { flex: 1; height: 14px; }
`;
