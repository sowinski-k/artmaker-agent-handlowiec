'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { api, getToken } from '@/lib/api';

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

interface SearchResponse {
  places: DiscoveredPlace[];
  diagnostics: Array<{ source: string; places: unknown[]; error?: string; duration_s?: number }>;
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

export default function PozyskiwaniePage() {
  const router = useRouter();
  const [segment, setSegment] = useState('sklep_papierniczy');
  const [location, setLocation] = useState('');
  const [customTarget, setCustomTarget] = useState('');
  const [maxPerSource, setMaxPerSource] = useState(50);
  const [selectedSources, setSelectedSources] = useState<string[]>(['google_places']);
  const [autoResearch, setAutoResearch] = useState(false);
  const [autoDraft, setAutoDraft] = useState(false);
  const [relevanceThreshold, setRelevanceThreshold] = useState(6);

  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<DiscoveredPlace[] | null>(null);
  const [diag, setDiag] = useState<SearchResponse['diagnostics']>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [log, setLog] = useState<string[]>([]);
  const [bulkRunning, setBulkRunning] = useState(false);

  useEffect(() => {
    if (!getToken()) router.push('/login');
  }, [router]);

  function toggleSource(key: string) {
    setSelectedSources((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (selectedSources.length === 0) {
      alert('Wybierz przynajmniej jedno źródło.');
      return;
    }
    setSearching(true);
    setResults(null);
    setSelected(new Set());
    setLog([]);
    try {
      const phrase = customTarget.trim() || segment.replace(/_/g, ' ');
      const query = location.trim() ? `${phrase} ${location.trim()}` : phrase;
      const res = await api<SearchResponse>('/api/discovery/search', {
        method: 'POST',
        body: JSON.stringify({
          query,
          sources: selectedSources,
          max_per_source: maxPerSource,
          segment,
          location: location.trim() || null,
          custom_description: customTarget.trim() || null,
          use_relevance_filter: true,
        }),
      });
      setResults(res.places);
      setDiag(res.diagnostics);
      // Auto-select trafnych
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

      if (autoResearch && auto.size > 0) {
        void runBulkResearch(res.places, Array.from(auto));
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Błąd wyszukiwania');
    } finally {
      setSearching(false);
    }
  }

  async function runBulkResearch(allPlaces: DiscoveredPlace[], indices: number[]) {
    setBulkRunning(true);
    setLog([]);
    let ok = 0, fail = 0, skipped = 0, drafts = 0;
    for (const idx of indices) {
      const p = allPlaces[idx];
      if (!p?.website) continue;
      setLog((prev) => [...prev, `→ ${p.name}: researchuję...`]);
      try {
        const res = await api<{ lead_id: number; was_researched: boolean; score: number; company: string }>(
          '/api/research', {
          method: 'POST',
          body: JSON.stringify({
            url: p.website,
            segment_hint: segment,
            city_hint: location || null,
          }),
        });
        if (!res.was_researched) {
          skipped++;
          setLog((prev) => [...prev, `⏭️ ${p.name}: już w bazie (#${res.lead_id})`]);
        } else {
          ok++;
          setLog((prev) => [...prev, `✅ ${p.name}: #${res.lead_id}, score ${res.score}/10`]);
          if (autoDraft && res.score >= 7) {
            try {
              const d = await api<{ draft_id: number }>('/api/drafts', {
                method: 'POST',
                body: JSON.stringify({ lead_id: res.lead_id }),
              });
              drafts++;
              setLog((prev) => [...prev, `   ✉️ draft #${d.draft_id} gotowy`]);
            } catch (e) {
              setLog((prev) => [...prev, `   ⚠️ draft padł: ${e instanceof Error ? e.message : e}`]);
            }
          }
        }
      } catch (err) {
        fail++;
        setLog((prev) => [...prev, `❌ ${p.name}: ${err instanceof Error ? err.message : 'błąd'}`]);
      }
    }
    setLog((prev) => [...prev, '', `=== ${ok} OK · ${skipped} duplikatów · ${fail} błędów · ${drafts} draftów ===`]);
    setBulkRunning(false);
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="topbar">
        <div className="crumb">
          Workspace <i className="ti ti-chevron-right" /> <strong>Ecombinat</strong>
          <i className="ti ti-chevron-right" /> Pozyskiwanie
        </div>
        <div className="search">
          <i className="ti ti-search" />
          Szukaj…
          <span className="kbd">⌘K</span>
        </div>
        <div className="avatar">EC</div>
      </div>

      <div className="content">
        <div className="page-head">
          <div>
            <h1>Pozyskiwanie leadów</h1>
            <p>Znajdź nowe firmy w Google Maps / Apify / LinkedIn z filtrem trafności LLM.</p>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <div className="card-title"><i className="ti ti-search" /> Wyszukiwanie</div>
          </div>
          <form onSubmit={handleSearch} className="card-body">
            <div className="form-row">
              <div className="field">
                <label>Segment</label>
                <select value={segment} onChange={(e) => setSegment(e.target.value)}>
                  {SEGMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Lokalizacja (miasto / województwo / "Polska")</label>
                <input type="text" value={location} onChange={(e) => setLocation(e.target.value)}
                  placeholder="np. Warszawa" />
              </div>
              <div className="field" style={{ maxWidth: 140 }}>
                <label>Max / źródło (1-200)</label>
                <input type="number" value={maxPerSource} min={1} max={200}
                  onChange={(e) => setMaxPerSource(parseInt(e.target.value) || 50)} />
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
                <input type="checkbox" checked={autoResearch}
                  onChange={(e) => setAutoResearch(e.target.checked)} />
                <span>🔥 Auto-research po wyszukaniu</span>
              </label>
              <label className="check">
                <input type="checkbox" checked={autoDraft}
                  onChange={(e) => setAutoDraft(e.target.checked)} />
                <span>✉️ Auto-draft jeśli score ≥ 7</span>
              </label>
              <div className="field" style={{ maxWidth: 200 }}>
                <label>Próg trafności</label>
                <input type="range" min={0} max={10} value={relevanceThreshold}
                  onChange={(e) => setRelevanceThreshold(parseInt(e.target.value))} />
                <span className="mono" style={{ fontSize: 12 }}>≥ {relevanceThreshold}</span>
              </div>
            </div>

            <button type="submit" className="btn btn-primary" disabled={searching}>
              {searching ? 'Szukam…' : '🚀 Szukaj'}
            </button>
          </form>
        </div>

        {diag.length > 0 && (
          <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            {diag.map((d) => (
              <div key={d.source} style={{
                padding: '6px 12px', borderRadius: 6, fontSize: 12,
                background: d.error ? '#fef2f2' : '#FDECED',
                color: d.error ? '#8F1018' : '#8F1018',
                border: `1px solid ${d.error ? '#fecaca' : 'rgba(212,33,44,0.15)'}`,
              }}>
                <strong>{d.source}</strong>: {d.error || `${(d.places as unknown[]).length} firm · ${d.duration_s}s`}
              </div>
            ))}
          </div>
        )}

        {results && (
          <div className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <div className="card-title">
                <i className="ti ti-list" /> Wyniki ({results.length})
                {results.some((r) => r.existing_lead_id) && (
                  <span style={{ fontSize: 12, color: '#6B7280', marginLeft: 8 }}>
                    · {results.filter((r) => r.existing_lead_id).length} już w bazie
                  </span>
                )}
              </div>
              <div className="card-actions">
                <span style={{ fontSize: 12 }}>Zaznaczonych: {selected.size}</span>
                <button className="btn btn-primary" disabled={bulkRunning || selected.size === 0}
                  onClick={() => runBulkResearch(results, Array.from(selected))}>
                  {bulkRunning ? 'Pracuję…' : `Researchuj ${selected.size}`}
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
                  <th>Status</th>
                  <th>WWW</th>
                </tr>
              </thead>
              <tbody>
                {results.map((p, i) => {
                  const dup = p.existing_lead_id != null;
                  const rel = p.relevance;
                  return (
                    <tr key={`${p.source}-${i}`} style={{ opacity: dup ? 0.5 : 1 }}>
                      <td>
                        <input type="checkbox" checked={selected.has(i)}
                          disabled={!p.website || dup}
                          onChange={() => {
                            const s = new Set(selected);
                            s.has(i) ? s.delete(i) : s.add(i);
                            setSelected(s);
                          }} />
                      </td>
                      <td><strong>{p.name}</strong>{dup && <span style={{ color: '#6B7280', fontSize: 11 }}> · w bazie #{p.existing_lead_id}</span>}</td>
                      <td style={{ color: '#6B7280' }}>{p.address || '-'}</td>
                      <td className="num">{p.rating?.toFixed(1) || '-'}</td>
                      <td className="num">{rel ? rel.score : '-'}</td>
                      <td><span style={{ color: '#6B7280', fontSize: 12 }}>{rel?.reason || ''}</span></td>
                      <td>
                        {p.website ? (
                          <a href={p.website} target="_blank" rel="noopener" style={{ color: '#D4212C', fontSize: 12 }}>{p.website.slice(0, 30)}…</a>
                        ) : '-'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {log.length > 0 && (
          <div className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <div className="card-title"><i className="ti ti-activity" /> Live log</div>
            </div>
            <pre style={{
              padding: 16, fontFamily: 'JetBrains Mono, monospace', fontSize: 12,
              color: '#111', background: '#FAFAF7', margin: 0,
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              maxHeight: 300, overflow: 'auto',
            }}>{log.join('\n')}</pre>
          </div>
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
.search { margin-left: auto; display: flex; align-items: center; gap: 8px; background: #FAFAF7; border: 1px solid #E5E7EB; border-radius: 6px; padding: 6px 10px; width: 280px; color: #6B7280; font-size: 13px; }
.kbd { margin-left: auto; font-family: 'JetBrains Mono', monospace; font-size: 10px; background: #fff; border: 1px solid #E5E7EB; padding: 1px 5px; border-radius: 3px; }
.avatar { width: 32px; height: 32px; border-radius: 50%; background: #1C1C1C; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 12px; border: 2px solid #D4212C; }
.content { padding: 24px; }
.page-head { margin-bottom: 20px; }
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-head p { color: #6B7280; font-size: 13.5px; margin: 0; }

.card { background: #fff; border: 1px solid #E5E7EB; border-radius: 8px; margin-bottom: 12px; }
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

.checkbox-row { display: flex; gap: 16px; flex-wrap: wrap; }
.check { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #111; cursor: pointer; }
.check input { margin: 0; cursor: pointer; }

.btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; font-family: inherit; }
.btn-primary { background: #D4212C; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #8F1018; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

table.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
table.tbl th { text-align: left; font-weight: 500; font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; padding: 10px 16px; background: #FAFAF7; border-bottom: 1px solid #E5E7EB; }
table.tbl th.num, table.tbl td.num { text-align: right; font-family: 'JetBrains Mono', monospace; }
table.tbl td { padding: 11px 16px; border-bottom: 1px solid #E5E7EB; }
table.tbl tr:last-child td { border-bottom: none; }
table.tbl tr:hover td { background: #FAFAF7; }
.mono { font-family: 'JetBrains Mono', monospace; }
`;
