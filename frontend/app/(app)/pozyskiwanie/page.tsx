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
import { useConfirm } from '@/lib/confirm';

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
  relevance_source?: 'llm' | 'heuristic' | 'none';
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

// Polskie etykiety segmentow + krotkie opisy do helper tekstu
const SEGMENT_INFO: Record<string, { label: string; desc: string }> = {
  sklep_plastyczny: { label: 'Sklep plastyczny', desc: 'Sklepy z farbami, płótnami, sztalugami - retail.' },
  sklep_papierniczy: { label: 'Sklep papierniczy', desc: 'Papier, biuro, szkolne, ozdobne, scrapbooking.' },
  paint_and_sip: { label: 'Paint & sip', desc: 'Studia malowania z winem dla dorosłych.' },
  warsztaty_dzieci: { label: 'Warsztaty dzieci', desc: 'Pracownie kreatywne, animacje urodzin.' },
  animatorzy_eventy: { label: 'Animatorzy / eventy', desc: 'Firmy eventowe organizujące zajęcia kreatywne.' },
  szkola_artystyczna: { label: 'Szkoła artystyczna', desc: 'Szkoły plastyczne, ogniska, kursy rysunku.' },
  marka_wlasna: { label: 'Marka własna / DIY', desc: 'Twórcy zestawów DIY, autorzy kursów, dystrybutorzy.' },
  inne: { label: 'Inne', desc: 'Bez konkretnego segmentu - LLM zaklasyfikuje.' },
};

// Sources z meta-info: opis, szacunkowy koszt, limit API. Bazuje na real cennikach
// Google Places New (Aug 2024) i Apify (Compass actors). Limity to twarde caps API.
interface SourceMeta {
  key: string;
  label: string;
  desc: string;
  costHint: string;        // dla cost estimate (USD per 1000 zapytan/items)
  costPer1000: number;     // do liczenia szacunku
  limit: number;           // twardy cap per query
  warning?: string;        // np. LinkedIn compliance
}

const SOURCES: SourceMeta[] = [
  {
    key: 'google_places',
    label: 'Google Places',
    desc: 'Bezpośrednio z Google. Najbogatsze pola (telefon, rating, kategoria, godziny). Najwyższa jakość.',
    costHint: '$25/1000',
    costPer1000: 25,
    limit: 60,
  },
  {
    key: 'apify',
    label: 'Apify Google Maps',
    desc: 'Apify scraper Google Maps - alternatywa dla Places API. Tańsze ale wolniejsze.',
    costHint: '$5/1000',
    costPer1000: 5,
    limit: 50,
  },
  {
    key: 'apify_allegro',
    label: 'Apify Allegro',
    desc: 'Sprzedawcy z Allegro - kandydaci na private label / hurt. Inny target niż Google Maps.',
    costHint: '$5/1000',
    costPer1000: 5,
    limit: 100,
  },
  {
    key: 'apify_linkedin',
    label: 'Apify LinkedIn',
    desc: 'Firmy z LinkedIna. UWAGA: TOS LinkedIn + RODO - używaj ostrożnie i tylko dla B2B.',
    costHint: '$10/1000',
    costPer1000: 10,
    limit: 50,
    warning: 'TOS LinkedIn + RODO - sprawdź compliance przed włączeniem.',
  },
];

// 16 wojewodztw + top miasta - do datalist autocomplete'a w Lokalizacja
const POLSKA_LOCATIONS = [
  // Wojewodztwa (z polskimi znakami zgodnie z nazewnictwem urzedowym)
  'Dolnośląskie', 'Kujawsko-Pomorskie', 'Lubelskie', 'Lubuskie',
  'Łódzkie', 'Małopolskie', 'Mazowieckie', 'Opolskie',
  'Podkarpackie', 'Podlaskie', 'Pomorskie', 'Śląskie',
  'Świętokrzyskie', 'Warmińsko-Mazurskie', 'Wielkopolskie', 'Zachodniopomorskie',
  // Top miasta wojewodzkie
  'Warszawa', 'Kraków', 'Łódź', 'Wrocław', 'Poznań', 'Gdańsk',
  'Szczecin', 'Bydgoszcz', 'Lublin', 'Białystok', 'Katowice', 'Gdynia',
  'Częstochowa', 'Radom', 'Sosnowiec', 'Toruń', 'Kielce', 'Rzeszów',
  'Gliwice', 'Zabrze', 'Olsztyn', 'Bielsko-Biała', 'Bytom', 'Zielona Góra',
  'Rybnik', 'Ruda Śląska', 'Tychy', 'Opole', 'Gorzów Wielkopolski',
  'Płock', 'Elbląg', 'Wałbrzych',
];

