'use client';

import { useEffect, useState } from 'react';
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

type StatusFilter = 'draft' | 'approved' | 'sent' | 'rejected' | 'all';

const STATUS_TABS: { key: StatusFilter; label: string; icon: string }[] = [
  { key: 'draft', label: 'Do review', icon: 'mail' },
  { key: 'approved', label: 'Zatwierdzone', icon: 'check' },
  { key: 'sent', label: 'Wysłane', icon: 'send' },
  { key: 'rejected', label: 'Odrzucone', icon: 'x' },
  { key: 'all', label: 'Wszystkie', icon: 'list' },
];

interface Campaign {
  id: number;
  name: string;
  status: string | null;
}

type Flash = { kind: 'success' | 'error' | 'info'; text: string };

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
  return <span className={`score-pill ${cls}`}>{score.toFixed(1)}</span>;
}

function trackBadge(variant: string | null) {
  if (!variant) return null;
  if (variant.includes('private_label')) {
    return <span className="track-badge track-a"><i className="ti ti-factory" /> Private Label</span>;
  }
  if (variant.includes('both')) {
    return <span className="track-badge track-both"><i className="ti ti-arrows-shuffle" /> Obie ścieżki</span>;
  }
  if (variant.includes('b2b_panel')) {
    return <span className="track-badge track-b"><i className="ti ti-building-store" /> Panel B2B</span>;
  }
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
  const [expandedView, setExpandedView] = useState<Record<number, boolean>>({});
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('draft');
  // Deep-link: ?open=42 z drawera lead'a
  const [highlightId, setHighlightId] = useState<number | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) router.push('/login');
    // Czytaj ?open=N z URL'a do scrolowania + highlight
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const openId = params.get('open');
      if (openId) setHighlightId(Number(openId));
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

  useEffect(() => { void load(); /* eslint-disable-next-line */ }, [statusFilter]);

  // Po załadowaniu, scroll do highlighted draft (deep link)
  useEffect(() => {
    if (!loading && highlightId !== null) {
      const el = document.getElementById(`draft-${highlightId}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        // Auto-clear po 4s
        setTimeout(() => setHighlightId(null), 4000);
      }
    }
  }, [loading, highlightId]);

  function startEdit(d: Draft) {
    setEditing(d.id);
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
        text: `Draft #${draftId} w kolejce do wysyłki (job #${res.job_id}). Worker dorzuci do Woodpecker w tle.`,
      });
      await load();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd wysyłki' });
    }
  }

  // Auto-dismiss flash po 5s
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="topbar">
        <div className="crumb">
          Workspace <i className="ti ti-chevron-right" /> <strong>Ecombinat</strong>
          <i className="ti ti-chevron-right" /> Drafty
        </div>
        {/* Kampania picker przeniesiony do topbar - cienki + zawsze widoczny */}
        {campaigns.length > 0 ? (
          <div className="topbar-campaign">
            <i className="ti ti-send" />
            <span className="tc-label">Wyślij do:</span>
            <select
              value={selectedCampaign || ''}
              onChange={(e) => setSelectedCampaign(Number(e.target.value))}
              title="Kampania Woodpecker"
            >
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.id} · {c.name} {c.status ? `(${c.status})` : ''}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="topbar-warning" title="Nie można wysłać dopóki nie skonfigurujesz kampanii w Woodpecker">
            <i className="ti ti-alert-triangle" /> Brak kampanii
          </div>
        )}
        <AccountMenu />
      </div>

      {/* Globalny flash (top-fixed) */}
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
            <h1>Drafty cold-email</h1>
            <p>
              {statusFilter === 'sent'
                ? `${drafts.length} wysłanych · nie wyślemy ich drugi raz (dedup po draft.status)`
                : statusFilter === 'rejected'
                ? `${drafts.length} odrzuconych`
                : statusFilter === 'approved'
                ? `${drafts.length} zatwierdzonych, czekają na wysyłkę`
                : statusFilter === 'all'
                ? `${drafts.length} draftów łącznie`
                : drafts.length === 0
                ? 'Brak draftów do review'
                : `${drafts.length} ${drafts.length === 1 ? 'draft' : drafts.length < 5 ? 'drafty' : 'draftów'} do review · po Twojej akceptacji idzie do Woodpecker`}
            </p>
          </div>
        </div>

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

        {loading ? (
          <>
            {[0, 1, 2].map((i) => (
              <div key={i} className="email-card" style={{ marginBottom: 16 }}>
                <div className="ec-head">
                  <span className="skel skel-line-lg skel-w-200" />
                  <span className="skel skel-pill" />
                </div>
                <div className="ec-meta">
                  <span className="skel skel-line skel-w-200" />
                  <span className="skel skel-line skel-w-140" />
                </div>
                <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <span className="skel skel-line-lg skel-w-200" />
                  <span className="skel skel-line skel-w-full" />
                  <span className="skel skel-line skel-w-full" />
                  <span className="skel skel-line" style={{ width: '70%' }} />
                </div>
              </div>
            ))}
          </>
        ) : drafts.length === 0 ? (
          <div className="empty-state">
            <i className="ti ti-mail-off" />
            <h3>Brak draftów do review</h3>
            <p>
              Drafty pojawią się tutaj po wygenerowaniu z poziomu researchowanego leada
              (<a href="/leady">/leady</a>) lub przez agenta w trybie auto-draft
              (<a href="/pozyskiwanie">/pozyskiwanie</a>).
            </p>
          </div>
        ) : (
          drafts.map((d) => {
            const isEditing = editing === d.id;
            const isExpanded = expandedView[d.id] || false;
            const isHighlighted = highlightId === d.id;
            return (
              <div
                key={d.id}
                id={`draft-${d.id}`}
                className={`email-card ${isHighlighted ? 'highlighted' : ''}`}
              >
                {/* HEAD: ID + status + track badges */}
                <div className="ec-head">
                  <div className="ec-id">
                    <i className="ti ti-mail" />
                    <span className="ec-num">Draft #{d.id}</span>
                    <span className={`status-pill status-${d.status}`}>
                      {d.status === 'draft' && 'do review'}
                      {d.status === 'approved' && 'zatwierdzony'}
                      {d.status === 'sent' && 'wysłany'}
                      {d.status === 'rejected' && 'odrzucony'}
                    </span>
                    {d.send_in_progress && (
                      <span className="status-pill status-queued" title="W kolejce - worker pushuje do Woodpeckera">
                        <i className="ti ti-loader" /> wysyłka w toku
                      </span>
                    )}
                    {trackBadge(d.template_variant)}
                    {d.edited_by_user && (
                      <span className="ec-edited" title="Edytowany ręcznie">
                        <i className="ti ti-pencil" /> edytowany
                      </span>
                    )}
                  </div>
                  <div className="ec-time">
                    {d.created_at && <span title={new Date(d.created_at).toLocaleString('pl-PL')}>{timeAgo(d.created_at)}</span>}
                  </div>
                </div>

                {/* Banery statusu wysylki - widoczne by user nie wysylal drugi raz */}
                {d.status === 'sent' && (
                  <div className="send-banner send-banner-success">
                    <i className="ti ti-circle-check" />
                    <div>
                      <strong>Wysłano do Woodpeckera</strong>
                      {d.sent_at && <> · {timeAgo(d.sent_at)}</>}
                      {d.woodpecker_prospect_id && (
                        <> · prospect <code>#{d.woodpecker_prospect_id}</code></>
                      )}
                      <div className="send-banner-sub">
                        Ten lead nie zostanie zaspamowany powtórnie - wyślij follow-up świeżą wiadomością.
                      </div>
                    </div>
                  </div>
                )}
                {d.last_send_error && d.status !== 'sent' && (
                  <div className="send-banner send-banner-error">
                    <i className="ti ti-alert-triangle" />
                    <div>
                      <strong>Ostatnia próba wysyłki nie powiodła się</strong>
                      <div className="send-banner-sub">{d.last_send_error}</div>
                    </div>
                  </div>
                )}

                {/* META: Do kogo, firma, segment, score, link do leada */}
                <div className="ec-meta">
                  <div className="ec-meta-row">
                    <span className="ec-meta-k">Do</span>
                    <span className="ec-meta-v">
                      {d.lead_contact_name && <strong>{d.lead_contact_name}</strong>}
                      {d.lead_email && (
                        <span className="ec-email">&lt;{d.lead_email}&gt;</span>
                      )}
                      {!d.lead_contact_name && !d.lead_email && <em>(brak kontaktu)</em>}
                    </span>
                  </div>
                  <div className="ec-meta-row">
                    <span className="ec-meta-k">Firma</span>
                    <span className="ec-meta-v ec-firma">
                      <strong>{d.company}</strong>
                      {d.lead_segment && <span className="seg-mini">{d.lead_segment}</span>}
                      {d.lead_city && <span className="city-mini"><i className="ti ti-map-pin" />{d.lead_city}</span>}
                      {scoreBadge(d.lead_score)}
                      <button
                        className="link-to-lead"
                        onClick={() => router.push(`/leady?open=${d.lead_id}`)}
                        title="Otwórz szczegóły leada"
                      >
                        <i className="ti ti-external-link" /> Zobacz lead
                      </button>
                    </span>
                  </div>
                </div>

                {/* BODY: edycja lub preview */}
                {isEditing ? (
                  <div className="ec-edit">
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
                  </div>
                ) : (
                  <div className="ec-body">
                    <div className="ec-subject-row">
                      <span className="ec-subject-k">Temat</span>
                      <span className="ec-subject-v">{d.subject || <em>(brak tematu)</em>}</span>
                    </div>
                    <div className="ec-mail">
                      {[d.snippet1, d.snippet2, d.snippet3, d.snippet5]
                        .filter(Boolean)
                        .map((p, i) => (
                          <p key={i}>{p}</p>
                        ))}
                      <p className="ec-signature">
                        <span>Pozdrawiam,</span><br />
                        <em>{'<Twoje imię>'}</em><br />
                        <em>Artmaker</em>
                      </p>
                    </div>
                  </div>
                )}

                {/* FOOTER: akcje */}
                <div className="ec-footer">
                  {isEditing ? (
                    <>
                      <button className="btn btn-primary" onClick={() => saveEdit(d.id)}>
                        <i className="ti ti-device-floppy" /> Zapisz zmiany
                      </button>
                      <button className="btn btn-ghost" onClick={cancelEdit}>
                        Anuluj
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="btn btn-ghost"
                        onClick={() => startEdit(d)}
                        title="Edytuj snippety + regeneracja per pole"
                      >
                        <i className="ti ti-edit" /> Edytuj
                      </button>
                      <button
                        className="btn btn-ghost btn-danger"
                        onClick={() => reject(d.id)}
                        title="Odrzuć - nie wysyłaj tego draftu"
                      >
                        <i className="ti ti-x" /> Odrzuć
                      </button>
                      {d.status === 'draft' && (
                        <button
                          className="btn btn-ghost btn-success"
                          onClick={() => approve(d.id)}
                          title="Zatwierdź - jeszcze nie wysyła, tylko oznacza jako gotowy"
                        >
                          <i className="ti ti-check" /> Zatwierdź
                        </button>
                      )}
                      {(() => {
                        const alreadySent = d.status === 'sent';
                        const isRejected = d.status === 'rejected';
                        const queued = d.send_in_progress;
                        const disabled = !selectedCampaign || alreadySent || isRejected || queued;
                        const title = alreadySent
                          ? `Już wysłany${d.sent_at ? ' ' + new Date(d.sent_at).toLocaleString('pl-PL') : ''} - nie wysyłamy drugi raz`
                          : isRejected
                          ? 'Draft odrzucony - przywróć go zanim wyślesz'
                          : queued
                          ? 'Wysyłka już w kolejce - poczekaj na zakończenie'
                          : !selectedCampaign
                          ? 'Wybierz kampanię u góry strony'
                          : 'Wyślij teraz do Woodpeckera';
                        const label = alreadySent
                          ? 'Wysłano'
                          : queued
                          ? 'W kolejce…'
                          : 'Wyślij do Woodpecker';
                        const icon = alreadySent ? 'circle-check' : queued ? 'loader' : 'send';
                        return (
                          <button
                            className="btn btn-primary"
                            disabled={disabled}
                            onClick={() => send(d.id)}
                            title={title}
                          >
                            <i className={`ti ti-${icon}`} /> {label}
                          </button>
                        );
                      })()}
                    </>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </>
  );
}

const CSS = `
.topbar {
  background: #fff; border-bottom: 1px solid #E5E7EB;
  padding: 0 24px; display: flex; align-items: center; height: 52px;
  gap: 16px; position: sticky; top: 0; z-index: 10;
}
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #6B7280; }
.crumb strong { color: #111; font-weight: 500; }
.crumb i { font-size: 12px; color: #9CA3AF; }

.topbar-campaign {
  margin-left: auto; display: flex; align-items: center; gap: 8px;
  background: #FAFAF7; border: 1px solid #E5E7EB; border-radius: 8px;
  padding: 4px 4px 4px 10px;
}
.topbar-campaign i { color: #D4212C; font-size: 14px; }
.tc-label { font-size: 12px; color: #6B7280; font-weight: 500; }
.topbar-campaign select {
  border: none; background: transparent; font-size: 12.5px; color: #111;
  font-family: inherit; cursor: pointer; padding: 4px 6px; border-radius: 4px;
  max-width: 260px; outline: none;
}
.topbar-campaign select:hover { background: #fff; }

.topbar-warning {
  margin-left: auto; display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: #92400E; background: #FEF3C7;
  border: 1px solid #FCD34D; border-radius: 6px; padding: 4px 10px;
}

.avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: #1C1C1C; color: #fff; display: flex; align-items: center;
  justify-content: center; font-weight: 600; font-size: 12px;
  border: 2px solid #D4212C; flex-shrink: 0;
}

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
@keyframes slideDown {
  from { transform: translate(-50%, -10px); opacity: 0; }
  to { transform: translate(-50%, 0); opacity: 1; }
}

.content { padding: 24px; max-width: 920px; margin: 0 auto; }
.page-head { margin-bottom: 20px; }
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-head p { color: #6B7280; font-size: 13.5px; margin: 0; }

.empty-state {
  text-align: center; padding: 60px 24px; background: #fff;
  border: 1px dashed #E5E7EB; border-radius: 12px;
}
.empty-state i { font-size: 40px; color: #D1D5DB; display: block; margin-bottom: 12px; }
.empty-state h3 { font-size: 16px; font-weight: 600; color: #111; margin: 0 0 8px; }
.empty-state p { color: #6B7280; font-size: 13.5px; margin: 0; }
.empty-state a { color: #D4212C; text-decoration: underline; }

/* ============ EMAIL CARD ============ */
.email-card {
  background: #fff; border: 1px solid #E5E7EB; border-radius: 12px;
  margin-bottom: 16px; overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.email-card.highlighted {
  border-color: #D4212C;
  box-shadow: 0 0 0 3px rgba(212,33,44,0.12), 0 4px 16px rgba(212,33,44,0.08);
}

.ec-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 12px 18px; background: #FAFAF7;
  border-bottom: 1px solid #E5E7EB; flex-wrap: wrap;
}
.ec-id { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ec-id i { color: #D4212C; font-size: 16px; }
.ec-num { font-weight: 600; font-size: 14px; color: #111; }
.ec-time { font-size: 11.5px; color: #6B7280; font-family: 'JetBrains Mono', monospace; }
.ec-edited {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; color: #92400E; background: #FEF3C7;
  border: 1px solid #FCD34D; border-radius: 4px; padding: 2px 6px;
}
.ec-edited i { font-size: 11px; color: #92400E; }

.status-pill {
  display: inline-block; padding: 3px 9px; border-radius: 12px;
  font-size: 10.5px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.6px; font-family: 'JetBrains Mono', monospace;
}
.status-draft { background: #FEF3C7; color: #92400E; }
.status-approved { background: #DCFCE7; color: #166534; }
.status-sent { background: #E0E7FF; color: #4338CA; }
.status-rejected { background: #FEE2E2; color: #991B1B; }
.status-queued {
  background: #FEF3C7; color: #92400E;
  display: inline-flex; align-items: center; gap: 4px;
}
.status-queued i {
  font-size: 11px;
  animation: spin 1.2s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Tabki filtra statusow */
.status-tabs {
  display: flex; gap: 2px; margin-bottom: 16px;
  background: #F3F4F6; padding: 4px; border-radius: 10px;
  width: fit-content;
}
.status-tab {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: 7px;
  background: transparent; border: none; cursor: pointer;
  font-size: 13px; font-weight: 500; color: #6B7280;
  font-family: inherit; transition: background 0.12s, color 0.12s;
}
.status-tab i { font-size: 14px; }
.status-tab:hover { color: #111; }
.status-tab.active {
  background: #fff; color: #111;
  box-shadow: 0 1px 2px rgba(0,0,0,0.06);
}

/* Banery statusu wysylki na karcie drafta */
.send-banner {
  display: flex; gap: 12px; align-items: flex-start;
  padding: 12px 18px; border-bottom: 1px solid #F3F4F6;
  font-size: 13px; line-height: 1.5;
}
.send-banner i { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
.send-banner strong { color: #111; }
.send-banner code {
  font-family: 'JetBrains Mono', monospace; font-size: 12px;
  background: rgba(0,0,0,0.04); padding: 1px 5px; border-radius: 3px;
}
.send-banner-sub {
  font-size: 12px; color: #6B7280; margin-top: 4px;
}
.send-banner-success {
  background: #ECFDF5; color: #065F46;
  border-left: 3px solid #10B981;
}
.send-banner-success i { color: #10B981; }
.send-banner-error {
  background: #FEF2F2; color: #991B1B;
  border-left: 3px solid #DC2626;
}
.send-banner-error i { color: #DC2626; }

.track-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 9px; border-radius: 12px;
  font-size: 11px; font-weight: 600; font-family: 'JetBrains Mono', monospace;
}
.track-badge i { font-size: 11px; }
.track-badge.track-a { background: #1C1C1C; color: #fff; }
.track-badge.track-b { background: #FDECED; color: #8F1018; }
.track-badge.track-both { background: linear-gradient(135deg, #1C1C1C 0%, #8F1018 100%); color: #fff; }

/* META rows (Do / Firma) */
.ec-meta { padding: 12px 18px; border-bottom: 1px solid #F3F4F6; }
.ec-meta-row { display: flex; gap: 12px; font-size: 13px; padding: 3px 0; }
.ec-meta-k {
  flex-shrink: 0; width: 56px;
  font-size: 11px; color: #9CA3AF; text-transform: uppercase;
  letter-spacing: 0.6px; font-weight: 600; padding-top: 3px;
}
.ec-meta-v { flex: 1; color: #111; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ec-email { color: #6B7280; font-family: 'JetBrains Mono', monospace; font-size: 12px; }
.ec-firma { gap: 10px; }
.seg-mini {
  font-size: 10.5px; color: #6B7280; background: #FAFAF7;
  border: 1px solid #E5E7EB; border-radius: 4px; padding: 1px 6px;
  font-family: 'JetBrains Mono', monospace;
}
.city-mini {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 12px; color: #6B7280;
}
.city-mini i { font-size: 12px; color: #9CA3AF; }

.score-pill {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 36px; padding: 2px 8px; border-radius: 4px;
  font-family: 'JetBrains Mono', monospace; font-size: 11.5px; font-weight: 600;
}
.score-pill.hot { background: #FDECED; color: #8F1018; }
.score-pill.warm { background: #FFF7ED; color: #C2410C; }
.score-pill.cold { background: #FAFAF7; color: #6B7280; border: 1px solid #E5E7EB; }

.link-to-lead {
  display: inline-flex; align-items: center; gap: 4px;
  background: none; border: none; cursor: pointer; color: #D4212C;
  font-size: 11.5px; font-weight: 500; padding: 2px 4px; margin-left: auto;
}
.link-to-lead:hover { text-decoration: underline; }
.link-to-lead i { font-size: 11px; }

/* BODY (preview) */
.ec-body { padding: 18px 22px; background: #fff; }
.ec-subject-row {
  display: flex; gap: 12px; padding-bottom: 14px; margin-bottom: 14px;
  border-bottom: 1px solid #F3F4F6;
}
.ec-subject-k {
  flex-shrink: 0; width: 56px;
  font-size: 11px; color: #9CA3AF; text-transform: uppercase;
  letter-spacing: 0.6px; font-weight: 600; padding-top: 4px;
}
.ec-subject-v { font-size: 15.5px; font-weight: 600; color: #111; flex: 1; }

.ec-mail {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  font-size: 14px; line-height: 1.65; color: #1F2937;
}
.ec-mail p { margin: 0 0 14px; }
.ec-mail p:last-child { margin-bottom: 0; }
.ec-signature { color: #6B7280; font-size: 13px; padding-top: 8px; }
.ec-signature em { color: #9CA3AF; font-style: italic; }

/* EDIT mode */
.ec-edit { padding: 18px 22px; }
.edit-field { margin-bottom: 14px; }
.edit-field-head {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 6px;
}
.edit-field-head label {
  font-size: 11px; color: #6B7280; text-transform: uppercase;
  letter-spacing: 0.8px; font-weight: 600;
}
.edit-hint { flex: 1; font-size: 11px; color: #9CA3AF; font-style: italic; }
.regen-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: #fff; border: 1px solid #E5E7EB; color: #6B7280;
  padding: 4px 10px; border-radius: 6px; cursor: pointer;
  font-size: 11.5px; font-weight: 500; font-family: inherit;
}
.regen-btn:hover:not(:disabled) { color: #D4212C; border-color: #D4212C; background: #FDECED; }
.regen-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.regen-btn i { font-size: 12px; }
.edit-field input, .edit-field textarea {
  width: 100%; padding: 10px 12px;
  border: 1px solid #E5E7EB; border-radius: 6px;
  font-family: 'Inter', sans-serif; font-size: 14px; color: #111;
  background: #fff; resize: vertical; line-height: 1.5;
}
.edit-field input:focus, .edit-field textarea:focus {
  outline: none; border-color: #D4212C;
  box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}

/* FOOTER (actions) */
.ec-footer {
  display: flex; gap: 8px; padding: 12px 18px;
  background: #FAFAF7; border-top: 1px solid #E5E7EB;
  flex-wrap: wrap;
}

.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 8px;
  font-size: 13px; font-weight: 500; border: 1px solid transparent;
  cursor: pointer; font-family: inherit;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.btn i { font-size: 14px; }
.btn-primary { background: #D4212C; color: #fff; border-color: #D4212C; margin-left: auto; }
.btn-primary:hover:not(:disabled) { background: #8F1018; border-color: #8F1018; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: #fff; color: #374151; border-color: #E5E7EB; }
.btn-ghost:hover { background: #F9FAFB; border-color: #D1D5DB; color: #111; }
.btn-ghost.btn-danger { color: #6B7280; }
.btn-ghost.btn-danger:hover { color: #991B1B; border-color: #FCA5A5; background: #FEF2F2; }
.btn-ghost.btn-success { color: #6B7280; }
.btn-ghost.btn-success:hover { color: #166534; border-color: #86EFAC; background: #F0FDF4; }
`;
