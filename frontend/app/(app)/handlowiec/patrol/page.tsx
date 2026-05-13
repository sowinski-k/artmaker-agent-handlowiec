/* Patrol mode - autonomiczny agent.
 *
 * User konfiguruje "patrol": segment + lokalizacje + cap dzienny + frequency.
 * Worker tick co 60s sprawdza wszystkie aktywne patrole, jak nadejdzie
 * next_run_at -> tworzy DISCOVERY_PIPELINE job. Wszystko leci 24/7.
 *
 * Sprzedazowe: "AI handlowiec ktory pracuje za ciebie".
 */

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { api, isAuthenticated } from '@/lib/api';

interface Patrol {
  id: number;
  name: string;
  enabled: boolean;
  segments: string[];
  locations: string[];
  sources: string[];
  custom_target: string | null;
  max_per_run: number;
  cap_per_day: number;
  frequency_hours: number;
  relevance_threshold: number;
  auto_draft_threshold: number | null;
  runs_today: number;
  total_runs: number;
  total_leads_found: number;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
}

const SEGMENTS = [
  'sklep_plastyczny', 'sklep_papierniczy', 'paint_and_sip',
  'warsztaty_dzieci', 'animatorzy_eventy', 'szkola_artystyczna',
  'marka_wlasna', 'inne',
];

const SOURCES = [
  { key: 'google_places', label: 'Google Places' },
  { key: 'apify', label: 'Apify Google Maps' },
  { key: 'apify_allegro', label: 'Apify Allegro' },
  { key: 'apify_linkedin', label: 'Apify LinkedIn' },
];

interface Form {
  name: string;
  enabled: boolean;
  segments: string[];
  locations: string[];     // text input split by commas -> array
  sources: string[];
  custom_target: string;
  max_per_run: number;
  cap_per_day: number;
  frequency_hours: number;
  relevance_threshold: number;
  auto_draft_threshold: number | null;
}

const EMPTY_FORM: Form = {
  name: '',
  enabled: true,
  segments: ['sklep_papierniczy'],
  locations: [],
  sources: ['google_places'],
  custom_target: '',
  max_per_run: 10,
  cap_per_day: 30,
  frequency_hours: 12,
  relevance_threshold: 6,
  auto_draft_threshold: null,
};

