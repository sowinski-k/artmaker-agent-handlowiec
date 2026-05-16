/* Pozyskiwanie leadów - dwa tryby:
 *
 *  1) Praca ręczna (peek + select + bulk research)
 *     - /api/discovery/peek SYNC: pokazuje listę firm bez palenia tokenów
 *     - user wybiera które researchować
 *     - /api/research/bulk -> BULK_RESEARCH_LEADS job -> worker
 *     - frontend polluje /api/jobs/{id}, pokazuje progress
 *
 *  2) Autonomous (cel + budzet, top miasta PL sam)
 *     - /api/discovery/autonomous -> AUTONOMOUS_DISCOVERY job
 *     - multi-segment chipy + bezposrednio do worker'a
 *     - user widzi live panel z hero "SEGMENT -> MIASTO"
 *
 * Stary tryb "Wyslij agenta w teren" (single-query discovery_pipeline)
 * usuniety - autonomous przejal funkcjonalnosc z wieksza widocznoscia.
 */

'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

import { api, isAuthenticated } from '@/lib/api';
import { AccountMenu } from '@/lib/AccountMenu';
import { useConfirm } from '@/lib/confirm';

interface DiscoveredPlace {
  source: string;
  name: string;
  website: string | null;
  address: string | null;
  phone: string | null;
  email: string | null;
  rating: number | null;
  review_count: number | null;
  existing_lead_id: number | null;
  existing_lead_score: number | null;
  relevance: { score: number; reason: string } | null;
}

interface PeekResponse {
  places: DiscoveredPlace[];
  diagnostics: Array<{ source: string; places: unknown[]; error?: string; duration_s?: number; note?: string }>;
  daily_used: number;
  daily_cap: number;
  relevance_source?: 'llm' | 'heuristic' | 'none' | 'cache';
  from_cache?: boolean;
  cached_at?: string | null;
  cached_run_id?: number;
  expand_stats?: {
    variants_total: number;
    cache_hits: number;
    api_calls: number;
    errors: number;
    places_before_dedup: number;
    places_after_dedup: number;
  };
}

interface DiscoveryHistoryItem {
  id: number;
  segment: string;
  location: string | null;
  sources: string[];
  query: string | null;
  result_count: number;
  leads_added: number;
  cost_usd: number | null;
  error: string | null;
  run_at: string;
  cache_active: boolean;
}

interface DiscoveryExclusion {
  id: number;
  exclusion_type: string;  // 'domain' | 'brand' | 'city_segment'
  value: string;
  reason: string | null;
  created_at: string;
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
    desc: 'Sklepy z Allegro w danej kategorii/keywordzie. Tylko discovery - email firmowy znajdziesz osobno przez Researchuj.',
    costHint: '$3-5/1000',
    costPer1000: 4,
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

// 'agent' (Wyslij agenta w teren) usuniety - duplikowal funkcjonalnosc
// autonomous z mniejszymi mozliwosciami. Mniej kodu = mniej miejsc na buga.
type Mode = 'manual' | 'autonomous';
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
  // Bulk discovery state - jeden klik = N jobow per city.
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  const [bulkCount, setBulkCount] = useState<30 | 50 | 100>(30);
  // Autonomous discovery - Faza 4
  const [autonomousTarget, setAutonomousTarget] = useState(50);
  const [autonomousBudget, setAutonomousBudget] = useState(5.0);
  const [autonomousSubmitting, setAutonomousSubmitting] = useState(false);
  // Multi-segment dla autonomicznego: pusta = uzyj `segment` (single, legacy),
  // niepusta = backend przerabia wszystkie segmenty z listy × miasta. Toggle
  // przez chip selector ponizej.
  const [autonomousSegments, setAutonomousSegments] = useState<string[]>([]);
  // Allegro query mode - widoczne tylko gdy 'apify_allegro' w selectedSources.
  // 'preset' = preset branzowy z core/industry_presets.py (najbardziej skalowalne)
  // 'keyword' = user wpisuje wlasne slowo kluczowe
  // 'category' = user wkleja URL kategorii Allegro
  const [allegroMode, setAllegroMode] = useState<'preset' | 'keyword' | 'category'>('preset');
  const [allegroPreset, setAllegroPreset] = useState('sklep_plastyczny');
  const [allegroKeyword, setAllegroKeyword] = useState('');
  const [allegroCategoryUrl, setAllegroCategoryUrl] = useState('');
  const [industryPresets, setIndustryPresets] = useState<{ key: string; label: string }[]>([]);

