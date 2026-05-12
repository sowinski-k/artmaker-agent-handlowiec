'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { api, getToken } from '@/lib/api';

interface Draft {
  id: number;
  lead_id: number;
  company: string;
  subject: string;
  snippet1: string;
  snippet2: string;
  snippet3: string;
  snippet4: string | null;
  snippet5: string;
  full_preview: string;
  status: string;
  template_variant: string | null;
  edited_by_user: boolean;
  created_at: string | null;
  sent_at: string | null;
}

interface Campaign {
  id: number;
  name: string;
  status: string | null;
}

const FIELD_LABELS: Record<string, string> = {
  subject: 'Subject',
  snippet1: 'Otwarcie',
  snippet2: 'Most do oferty',
  snippet3: 'Propozycja wartości',
  snippet4: 'Social proof (opcjonalny)',
  snippet5: 'CTA',
};

export default function DraftyPage() {
  const router = useRouter();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selectedCampaign, setSelectedCampaign] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<number | null>(null);
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [regenerating, setRegenerating] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) router.push('/login');
  }, [router]);

  async function load() {
    setLoading(true);
    try {
      const [d, c] = await Promise.all([
        api<Draft[]>('/api/drafts'),
        api<Campaign[]>('/api/woodpecker/campaigns').catch(() => []),
      ]);
      setDrafts(d);
      setCampaigns(c);
      if (c.length > 0 && selectedCampaign == null) setSelectedCampaign(c[0].id);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  function startEdit(d: Draft) {
    setEditing(d.id);
    setEditValues({
      subject: d.subject || '',
      snippet1: d.snippet1 || '',
      snippet2: d.snippet2 || '',
      snippet3: d.snippet3 || '',
      snippet4: d.snippet4 || '',
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
        body: JSON.stringify({
          ...editValues,
          snippet4: editValues.snippet4 || null,
        }),
      });
      setEditing(null);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd zapisu');
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
      alert(err instanceof Error ? err.message : 'Błąd regeneracji');
    } finally {
      setRegenerating(null);
    }
  }

  async function approve(draftId: number) {
    try {
      await api(`/api/drafts/${draftId}/approve`, { method: 'POST' });
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd');
    }
  }

  async function reject(draftId: number) {
    if (!confirm('Odrzucić draft? Nie da się tego cofnąć.')) return;
    try {
      await api(`/api/drafts/${draftId}/reject`, { method: 'POST' });
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd');
    }
  }

  async function send(draftId: number) {
    if (!selectedCampaign) {
      alert('Wybierz kampanię Woodpecker.');
      return;
    }
    if (!confirm('Wysłać draft do Woodpecker? Lead trafi do sekwencji follow-upów.')) return;
    try {
      const res = await api<{ prospect_id: string }>(`/api/drafts/${draftId}/send`, {
        method: 'POST',
        body: JSON.stringify({ campaign_id: selectedCampaign }),
      });
      alert(`✅ Wysłano. Woodpecker prospect_id: ${res.prospect_id || 'unknown'}`);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd wysyłki');
    }
  }

  function assemblePreview(): string {
    const { subject, snippet1, snippet2, snippet3, snippet4, snippet5 } = editValues;
    const parts = [`Subject: ${subject}`, '', snippet1, '', snippet2, '', snippet3];
    if (snippet4) parts.push('', snippet4);
    parts.push('', snippet5);
    return parts.join('\n');
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="topbar">
        <div className="crumb">
          Workspace <i className="ti ti-chevron-right" /> <strong>Ecombinat</strong>
          <i className="ti ti-chevron-right" /> Drafty
        </div>
        <div className="avatar">EC</div>
      </div>

      <div className="content">
        <div className="page-head">
          <div>
            <h1>Drafty cold-email</h1>
            <p>{drafts.length} draftów do review · wysłanych w Woodpecker po Twojej akceptacji</p>
          </div>
          {campaigns.length > 0 ? (
            <div className="field" style={{ maxWidth: 320 }}>
              <label>Kampania Woodpecker do wysyłki</label>
              <select value={selectedCampaign || ''} onChange={(e) => setSelectedCampaign(Number(e.target.value))}>
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>#{c.id} - {c.name} {c.status ? `[${c.status}]` : ''}</option>
                ))}
              </select>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: '#92400E', padding: '8px 12px', background: '#FEF3C7', borderRadius: 6 }}>
              ⚠️ Brak kampanii Woodpecker. Stwórz kampanię w UI Woodpecker żeby wysyłać.
            </div>
          )}
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#6B7280' }}>Ładowanie…</div>
        ) : drafts.length === 0 ? (
          <div className="card" style={{ padding: 40, textAlign: 'center', color: '#6B7280' }}>
            Brak draftów. Wygeneruj draft dla researchowanego leada w <a href="/leady" style={{ color: '#D4212C' }}>Leady</a>.
          </div>
        ) : (
          drafts.map((d) => (
            <div key={d.id} className="card draft-card">
              <div className="card-head">
                <div className="card-title">
                  <i className="ti ti-mail" /> #{d.id} · {d.company}
                  {d.edited_by_user && <span className="badge edited">✏️ edytowany</span>}
                  {d.template_variant?.includes('b2b_panel') && <span className="badge track-b">🏪 Panel B2B</span>}
                  {d.template_variant?.includes('private_label') && <span className="badge track-a">🏭 Private Label</span>}
                  {d.template_variant?.includes('both') && <span className="badge track-both">🔀 Obie</span>}
                </div>
                <div className="card-actions">
                  {editing !== d.id && (
                    <>
                      <button className="btn-icon" title="Edytuj" onClick={() => startEdit(d)}>
                        <i className="ti ti-edit" />
                      </button>
                      <button className="btn-icon danger" title="Odrzuć" onClick={() => reject(d.id)}>
                        <i className="ti ti-x" />
                      </button>
                      <button className="btn-icon success" title="Zatwierdź" onClick={() => approve(d.id)}>
                        <i className="ti ti-check" />
                      </button>
                      <button className="btn btn-primary btn-sm"
                        disabled={!selectedCampaign} onClick={() => send(d.id)}>
                        <i className="ti ti-send" /> Wyślij
                      </button>
                    </>
                  )}
                </div>
              </div>

              {editing === d.id ? (
                <div className="card-body">
                  {(['subject', 'snippet1', 'snippet2', 'snippet3', 'snippet4', 'snippet5'] as const).map((field) => (
                    <div className="field-row" key={field}>
                      <div style={{ flex: 1 }}>
                        <label>{FIELD_LABELS[field]}</label>
                        {field === 'subject' ? (
                          <input type="text" value={editValues[field] || ''}
                            onChange={(e) => setEditValues({ ...editValues, [field]: e.target.value })} />
                        ) : (
                          <textarea value={editValues[field] || ''}
                            onChange={(e) => setEditValues({ ...editValues, [field]: e.target.value })}
                            rows={field === 'snippet3' ? 4 : 3} />
                        )}
                      </div>
                      <button className="btn btn-secondary" title="Wygeneruj alternatywę"
                        onClick={() => regenerateField(d.id, field)}
                        disabled={regenerating === `${d.id}-${field}`}>
                        {regenerating === `${d.id}-${field}` ? '…' : '🎲'}
                      </button>
                    </div>
                  ))}
                  <div style={{ marginTop: 16, padding: 12, background: '#FAFAF7', borderRadius: 6, border: '1px solid #E5E7EB' }}>
                    <div style={{ fontSize: 11, color: '#6B7280', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 8 }}>Podgląd</div>
                    <pre style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, whiteSpace: 'pre-wrap', margin: 0 }}>{assemblePreview()}</pre>
                  </div>
                  <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                    <button className="btn btn-primary" onClick={() => saveEdit(d.id)}>💾 Zapisz</button>
                    <button className="btn btn-secondary" onClick={cancelEdit}>Anuluj</button>
                  </div>
                </div>
              ) : (
                <pre className="preview">{d.full_preview}</pre>
              )}
            </div>
          ))
        )}
      </div>
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
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 20px; }
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-head p { color: #6B7280; font-size: 13.5px; margin: 0; }

.field { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.field label { font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 500; }
.field select, .field input, .field textarea {
  padding: 8px 12px; border: 1px solid #E5E7EB; border-radius: 6px; font-family: inherit; font-size: 13.5px;
  background: #fff; color: #111;
}
.field select:focus, .field input:focus, .field textarea:focus {
  outline: none; border-color: #D4212C; box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}

.card { background: #fff; border: 1px solid #E5E7EB; border-radius: 8px; margin-bottom: 12px; }
.card-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #E5E7EB; gap: 12px; }
.card-title { font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.card-title i { color: #D4212C; font-size: 15px; }
.card-actions { display: flex; gap: 6px; align-items: center; }
.card-body { padding: 16px; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10.5px; font-weight: 600; letter-spacing: 0.5px; font-family: 'JetBrains Mono', monospace; }
.badge.edited { background: #FEF3C7; color: #92400E; }
.badge.track-a { background: #1C1C1C; color: #fff; }
.badge.track-b { background: #FDECED; color: #8F1018; }
.badge.track-both { background: #EFF6FF; color: #1E40AF; }

.preview { padding: 16px; margin: 0; font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: #111; white-space: pre-wrap; word-break: break-word; background: #fff; }

.btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 6px; font-size: 13.5px; font-weight: 500; border: none; cursor: pointer; font-family: inherit; }
.btn-sm { padding: 6px 12px; font-size: 12.5px; }
.btn-primary { background: #D4212C; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #8F1018; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: #fff; color: #111; border: 1px solid #E5E7EB; }
.btn-secondary:hover { background: #FAFAF7; }

.btn-icon { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border-radius: 6px; border: 1px solid #E5E7EB; background: #fff; cursor: pointer; color: #6B7280; }
.btn-icon:hover { color: #111; border-color: #D1D5DB; }
.btn-icon.danger:hover { color: #8F1018; border-color: #FCA5A5; background: #FEF2F2; }
.btn-icon.success:hover { color: #166534; border-color: #86EFAC; background: #DCFCE7; }

.field-row { display: flex; gap: 8px; align-items: flex-end; margin-bottom: 12px; }
.field-row label { display: block; font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 500; margin-bottom: 4px; }
.field-row input, .field-row textarea {
  width: 100%; padding: 8px 12px; border: 1px solid #E5E7EB; border-radius: 6px;
  font-family: inherit; font-size: 13.5px; background: #fff; color: #111; resize: vertical;
}
.field-row input:focus, .field-row textarea:focus {
  outline: none; border-color: #D4212C; box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}
`;