type Mode = 'manual' | 'agent';
type Flash = { kind: 'success' | 'error' | 'info'; text: string };

export default function PozyskiwaniePage() {
  const router = useRouter();
  const confirm = useConfirm();
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
  const [peekRelevanceSource, setPeekRelevanceSource] = useState<string | null>(null);
  const [peekCap, setPeekCap] = useState<{ used: number; cap: number } | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Job tracking (manual bulk research + agent mode)
  const [activeJob, setActiveJob] = useState<JobInfo | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Globalny flash zamiast alert()
  const [flash, setFlash] = useState<Flash | null>(null);

  // Cost estimate - liczy szacunek na podstawie wybranych zrodel x max/source +
  // LLM relevance check (gemini-flash-lite ~$0.001/lead).
  const costEstimate = (() => {
    let usd = 0;
    for (const key of selectedSources) {
      const src = SOURCES.find((s) => s.key === key);
      if (src) {
        // (max/1000) * cost_per_1000 = USD per source
        usd += (Math.min(maxPerSource, src.limit) / 1000) * src.costPer1000;
      }
    }
    // Plus LLM relevance check dla wszystkich znalezionych (tani model)
    const totalLeads = selectedSources.length * Math.min(maxPerSource, 100);
    usd += totalLeads * 0.0005;  // ~$0.5 per 1000
    return usd;
  })();

  // Auto-dismiss flash po 5s
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

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

  // Custom queries per segment - lepsze niz raw "warsztaty dzieci" ktore
  // wciaga z Google Maps wszystko (Minecraft, kulinarne, jezykow). Bardziej
  // specyficzny query = mniej smieci na input = mniej palonych tokenow LLM.
  const SEGMENT_QUERY_HINTS: Record<string, string> = {
    sklep_plastyczny: 'sklep plastyczny artykuly malarskie',
    sklep_papierniczy: 'sklep papierniczy artykuly biurowe',
    paint_and_sip: 'paint and sip malowanie z winem',
    warsztaty_dzieci: 'warsztaty plastyczne kreatywne dla dzieci',
    animatorzy_eventy: 'animatorzy eventy warsztaty kreatywne',
    szkola_artystyczna: 'szkola artystyczna plastyczna ognisko',
    marka_wlasna: 'zestawy DIY kreatywne marka wlasna',
    inne: 'artykuly plastyczne kreatywne',
  };

  function buildQuery() {
    // Custom target ma pierwszeństwo (user wpisuje co chce)
    if (customTarget.trim()) {
      const phrase = customTarget.trim();
      return location.trim() ? `${phrase} ${location.trim()}` : phrase;
    }
    // Inaczej - specyficzny query per segment, nie raw "warsztaty_dzieci"
    const phrase = SEGMENT_QUERY_HINTS[segment] || segment.replace(/_/g, ' ');
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
      setFlash({ kind: 'error', text: 'Wybierz przynajmniej jedno źródło danych.' });
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
      setPeekRelevanceSource(res.relevance_source || null);

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
      setFlash({
        kind: 'success',
        text: `Znalazłem ${res.places.length} firm. ${auto.size} pasujących zaznaczonych automatycznie - sprawdź i kliknij "Researchuj".`,
      });
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Błąd wyszukiwania',
      });
    } finally {
      setPeeking(false);
    }
  }

  async function handleResearchSelected() {
    if (!peekResults || selected.size === 0) return;
    const selectedPlaces = Array.from(selected)
      .map((i) => peekResults[i])
      .filter((p): p is DiscoveredPlace => !!p && !!p.website);
    const urls = selectedPlaces.map((p) => p.website as string);
    if (urls.length === 0) return;

    // Force refresh jezeli ktorykolwiek zaznaczony jest duplikatem -
    // user swiadomie chce re-research (spala tokeny ponownie).
    const hasDuplicates = selectedPlaces.some((p) => p.existing_lead_id != null);
    if (hasDuplicates) {
      const dupCount = selectedPlaces.filter((p) => p.existing_lead_id != null).length;
      const ok = await confirm({
        title: dupCount === 1 ? 'Re-research duplikatu?' : `Re-research ${dupCount} duplikatów?`,
        message: (
          <>
            Wybrane firmy są już w Twojej bazie. Możemy je sprawdzić ponownie,
            ale to <strong>spali ponownie tokeny LLM</strong> (orientacyjnie
            ~$0.01-0.05 za firmę).
            <br /><br />
            Score i dane zostaną zaktualizowane na świeższe.
          </>
        ),
        confirmLabel: 'Tak, sprawdź ponownie',
        cancelLabel: 'Anuluj',
        icon: 'refresh',
      });
      if (!ok) {
        setSubmitting(false);
        return;
      }
    }

    setSubmitting(true);
    try {
      const res = await api<{ job_id: number; total: number }>('/api/research/bulk', {
        method: 'POST',
        body: JSON.stringify({
          urls,
          segment_hint: segment,
          city_hint: location || null,
          auto_draft_threshold: autoDraft ? 7 : null,
          force_refresh: hasDuplicates,
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
      setFlash({
        kind: 'info',
        text: `${msg} Pokazuję aktualnie pracującego agenta poniżej.`,
      });
      try {
        const job = await api<JobInfo>(`/api/jobs/${e.detail.active_job_id}`);
        setActiveJob(job);
        if (job.status === 'pending' || job.status === 'running') {
          startJobPolling(job.id);
        }
      } catch {/* ignore */}
      return;
    }
    setFlash({ kind: 'error', text: e.message || fallbackMsg });
  }

  async function handleSendAgent(e: React.FormEvent) {
    e.preventDefault();
    if (selectedSources.length === 0) {
      setFlash({ kind: 'error', text: 'Wybierz przynajmniej jedno źródło danych.' });
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

      {/* Global flash (zamiast alert) */}
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
          <div className={`job-card ${jobActive ? 'active' : ''}`}>
            <div className="job-head">
              <div className="job-head-left">
                {jobActive ? (
                  <div className="job-ring-wrap">
                    <span className="job-ring" />
                  </div>
                ) : (
                  <div className={`job-icon-wrap ${activeJob.status}`}>
                    <i className={`ti ti-${activeJob.status === 'done' ? 'check' : 'x'}`} />
                  </div>
                )}
                <div>
                  <div className="job-title">
                    {jobActive ? (
                      <>
                        <span className="dot-pulse" />
                        {activeJob.type === 'discovery_pipeline'
                          ? <>Agent w terenie<span className="working-dots" /></>
                          : activeJob.type === 'bulk_research_leads'
                          ? <>Researchuję leady<span className="working-dots" /></>
                          : <>Agent pracuje<span className="working-dots" /></>}
                      </>
                    ) : activeJob.status === 'done' ? 'Gotowe!' :
                     activeJob.status === 'failed' ? 'Job padł' : 'Anulowano'}
                  </div>
                  {jobActive && (
                    <div className="job-subtitle">
                      Pracuję w tle - możesz wylogować się, agent leci dalej
                    </div>
                  )}
                </div>
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
                  {jobActive ? (
                    <span className="working-now">
                      <span className="dot-pulse" />
                      Pracuje nad {activeJob.progress + 1}-tym z {activeJob.total}
                      <span className="working-dots" />
                    </span>
                  ) : (
                    <span>{activeJob.progress} / {activeJob.total} przerobione</span>
                  )}
                  <span className="mono">job #{activeJob.id}</span>
                </div>
              </>
            )}
            {!activeJob.total && jobActive && (
              <div className="progress-meta">
                <span className="working-now">
                  <span className="dot-pulse" />
                  Agent znajduje miejsca<span className="working-dots" />
                </span>
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
                  {SEGMENTS.map((s) => (
                    <option key={s} value={s}>
                      {SEGMENT_INFO[s]?.label || s}
                    </option>
                  ))}
                </select>
                <span className="field-hint">
                  {SEGMENT_INFO[segment]?.desc || ''}
                </span>
              </div>
              <div className="field">
                <label>Lokalizacja (miasto / województwo)</label>
                <input
                  type="text"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="np. Warszawa, Mazowieckie"
                  list="pl-locations"
                />
                <datalist id="pl-locations">
                  {POLSKA_LOCATIONS.map((loc) => (
                    <option key={loc} value={loc} />
                  ))}
                </datalist>
                <span className="field-hint">
                  Wpisz miasto albo wybierz z listy 16 województw + top miast PL.
                </span>
              </div>
              <div className="field" style={{ maxWidth: 200 }}>
                <label>Max / źródło</label>
                <input type="number" value={maxPerSource} min={1} max={100}
                  onChange={(e) => setMaxPerSource(parseInt(e.target.value) || 50)} />
                <span className="field-hint">
                  Twarde limity API: Google Places 60, Apify Maps 50, Allegro 100, LinkedIn 50.
                </span>
              </div>
            </div>

            <div className="field">
              <label>Własny opis targetu <span style={{ fontWeight: 400, color: '#9CA3AF' }}>(opcjonalny, nadpisuje segment)</span></label>
              <textarea value={customTarget} onChange={(e) => setCustomTarget(e.target.value)}
                placeholder="np. 'producenci sztalug i ram do obrazów', 'paint&sip studia z winem'"
                rows={2} />
            </div>

            <div className="field">
              <label>Źródła danych</label>
              <div className="source-grid">
                {SOURCES.map((s) => {
                  const checked = selectedSources.includes(s.key);
                  return (
                    <label
                      key={s.key}
                      className={`source-card ${checked ? 'on' : ''} ${s.warning ? 'has-warning' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSource(s.key)}
                      />
                      <div className="src-content">
                        <div className="src-head">
                          <span className="src-label">{s.label}</span>
                          <span className="src-cost" title={`Szacunkowy koszt: ${s.costHint}`}>
                            {s.costHint}
                          </span>
                        </div>
                        <div className="src-desc">{s.desc}</div>
                        <div className="src-foot">
                          Limit API: {s.limit} / zapytanie
                        </div>
                        {s.warning && (
                          <div className="src-warning">
                            <i className="ti ti-alert-triangle" /> {s.warning}
                          </div>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="form-row" style={{ alignItems: 'center' }}>
              <div className="field" style={{ maxWidth: 280 }}>
                <label>
                  Próg trafności LLM ≥ <strong>{relevanceThreshold}</strong>/10
                </label>
                <input
                  type="range" min={0} max={10}
                  value={relevanceThreshold}
                  onChange={(e) => setRelevanceThreshold(parseInt(e.target.value))}
                />
                <span className="field-hint">
                  {relevanceThreshold <= 4 && 'Luźny - sprawdzimy też mniej dopasowane firmy.'}
                  {relevanceThreshold === 5 && 'Średni - rozsądny default.'}
                  {relevanceThreshold === 6 && 'Standardowy - typowy próg "dobry lead".'}
                  {relevanceThreshold === 7 && 'Wymagający - tylko jasno pasujące firmy.'}
                  {relevanceThreshold >= 8 && 'Surowy - tylko top - może wyrzucić sporo.'}
                </span>
              </div>
              <label className="check check-card">
                <input
                  type="checkbox"
                  checked={autoDraft}
                  onChange={(e) => setAutoDraft(e.target.checked)}
                />
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                    <i className="ti ti-mail" /> Auto-draft jeśli score ≥ 7
                  </div>
                  <div style={{ fontSize: 11, color: '#6B7280', marginTop: 2 }}>
                    Po researchu agent wygeneruje draft maila dla hot leadów (zużywa więcej tokenów).
                  </div>
                </div>
              </label>
            </div>

            {/* COST ESTIMATE - real-time pod button */}
            <div className="cost-estimate">
              <div className="ce-row">
                <span className="ce-k">Szacunkowy koszt API:</span>
                <span className="ce-v">
                  {selectedSources.length === 0 ? (
                    <span style={{ color: '#9CA3AF' }}>wybierz źródła</span>
                  ) : (
                    <strong>~${costEstimate.toFixed(2)}</strong>
                  )}
                </span>
              </div>
              <div className="ce-hint">
                {selectedSources.length > 0 && (
                  <>
                    {selectedSources.length} {selectedSources.length === 1 ? 'źródło' : 'źródła'} ×
                    do {maxPerSource} firm + LLM filtr trafności.
                    {' '}Ostateczna liczba leadów zależy od deduplikacji i progu trafności.
                  </>
                )}
              </div>
            </div>

            {(peeking || submitting) ? (
              // Pelnoekranowy "agent w akcji" panel zamiast disabled buttona.
              // Daje wizualne potwierdzenie ze cos sie dzieje + jakie zrodla
              // sprawdza w tej chwili (rotuje co 1.5s przez wybrane sources).
              <div className="agent-working-card">
                <div className="aw-spinner">
                  <span className="aw-ring" />
                </div>
                <div className="aw-content">
                  <div className="aw-title">
                    <span className="dot-pulse" />
                    {mode === 'manual' ? 'Agent szuka firm' : 'Agent wyrusza w teren'}
                    <span className="working-dots" />
                  </div>
                  <div className="aw-sources">
                    <SourceRotator sources={selectedSources} />
                  </div>
                  <div className="aw-progress">
                    <div className="aw-progress-fill" />
                  </div>
                  <div className="aw-foot">
                    {mode === 'manual'
                      ? 'Pobieram listę firm bez palenia tokenów. Zajmie 10-30s zależnie od ilości źródeł.'
                      : 'Tworzę zadanie w kolejce. Worker za chwilę podpie agenta.'}
                  </div>
                </div>
              </div>
            ) : (
              <button type="submit" className="btn btn-primary btn-cta"
                disabled={!!jobActive || selectedSources.length === 0}>
                {mode === 'manual'
                  ? <><i className="ti ti-search" /> Zajrzyj na rynek</>
                  : <><i className="ti ti-rocket" /> Wyślij agenta w teren</>}
              </button>
            )}
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

        {/* PEEK RESULTS - banner gdy relevance source != llm */}
        {mode === 'manual' && peekResults && peekRelevanceSource === 'heuristic' && (
          <div className="banner-warn" style={{ marginTop: 16 }}>
            <i className="ti ti-alert-triangle" />
            <div>
              <strong>Filtr trafnosci LLM nie zadzialal</strong> - pokazujemy
              heurystyczne score (na podstawie nazw firm). Mozliwe przyczyny:
              brak klucza Gemini, timeout, lub zbyt duzy batch.
              {' '}<strong>Sprawdz wyniki recznie</strong> - heurystyka jest mniej
              dokladna niz LLM. Sprawdz tez ze klucz GEMINI_API_KEY jest ustawiony
              w Railway Variables (backend service).
            </div>
          </div>
        )}

        {/* PEEK RESULTS - info gdy 0 zaznaczonych mimo wynikow.
            Diagnostyka per powod: duplikaty / brak URL / ponizej progu.
            Zamiast jednego mylacego komunikatu "nie przekroczyly progu trafnosci"
            (ktory byl falszywy gdy wszystkie 4 firmy mialy trafnosc 9-10 ale
            byly duplikatami) pokazujemy konkretne liczby per problem. */}
        {mode === 'manual' && peekResults && peekResults.length > 0 && selected.size === 0 && !peeking && (() => {
          const dupCount = peekResults.filter((r) => r.existing_lead_id != null).length;
          const noUrlCount = peekResults.filter((r) => !r.website && r.existing_lead_id == null).length;
          const belowThreshold = peekResults.filter((r) =>
            r.website &&
            r.existing_lead_id == null &&
            r.relevance &&
            r.relevance.score < relevanceThreshold,
          ).length;
          const noRelevance = peekResults.filter((r) =>
            r.website && r.existing_lead_id == null && !r.relevance,
          ).length;
          return (
            <div className="banner-info" style={{ marginTop: 16 }}>
              <i className="ti ti-info-circle" />
              <div>
                <strong>0 firm zaznaczonych automatycznie</strong> z {peekResults.length} wynikow.
                Przyczyny:
                <ul style={{ margin: '6px 0 0 18px', padding: 0, fontSize: 12.5 }}>
                  {dupCount > 0 && (
                    <li>
                      <strong>{dupCount}</strong> juz w bazie (duplikat).
                      Mozesz zaznaczyc recznie zeby <em>wymusic re-research</em> - tokeny LLM zostana spalone ponownie.
                    </li>
                  )}
                  {noUrlCount > 0 && (
                    <li>
                      <strong>{noUrlCount}</strong> bez strony WWW - nie da sie zresearchowac bez URL.
                      Sprawdz w Google i dodaj recznie w <Link href="/leady">/leady</Link> jezeli warto.
                    </li>
                  )}
                  {belowThreshold > 0 && (
                    <li>
                      <strong>{belowThreshold}</strong> ponizej progu trafnosci ({relevanceThreshold}/10).
                      Obnizyc prog w formularzu (np. na 4-5) albo zaznaczyc recznie.
                    </li>
                  )}
                  {noRelevance > 0 && (
                    <li>
                      <strong>{noRelevance}</strong> bez oceny LLM (filtr trafnosci wylaczony lub blad).
                      Mozesz zaznaczyc recznie wszystkie ktore wydaja sie sensowne.
                    </li>
                  )}
                </ul>
              </div>
            </div>
          );
        })()}

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
                {peekRelevanceSource === 'heuristic' && (
                  <span style={{ fontSize: 11, color: '#92400E', marginLeft: 8, fontWeight: 500 }}>
                    · trafnosc: heurystyka lokalna
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
                  const noUrl = !p.website;
                  const rel = p.relevance;
                  // Disabled tylko gdy nie ma URL - bez URL nie da sie zresearchowac.
                  // Duplikaty teraz mozna zaznaczyc -> backend force_refresh re-research.
                  const checkboxDisabled = noUrl;
                  const checkboxTitle = noUrl
                    ? 'Lead bez strony WWW - nie da sie zresearchowac. Dodaj recznie w /leady.'
                    : dup
                      ? `Duplikat (lead #${p.existing_lead_id}) - zaznaczenie wymusi re-research (spali tokeny LLM ponownie)`
                      : '';
                  return (
                    <tr key={`${p.source}-${i}`} style={{ opacity: dup || noUrl ? 0.55 : 1 }}>
                      <td>
                        <input type="checkbox" checked={selected.has(i)}
                          disabled={checkboxDisabled}
                          title={checkboxTitle}
                          onChange={() => {
                            const s = new Set(selected);
                            if (s.has(i)) s.delete(i); else s.add(i);
                            setSelected(s);
                          }} />
                      </td>
                      <td>
                        <strong>{p.name}</strong>
                        {dup && <span style={{ color: '#6B7280', fontSize: 11 }}> · w bazie #{p.existing_lead_id} (re-research mozliwy)</span>}
                        {noUrl && !dup && <span style={{ color: '#92400E', fontSize: 11 }}> · brak WWW</span>}
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

/**
 * Cyclic-rotating display sources. Pokazuje aktualnie sprawdzane zrodlo
 * podczas "agent szuka". Cycle co 1.5s przez wszystkie wybrane.
 *
 * Fake "co aktualnie robi" - backend tego nie zwraca w peek mode (peek
 * jest synchroniczne). Ale wizualnie daje user'owi poczucie ze nie wisi.
 */
function SourceRotator({ sources }: { sources: string[] }) {
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    if (sources.length === 0) return;
    const t = setInterval(() => setIdx((i) => (i + 1) % sources.length), 1500);
    return () => clearInterval(t);
  }, [sources.length]);

  if (sources.length === 0) return null;
  const current = SOURCES.find((s) => s.key === sources[idx]);
  return (
    <div className="aw-source-row">
      <span className="aw-source-label">Sprawdzam:</span>
      <span className="aw-source-name" key={idx}>
        <i className="ti ti-arrow-right" /> {current?.label || sources[idx]}
      </span>
      <span className="aw-source-count">
        {idx + 1} / {sources.length}
      </span>
    </div>
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
  border: 1px solid #E5E7EB;
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 16px;
}
/* GDY agent aktywny - red glow accent + pulse-bg "oddech" kontenera */
.job-card.active {
  background: linear-gradient(135deg, #FDECED 0%, #FAFAF7 60%, #fff 100%);
  border-color: #FCA5A5;
  box-shadow: 0 4px 20px -8px rgba(212,33,44,0.25);
  animation: jc-pulse-bg 2.5s ease-in-out infinite;
}
@keyframes jc-pulse-bg {
  0%, 100% { box-shadow: 0 4px 20px -8px rgba(212,33,44,0.25); }
  50%      { box-shadow: 0 4px 20px -8px rgba(212,33,44,0.4), 0 0 0 6px rgba(212,33,44,0.08); }
}

.job-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; gap: 12px; }
.job-head-left { display: flex; align-items: center; gap: 14px; }

/* Duzy spinner ring 48px - jak w drawer leadu, mocny visual */
.job-ring-wrap {
  display: flex; align-items: center; justify-content: center;
  width: 48px; height: 48px;
  background: #fff; border-radius: 50%;
  border: 1px solid #FCD8DB;
  flex-shrink: 0;
}
.job-ring {
  width: 28px; height: 28px;
  border: 3px solid #FDECED;
  border-top-color: #D4212C;
  border-right-color: #D4212C;
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}
/* Icon wrap dla finished states (done/failed/cancelled) */
.job-icon-wrap {
  display: flex; align-items: center; justify-content: center;
  width: 48px; height: 48px;
  border-radius: 50%;
  flex-shrink: 0;
  font-size: 22px;
}
.job-icon-wrap.done { background: #DCFCE7; color: #166534; }
.job-icon-wrap.failed { background: #FEE2E2; color: #991B1B; }
.job-icon-wrap.cancelled { background: #FAFAF7; color: #6B7280; }

.job-title {
  font-size: 16px;
  font-weight: 600;
  display: flex; align-items: center; gap: 8px;
  color: #111;
  line-height: 1.2;
}
.job-title .dot-pulse {
  width: 9px; height: 9px;
  flex-shrink: 0;
}
.job-subtitle {
  font-size: 11.5px;
  color: #6B7280;
  margin-top: 3px;
  line-height: 1.3;
}

.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.job-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }

/* Progress bar z 2 warstwami animacji:
   1. Glowna szerokosc (width %) - dyskretne update'y co poll
   2. Shimmer overlay (gdy job-card.active) - ciagly ruch, sygnal "zyje" */
.progress-bar {
  height: 10px;
  background: #FAFAF7;
  border-radius: 5px;
  overflow: hidden;
  margin-bottom: 8px;
  position: relative;
}
.progress-bar > div {
  height: 100%;
  background: linear-gradient(90deg, #D4212C, #8F1018);
  /* Plynniejszy transition - 0.8s ease-out zamiast 0.3s linear daje
     poczucie "wlewania sie" zamiast skoku */
  transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}
/* Shimmer overlay - widoczny TYLKO gdy job aktywny.
   Klasa .active dodawana do .job-card warunkowo. */
.job-card.active .progress-bar > div::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255,255,255,0.35) 30%,
    rgba(255,255,255,0.55) 50%,
    rgba(255,255,255,0.35) 70%,
    transparent 100%
  );
  animation: shimmer-progress 1.6s linear infinite;
  transform: translateX(-100%);
}
@keyframes shimmer-progress {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
/* Pulsing glow wokol progress bar gdy job aktywny - subtle "heartbeat" */
.job-card.active .progress-bar {
  box-shadow: 0 0 0 0 rgba(212,33,44,0.0);
  animation: pulse-glow 2s ease-in-out infinite;
}
@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(212,33,44,0.0); }
  50%      { box-shadow: 0 0 0 4px rgba(212,33,44,0.10); }
}

.progress-meta {
  display: flex; justify-content: space-between;
  font-size: 12px; color: #6B7280;
}
.progress-meta .mono { font-family: 'JetBrains Mono', monospace; }
.progress-meta .working-now {
  display: inline-flex; align-items: center; gap: 6px;
  color: #D4212C; font-weight: 500;
}
.working-now .dot-pulse {
  display: inline-block;
  width: 8px; height: 8px; border-radius: 50%;
  background: #D4212C;
  animation: dot-pulse 1.4s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { transform: scale(1);   opacity: 1;   }
  50%      { transform: scale(1.4); opacity: 0.6; }
}
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
/* '>' = direct child only, zeby nie lapac <label class="source-card"> wewnatrz .source-grid */
.field > label { font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 500; }
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

/* ============ GLOBAL FLASH ============ */
.global-flash {
  position: fixed; top: 64px; left: 50%; transform: translateX(-50%);
  z-index: 200; min-width: 320px; max-width: 600px;
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; border-radius: 8px;
  font-size: 13.5px; font-weight: 500;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  animation: slideDownFlash 0.2s ease-out;
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
@keyframes slideDownFlash {
  from { transform: translate(-50%, -10px); opacity: 0; }
  to { transform: translate(-50%, 0); opacity: 1; }
}

/* ============ FIELD HINTS ============ */
.field-hint {
  display: block;
  font-size: 11.5px;
  color: #6B7280;
  margin-top: 4px;
  line-height: 1.4;
}

/* ============ SOURCE GRID ============ */
.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
  margin-top: 6px;
}
.source-card {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  background: #fff;
  border: 1.5px solid #E5E7EB;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  align-items: flex-start;
}
.source-card:hover { border-color: #D1D5DB; background: #FAFAF7; }
.source-card.on {
  border-color: #D4212C;
  background: #FDECED;
}
.source-card.on:hover { background: #FCD8DB; }
.source-card input[type="checkbox"] {
  flex-shrink: 0;
  width: 18px; height: 18px;
  margin-top: 2px;
  accent-color: #D4212C;
  cursor: pointer;
}
.src-content { flex: 1; min-width: 0; }
.src-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; margin-bottom: 4px;
}
.src-label { font-weight: 600; font-size: 13.5px; color: #111; }
.src-cost {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
  color: #6B7280;
  background: #FAFAF7;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #E5E7EB;
}
.source-card.on .src-cost {
  background: #fff;
  border-color: #FCA5A5;
  color: #8F1018;
}
.src-desc {
  font-size: 12px; color: #4B5563;
  line-height: 1.4; margin-bottom: 6px;
}
.src-foot {
  font-size: 11px; color: #9CA3AF;
  font-family: 'JetBrains Mono', monospace;
}
.src-warning {
  margin-top: 8px;
  padding: 6px 8px;
  background: #FFF7ED;
  border: 1px solid #FED7AA;
  border-radius: 4px;
  font-size: 11px;
  color: #9A3412;
  display: flex; align-items: flex-start; gap: 6px;
  line-height: 1.4;
}
.src-warning i { font-size: 12px; margin-top: 1px; flex-shrink: 0; }

/* ============ CHECK CARD ============ */
.check-card {
  display: flex;
  gap: 10px;
  padding: 10px 14px;
  background: #fff;
  border: 1.5px solid #E5E7EB;
  border-radius: 10px;
  cursor: pointer;
  flex: 1; min-width: 260px;
  align-items: flex-start;
}
.check-card:hover { border-color: #D1D5DB; }
.check-card input[type="checkbox"] {
  width: 18px; height: 18px;
  margin-top: 2px;
  accent-color: #D4212C;
  flex-shrink: 0;
}
.check-card i { color: #D4212C; }

/* ============ COST ESTIMATE ============ */
.cost-estimate {
  background: #FAFAF7;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 12px 16px;
  margin-top: 8px;
}
.ce-row {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 12px;
}
.ce-k { font-size: 12px; color: #6B7280; font-weight: 500; }
.ce-v { font-size: 18px; font-family: 'JetBrains Mono', monospace; color: #111; }
.ce-v strong { font-weight: 700; }
.ce-hint {
  font-size: 11.5px;
  color: #9CA3AF;
  margin-top: 6px;
  line-height: 1.4;
}

/* ============ CTA BUTTON + SPINNER ============ */
.btn-cta { padding: 12px 24px; font-size: 14.5px; font-weight: 600; margin-top: 4px; }
.spinner-mini {
  display: inline-block;
  width: 14px; height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* ============ INFO BANNERS (warn / info) ============ */
.banner-warn, .banner-info {
  display: flex; gap: 12px; align-items: flex-start;
  padding: 14px 16px; border-radius: 10px;
  font-size: 13px; line-height: 1.5;
}
.banner-warn {
  background: #FFF7ED;
  border: 1px solid #FED7AA;
  color: #9A3412;
}
.banner-warn i {
  font-size: 18px;
  color: #C2410C;
  flex-shrink: 0;
  margin-top: 2px;
}
.banner-info {
  background: #EFF6FF;
  border: 1px solid #BFDBFE;
  color: #1E40AF;
}
.banner-info i {
  font-size: 18px;
  color: #2563EB;
  flex-shrink: 0;
  margin-top: 2px;
}

/* ============ AGENT WORKING CARD (zamiast disabled buttona "Szukam...") ============ */
.agent-working-card {
  display: flex; align-items: stretch; gap: 16px;
  padding: 16px 18px; margin-top: 4px;
  background: linear-gradient(135deg, #FDECED 0%, #FAFAF7 60%, #fff 100%);
  border: 1.5px solid #FCA5A5;
  border-radius: 12px;
  animation: aw-pulse-bg 2.5s ease-in-out infinite;
}
@keyframes aw-pulse-bg {
  0%, 100% { box-shadow: 0 0 0 0 rgba(212,33,44,0.0); }
  50%      { box-shadow: 0 0 0 6px rgba(212,33,44,0.10); }
}

.aw-spinner {
  display: flex; align-items: center; justify-content: center;
  width: 52px; height: 52px;
  background: #fff; border-radius: 50%;
  border: 1px solid #FCD8DB;
  flex-shrink: 0;
  position: relative;
}
.aw-ring {
  width: 32px; height: 32px;
  border: 3px solid #FDECED;
  border-top-color: #D4212C;
  border-right-color: #D4212C;
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}

.aw-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }

.aw-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 15px; font-weight: 600; color: #111;
}
.aw-title .dot-pulse {
  display: inline-block;
  width: 8px; height: 8px; border-radius: 50%;
  background: #D4212C;
  animation: dot-pulse 1.4s ease-in-out infinite;
}

/* Source rotator - aktualnie sprawdzane zrodlo */
.aw-sources {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px;
}
.aw-source-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.aw-source-label { color: #6B7280; font-size: 12px; }
.aw-source-name {
  display: inline-flex; align-items: center; gap: 4px;
  font-weight: 600; color: #8F1018;
  /* Re-mount na zmiane idx wywoluje fade animation */
  animation: fade-in 0.4s ease-out;
}
.aw-source-name i { font-size: 13px; }
.aw-source-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px; color: #9CA3AF;
  background: #fff; padding: 2px 8px;
  border-radius: 4px; border: 1px solid #FCD8DB;
}
@keyframes fade-in {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Indeterminate progress - 'agent zyje' */
.aw-progress {
  height: 4px;
  background: #fff;
  border: 1px solid #FCD8DB;
  border-radius: 2px;
  overflow: hidden;
}
.aw-progress-fill {
  height: 100%; width: 30%;
  background: linear-gradient(90deg, transparent, #D4212C 50%, transparent);
  animation: aw-indeterminate 1.4s ease-in-out infinite;
}
@keyframes aw-indeterminate {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(333%); }
}

.aw-foot {
  font-size: 11.5px;
  color: #6B7280;
  line-height: 1.4;
}

@keyframes spin { to { transform: rotate(360deg); } }
`;