  // Peek state (manual)
  const [peeking, setPeeking] = useState(false);
  const [peekResults, setPeekResults] = useState<DiscoveredPlace[] | null>(null);
  const [peekDiag, setPeekDiag] = useState<PeekResponse['diagnostics']>([]);
  const [peekRelevanceSource, setPeekRelevanceSource] = useState<string | null>(null);
  const [peekCap, setPeekCap] = useState<{ used: number; cap: number } | null>(null);
  const [peekFromCache, setPeekFromCache] = useState<{ at: string | null; run_id?: number } | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Force refresh: jezeli zaznaczone, omijamy 30-dniowy cache i wywolujemy
  // API od nowa. Domyslnie OFF zeby chronic kredyty.
  const [forceRefresh, setForceRefresh] = useState(false);
  // Query expansion: zamiast jednego query "sklep papierniczy Warszawa" wyslij
  // serie wariantow (synonimy + dzielnice). Omija limit 60/query.
  const [expandQueries, setExpandQueries] = useState(false);
  const [peekExpandStats, setPeekExpandStats] = useState<PeekResponse['expand_stats'] | null>(null);
  // Historia discovery runow - lista lewa nad wynikami
  const [history, setHistory] = useState<DiscoveryHistoryItem[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  // Exclusions (wykluczenia per workspace) - panel ponizej historii
  const [exclusions, setExclusions] = useState<DiscoveryExclusion[]>([]);
  const [showExclusions, setShowExclusions] = useState(false);
  const [newExclusionType, setNewExclusionType] = useState<'domain' | 'brand'>('domain');
  const [newExclusionValue, setNewExclusionValue] = useState('');
  const [newExclusionReason, setNewExclusionReason] = useState('');

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

  // Pobierz presety branzy z backendu (uzywane gdy Allegro w trybie 'preset')
  useEffect(() => {
    let cancelled = false;
    api<{ key: string; label: string }[]>('/api/discovery/industry-presets')
      .then((data) => { if (!cancelled) setIndustryPresets(data); })
      .catch(() => { /* fallback - allegro mode 'preset' bedzie pusty */ });
    return () => { cancelled = true; };
  }, []);

  // Historia error state - widoczny jak fetch padl (zamiast silent fail)
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Pobierz historie discovery runow (do panelu "Historia").
  async function loadHistory() {
    try {
      const data = await api<DiscoveryHistoryItem[]>('/api/discovery/history?limit=50');
      setHistory(data);
      setHistoryError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Błąd nieznany';
      console.error('loadHistory failed:', err);
      setHistoryError(msg);
    }
  }

  // Pobierz exclusions (wykluczenia per workspace).
  async function loadExclusions() {
    try {
      const data = await api<DiscoveryExclusion[]>('/api/discovery/exclusions');
      setExclusions(data);
    } catch {
      /* niekrytyczne */
    }
  }

  async function addExclusion() {
    const value = newExclusionValue.trim();
    if (!value) {
      setFlash({ kind: 'error', text: 'Wartość nie może być pusta.' });
      return;
    }
    try {
      await api('/api/discovery/exclusions', {
        method: 'POST',
        body: JSON.stringify({
          exclusion_type: newExclusionType,
          value,
          reason: newExclusionReason.trim() || null,
        }),
      });
      setNewExclusionValue('');
      setNewExclusionReason('');
      await loadExclusions();
      setFlash({ kind: 'success', text: `Wykluczono ${newExclusionType}: ${value}` });
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd' });
    }
  }

  async function deleteExclusion(id: number) {
    try {
      await api(`/api/discovery/exclusions/${id}`, { method: 'DELETE' });
      await loadExclusions();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd' });
    }
  }

  useEffect(() => {
    void loadHistory();
    void loadExclusions();
  }, []);

  // Allegro source_queries - zbuduj na podstawie wybranego trybu.
  // Wraca null jak Allegro nie jest zaznaczone (zaden override).
  function buildAllegroQuery(): string | null {
    if (!selectedSources.includes('apify_allegro')) return null;
    if (allegroMode === 'keyword') return `keyword:${allegroKeyword.trim()}`;
    if (allegroMode === 'category') return `category:${allegroCategoryUrl.trim()}`;
    if (allegroMode === 'preset') return `preset:${allegroPreset}`;
    return null;
  }

  function buildSourceQueries(): Record<string, string> | undefined {
    const allegro = buildAllegroQuery();
    if (!allegro) return undefined;
    return { apify_allegro: allegro };
  }

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push('/login');
      return;
    }
    // Hydrate activeJob na load - jak user wraca/refreshuje strone, a backend
    // ma juz aktywny job discovery/bulk research/autonomous, odzyskujemy go
    // zeby live panel sie pokazal + zeby nie pozwolic na konflikt (manual+agent).
    // autonomous_discovery moze chodzic rownolegle z innymi - tez go hydratujemy
    // zeby uzytkownik widzial progress (top miasta + segmenty x miasta).
    (async () => {
      try {
        const running = await api<JobInfo[]>(
          '/api/jobs?status=running&limit=5'
        ).catch(() => [] as JobInfo[]);
        const pending = await api<JobInfo[]>(
          '/api/jobs?status=pending&limit=5'
        ).catch(() => [] as JobInfo[]);
        // Priorytet hydracji: autonomous_discovery (zwykle dluzszy, wazniejszy
        // dla widocznosci) > discovery_pipeline > bulk_research_leads.
        const all = [...running, ...pending];
        const found =
          all.find((j) => j.type === 'autonomous_discovery') ||
          all.find((j) => j.type === 'discovery_pipeline' || j.type === 'bulk_research_leads');
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
    setPeekFromCache(null);
    setSelected(new Set());
    try {
      const res = await api<PeekResponse>('/api/discovery/peek', {
        method: 'POST',
        body: JSON.stringify({
          query: buildQuery(),
          sources: selectedSources,
          source_queries: buildSourceQueries(),
          max_per_source: maxPerSource,
          segment,
          location: location.trim() || null,
          custom_description: customTarget.trim() || null,
          use_relevance_filter: true,
          relevance_threshold: relevanceThreshold,
          force_refresh: forceRefresh,
          expand_queries: expandQueries,
        }),
      });
      setPeekResults(res.places);
      setPeekDiag(res.diagnostics);
      setPeekCap({ used: res.daily_used, cap: res.daily_cap });
      setPeekRelevanceSource(res.relevance_source || null);
      setPeekExpandStats(res.expand_stats || null);
      if (res.from_cache) {
        setPeekFromCache({ at: res.cached_at || null, run_id: res.cached_run_id });
      }
      // Po peek odsiez historie zeby user widzial nowy run
      void loadHistory();

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

  // Bulk discovery: jeden klik = jobs dla top N miast PL paralelnie.
  // Cache + exclusions z Faza 1/2 dzialaja automatycznie.
  async function handleBulkDiscover() {
    if (selectedSources.length === 0) {
      setFlash({ kind: 'error', text: 'Wybierz przynajmniej jedno źródło.' });
      return;
    }
    setBulkSubmitting(true);
    try {
      // Pobierz top N miast z backendu (najlepsze swieze dane)
      type CitiesResp = { cities: { name: string }[]; voivodeships: string[]; total: number };
      const citiesData = await api<CitiesResp>(`/api/discovery/cities?top_n=${bulkCount}`);
      const cityNames = citiesData.cities.map((c) => c.name);

      type BulkResp = {
        queued: number; skipped: number;
        queued_jobs: { city: string; job_id: number }[];
        skipped_details: { city: string; reason: string; cached_count?: number }[];
        daily_used: number; daily_cap: number;
      };
      const res = await api<BulkResp>('/api/discovery/bulk-discover', {
        method: 'POST',
        body: JSON.stringify({
          segment,
          sources: selectedSources,
          cities: cityNames,
          force_refresh: forceRefresh,
          relevance_threshold: relevanceThreshold,
          auto_draft_threshold: autoDraft ? 7 : null,
          custom_description: customTarget.trim() || null,
        }),
      });
      const cachedSkipped = res.skipped_details.filter((s) => s.reason === 'cache_active').length;
      const otherSkipped = res.skipped - cachedSkipped;
      setFlash({
        kind: 'success',
        text: (
          `Zakolejkowano ${res.queued} jobów dla top ${bulkCount} miast PL` +
          (cachedSkipped > 0 ? ` · ${cachedSkipped} pominiętych (cache aktywny, 0 kredytu)` : '') +
          (otherSkipped > 0 ? ` · ${otherSkipped} pominiętych z innych powodów` : '') +
          `. Postępy w /pulpit.`
        ),
      });
      void loadHistory();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd bulk discovery' });
    } finally {
      setBulkSubmitting(false);
    }
  }

  // Autonomous discovery: agent sam iteruje top miast PL z celem +
  // budżetem. Stop gdy target_new_leads osiagniete LUB max_cost_usd.
  async function handleAutonomousDiscover() {
    if (selectedSources.length === 0) {
      setFlash({ kind: 'error', text: 'Wybierz przynajmniej jedno źródło.' });
      return;
    }
    setAutonomousSubmitting(true);
    try {
      // Jak user wybral multi-segment (chipy), wyslij `segments[]`. Backend ma
      // jeden work_queue (segment × miasto). Inaczej (pusty) wysylamy `segment`
      // pojedyncze - legacy single-segment path.
      const body: Record<string, unknown> = {
        sources: selectedSources,
        target_new_leads: autonomousTarget,
        max_cost_usd: autonomousBudget,
        relevance_threshold: relevanceThreshold,
        auto_draft_threshold: autoDraft ? 7 : null,
        custom_description: customTarget.trim() || null,
      };
      if (autonomousSegments.length > 0) {
        body.segments = autonomousSegments;
      } else {
        body.segment = segment;
      }
      const res = await api<{ ok: boolean; job_id: number }>(
        '/api/discovery/autonomous', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setFlash({
        kind: 'success',
        text: (
          `Agent autonomous uruchomiony (job #${res.job_id}). ` +
          `Cel: ${autonomousTarget} nowych leadów, budżet $${autonomousBudget.toFixed(2)}. ` +
          `Postępy w /pulpit. Możesz wylogować się - agent leci dalej.`
        ),
      });
      // Pobierz info o jobie i pokazaj activeJob "panel pracy w tle"
      try {
        const job = await api<JobInfo>(`/api/jobs/${res.job_id}`);
        setActiveJob(job);
        if (job.status === 'pending' || job.status === 'running') {
          startJobPolling(job.id);
        }
      } catch {/* ignore */}
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Błąd';
      setFlash({ kind: 'error', text: msg });
    } finally {
      setAutonomousSubmitting(false);
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
  // Peek (mode='manual') jest synchroniczny - nigdy nie blokowany przez aktywne joby.
  // Autonomous ma osobny button, ten dotyczy tylko manual.
  const submitButtonDisabled = selectedSources.length === 0;
  // Research button (na zaznaczonych peek results) - tworzy BULK_RESEARCH_LEADS.
  // Blokujemy tylko jak juz leci research (nie discovery!).
  const researchButtonBlockedByJob = !!jobActive && activeJob?.type === 'bulk_research_leads';

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
        <div style={{ marginLeft: 'auto' }}>
          <AccountMenu />
        </div>
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
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn btn-ghost"
              onClick={() => setShowExclusions((s) => !s)}
              title="Wykluczenia - domeny / brandy które na zawsze ignorujemy w discovery"
            >
              <i className="ti ti-ban" /> Wykluczenia ({exclusions.length})
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => setShowHistory((s) => !s)}
              title="Historia ostatnich zapytań discovery - chroni Cię przed powtarzaniem"
            >
              <i className="ti ti-history" /> Historia ({history.length})
            </button>
          </div>
        </div>

        {/* EXCLUSIONS PANEL - workspace blacklist domain/brand */}
        {showExclusions && (
          <div className="history-panel">
            <div className="history-head">
              <strong>Wykluczenia</strong>
              <span className="history-sub">
                Domeny i brandy które discovery automatycznie pominie (sieci handlowe, marki nie pasujące do oferty).
              </span>
              <button className="btn-icon" onClick={() => setShowExclusions(false)} aria-label="Zamknij">
                <i className="ti ti-x" />
              </button>
            </div>
            <div style={{ padding: 12, display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap', borderBottom: '1px solid #F3F4F6' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <label style={{ fontSize: 11, color: '#6B7280', fontWeight: 500 }}>Typ</label>
                <select
                  value={newExclusionType}
                  onChange={(e) => setNewExclusionType(e.target.value as 'domain' | 'brand')}
                  style={{ padding: '6px 8px', border: '1px solid #E5E7EB', borderRadius: 6, fontSize: 13 }}
                >
                  <option value="domain">Domena</option>
                  <option value="brand">Brand (nazwa)</option>
                </select>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 180 }}>
                <label style={{ fontSize: 11, color: '#6B7280', fontWeight: 500 }}>Wartość</label>
                <input
                  type="text"
                  value={newExclusionValue}
                  onChange={(e) => setNewExclusionValue(e.target.value)}
                  placeholder={newExclusionType === 'domain' ? 'np. rossmann.pl' : 'np. Empik'}
                  style={{ padding: '6px 8px', border: '1px solid #E5E7EB', borderRadius: 6, fontSize: 13 }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 180 }}>
                <label style={{ fontSize: 11, color: '#6B7280', fontWeight: 500 }}>Powód (opcjonalny)</label>
                <input
                  type="text"
                  value={newExclusionReason}
                  onChange={(e) => setNewExclusionReason(e.target.value)}
                  placeholder="np. sieć drogerii"
                  style={{ padding: '6px 8px', border: '1px solid #E5E7EB', borderRadius: 6, fontSize: 13 }}
                />
              </div>
              <button className="btn btn-primary" onClick={addExclusion}>
                <i className="ti ti-plus" /> Dodaj
              </button>
            </div>
            {exclusions.length === 0 ? (
              <div className="history-empty">Brak wykluczeń — dodaj domenę/brand który chcesz pomijać.</div>
            ) : (
              <table className="history-table">
                <thead>
                  <tr>
                    <th>Typ</th>
                    <th>Wartość</th>
                    <th>Powód</th>
                    <th>Dodano</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {exclusions.map((e) => (
                    <tr key={e.id}>
                      <td>{e.exclusion_type === 'domain' ? '🌐 Domena' : '🏷️ Brand'}</td>
                      <td style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12 }}>{e.value}</td>
                      <td style={{ color: '#6B7280', fontSize: 12 }}>{e.reason || '—'}</td>
                      <td style={{ fontSize: 11, color: '#9CA3AF' }}>{new Date(e.created_at).toLocaleDateString('pl-PL')}</td>
                      <td>
                        <button
                          className="btn-icon"
                          onClick={() => void deleteExclusion(e.id)}
                          title="Usuń wykluczenie"
                        >
                          <i className="ti ti-trash" style={{ color: '#DC2626' }} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* HISTORY PANEL - kolepsowalny */}
        {showHistory && (
          <div className="history-panel">
            <div className="history-head">
              <strong>Historia discovery</strong>
              <span className="history-sub">
                {history.filter((h) => h.cache_active).length} runów w cache (30 dni) ·
                pozostałe to historyczne
              </span>
              <button
                className="btn-icon"
                onClick={() => void loadHistory()}
                aria-label="Odśwież historię"
                title="Pobierz ponownie z backendu"
              >
                <i className="ti ti-refresh" />
              </button>
              <button className="btn-icon" onClick={() => setShowHistory(false)} aria-label="Zamknij">
                <i className="ti ti-x" />
              </button>
            </div>
            {historyError ? (
              <div className="history-empty" style={{ color: '#DC2626' }}>
                <i className="ti ti-alert-triangle" /> Nie udało się pobrać historii: {historyError}
                <div style={{ fontSize: 11, marginTop: 6, color: '#9CA3AF' }}>
                  Możliwe: backend jeszcze nie wdrożony, brak tabeli discovery_runs w bazie, błąd 500.
                  Sprawdź Railway logs backend service.
                </div>
              </div>
            ) : history.length === 0 ? (
              <div className="history-empty">
                Brak runów — pierwsze zapytanie pojawi się tutaj.
                <div style={{ fontSize: 11, marginTop: 6, color: '#9CA3AF' }}>
                  Historia zapisuje się od momentu wdrożenia Fazy 1 cache (PR #33).
                  Wcześniejsze peek'i nie były zapisywane.
                </div>
              </div>
            ) : (
              <table className="history-table">
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Segment</th>
                    <th>Lokalizacja</th>
                    <th>Źródła</th>
                    <th style={{ textAlign: 'right' }}>Wyniki</th>
                    <th>Cache</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id}>
                      <td>{new Date(h.run_at).toLocaleString('pl-PL')}</td>
                      <td>{h.segment}</td>
                      <td>{h.location || <em style={{ color: '#9CA3AF' }}>—</em>}</td>
                      <td style={{ fontSize: 11, color: '#6B7280' }}>{h.sources.join(', ')}</td>
                      <td style={{ textAlign: 'right', fontFamily: 'JetBrains Mono, monospace' }}>
                        {h.error ? (
                          <span style={{ color: '#DC2626' }}>error</span>
                        ) : (
                          h.result_count
                        )}
                      </td>
                      <td>
                        {h.cache_active ? (
                          <span style={{ color: '#10B981', fontSize: 11 }}>
                            <i className="ti ti-database-check" /> aktywny
                          </span>
                        ) : (
                          <span style={{ color: '#9CA3AF', fontSize: 11 }}>—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* MODE TOGGLE - 2 tryby: manual (recznie wybieram firmy) +
            autonomous (cel + budzet, agent leci sam) */}
        <div className="mode-tabs">
          <button
            className={`mode-tab ${mode === 'manual' ? 'active' : ''}`}
            onClick={() => setMode('manual')}>
            <div className="mode-tab-icon"><i className="ti ti-hand-click" /></div>
            <div className="mode-tab-text">
              <div className="mode-tab-name">Praca ręczna</div>
              <div className="mode-tab-desc">Zobacz listę, wybierz co researchować. Pojedyncze + bulk top miast.</div>
            </div>
          </button>
          <button
            className={`mode-tab ${mode === 'autonomous' ? 'active' : ''}`}
            onClick={() => setMode('autonomous')}>
            <div className="mode-tab-icon"><i className="ti ti-robot" /></div>
            <div className="mode-tab-text">
              <div className="mode-tab-name">Autonomous</div>
              <div className="mode-tab-desc">Powiedz "chcę 50 nowych leadów za $5". Agent iteruje top miasta sam, stop gdy osiągnie cel.</div>
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
            {/* AUTONOMOUS DETAILED LIVE STATUS - dla autonomous_discovery job */}
            {activeJob.type === 'autonomous_discovery' && activeJob.result && (() => {
              const r = activeJob.result as {
                status?: string;
                current_city?: string;
                current_segment?: string;
                segments?: string[];
                cities_processed?: number;
                cities_total?: number;
                new_leads_count?: number;
                target_new_leads?: number;
                drafts_made?: number;
                estimated_cost_usd?: number;
                max_cost_usd?: number;
                cities_skipped_no_results?: number;
                stopped_reason?: string;
                research_errors_count?: number;
                last_research_error?: string;
                setup_error?: string;
              };
              const segs = r.segments || (r.current_segment ? [r.current_segment] : []);
              const segLabel = (s: string) => SEGMENT_INFO[s]?.label || s;
              return (
                <div className="autonomous-status">
                  {/* Hero row - co teraz robi agent, max widocznosc */}
                  <div className="as-hero">
                    <div className="as-hero-left">
                      <div className="as-hero-label">
                        <i className="ti ti-radar" /> Agent pracuje
                      </div>
                      <div className="as-hero-now">
                        {jobActive ? (
                          <>
                            <span className="dot-pulse" />
                            <strong>
                              {r.current_segment ? segLabel(r.current_segment) : '—'}
                            </strong>
                            <span className="as-hero-arrow">→</span>
                            <strong className="as-hero-city">
                              {r.current_city || '…'}
                            </strong>
                          </>
                        ) : (
                          <span style={{ color: '#9CA3AF' }}>—</span>
                        )}
                      </div>
                      {segs.length > 1 && (
                        <div className="as-hero-segs">
                          <span className="as-hero-segs-label">
                            Multi-segment ({segs.length}):
                          </span>
                          {segs.map((s) => (
                            <span
                              key={s}
                              className={`as-seg-pill ${s === r.current_segment ? 'active' : ''}`}
                            >
                              {segLabel(s)}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="autonomous-status-grid">
                    <div className="as-stat">
                      <div className="as-label">Miasta sprawdzone</div>
                      <div className="as-value as-mono">
                        {r.cities_processed || 0} / {r.cities_total || '?'}
                      </div>
                    </div>
                    <div className="as-stat">
                      <div className="as-label">Nowe leady</div>
                      <div className="as-value as-mono as-success">
                        {r.new_leads_count || 0} / {r.target_new_leads || 0}
                      </div>
                    </div>
                    <div className="as-stat">
                      <div className="as-label">Drafty</div>
                      <div className="as-value as-mono">
                        {r.drafts_made || 0}
                      </div>
                    </div>
                    <div className="as-stat">
                      <div className="as-label">Szacowany koszt</div>
                      <div className="as-value as-mono">
                        ${(r.estimated_cost_usd || 0).toFixed(2)} / ${(r.max_cost_usd || 0).toFixed(2)}
                      </div>
                    </div>
                    <div className="as-stat">
                      <div className="as-label">Pomijane miasta</div>
                      <div className="as-value as-mono" title="Miasta gdzie 0 firm matchujących nasz segment">
                        {r.cities_skipped_no_results || 0}
                      </div>
                    </div>
                    {(r.research_errors_count || 0) > 0 && (
                      <div className="as-stat as-stat-err">
                        <div className="as-label">Błędy researchu</div>
                        <div
                          className="as-value as-mono"
                          title={r.last_research_error || 'Brak szczegolow'}
                        >
                          {r.research_errors_count}
                        </div>
                      </div>
                    )}
                  </div>
                  {r.setup_error && (
                    <div className="as-setup-error">
                      <i className="ti ti-alert-octagon" />
                      <strong>Setup error:</strong> {r.setup_error}
                    </div>
                  )}
                  {!jobActive && r.stopped_reason && (
                    <div className="autonomous-stopped">
                      <strong>Zakończono:</strong> {
                        r.stopped_reason === 'target_reached' ? '🎯 cel osiągnięty' :
                        r.stopped_reason === 'budget_reached' ? '💰 wyczerpany budżet' :
                        r.stopped_reason === 'cancelled' ? '⏹️ anulowane przez Ciebie' :
                        '📋 wszystkie miasta przerobione'
                      }
                    </div>
                  )}
                </div>
              );
            })()}
            {activeJob.total > 0 && (
              <>
                <div className="progress-bar">
                  <div style={{ width: `${(activeJob.progress / Math.max(activeJob.total, 1)) * 100}%` }} />
                </div>
                <div className="progress-meta">
                  {jobActive ? (
                    <span className="working-now">
                      <span className="dot-pulse" />
                      {activeJob.type === 'autonomous_discovery'
                        ? <>Agent szuka leadów ({activeJob.progress} / {activeJob.total})</>
                        : <>Pracuje nad {activeJob.progress + 1}-tym z {activeJob.total}</>}
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
            {/* LIVE TICKER - lista ostatnio przetworzonych leadow.
                Worker dorzuca per-entry `segment` + `city` (multi-segment context). */}
            {(() => {
              const recent = (activeJob.result as { recent?: Array<{
                name?: string; url?: string; status?: string; score?: number;
                lead_id?: number; drafted?: boolean; error?: string;
                segment?: string; city?: string;
              }> } | null)?.recent;
              if (!recent || recent.length === 0) return null;
              const segLabel = (s: string) => SEGMENT_INFO[s]?.label || s;
              // Status worker'a: 'researched' | 'city_scanned' | 'research_failed' |
              // 'city_search_failed' | 'city_relevance_failed' | 'failed' | 'duplicate'
              const isFailed = (s?: string) =>
                s === 'failed' || s === 'research_failed' ||
                s === 'city_search_failed' || s === 'city_relevance_failed';
              const errorsCount = recent.filter((r) => isFailed(r.status)).length;
              return (
                <div className="live-ticker">
                  <div className="live-ticker-head">
                    <i className="ti ti-activity" /> Ostatnio przetworzone ({recent.length})
                    {errorsCount > 0 && (
                      <span className="lt-errors-badge" title="Liczba bledow w ostatnich entries">
                        <i className="ti ti-alert-triangle" /> {errorsCount} błędów
                      </span>
                    )}
                  </div>
                  <div className="live-ticker-list">
                    {[...recent].reverse().map((r, i) => (
                      <div className={`lt-row lt-${isFailed(r.status) ? 'failed' : (r.status || 'pending')}`} key={i}>
                        <span className="lt-icon">
                          {r.status === 'researched' && <i className="ti ti-check" />}
                          {r.status === 'city_scanned' && <i className="ti ti-map-pin" />}
                          {r.status === 'duplicate' && <i className="ti ti-copy" />}
                          {isFailed(r.status) && <i className="ti ti-alert-triangle" />}
                        </span>
                        <span className="lt-name" title={r.url || r.error}>{r.name || r.url}</span>
                        {r.segment && (
                          <span className="lt-meta" title={`Segment: ${r.segment}`}>
                            {segLabel(r.segment)}
                          </span>
                        )}
                        {r.city && (
                          <span className="lt-meta lt-city">{r.city}</span>
                        )}
                        {r.score != null && (
                          <span className="lt-score mono">{r.score}/10</span>
                        )}
                        {r.drafted && <span className="lt-tag">draft</span>}
                        {r.status === 'duplicate' && <span className="lt-tag muted">dup</span>}
                        {isFailed(r.status) && (
                          <span className="lt-tag err" title={r.error || 'Brak szczegolow'}>
                            {r.status === 'research_failed' ? 'research padl' :
                             r.status === 'city_search_failed' ? 'search padl' :
                             r.status === 'city_relevance_failed' ? 'LLM filter padl' :
                             'błąd'}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                  {errorsCount >= 3 && (
                    <div className="lt-errors-hint">
                      <i className="ti ti-info-circle" />
                      <strong>{errorsCount} blędów</strong> w ostatnich entries -
                      hover na czerwone tagi zeby zobaczyc szczegoly. Najczestsze powody:
                      strona offline (timeout), CloudFlare blokada, DataDome captcha,
                      brak GEMINI/ANTHROPIC API key.
                    </div>
                  )}
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
          <form
            onSubmit={
              mode === 'manual' ? handlePeek
                : (e) => e.preventDefault()  // autonomous uzywa type=button, no submit
            }
            className="card-body">
            {/* Manual: pojedyncze query - user wybiera segment + miasto.
                Autonomous: hide te pola (multi-segment chipy + auto top miasta). */}
            {mode === 'manual' && (
              <>
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
              </>
            )}

            {/* Custom target - dla obu trybow. W autonomous nadpisuje segments chipy
                w prompcie LLM relevance (jak user da target free-text). */}
            <div className="field">
              <label>Własny opis targetu <span style={{ fontWeight: 400, color: '#9CA3AF' }}>(opcjonalny{mode === 'manual' ? ', nadpisuje segment' : ''})</span></label>
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

            {/* Allegro mode panel - widoczny tylko w manual + gdy 'apify_allegro'
                zaznaczone. Autonomous nie korzysta z keyword/category modes,
                tylko przerabia top miasta z presetem segmentowym. */}
            {mode === 'manual' && selectedSources.includes('apify_allegro') && (
              <div className="field allegro-panel">
                <label>
                  <i className="ti ti-shopping-cart" /> Allegro - tryb wyszukiwania
                </label>
                <div className="allegro-mode-grid">
                  <label className={`allegro-mode-card ${allegroMode === 'preset' ? 'on' : ''}`}>
                    <input
                      type="radio"
                      name="allegro-mode"
                      checked={allegroMode === 'preset'}
                      onChange={() => setAllegroMode('preset')}
                    />
                    <div className="amc-content">
                      <div className="amc-title">Preset branżowy</div>
                      <div className="amc-desc">
                        Wbudowane keywords + kategorie + filtry skali per branża.
                        Rekomendowane.
                      </div>
                    </div>
                  </label>
                  <label className={`allegro-mode-card ${allegroMode === 'keyword' ? 'on' : ''}`}>
                    <input
                      type="radio"
                      name="allegro-mode"
                      checked={allegroMode === 'keyword'}
                      onChange={() => setAllegroMode('keyword')}
                    />
                    <div className="amc-content">
                      <div className="amc-title">Po słowie kluczowym</div>
                      <div className="amc-desc">
                        Wpisz dokładnie czego szukasz (np. "farby akrylowe hurt").
                      </div>
                    </div>
                  </label>
                  <label className={`allegro-mode-card ${allegroMode === 'category' ? 'on' : ''}`}>
                    <input
                      type="radio"
                      name="allegro-mode"
                      checked={allegroMode === 'category'}
                      onChange={() => setAllegroMode('category')}
                    />
                    <div className="amc-content">
                      <div className="amc-title">URL kategorii Allegro</div>
                      <div className="amc-desc">
                        Wklej link kategorii (np. allegro.pl/kategoria/sztuki-piekne-...).
                      </div>
                    </div>
                  </label>
                </div>

                {allegroMode === 'preset' && (
                  <div style={{ marginTop: 10 }}>
                    <select
                      value={allegroPreset}
                      onChange={(e) => setAllegroPreset(e.target.value)}
                      style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid #E5E7EB', fontSize: 13.5 }}
                    >
                      {industryPresets.length === 0 ? (
                        <option value="sklep_plastyczny">Sklepy plastyczne / artystyczne</option>
                      ) : (
                        industryPresets.map((p) => (
                          <option key={p.key} value={p.key}>{p.label}</option>
                        ))
                      )}
                    </select>
                  </div>
                )}
                {allegroMode === 'keyword' && (
                  <input
                    type="text"
                    value={allegroKeyword}
                    onChange={(e) => setAllegroKeyword(e.target.value)}
                    placeholder="np. farby akrylowe hurt"
                    style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid #E5E7EB', fontSize: 13.5, marginTop: 10 }}
                  />
                )}
                {allegroMode === 'category' && (
                  <input
                    type="url"
                    value={allegroCategoryUrl}
                    onChange={(e) => setAllegroCategoryUrl(e.target.value)}
                    placeholder="https://allegro.pl/kategoria/..."
                    style={{ width: '100%', padding: '8px 10px', borderRadius: 6, border: '1px solid #E5E7EB', fontSize: 13.5, marginTop: 10 }}
                  />
                )}
                <span className="field-hint" style={{ marginTop: 8 }}>
                  <strong>Allegro to discovery sklepów</strong> - dostajesz nazwę
                  sprzedawcy + URL profilu Allegro + asortyment.{' '}
                  <strong>Bez emaila firmowego</strong> (Allegro maskuje wszystkie
                  maile do @allegromail.pl - proxy aliasy bezużyteczne dla
                  cold-mail). Email firmowy zdobędziesz osobno: zaznacz lead →
                  Researchuj → agent wejdzie głębiej i znajdzie ich prawdziwą
                  stronę WWW + email.
                </span>
              </div>
            )}

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
              <>
                {mode === 'manual' && (
                  <div className="peek-options">
                    <label className="peek-toggle" title="Domyslnie pomijamy zapytanie ktorego identyczna wersja byla w ostatnich 30 dniach (cache). Zaznacz aby wymusic odswiezenie i zapłacic za nowe API call.">
                      <input
                        type="checkbox"
                        checked={forceRefresh}
                        onChange={(e) => setForceRefresh(e.target.checked)}
                      />
                      <span>Pomiń cache (zapłać za odświeżenie zapytania)</span>
                    </label>
                    <label className="peek-toggle peek-toggle-expand" title="Wyślij serię wariantów zapytania (synonimy + dzielnice) zamiast jednego. Omija limit 60/query, znajduje 5-8x więcej firm. Każdy wariant ma swój cache - 0 kredytu jak już sprawdzane.">
                      <input
                        type="checkbox"
                        checked={expandQueries}
                        onChange={(e) => setExpandQueries(e.target.checked)}
                      />
                      <span>
                        <i className="ti ti-arrows-maximize" /> Rozszerz zapytanie (5-8× więcej firm, omija limit 60)
                      </span>
                    </label>
                  </div>
                )}
                {mode === 'autonomous' && (
                  <>
                    <div className="autonomous-controls">
                      <div className="autonomous-input">
                        <label>Cel - ile nowych leadów chcę?</label>
                        <input
                          type="number" min={1} max={500}
                          value={autonomousTarget}
                          onChange={(e) => setAutonomousTarget(Math.max(1, Math.min(500, Number(e.target.value) || 50)))}
                        />
                        <span className="field-hint">1-500</span>
                      </div>
                      <div className="autonomous-input">
                        <label>Max budżet API ($)</label>
                        <input
                          type="number" min={0.1} max={100} step={0.5}
                          value={autonomousBudget}
                          onChange={(e) => setAutonomousBudget(Math.max(0.1, Math.min(100, Number(e.target.value) || 5)))}
                        />
                        <span className="field-hint">Stop gdy osiągniesz</span>
                      </div>
                    </div>
                    {/* Multi-segment chips: wybor wielu segmentow naraz. Worker
                        przerabia segment × miasto. Pusty wybor = uzywa pojedynczego
                        segmentu z dropdowna powyzej (legacy mode). */}
                    <div className="autonomous-segments">
                      <div className="autonomous-segments-head">
                        <strong>
                          <i className="ti ti-stack-2" /> Multi-segment (opcjonalne)
                        </strong>
                        <span className="autonomous-segments-sub">
                          {autonomousSegments.length === 0
                            ? `Pojedynczy: ${SEGMENT_INFO[segment]?.label || segment}`
                            : `${autonomousSegments.length} segmentów wybranych - agent zrobi każdy × każde miasto`}
                        </span>
                        {autonomousSegments.length > 0 && (
                          <button
                            type="button" className="link-btn"
                            onClick={() => setAutonomousSegments([])}
                          >
                            Wyczyść
                          </button>
                        )}
                      </div>
                      <div className="autonomous-segments-chips">
                        {SEGMENTS.map((s) => {
                          const active = autonomousSegments.includes(s);
                          return (
                            <button
                              key={s} type="button"
                              className={`seg-chip ${active ? 'active' : ''}`}
                              onClick={() => {
                                setAutonomousSegments((prev) =>
                                  prev.includes(s)
                                    ? prev.filter((x) => x !== s)
                                    : [...prev, s],
                                );
                              }}
                              title={SEGMENT_INFO[s]?.desc || s}
                            >
                              {active && <i className="ti ti-check" />}
                              {SEGMENT_INFO[s]?.label || s}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </>
                )}
                <div className="cta-row">
                  {mode === 'autonomous' ? (
                    <button type="button" className="btn btn-primary btn-cta"
                      onClick={handleAutonomousDiscover}
                      disabled={autonomousSubmitting || selectedSources.length === 0 || !!jobActive}
                      title={
                        jobActive
                          ? 'Aktywny job - poczekaj albo anuluj'
                          : `Uruchom agenta autonomicznego - cel ${autonomousTarget} leadów, budżet $${autonomousBudget.toFixed(2)}`
                      }
                    >
                      {autonomousSubmitting ? (
                        <><i className="ti ti-loader" /> Startuję…</>
                      ) : (
                        <><i className="ti ti-robot" /> Uruchom agenta autonomicznego</>
                      )}
                    </button>
                  ) : (
                    <button type="submit" className="btn btn-primary btn-cta"
                      disabled={submitButtonDisabled}>
                      <i className="ti ti-search" /> Zajrzyj na rynek
                    </button>
                  )}
                  {mode === 'manual' && (
                    <div className="bulk-cta-group">
                      <select
                        className="bulk-count-select"
                        value={bulkCount}
                        onChange={(e) => setBulkCount(Number(e.target.value) as 30 | 50 | 100)}
                        title="Ile miast PL przerobić"
                      >
                        <option value={30}>Top 30 miast PL</option>
                        <option value={50}>Top 50 miast PL</option>
                        <option value={100}>Top 100 miast PL</option>
                      </select>
                      <button
                        type="button"
                        className="btn btn-secondary btn-cta-bulk"
                        onClick={handleBulkDiscover}
                        disabled={bulkSubmitting || selectedSources.length === 0}
                        title="Bulk: utwórz job per miasto. Worker pool przerabia paralelnie. Cache miast już sprawdzonych skip'uje automatycznie."
                      >
                        {bulkSubmitting ? (
                          <><i className="ti ti-loader" /> Kolejkuję…</>
                        ) : (
                          <><i className="ti ti-map" /> Bulk discovery</>
                        )}
                      </button>
                    </div>
                  )}
                </div>
              </>
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

        {/* PEEK RESULTS - banner ze statsami expansion */}
        {mode === 'manual' && peekExpandStats && (
          <div className="banner-info" style={{ marginTop: 16 }}>
            <i className="ti ti-arrows-maximize" />
            <div>
              <strong>Rozszerzone zapytanie:</strong>{' '}
              {peekExpandStats.variants_total} wariantów ·{' '}
              <span style={{ color: '#10B981' }}>{peekExpandStats.cache_hits} z cache (0 kredytu)</span> ·{' '}
              <span>{peekExpandStats.api_calls} nowych API calls</span>
              {peekExpandStats.errors > 0 && (
                <span style={{ color: '#DC2626' }}> · {peekExpandStats.errors} błędów</span>
              )}
              {' '}→ <strong>{peekExpandStats.places_after_dedup} unikalnych firm</strong>{' '}
              (z {peekExpandStats.places_before_dedup} przed dedupem)
            </div>
          </div>
        )}

        {/* PEEK RESULTS - banner gdy wynik z cache (zero kredytu) */}
        {mode === 'manual' && peekFromCache && (
          <div className="banner-info" style={{ marginTop: 16 }}>
            <i className="ti ti-database" />
            <div>
              <strong>✓ Cache hit — 0 kredytu Apify/Places.</strong>{' '}
              Wynik z wcześniejszego sprawdzenia
              {peekFromCache.at && (
                <> ({new Date(peekFromCache.at).toLocaleString('pl-PL')})</>
              )}. Jeśli chcesz odświeżyć i zapłacić za nowe zapytanie,
              zaznacz <strong>"Pomiń cache"</strong> nad przyciskiem i kliknij ponownie.
            </div>
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
                  disabled={submitting || selected.size === 0 || researchButtonBlockedByJob}
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
                        {p.email && (
                          <div style={{ fontSize: 11, color: '#10B981', marginTop: 2, fontFamily: 'JetBrains Mono, monospace' }}>
                            <i className="ti ti-mail" /> {p.email}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
.page-head {
  display: flex; justify-content: space-between; align-items: flex-start; gap: 16px;
  margin-bottom: 20px;
}
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-head p { color: #6B7280; font-size: 13.5px; margin: 0; }

/* Historia discovery - panel collapsible */
.history-panel {
  background: #fff; border: 1px solid #E5E7EB; border-radius: 9px;
  margin-bottom: 16px; overflow: hidden;
}
.history-head {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; border-bottom: 1px solid #F3F4F6;
  background: #FAFAF7;
}
.history-head strong { font-size: 13.5px; }
.history-sub { font-size: 11.5px; color: #6B7280; flex: 1; }
.btn-icon {
  background: none; border: none; cursor: pointer;
  color: #9CA3AF; padding: 4px; border-radius: 5px; display: flex;
}
.btn-icon:hover { background: #F3F4F6; color: #111; }
.history-empty {
  padding: 24px 16px; text-align: center; color: #9CA3AF; font-size: 13px;
}
.history-table {
  width: 100%; border-collapse: collapse; font-size: 12.5px;
}
.history-table th {
  text-align: left; padding: 8px 12px; font-weight: 600;
  color: #6B7280; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.5px; border-bottom: 1px solid #F3F4F6;
}
.history-table td {
  padding: 9px 12px; border-bottom: 1px solid #F9FAFB; color: #1F2937;
}
.history-table tbody tr:hover { background: #FAFAF7; }
.history-table tbody tr:last-child td { border-bottom: none; }

/* Peek options - toggle'i nad CTA (force_refresh, expand_queries) */
.peek-options {
  display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px;
}
.peek-toggle {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 12px; background: #FAFAF7;
  border: 1px solid #E5E7EB; border-radius: 7px;
  font-size: 12.5px; color: #6B7280; cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.peek-toggle:hover { background: #F3F4F6; color: #111; }
.peek-toggle input[type="checkbox"] {
  accent-color: #D4212C; cursor: pointer;
}
.peek-toggle-expand {
  background: linear-gradient(90deg, #F0FDF4 0%, #FAFAF7 100%);
  border-color: #BBF7D0;
}
.peek-toggle-expand:hover { background: #DCFCE7; }
.peek-toggle-expand i { color: #10B981; }

/* Bulk CTA - przycisk obok glownego "Sprawdź" w manual mode */
.cta-row {
  display: flex; gap: 8px; align-items: stretch; flex-wrap: wrap;
}
.bulk-cta-group {
  display: flex; gap: 0; align-items: stretch;
}
.bulk-count-select {
  padding: 0 12px; border: 1px solid #E5E7EB;
  border-right: none; border-radius: 8px 0 0 8px;
  background: #fff; font-size: 13px; font-family: inherit;
  cursor: pointer;
}
.btn-cta-bulk {
  border-radius: 0 8px 8px 0;
  display: inline-flex; align-items: center; gap: 6px;
}
.btn-cta-bulk .ti-loader { animation: spin 1.2s linear infinite; }

@media (max-width: 800px) {
  .mode-tabs { grid-template-columns: 1fr !important; }
}

/* Autonomous mode controls - target + budget inputy */
.autonomous-controls {
  display: flex; gap: 16px; flex-wrap: wrap;
  padding: 16px; margin-bottom: 14px;
  background: linear-gradient(135deg, #FEF3C7 0%, #FAFAF7 100%);
  border: 1px solid #FDE68A; border-radius: 9px;
}
.autonomous-input {
  display: flex; flex-direction: column; gap: 4px;
  flex: 1; min-width: 180px;
}
.autonomous-input label {
  font-size: 12px; font-weight: 600; color: #4B5563;
}
.autonomous-input input {
  padding: 8px 10px; border: 1px solid #FBBF24;
  border-radius: 7px; font-size: 15px; font-weight: 600;
  font-family: 'JetBrains Mono', monospace; color: #92400E;
  background: #fff;
}
.autonomous-input input:focus {
  outline: none; border-color: #F59E0B;
  box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.2);
}
.autonomous-input .field-hint { font-size: 11px; color: #92400E; }

/* Autonomous multi-segment chips */
.autonomous-segments {
  padding: 14px;
  margin-bottom: 14px;
  background: #FAFAF7;
  border: 1px dashed #D1D5DB;
  border-radius: 9px;
}
.autonomous-segments-head {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 10px; font-size: 12px;
}
.autonomous-segments-head strong { font-size: 13px; color: #1C1C1C; }
.autonomous-segments-sub {
  color: #6B7280; font-size: 11.5px; flex: 1;
}
.autonomous-segments-chips {
  display: flex; flex-wrap: wrap; gap: 6px;
}
.seg-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 5px 11px; border-radius: 999px;
  border: 1px solid #D1D5DB; background: #fff;
  font-size: 12px; color: #4B5563; cursor: pointer;
  transition: all 0.15s;
}
.seg-chip:hover { border-color: #6B7280; color: #1C1C1C; }
.seg-chip.active {
  background: #1C1C1C; border-color: #1C1C1C; color: #fff;
}
.seg-chip.active i { font-size: 14px; }
.link-btn {
  background: transparent; border: none; padding: 0;
  font-size: 11.5px; color: #DC2626; cursor: pointer;
  text-decoration: underline;
}
.link-btn:hover { color: #991B1B; }

/* Autonomous status panel - live updates w trakcie joba */
.autonomous-status {
  margin: 14px 0 8px;
  padding: 14px;
  background: linear-gradient(135deg, #1C1C1C 0%, #2A2A2A 100%);
  border-radius: 9px;
  color: #fff;
}
/* Hero row pokazujacy CO TERAZ robi agent - duzo widoczniej niz reszta gridu */
.as-hero {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; margin-bottom: 14px;
  padding: 12px 14px;
  background: linear-gradient(135deg, rgba(220, 38, 38, 0.18), rgba(255,255,255,0.04));
  border: 1px solid rgba(220, 38, 38, 0.35);
  border-radius: 8px;
}
.as-hero-left { display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 0; }
.as-hero-label {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 700; color: #FCA5A5;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.as-hero-now {
  display: flex; align-items: center; gap: 8px;
  font-size: 15px; line-height: 1.2; flex-wrap: wrap;
}
.as-hero-now strong { font-weight: 700; }
.as-hero-arrow { color: rgba(255,255,255,0.4); }
.as-hero-city { color: #FECACA; }
.as-hero-segs {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 11px;
}
.as-hero-segs-label { color: rgba(255,255,255,0.5); }
.as-seg-pill {
  padding: 2px 8px; border-radius: 999px;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  color: rgba(255,255,255,0.6);
  font-size: 10.5px;
}
.as-seg-pill.active {
  background: #DC2626; border-color: #DC2626; color: #fff;
  font-weight: 600;
}

.autonomous-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}
.as-stat {
  display: flex; flex-direction: column; gap: 4px;
  padding: 8px 10px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 7px;
}
.as-label {
  font-size: 10.5px;
  color: rgba(255, 255, 255, 0.55);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}
.as-value {
  font-size: 14px;
  color: #fff;
  font-weight: 600;
  display: flex; align-items: center; gap: 6px;
}
.as-mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
}
.as-success { color: #6EE7B7; }
.as-value .dot-pulse {
  display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: #D4212C; animation: dot-pulse 1.2s ease-in-out infinite;
}
.autonomous-stopped {
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 13px;
  color: rgba(255, 255, 255, 0.85);
}

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
  display: flex; align-items: center; gap: 6px;
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
/* Per-row segment + city w live ticker (multi-segment job widzialny per linia) */
.lt-meta {
  font-size: 10.5px; color: #6B7280;
  padding: 1px 7px; border-radius: 999px;
  background: #F9FAFB; border: 1px solid #E5E7EB;
  white-space: nowrap;
}
.lt-meta.lt-city { background: #FEF3C7; border-color: #FDE68A; color: #92400E; }

/* Failed entries - czerwone tlo zeby user OD RAZU widzial ze cos padło */
.lt-row.lt-failed {
  background: rgba(212,33,44,0.05);
  border-left: 2px solid #DC2626;
  padding-left: 8px;
}
.lt-row.lt-failed .lt-icon { color: #DC2626; }
.lt-row.lt-failed .lt-name { color: #8F1018; }

/* Badge z liczba bledow w naglowku */
.lt-errors-badge {
  margin-left: auto;
  padding: 2px 9px;
  background: #FEE2E2;
  border: 1px solid #FCA5A5;
  border-radius: 999px;
  color: #8F1018;
  font-size: 11px;
  font-weight: 700;
  text-transform: none;
  letter-spacing: 0;
  display: inline-flex; align-items: center; gap: 4px;
}

/* Hint pod ticker'em jak >3 bledy - mowi userowi co moze byc */
.lt-errors-hint {
  margin-top: 8px;
  padding: 8px 10px;
  background: #FEF3C7;
  border: 1px solid #FDE68A;
  border-radius: 7px;
  font-size: 11.5px;
  color: #78350F;
  display: flex; align-items: flex-start; gap: 6px;
  line-height: 1.4;
}
.lt-errors-hint i { color: #B45309; flex-shrink: 0; margin-top: 1px; }

/* Stat err styling - kafelek z liczba bledow w autonomous-status-grid */
.as-stat.as-stat-err {
  background: rgba(220, 38, 38, 0.15);
  border: 1px solid rgba(220, 38, 38, 0.35);
}
.as-stat.as-stat-err .as-value { color: #FECACA; }

/* Setup error - duzy banner gdy job padl na konfiguracji */
.as-setup-error {
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(220, 38, 38, 0.18);
  border: 1px solid rgba(220, 38, 38, 0.45);
  border-radius: 7px;
  color: #FECACA;
  font-size: 12.5px;
  line-height: 1.4;
  display: flex; align-items: flex-start; gap: 8px;
}
.as-setup-error i { color: #FCA5A5; flex-shrink: 0; margin-top: 1px; font-size: 16px; }
.as-setup-error strong { color: #FEE2E2; }

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

/* Allegro mode panel - widoczny gdy 'apify_allegro' jest w selectedSources */
.allegro-panel {
  background: #FAFAF7;
  border: 1px solid #E5E7EB;
  border-radius: 9px;
  padding: 14px;
}
.allegro-panel > label:first-child {
  display: flex; align-items: center; gap: 6px;
  font-weight: 600; font-size: 13px;
}
.allegro-panel > label:first-child i { color: #D4212C; font-size: 16px; }
.allegro-mode-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px; margin-top: 10px;
}
.allegro-mode-card {
  display: flex; gap: 8px; align-items: flex-start;
  padding: 10px; border: 1px solid #E5E7EB; border-radius: 7px;
  background: #fff; cursor: pointer;
  transition: border-color 0.12s, background 0.12s;
}
.allegro-mode-card:hover { border-color: #D1D5DB; }
.allegro-mode-card.on {
  border-color: #D4212C;
  background: #FEF7F7;
}
.allegro-mode-card input[type="radio"] {
  accent-color: #D4212C; margin-top: 1px; flex-shrink: 0;
}
.amc-content { flex: 1; }
.amc-title { font-size: 12.5px; font-weight: 600; color: #111; margin-bottom: 2px; }
.amc-desc { font-size: 11px; color: #6B7280; line-height: 1.4; }

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