export default function PatrolPage() {
  const router = useRouter();
  const [patrols, setPatrols] = useState<Patrol[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<Form>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push('/login');
      return;
    }
    void fetchPatrols();
  }, [router]);

  async function fetchPatrols() {
    try {
      const list = await api<Patrol[]>('/api/patrol');
      setPatrols(list);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  function openNew() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  }

  function openEdit(p: Patrol) {
    setEditingId(p.id);
    setForm({
      name: p.name,
      enabled: p.enabled,
      segments: p.segments,
      locations: p.locations,
      sources: p.sources,
      custom_target: p.custom_target || '',
      max_per_run: p.max_per_run,
      cap_per_day: p.cap_per_day,
      frequency_hours: p.frequency_hours,
      relevance_threshold: p.relevance_threshold,
      auto_draft_threshold: p.auto_draft_threshold,
    });
    setShowForm(true);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const payload = {
        ...form,
        custom_target: form.custom_target.trim() || null,
      };
      if (editingId) {
        await api(`/api/patrol/${editingId}`, {
          method: 'PATCH', body: JSON.stringify(payload),
        });
      } else {
        await api('/api/patrol', {
          method: 'POST', body: JSON.stringify(payload),
        });
      }
      setShowForm(false);
      void fetchPatrols();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd zapisu');
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleEnabled(p: Patrol) {
    try {
      await api(`/api/patrol/${p.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: p.name, enabled: !p.enabled,
          segments: p.segments, locations: p.locations,
          sources: p.sources, custom_target: p.custom_target,
          max_per_run: p.max_per_run, cap_per_day: p.cap_per_day,
          frequency_hours: p.frequency_hours,
          relevance_threshold: p.relevance_threshold,
          auto_draft_threshold: p.auto_draft_threshold,
        }),
      });
      void fetchPatrols();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd');
    }
  }

  async function deletePatrol(id: number) {
    if (!confirm('Usunąć patrol? Już zebrane leady zostaną w bazie.')) return;
    try {
      await api(`/api/patrol/${id}`, { method: 'DELETE' });
      void fetchPatrols();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd');
    }
  }

  async function runNow(id: number) {
    try {
      const r = await api<{ msg: string }>(`/api/patrol/${id}/run-now`, { method: 'POST' });
      alert(r.msg);
      void fetchPatrols();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd');
    }
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CSS }} />
      <div className="topbar">
        <div className="crumb">
          <strong>Handlowiec</strong>
          <i className="ti ti-chevron-right" /> Patrol AI
        </div>
      </div>

      <div className="content">
        <div className="page-head">
          <div>
            <h1>Patrol AI - autonomiczny handlowiec</h1>
            <p>
              Skonfiguruj patrol raz. Agent sam co X godzin szuka leadów, robi research,
              generuje drafty. Nie musisz nic klikać - możesz spać.
            </p>
          </div>
          <button className="btn btn-primary" onClick={openNew}>
            <i className="ti ti-plus" /> Nowy patrol
          </button>
        </div>

        {loading ? (
          <div className="patrols-list">
            {[0, 1, 2].map((i) => (
              <div key={i} className="patrol-card on">
                <div className="pc-head">
                  <div className="pc-name" style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                    <span className="skel skel-circle" />
                    <span className="skel skel-line-lg skel-w-200" />
                    <span className="skel skel-pill" />
                  </div>
                  <div className="pc-actions" style={{ display: 'flex', gap: 8 }}>
                    <span className="skel skel-circle" />
                    <span className="skel skel-circle" />
                    <span className="skel skel-circle" />
                    <span className="skel skel-circle" />
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, padding: 16 }}>
                  <span className="skel skel-line" />
                  <span className="skel skel-line" />
                  <span className="skel skel-line" />
                  <span className="skel skel-line" />
                </div>
              </div>
            ))}
          </div>
        ) : patrols.length === 0 ? (
          <div className="empty-card">
            <i className="ti ti-radar-2" />
            <h3>Brak patroli</h3>
            <p>
              Stwórz pierwszy patrol - agent będzie automatycznie szukać nowych leadów
              co X godzin. Idealne dla "set & forget" - rano wstajesz, masz nowe drafty.
            </p>
            <button className="btn btn-primary" onClick={openNew}>
              <i className="ti ti-plus" /> Stwórz pierwszy patrol
            </button>
          </div>
        ) : (
          <div className="patrols-list">
            {patrols.map((p) => (
              <div className={`patrol-card ${p.enabled ? 'on' : 'off'}`} key={p.id}>
                <div className="pc-head">
                  <div className="pc-name">
                    <i className={`ti ti-${p.enabled ? 'radar-2' : 'radar-off'}`} />
                    {p.name}
                    <span className={`pc-badge ${p.enabled ? 'on' : 'off'}`}>
                      {p.enabled ? 'aktywny' : 'wyłączony'}
                    </span>
                  </div>
                  <div className="pc-actions">
                    <button className="btn-icon" onClick={() => runNow(p.id)} title="Odpal teraz" disabled={!p.enabled}>
                      <i className="ti ti-player-play" />
                    </button>
                    <button className="btn-icon" onClick={() => toggleEnabled(p)} title={p.enabled ? 'Wyłącz' : 'Włącz'}>
                      <i className={`ti ti-${p.enabled ? 'pause' : 'play'}`} />
                    </button>
                    <button className="btn-icon" onClick={() => openEdit(p)} title="Edytuj">
                      <i className="ti ti-edit" />
                    </button>
                    <button className="btn-icon danger" onClick={() => deletePatrol(p.id)} title="Usuń">
                      <i className="ti ti-trash" />
                    </button>
                  </div>
                </div>
                <div className="pc-config">
                  <span className="chip">
                    <i className="ti ti-target" /> {p.segments.join(', ') || p.custom_target || '-'}
                  </span>
                  {p.locations.length > 0 && (
                    <span className="chip">
                      <i className="ti ti-map-pin" /> {p.locations.join(', ')}
                    </span>
                  )}
                  <span className="chip">
                    <i className="ti ti-clock" /> co {p.frequency_hours}h
                  </span>
                  <span className="chip">
                    <i className="ti ti-bolt" /> max {p.max_per_run}/run · cap {p.cap_per_day}/dzień
                  </span>
                  {p.auto_draft_threshold && (
                    <span className="chip accent">
                      <i className="ti ti-mail" /> auto-draft ≥ {p.auto_draft_threshold}
                    </span>
                  )}
                </div>
                <div className="pc-stats">
                  <div className="pc-stat">
                    <span className="pcs-value mono">{p.runs_today}/{p.cap_per_day}</span>
                    <span className="pcs-label">dziś</span>
                  </div>
                  <div className="pc-stat">
                    <span className="pcs-value mono">{p.total_runs}</span>
                    <span className="pcs-label">total runów</span>
                  </div>
                  <div className="pc-stat">
                    <span className="pcs-value mono">{p.total_leads_found}</span>
                    <span className="pcs-label">leadów znaleziono</span>
                  </div>
                  <div className="pc-stat">
                    <span className="pcs-value mono">
                      {p.next_run_at ? formatRelative(p.next_run_at) : '-'}
                    </span>
                    <span className="pcs-label">następny tick</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {showForm && (
          <div className="modal-overlay" onClick={() => setShowForm(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-head">
                <h2>{editingId ? 'Edytuj patrol' : 'Nowy patrol'}</h2>
                <button className="btn-icon" onClick={() => setShowForm(false)}>
                  <i className="ti ti-x" />
                </button>
              </div>
              <form onSubmit={handleSubmit}>
                <div className="form-row">
                  <label>NAZWA</label>
                  <input
                    type="text" value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="np. Sklepy plastyczne - duże miasta"
                    required
                  />
                </div>

                <div className="form-row">
                  <label>SEGMENT (możesz wybrać kilka - patrol rotuje co tick)</label>
                  <div className="checkboxes">
                    {SEGMENTS.map((s) => (
                      <label key={s} className="cb">
                        <input
                          type="checkbox"
                          checked={form.segments.includes(s)}
                          onChange={(e) => {
                            setForm({
                              ...form,
                              segments: e.target.checked
                                ? [...form.segments, s]
                                : form.segments.filter((x) => x !== s),
                            });
                          }}
                        />
                        <span>{s.replace(/_/g, ' ')}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="form-row">
                  <label>LOKALIZACJE (oddzielone przecinkami, opcjonalne)</label>
                  <input
                    type="text"
                    value={form.locations.join(', ')}
                    onChange={(e) => setForm({
                      ...form,
                      locations: e.target.value
                        .split(',').map((s) => s.trim()).filter(Boolean),
                    })}
                    placeholder="Kraków, Warszawa, Wrocław"
                  />
                </div>

                <div className="form-row">
                  <label>WŁASNY OPIS (opcjonalne - nadpisuje segment)</label>
                  <textarea
                    value={form.custom_target}
                    onChange={(e) => setForm({ ...form, custom_target: e.target.value })}
                    rows={2}
                    placeholder="np. 'producenci ram do obrazów w Polsce'"
                  />
                </div>

                <div className="form-row">
                  <label>ŹRÓDŁA</label>
                  <div className="checkboxes">
                    {SOURCES.map((s) => (
                      <label key={s.key} className="cb">
                        <input
                          type="checkbox"
                          checked={form.sources.includes(s.key)}
                          onChange={(e) => {
                            setForm({
                              ...form,
                              sources: e.target.checked
                                ? [...form.sources, s.key]
                                : form.sources.filter((x) => x !== s.key),
                            });
                          }}
                        />
                        <span>{s.label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="form-grid">
                  <div className="form-row">
                    <label>MAX / RUN</label>
                    <input type="number" min={1} max={100}
                      value={form.max_per_run}
                      onChange={(e) => setForm({ ...form, max_per_run: parseInt(e.target.value) || 1 })}
                    />
                  </div>
                  <div className="form-row">
                    <label>CAP / DZIEŃ</label>
                    <input type="number" min={1} max={500}
                      value={form.cap_per_day}
                      onChange={(e) => setForm({ ...form, cap_per_day: parseInt(e.target.value) || 1 })}
                    />
                  </div>
                  <div className="form-row">
                    <label>CO ILE GODZIN</label>
                    <input type="number" min={1} max={168}
                      value={form.frequency_hours}
                      onChange={(e) => setForm({ ...form, frequency_hours: parseInt(e.target.value) || 1 })}
                    />
                  </div>
                  <div className="form-row">
                    <label>PRÓG TRAFNOŚCI (0-10)</label>
                    <input type="number" min={0} max={10}
                      value={form.relevance_threshold}
                      onChange={(e) => setForm({ ...form, relevance_threshold: parseInt(e.target.value) || 0 })}
                    />
                  </div>
                </div>

                <div className="form-row">
                  <label className="cb">
                    <input
                      type="checkbox"
                      checked={form.auto_draft_threshold !== null}
                      onChange={(e) => setForm({
                        ...form,
                        auto_draft_threshold: e.target.checked ? 7 : null,
                      })}
                    />
                    <span>Auto-draft jak score ≥</span>
                  </label>
                  {form.auto_draft_threshold !== null && (
                    <input type="number" min={1} max={10}
                      value={form.auto_draft_threshold}
                      onChange={(e) => setForm({ ...form, auto_draft_threshold: parseInt(e.target.value) || 7 })}
                      style={{ maxWidth: 100, marginTop: 6 }}
                    />
                  )}
                </div>

                <div className="form-row">
                  <label className="cb">
                    <input
                      type="checkbox"
                      checked={form.enabled}
                      onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                    />
                    <span>Aktywny od razu po zapisie</span>
                  </label>
                </div>

                <div className="form-actions">
                  <button type="button" className="btn btn-ghost" onClick={() => setShowForm(false)}>
                    Anuluj
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={submitting}>
                    {submitting ? 'Zapisuję...' : (editingId ? 'Zapisz zmiany' : 'Stwórz patrol')}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function formatRelative(iso: string): string {
  const t = new Date(iso).getTime();
  const now = Date.now();
  const diff = t - now;
  const abs = Math.abs(diff);
  const min = Math.floor(abs / 60000);
  const hr = Math.floor(min / 60);
  if (diff < 0) {
    if (min < 1) return 'teraz';
    if (min < 60) return `${min}min temu`;
    if (hr < 24) return `${hr}h temu`;
    return new Date(iso).toLocaleString('pl-PL');
  }
  if (min < 1) return 'za chwilę';
  if (min < 60) return `za ${min}min`;
  if (hr < 24) return `za ${hr}h`;
  return new Date(iso).toLocaleDateString('pl-PL');
}

const CSS = `
.topbar {
  background: #FFFFFF;
  border-bottom: 1px solid #E5E7EB;
  padding: 0 24px;
  display: flex; align-items: center;
  height: 52px; gap: 16px;
  position: sticky; top: 0; z-index: 10;
}
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #6B7280; }
.crumb strong { color: #1F2937; font-weight: 500; }
.crumb i { font-size: 12px; color: #9CA3AF; }
.content { padding: 24px; max-width: 1100px; }
.page-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 24px; gap: 16px;
}
.page-head h1 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 28px; font-weight: 700; margin: 0 0 6px;
  letter-spacing: -0.5px; color: #1F2937;
}
.page-head p { color: #6B7280; font-size: 14px; line-height: 1.55; max-width: 720px; }

.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 10px 16px; border-radius: 8px;
  font-size: 13px; font-weight: 500;
  cursor: pointer; border: 1px solid transparent;
  transition: all 0.15s;
}
.btn-primary { background: #D4212C; color: white; }
.btn-primary:hover:not(:disabled) { background: #8F1018; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-ghost { background: white; border-color: #E5E7EB; color: #1F2937; }
.btn-ghost:hover { background: #FAFAF7; }

.empty {
  padding: 60px; text-align: center; color: #6B7280;
}
.empty-card {
  background: white; border: 1px dashed #E5E7EB;
  border-radius: 12px; padding: 48px 32px;
  text-align: center; max-width: 560px; margin: 0 auto;
}
.empty-card > i { font-size: 48px; color: #D4212C; margin-bottom: 12px; }
.empty-card h3 { font-size: 18px; margin: 0 0 8px; color: #1F2937; }
.empty-card p { color: #6B7280; font-size: 13.5px; line-height: 1.5; margin: 0 0 18px; }

.patrols-list { display: flex; flex-direction: column; gap: 12px; }
.patrol-card {
  background: white; border: 1px solid #E5E7EB;
  border-radius: 12px; padding: 18px;
  transition: all 0.15s;
}
.patrol-card.on { border-left: 4px solid #16A34A; }
.patrol-card.off { border-left: 4px solid #9CA3AF; opacity: 0.85; }
.pc-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 12px;
}
.pc-name {
  display: flex; align-items: center; gap: 10px;
  font-size: 15px; font-weight: 600; color: #1F2937;
}
.pc-name i { color: #D4212C; font-size: 18px; }
.patrol-card.off .pc-name i { color: #9CA3AF; }
.pc-badge {
  font-size: 10px; font-family: 'JetBrains Mono', monospace;
  font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
  padding: 2px 8px; border-radius: 3px;
}
.pc-badge.on { background: rgba(22,163,74,0.15); color: #15803D; border: 1px solid rgba(22,163,74,0.25); }
.pc-badge.off { background: #F3F4F6; color: #6B7280; border: 1px solid #E5E7EB; }

.pc-actions { display: flex; gap: 6px; }
.btn-icon {
  width: 32px; height: 32px;
  background: #FAFAF7; border: 1px solid #E5E7EB;
  border-radius: 6px; cursor: pointer; color: #6B7280;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.btn-icon:hover:not(:disabled) { background: white; color: #1F2937; border-color: #9CA3AF; }
.btn-icon.danger:hover { color: #D4212C; border-color: rgba(212,33,44,0.4); }
.btn-icon:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-icon i { font-size: 14px; }

.pc-config {
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-bottom: 14px;
}
.chip {
  font-size: 11.5px; color: #1F2937;
  background: #FAFAF7; border: 1px solid #E5E7EB;
  padding: 4px 10px; border-radius: 5px;
  display: flex; align-items: center; gap: 4px;
}
.chip i { font-size: 12px; color: #6B7280; }
.chip.accent { background: rgba(212,33,44,0.08); border-color: rgba(212,33,44,0.2); color: #8F1018; }
.chip.accent i { color: #D4212C; }

.pc-stats {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 12px; padding-top: 12px;
  border-top: 1px solid #F3F4F6;
}
.pc-stat { display: flex; flex-direction: column; gap: 2px; }
.pcs-value {
  font-size: 16px; font-weight: 600;
  font-family: 'JetBrains Mono', monospace; color: #1F2937;
}
.pcs-label {
  font-size: 10.5px; color: #6B7280;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.mono { font-family: 'JetBrains Mono', monospace; }

/* Modal */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex; align-items: flex-start; justify-content: center;
  padding: 40px 20px; z-index: 100;
  overflow-y: auto;
}
.modal {
  background: white; border-radius: 12px;
  width: 100%; max-width: 720px;
  padding: 28px;
  box-shadow: 0 20px 50px rgba(0,0,0,0.15);
}
.modal-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 20px;
}
.modal-head h2 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 20px; font-weight: 700; margin: 0; color: #1F2937;
}
.form-row { margin-bottom: 16px; }
.form-row label {
  display: block; font-size: 11px; font-weight: 600;
  color: #6B7280; text-transform: uppercase; letter-spacing: 0.6px;
  margin-bottom: 6px;
}
.form-row label.cb {
  display: flex; align-items: center; gap: 8px;
  text-transform: none; letter-spacing: 0;
  font-size: 13px; font-weight: 400; color: #1F2937;
  cursor: pointer;
}
.form-row input[type=text], .form-row input[type=number], .form-row textarea, .form-row select {
  width: 100%; padding: 9px 12px;
  border: 1px solid #E5E7EB; border-radius: 6px;
  font-size: 13px; color: #1F2937; background: white;
  font-family: inherit;
}
.form-row textarea { resize: vertical; }
.form-row input:focus, .form-row textarea:focus, .form-row select:focus {
  outline: none; border-color: #D4212C;
  box-shadow: 0 0 0 3px rgba(212,33,44,0.1);
}
.form-grid {
  display: grid; grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.checkboxes {
  display: flex; flex-wrap: wrap; gap: 6px;
}
.cb {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12.5px; color: #1F2937;
  padding: 5px 10px; border: 1px solid #E5E7EB;
  background: #FAFAF7; border-radius: 5px; cursor: pointer;
}
.cb input { cursor: pointer; }
.cb:hover { background: white; border-color: #9CA3AF; }
.form-actions {
  display: flex; justify-content: flex-end; gap: 8px;
  margin-top: 20px; padding-top: 16px;
  border-top: 1px solid #F3F4F6;
}
`;
