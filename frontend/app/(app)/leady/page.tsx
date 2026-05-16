'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { api, isAuthenticated } from '@/lib/api';
import { AccountMenu } from '@/lib/AccountMenu';
import { useConfirm } from '@/lib/confirm';

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
  active_job_type: string | null;
}

const JOB_LABEL: Record<string, string> = {
  generate_draft: 'Pisze maila',
  enrich_lead: 'Szuka kontaktu',
  research_lead: 'Sprawdza firmę',
};

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

interface TrashLeadRow {
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
  deleted_at: string | null;
  days_until_purge: number;
  created_at: string | null;
}

interface TrashResponse {
  total: number;
  items: TrashLeadRow[];
  recycle_bin_days: number;
}

interface LeadsResponse {
  total: number;
  items: LeadRow[];
}

// 'not_sent' to virtualny filter (backend rozpoznaje) = wszystkie poza
// sent/replied/bounced. Domyslny by user widzial leady "do roboty".
const STATUSES = ['not_sent', '', 'new', 'researched', 'drafted', 'approved', 'sent', 'replied', 'bounced', 'blacklisted'];
const STATUS_LABELS: Record<string, string> = {
  '': 'Wszystkie statusy',
  'not_sent': 'Tylko nie wysłane (domyślne)',
  'new': 'Status: new',
  'researched': 'Status: researched',
  'drafted': 'Status: drafted',
  'approved': 'Status: approved',
  'sent': 'Status: sent',
  'replied': 'Status: replied',
  'bounced': 'Status: bounced',
  'blacklisted': 'Status: blacklisted',
};
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

type AddLeadForm = {
  company_name: string;
  contact_name: string;
  email: string;
  phone: string;
  website: string;
  city: string;
  segment: string;
  notes: string;
};

const SEGMENT_OPTIONS: { value: string; label: string }[] = [
  { value: 'sklep_plastyczny', label: 'Sklep plastyczny' },
  { value: 'sklep_papierniczy', label: 'Sklep papierniczy' },
  { value: 'paint_and_sip', label: 'Paint & Sip' },
  { value: 'warsztaty_dzieci', label: 'Warsztaty dla dzieci' },
  { value: 'animatorzy_eventy', label: 'Animatorzy / Eventy' },
  { value: 'szkola_artystyczna', label: 'Szkoła artystyczna' },
  { value: 'marka_wlasna', label: 'Marka własna' },
  { value: 'inne', label: 'Inne' },
];

const EMPTY_ADD_LEAD_FORM: AddLeadForm = {
  company_name: '', contact_name: '', email: '', phone: '',
  website: '', city: '', segment: 'inne', notes: '',
};

export default function LeadyPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const confirm = useConfirm();
  // View toggle: 'all' (zwykla lista) vs 'trash' (kosz).
  // Kosz pokazuje deleted_at != null leady + akcje przywroc/usun-permanentnie.
  const [view, setView] = useState<'all' | 'trash'>('all');
  const [leads, setLeads] = useState<LeadRow[]>([]);
  const [trash, setTrash] = useState<TrashLeadRow[]>([]);
  // Modal "Dodaj lead recznie" - bez discovery, bez Apify, user wpisuje sam.
  const [showAddLead, setShowAddLead] = useState(false);
  const [addLeadForm, setAddLeadForm] = useState<AddLeadForm>(EMPTY_ADD_LEAD_FORM);
  const [addLeadSubmitting, setAddLeadSubmitting] = useState(false);
  const [trashTotal, setTrashTotal] = useState(0);
  const [recycleBinDays, setRecycleBinDays] = useState(7);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [segment, setSegment] = useState('');
  // Default 'not_sent': pokaz tylko leady do roboty (bez wyslanych/odpowiedzialych)
  const [status, setStatus] = useState('not_sent');
  const [minScore, setMinScore] = useState(0);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  // Default 'newest' - swieze leady na gorze, najczestszy use case po pozyskiwaniu
  const [sort, setSort] = useState('newest');
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
  // Enrich (re-scrape kontakt) state - osobne, bo to inny job type niz draft
  const [enrichJobId, setEnrichJobId] = useState<number | null>(null);
  const [enrichJobStatus, setEnrichJobStatus] = useState<string | null>(null);
  // Manual edit state - tryb edycji leada w drawer'ze (email/telefon/kontakt)
  const [editMode, setEditMode] = useState(false);
  const [editValues, setEditValues] = useState<{
    contact_name: string;
    email: string;
    phone: string;
    website: string;
    city: string;
    segment: string;
    notes: string;
  }>({
    contact_name: '', email: '', phone: '', website: '',
    city: '', segment: '', notes: '',
  });
  const [editSubmitting, setEditSubmitting] = useState(false);
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

  async function loadTrash() {
    setLoading(true);
    try {
      const res = await api<TrashResponse>('/api/leads/trash?limit=200');
      setTrash(res.items);
      setTrashTotal(res.total);
      setRecycleBinDays(res.recycle_bin_days);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  // Header badge - liczba w koszu (do tab toggle). Ladowane raz przy mount
  // + odswiezane po kazdej akcji (delete/restore/empty). Lekkie - tylko count.
  async function refreshTrashCount() {
    try {
      const res = await api<TrashResponse>('/api/leads/trash?limit=1');
      setTrashTotal(res.total);
      setRecycleBinDays(res.recycle_bin_days);
    } catch {/* ignore */}
  }

  useEffect(() => {
    if (view === 'all') {
      void load();
    } else {
      void loadTrash();
    }
    /* eslint-disable-next-line */
  }, [view, segment, status, minScore, search, sort]);

  // Trash count - laduje sie raz na mount + przy zmianie view (do badge w tab)
  useEffect(() => { void refreshTrashCount(); }, []);

  // Deep-link z innych stron: ?open=NN otwiera drawer dla tego leada.
  // Uzywane przez /drafty (przycisk "Lead") + potencjalnie inne. Po otwarciu
  // czyscimy query param zeby refresh strony nie reopenowal w kolko.
  useEffect(() => {
    const openParam = searchParams.get('open');
    if (!openParam) return;
    const leadId = Number.parseInt(openParam, 10);
    if (!Number.isFinite(leadId) || leadId <= 0) return;
    void openDetail(leadId);
    // Usun ?open z URL po otwarciu zeby nie blokowalo nawigacji wstecz
    router.replace('/leady', { scroll: false });
    /* eslint-disable-next-line */
  }, []);

  // Auto-refresh listy CO 3s gdy chocaby 1 lead ma active_job_type
  // (cichy refresh - bez setLoading, zeby tabela nie migotala). Daje
  // poczucie ze indykatory aktualizuja sie 'live'. Jak nie ma zadnych
  // running jobow, polling stoi (zero load na backend).
  useEffect(() => {
    const hasActive = leads.some(l => l.active_job_type !== null);
    if (!hasActive) return;
    const t = setInterval(() => {
      // Silent refresh - nie ruszamy loading state'a (no skeleton flash)
      const params = new URLSearchParams({ limit: '100', sort });
      if (segment) params.set('segment', segment);
      if (status) params.set('status', status);
      if (minScore > 0) params.set('min_score', String(minScore));
      if (search.trim()) params.set('q', search.trim());
      api<LeadsResponse>(`/api/leads?${params}`)
        .then((res) => { setLeads(res.items); setTotal(res.total); })
        .catch(() => {/* network glitch - probuj dalej */});
    }, 3000);
    return () => clearInterval(t);
  }, [leads, segment, status, minScore, search, sort]);

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
    // Reset wszystkich state'ow przy zmianie leada
    if (pollAbortRef.current) pollAbortRef.current.cancelled = true;
    setDraftFlash(null);
    setDraftJobId(null);
    setDraftJobStatus(null);
    setEnrichJobId(null);
    setEnrichJobStatus(null);
    setEditMode(false);
    setSelectedId(id);
    setDetail(null);
    await refreshDetail(id);
  }

  function startEdit() {
    if (!detail) return;
    setEditValues({
      contact_name: detail.contact_name || '',
      email: detail.email || '',
      phone: detail.phone || '',
      website: detail.website || '',
      city: detail.city || '',
      segment: detail.segment || '',
      notes: detail.notes || '',
    });
    setEditMode(true);
  }

  function cancelEdit() {
    setEditMode(false);
  }

  async function saveEdit() {
    if (!detail) return;
    setEditSubmitting(true);
    try {
      const res = await api<{
        ok: boolean; changed_fields: string[];
      }>(`/api/leads/${detail.id}`, {
        method: 'PATCH',
        body: JSON.stringify(editValues),
      });
      if (res.changed_fields.length === 0) {
        setDraftFlash({ kind: 'info', text: 'Nic się nie zmieniło.' });
      } else {
        setDraftFlash({
          kind: 'success',
          text: `Zaktualizowano: ${res.changed_fields.join(', ')}.`,
        });
      }
      setEditMode(false);
      await refreshDetail(detail.id);
      await load();
    } catch (err) {
      setDraftFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udało się zapisać',
      });
    } finally {
      setEditSubmitting(false);
    }
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

  async function submitAddLead(e: React.FormEvent) {
    e.preventDefault();
    const company = addLeadForm.company_name.trim();
    if (!company) {
      setFlash({ kind: 'error', text: 'Nazwa firmy jest wymagana.' });
      return;
    }
    setAddLeadSubmitting(true);
    try {
      type AddLeadResp = {
        ok: boolean;
        lead: { id: number; company_name: string; status: string; email: string | null };
      };
      const res = await api<AddLeadResp>('/api/leads', {
        method: 'POST',
        body: JSON.stringify({
          company_name: company,
          contact_name: addLeadForm.contact_name.trim() || null,
          email: addLeadForm.email.trim() || null,
          phone: addLeadForm.phone.trim() || null,
          website: addLeadForm.website.trim() || null,
          city: addLeadForm.city.trim() || null,
          segment: addLeadForm.segment || null,
          notes: addLeadForm.notes.trim() || null,
        }),
      });
      setFlash({
        kind: 'success',
        text: (
          res.lead.status === 'researched'
            ? `Lead "${res.lead.company_name}" dodany (#${res.lead.id}). Możesz od razu wygenerować draft.`
            : `Lead "${res.lead.company_name}" dodany (#${res.lead.id}). Bez emaila - uruchom enrichment z drawera.`
        ),
      });
      setShowAddLead(false);
      setAddLeadForm(EMPTY_ADD_LEAD_FORM);
      await load();
      // Otworz drawer nowego leada zeby user widzial co dodal
      setSelectedId(res.lead.id);
    } catch (err) {
      // 409 = duplikat strony www
      const msg = err instanceof Error ? err.message : 'Błąd zapisu';
      setFlash({ kind: 'error', text: msg });
    } finally {
      setAddLeadSubmitting(false);
    }
  }

  async function blockLead() {
    if (!detail) return;
    const ok = await confirm({
      title: 'Zablokować ten lead?',
      message: (
        <>
          Lead <strong>{detail.company_name}</strong> (#{detail.id}) zniknie z domyślnej
          listy. Pozostanie w bazie - możesz go odblokować ustawiając filtr
          &ldquo;Status: blacklisted&rdquo;. Użyj dla &ldquo;pewniaczków&rdquo;
          z których wiesz że nic nie będzie.
        </>
      ),
      confirmLabel: 'Zablokuj',
      cancelLabel: 'Anuluj',
      destructive: false,
      icon: 'ban',
    });
    if (!ok) return;
    try {
      await api(`/api/leads/${detail.id}/block`, { method: 'POST' });
      setFlash({
        kind: 'success',
        text: `Lead "${detail.company_name}" zablokowany - nie pokaże się więcej w domyślnej liście.`,
      });
      setSelectedId(null);
      setDetail(null);
      await load();
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udalo sie zablokowac',
      });
    }
  }

  async function unblockLead() {
    if (!detail) return;
    try {
      await api(`/api/leads/${detail.id}/unblock`, { method: 'POST' });
      setFlash({
        kind: 'success',
        text: `Lead "${detail.company_name}" odblokowany.`,
      });
      await refreshDetail(detail.id);
      await load();
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udalo sie odblokowac',
      });
    }
  }

  async function deleteLead() {
    if (!detail) return;
    const ok = await confirm({
      title: 'Przenieść do kosza?',
      message: (
        <>
          Lead <strong>{detail.company_name}</strong> (#{detail.id}) trafi do kosza.
          Możesz go przywrócić w ciągu <strong>{recycleBinDays} dni</strong> -
          później auto-usunięcie wraz z draftami ({detail.drafts.length}).
        </>
      ),
      confirmLabel: 'Przenieś do kosza',
      cancelLabel: 'Anuluj',
      destructive: true,
      icon: 'trash',
    });
    if (!ok) return;
    try {
      await api(`/api/leads/${detail.id}`, { method: 'DELETE' });
      setFlash({
        kind: 'success',
        text: `Lead "${detail.company_name}" przeniesiony do kosza (auto-usunięcie za ${recycleBinDays} dni).`,
      });
      setSelectedId(null);
      setDetail(null);
      await load();
      await refreshTrashCount();
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udalo sie usunac',
      });
    }
  }

  // Bulk soft-delete z bulk-bar (button "Usun N").
  async function bulkDeleteLeads() {
    if (selectedIds.size === 0) return;
    const ids = Array.from(selectedIds);
    const ok = await confirm({
      title: ids.length === 1 ? 'Przenieść do kosza?' : `Przenieść ${ids.length} leadów do kosza?`,
      message: (
        <>
          {ids.length === 1 ? 'Lead trafi' : `${ids.length} leadów trafi`} do kosza.
          Możesz przywrócić każdy z nich w ciągu <strong>{recycleBinDays} dni</strong>.
          Po tym czasie auto-usunięcie wraz z draftami.
        </>
      ),
      confirmLabel: 'Przenieś do kosza',
      cancelLabel: 'Anuluj',
      destructive: true,
      icon: 'trash',
    });
    if (!ok) return;
    setBulkSubmitting(true);
    try {
      const res = await api<{
        ok: boolean; requested: number; moved_to_trash: number; skipped: number;
      }>('/api/leads/bulk-delete', {
        method: 'POST',
        body: JSON.stringify({ lead_ids: ids }),
      });
      setFlash({
        kind: 'success',
        text: `Przeniesione do kosza: ${res.moved_to_trash}${res.skipped > 0 ? ` (${res.skipped} pominięte - już w koszu)` : ''}. Auto-usunięcie za ${recycleBinDays} dni.`,
      });
      clearSelection();
      await load();
      await refreshTrashCount();
    } catch (err) {
      setFlash({ kind: 'error', text: err instanceof Error ? err.message : 'Błąd' });
    } finally {
      setBulkSubmitting(false);
    }
  }

  // Trash view actions
  async function restoreLead(leadId: number, companyName: string) {
    try {
      await api(`/api/leads/${leadId}/restore`, { method: 'POST' });
      setFlash({
        kind: 'success',
        text: `Lead "${companyName}" przywrócony do bazy.`,
      });
      await loadTrash();
      await refreshTrashCount();
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udało się przywrócić',
      });
    }
  }

  async function permanentDelete(leadId: number, companyName: string) {
    const ok = await confirm({
      title: 'Usunąć permanentnie?',
      message: (
        <>
          Lead <strong>{companyName}</strong> (#{leadId}) zostanie usunięty
          razem z draftami. <strong>Tej operacji nie można cofnąć.</strong>
        </>
      ),
      confirmLabel: 'Usuń na zawsze',
      cancelLabel: 'Anuluj',
      destructive: true,
      icon: 'trash-x',
    });
    if (!ok) return;
    try {
      await api(`/api/leads/${leadId}/permanent`, { method: 'DELETE' });
      setFlash({
        kind: 'success',
        text: `Lead "${companyName}" usunięty permanentnie.`,
      });
      await loadTrash();
      await refreshTrashCount();
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udało się usunąć',
      });
    }
  }

  async function emptyTrash() {
    if (trashTotal === 0) return;
    const ok = await confirm({
      title: 'Wyczyścić kosz?',
      message: (
        <>
          Wszystkie <strong>{trashTotal}</strong> leadów w koszu zostanie usuniętych
          permanentnie razem z draftami. <strong>Tej operacji nie można cofnąć.</strong>
        </>
      ),
      confirmLabel: 'Wyczyść kosz',
      cancelLabel: 'Anuluj',
      destructive: true,
      icon: 'trash-x',
    });
    if (!ok) return;
    try {
      const res = await api<{ ok: boolean; deleted_count: number }>(
        '/api/leads/trash/empty', { method: 'POST' },
      );
      setFlash({
        kind: 'success',
        text: `Kosz wyczyszczony: ${res.deleted_count} leadów usuniętych permanentnie.`,
      });
      await loadTrash();
      await refreshTrashCount();
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udało się wyczyścić',
      });
    }
  }

  async function reEnrich(leadId: number) {
    setDraftFlash(null);
    try {
      const res = await api<{ ok: boolean; job_id: number }>('/api/leads/enrich', {
        method: 'POST',
        body: JSON.stringify({ lead_id: leadId }),
      });
      setEnrichJobId(res.job_id);
      setEnrichJobStatus('pending');
      setDraftFlash({
        kind: 'info',
        text: 'Sprawdzam stronę jeszcze raz - scrape footer + zakładka kontakt + obfuskowane emaile (~10s)...',
      });
      void pollEnrichJob(res.job_id, leadId);
    } catch (err) {
      setDraftFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Nie udało się zlecić re-enrich',
      });
    }
  }

  /** Polling enrich job - identyczny pattern jak pollDraftJob ale dla
   *  enrichment. Po success: refreshDetail (lead.email pojawi sie), load(). */
  async function pollEnrichJob(jobId: number, leadId: number) {
    const ctrl = { cancelled: false };
    // Reuse pollAbortRef bo nigdy nie powinno byc obu jobow naraz dla jednego leada
    pollAbortRef.current = ctrl;
    const maxWaitMs = 60_000;  // enrich krotszy niz draft (no LLM)
    const start = Date.now();
    while (!ctrl.cancelled && Date.now() - start < maxWaitMs) {
      await new Promise((r) => setTimeout(r, 1500));
      if (ctrl.cancelled) return;
      try {
        const job = await api<{
          status: string;
          result: { email?: string | null; phone?: string | null; source?: string; pages_checked?: number } | null;
          last_error?: string;
        }>(`/api/jobs/${jobId}`);
        setEnrichJobStatus(job.status);
        if (job.status === 'done') {
          const email = job.result?.email;
          const phone = job.result?.phone;
          if (email || phone) {
            setDraftFlash({
              kind: 'success',
              text: email
                ? `Znaleziono email: ${email}${phone ? ' + tel ' + phone : ''}. Lead odblokowany do draftowania.`
                : `Znaleziono telefon: ${phone}. Email nadal nieznany.`,
            });
          } else {
            setDraftFlash({
              kind: 'info',
              text: 'Nadal nie znaleziono kontaktu. Sprawdz strone ręcznie lub zlec re-research z LLM.',
            });
          }
          setEnrichJobId(null);
          await refreshDetail(leadId);
          await load();
          return;
        }
        if (job.status === 'failed' || job.status === 'cancelled') {
          setDraftFlash({
            kind: 'error',
            text: `Re-enrich nieudany (${job.status}): ${job.last_error || 'unknown'}`,
          });
          setEnrichJobId(null);
          return;
        }
      } catch {
        /* network glitch */
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
        <AccountMenu />
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
              {view === 'all' ? (
                <>
                  {total} {total === 1 ? 'firma' : total < 5 ? 'firmy' : 'firm'} w bazie
                  {search.trim() && ` · filtr: "${search.trim()}"`}
                </>
              ) : (
                <>
                  Kosz: {trashTotal} {trashTotal === 1 ? 'lead' : 'leadów'}.
                  Auto-usunięcie po {recycleBinDays} dniach od daty usunięcia.
                </>
              )}
            </p>
          </div>
          <div className="page-head-actions">
            <button
              className="btn btn-secondary"
              onClick={() => { setAddLeadForm(EMPTY_ADD_LEAD_FORM); setShowAddLead(true); }}
              title="Dodaj lead ręcznie - bez Apify, bez kredytów"
            >
              <i className="ti ti-plus" /> Dodaj lead ręcznie
            </button>
            <a href="/pozyskiwanie" className="btn btn-secondary">
              <i className="ti ti-search" /> Znajdź nowe leady
            </a>
          </div>
        </div>

        {/* View toggle: Wszystkie vs Kosz */}
        <div className="view-tabs">
          <button
            className={`view-tab ${view === 'all' ? 'active' : ''}`}
            onClick={() => { setView('all'); setSelectedId(null); clearSelection(); }}
          >
            <i className="ti ti-users" /> Wszystkie
            {total > 0 && <span className="vt-count">{total}</span>}
          </button>
          <button
            className={`view-tab ${view === 'trash' ? 'active' : ''}`}
            onClick={() => { setView('trash'); setSelectedId(null); clearSelection(); }}
          >
            <i className="ti ti-trash" /> Kosz
            {trashTotal > 0 && <span className="vt-count vt-count-trash">{trashTotal}</span>}
          </button>
        </div>

        {/* Toolbar/bulk-bar + lista tylko w view 'all'. Trash ma osobny renderer ponizej. */}
        {view === 'all' && (
        <>
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
              {STATUSES.map((s) => (
                <option key={s || 'all'} value={s}>{STATUS_LABELS[s] || s}</option>
              ))}
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
            <button
              className="btn btn-bulk-delete btn-sm"
              onClick={bulkDeleteLeads}
              disabled={bulkSubmitting}
              title={`Przeniesie ${selectedIds.size} leadów do kosza (przywracalne ${recycleBinDays} dni)`}
            >
              <i className="ti ti-trash" />
              {bulkSubmitting ? 'Przenoszę...' : `Przenieś do kosza (${selectedIds.size})`}
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
                        <div className="firma-cell">
                          <strong>{l.company_name}</strong>
                          {l.active_job_type && (
                            <span
                              className="working-pill"
                              title={`Agent ${JOB_LABEL[l.active_job_type] || l.active_job_type}... (klik = otwórz drawer)`}
                            >
                              <span className="wp-dot" />
                              {JOB_LABEL[l.active_job_type] || 'Pracuje'}
                            </span>
                          )}
                        </div>
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
        </>
        )}

        {/* ============= VIEW: KOSZ ============= */}
        {view === 'trash' && (
          <>
            <div className="trash-banner">
              <i className="ti ti-info-circle" />
              <div>
                <strong>Kosz - leady oczekujące na auto-usunięcie</strong>
                <div style={{ fontSize: 12.5, color: '#6B7280', marginTop: 2 }}>
                  Każdy lead zostaje w koszu przez {recycleBinDays} dni od daty usunięcia.
                  Po tym czasie znika permanentnie wraz z draftami. Możesz przywrócić
                  go w każdej chwili lub usunąć od razu permanentnie.
                </div>
              </div>
              {trashTotal > 0 && (
                <button
                  className="btn btn-bulk-delete btn-sm"
                  onClick={emptyTrash}
                  title={`Permanentnie usun wszystkie ${trashTotal} leadow z kosza`}
                >
                  <i className="ti ti-trash-x" /> Wyczyść kosz ({trashTotal})
                </button>
              )}
            </div>

            <div className="card" style={{ marginTop: 12 }}>
              <div className="card-head">
                <div className="card-title">
                  <i className="ti ti-trash" /> Kosz ({trashTotal})
                </div>
              </div>
              {loading ? (
                <div style={{ padding: 40, textAlign: 'center', color: '#6B7280' }}>
                  Ładowanie...
                </div>
              ) : trash.length === 0 ? (
                <div className="empty-state">
                  <i className="ti ti-trash-off" />
                  <h3>Kosz jest pusty</h3>
                  <p>Nie ma żadnych leadów oczekujących na auto-usunięcie.</p>
                </div>
              ) : (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th className="num">Score</th>
                      <th>Firma</th>
                      <th>Segment</th>
                      <th>Email</th>
                      <th>Usunięty</th>
                      <th>Auto-usunięcie za</th>
                      <th style={{ textAlign: 'right' }}>Akcje</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trash.map((l) => {
                      const days = l.days_until_purge;
                      const urgent = days <= 1;
                      return (
                        <tr key={l.id}>
                          <td className="num">{scoreBadge(l.score)}</td>
                          <td>
                            <strong>{l.company_name}</strong>
                            {l.contact_name && <div className="contact-sub">{l.contact_name}</div>}
                          </td>
                          <td><span className="seg-badge">{l.segment}</span></td>
                          <td className="email-cell">{l.email || <span className="muted">brak</span>}</td>
                          <td className="muted">
                            {l.deleted_at ? formatTimeAgo(l.deleted_at) : '-'}
                          </td>
                          <td>
                            <span className={`purge-pill ${urgent ? 'urgent' : ''}`}>
                              <i className="ti ti-clock" />
                              {days < 1
                                ? `${Math.round(days * 24)}h`
                                : `${Math.ceil(days)} ${Math.ceil(days) === 1 ? 'dzień' : 'dni'}`}
                            </span>
                          </td>
                          <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => restoreLead(l.id, l.company_name)}
                              title="Przywróć lead z kosza"
                            >
                              <i className="ti ti-arrow-back-up" /> Przywróć
                            </button>
                            <button
                              className="btn-icon-mini btn-icon-danger"
                              onClick={() => permanentDelete(l.id, l.company_name)}
                              title="Usuń permanentnie (nieodwracalne)"
                              style={{ marginLeft: 6 }}
                            >
                              <i className="ti ti-trash-x" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>

      {selectedId && (
        <div className="drawer-overlay" onClick={() => setSelectedId(null)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <h2>Lead #{selectedId}</h2>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                {detail && !editMode && (
                  <button
                    className="btn-icon-mini"
                    onClick={startEdit}
                    title="Edytuj ręcznie email/telefon/kontakt/segment"
                  >
                    <i className="ti ti-edit" />
                  </button>
                )}
                <button className="close-btn" onClick={() => setSelectedId(null)}>
                  <i className="ti ti-x" />
                </button>
              </div>
            </div>
            {!detail ? (
              <div style={{ padding: 40, textAlign: 'center', color: '#6B7280' }}>Ładowanie…</div>
            ) : editMode ? (
              <div className="drawer-body">
                <div className="edit-banner">
                  <i className="ti ti-edit" />
                  <div>
                    <strong>Edytujesz ręcznie</strong>
                    <div style={{ fontSize: 12, color: '#6B7280', marginTop: 2 }}>
                      Tylko pola które chcesz poprawić. Zmiany zapisują się od razu po kliknięciu "Zapisz".
                    </div>
                  </div>
                </div>

                <div className="edit-grid">
                  <div className="edit-field">
                    <label>Kontakt (imię + nazwisko)</label>
                    <input
                      type="text"
                      value={editValues.contact_name}
                      onChange={(e) => setEditValues({ ...editValues, contact_name: e.target.value })}
                      placeholder="np. Jan Kowalski"
                    />
                  </div>
                  <div className="edit-field">
                    <label>Email</label>
                    <input
                      type="email"
                      value={editValues.email}
                      onChange={(e) => setEditValues({ ...editValues, email: e.target.value })}
                      placeholder="np. info@firma.pl"
                    />
                  </div>
                  <div className="edit-field">
                    <label>Telefon</label>
                    <input
                      type="tel"
                      value={editValues.phone}
                      onChange={(e) => setEditValues({ ...editValues, phone: e.target.value })}
                      placeholder="np. +48 22 123 45 67"
                    />
                  </div>
                  <div className="edit-field">
                    <label>Strona</label>
                    <input
                      type="url"
                      value={editValues.website}
                      onChange={(e) => setEditValues({ ...editValues, website: e.target.value })}
                      placeholder="np. https://firma.pl"
                    />
                  </div>
                  <div className="edit-field">
                    <label>Miasto</label>
                    <input
                      type="text"
                      value={editValues.city}
                      onChange={(e) => setEditValues({ ...editValues, city: e.target.value })}
                      placeholder="np. Warszawa"
                    />
                  </div>
                  <div className="edit-field">
                    <label>Segment</label>
                    <select
                      value={editValues.segment}
                      onChange={(e) => setEditValues({ ...editValues, segment: e.target.value })}
                    >
                      <option value="sklep_plastyczny">sklep_plastyczny</option>
                      <option value="sklep_papierniczy">sklep_papierniczy</option>
                      <option value="paint_and_sip">paint_and_sip</option>
                      <option value="warsztaty_dzieci">warsztaty_dzieci</option>
                      <option value="animatorzy_eventy">animatorzy_eventy</option>
                      <option value="szkola_artystyczna">szkola_artystyczna</option>
                      <option value="marka_wlasna">marka_wlasna</option>
                      <option value="inne">inne</option>
                    </select>
                  </div>
                  <div className="edit-field" style={{ gridColumn: '1 / -1' }}>
                    <label>Notatki (tylko Ty widzisz)</label>
                    <textarea
                      value={editValues.notes}
                      onChange={(e) => setEditValues({ ...editValues, notes: e.target.value })}
                      placeholder="np. 'Rozmawiałem z Piotrkiem na targach, w czerwcu wracać'"
                      rows={3}
                    />
                  </div>
                </div>

                <div className="edit-actions">
                  <button
                    className="btn btn-primary"
                    onClick={saveEdit}
                    disabled={editSubmitting}
                  >
                    <i className="ti ti-device-floppy" />
                    {editSubmitting ? 'Zapisuję…' : 'Zapisz zmiany'}
                  </button>
                  <button
                    className="btn btn-ghost"
                    onClick={cancelEdit}
                    disabled={editSubmitting}
                  >
                    Anuluj
                  </button>
                </div>
              </div>
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
                        <div className="jp-progress">
                          <div className="jp-progress-fill" />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Enrich job in progress */}
                  {enrichJobId !== null && (
                    <div className="job-progress active">
                      <div className="jp-spinner" />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>
                          <span className="jp-dot" />
                          Szukam kontaktu na stronie<span className="working-dots" />{' '}
                          <span className="mono" style={{ color: '#6B7280' }}>#{enrichJobId}</span>
                        </div>
                        <div style={{ fontSize: 11, color: '#6B7280', marginTop: 2 }}>
                          Sprawdzam stopkę, /kontakt, /wspolpraca, /dla-firm, /footer
                          + dekoduję obfuskowane emaile (HTML entities, CloudFlare, [at]).
                        </div>
                        <div className="jp-progress">
                          <div className="jp-progress-fill" />
                        </div>
                      </div>
                    </div>
                  )}

                  {detail.status !== 'sent' && detail.status !== 'replied' && detail.email && draftJobId === null && enrichJobId === null && (
                    <button
                      className="btn btn-primary"
                      onClick={() => generateDraft(detail.id)}
                    >
                      <i className="ti ti-mail-plus" />{' '}
                      {detail.drafts.length > 0 ? 'Generuj kolejny draft' : 'Generuj draft maila'}
                    </button>
                  )}

                  {/* Brak emaila -> button "Sprawdz strone jeszcze raz".
                      Dostepny tez gdy lead.status='dead_end' (cofa z dead-end'a
                      jak znajdzie email - logika w backend enrich_lead_in_db). */}
                  {!detail.email && detail.website && enrichJobId === null && (
                    <>
                      <div className="missing-email-box">
                        <div className="me-title">
                          <i className="ti ti-mail-off" />
                          Brak emaila - nie mozna wyslac maila do tego leada
                        </div>
                        <div className="me-desc">
                          Strona moze ukrywac email w stopce / zakladce kontakt /
                          obfuskowac przez JavaScript albo HTML entities. Sprobuj
                          ponownie - nowy scraper sprawdza wiecej miejsc i dekoduje
                          typowe obfuscation patterny.
                        </div>
                        <button
                          className="btn btn-secondary"
                          onClick={() => reEnrich(detail.id)}
                          style={{ marginTop: 10 }}
                        >
                          <i className="ti ti-refresh" /> Sprawdź stronę jeszcze raz
                        </button>
                      </div>
                    </>
                  )}

                  {!detail.email && !detail.website && (
                    <span style={{ fontSize: 13, color: '#8F1018' }}>
                      Brak emaila i brak strony - nie da się tu nic zrobić automatycznie.
                    </span>
                  )}

                  {/* Block / Unblock - manualny hard-skip dla "pewniakow z
                      ktorych nic nie bedzie". Lead pozostaje w bazie ale znika
                      z domyslnego widoku (filtr 'not_sent'). */}
                  {detail.status === 'blacklisted' ? (
                    <button
                      className="btn btn-secondary"
                      onClick={unblockLead}
                      title="Przywroc lead do widoku 'do roboty'"
                    >
                      <i className="ti ti-rotate-clockwise" /> Odblokuj lead
                    </button>
                  ) : (
                    <button
                      className="btn-block-lead"
                      onClick={blockLead}
                      title="Ukryj lead z listy - pozostaje w bazie, ale znika z domyslnego filtra"
                    >
                      <i className="ti ti-ban" /> Zablokuj lead
                    </button>
                  )}

                  {/* Destrukcyjna akcja - na samym dole, dyskretna.
                      Soft-delete: lead trafia do kosza (przywracalny przez {recycleBinDays} dni). */}
                  <button
                    className="btn-delete-lead"
                    onClick={deleteLead}
                    title={`Przenieś lead do kosza (przywracalny przez ${recycleBinDays} dni)`}
                  >
                    <i className="ti ti-trash" /> Przenieś do kosza
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Modal "Dodaj lead ręcznie" - center modal, NIE drawer (form jest dluzszy) */}
      {showAddLead && (
        <div
          className="modal-overlay"
          onClick={() => !addLeadSubmitting && setShowAddLead(false)}
          role="presentation"
        >
          <div
            className="modal add-lead-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-labelledby="add-lead-title"
          >
            <div className="modal-head">
              <h2 id="add-lead-title">
                <i className="ti ti-plus" /> Dodaj lead ręcznie
              </h2>
              <button
                className="modal-close"
                onClick={() => setShowAddLead(false)}
                disabled={addLeadSubmitting}
                aria-label="Zamknij"
              >
                <i className="ti ti-x" />
              </button>
            </div>
            <form className="modal-body add-lead-form" onSubmit={submitAddLead}>
              <p className="add-lead-hint">
                Bez discovery, bez kredytów Apify. Wpisz tyle ile wiesz — minimum to nazwa firmy.
                Jeśli podasz email, lead od razu będzie gotowy do draftowania.
              </p>

              <div className="form-row">
                <label>
                  Nazwa firmy <span className="req">*</span>
                  <input
                    type="text" required maxLength={255} autoFocus
                    value={addLeadForm.company_name}
                    onChange={(e) => setAddLeadForm({ ...addLeadForm, company_name: e.target.value })}
                    placeholder="np. ArtBox Studio"
                  />
                </label>
                <label>
                  Segment
                  <select
                    value={addLeadForm.segment}
                    onChange={(e) => setAddLeadForm({ ...addLeadForm, segment: e.target.value })}
                  >
                    {SEGMENT_OPTIONS.map((s) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="form-row">
                <label>
                  Strona www
                  <input
                    type="text"
                    value={addLeadForm.website}
                    onChange={(e) => setAddLeadForm({ ...addLeadForm, website: e.target.value })}
                    placeholder="artbox.pl"
                  />
                </label>
                <label>
                  Miasto
                  <input
                    type="text" maxLength={100}
                    value={addLeadForm.city}
                    onChange={(e) => setAddLeadForm({ ...addLeadForm, city: e.target.value })}
                    placeholder="Kraków"
                  />
                </label>
              </div>

              <div className="form-row">
                <label>
                  Imię i nazwisko kontaktu
                  <input
                    type="text" maxLength={255}
                    value={addLeadForm.contact_name}
                    onChange={(e) => setAddLeadForm({ ...addLeadForm, contact_name: e.target.value })}
                    placeholder="Anna Kowalska"
                  />
                </label>
                <label>
                  Telefon
                  <input
                    type="text" maxLength={50}
                    value={addLeadForm.phone}
                    onChange={(e) => setAddLeadForm({ ...addLeadForm, phone: e.target.value })}
                    placeholder="+48 123 456 789"
                  />
                </label>
              </div>

              <label>
                Email
                <input
                  type="email" maxLength={255}
                  value={addLeadForm.email}
                  onChange={(e) => setAddLeadForm({ ...addLeadForm, email: e.target.value })}
                  placeholder="kontakt@artbox.pl"
                />
                <span className="field-hint">
                  Bez emaila lead pójdzie do enrichmentu. Z emailem - od razu gotowy do draftowania.
                </span>
              </label>

              <label>
                Notatki
                <textarea
                  rows={3}
                  value={addLeadForm.notes}
                  onChange={(e) => setAddLeadForm({ ...addLeadForm, notes: e.target.value })}
                  placeholder="Skąd lead? Co Ci o nich wiadomo?"
                />
              </label>

              <div className="modal-actions">
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setShowAddLead(false)}
                  disabled={addLeadSubmitting}
                >
                  Anuluj
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={addLeadSubmitting || !addLeadForm.company_name.trim()}
                >
                  {addLeadSubmitting ? (
                    <><i className="ti ti-loader" /> Zapisuję…</>
                  ) : (
                    <><i className="ti ti-check" /> Dodaj lead</>
                  )}
                </button>
              </div>
            </form>
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

/* ===== VIEW TABS (Wszystkie / Kosz) ===== */
.view-tabs {
  display: flex; gap: 4px; margin-bottom: 12px;
  border-bottom: 1px solid #E5E7EB;
  padding: 0 0 0 4px;
}
.view-tab {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 16px;
  background: none; border: none; cursor: pointer;
  font-family: inherit; font-size: 13.5px; font-weight: 500;
  color: #6B7280;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color 0.12s, border-color 0.12s;
}
.view-tab:hover { color: #111; }
.view-tab.active { color: #D4212C; border-bottom-color: #D4212C; }
.view-tab i { font-size: 16px; }
.vt-count {
  font-size: 11px; font-weight: 600;
  padding: 2px 7px; border-radius: 10px;
  background: #F3F4F6; color: #6B7280;
}
.view-tab.active .vt-count { background: #FDECED; color: #8F1018; }
.vt-count-trash { background: #FEF3C7; color: #92400E; }
.view-tab.active .vt-count-trash { background: #FDECED; color: #8F1018; }

/* Bulk-delete button - czerwonawy, dyskretny w bulk-bar */
.btn-bulk-delete {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; font-size: 12.5px; font-weight: 500;
  background: #fff; color: #8F1018; border: 1px solid #FCA5A5;
  border-radius: 6px; cursor: pointer; font-family: inherit;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.btn-bulk-delete:hover:not(:disabled) {
  background: #D4212C; color: #fff; border-color: #D4212C;
}
.btn-bulk-delete:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-bulk-delete i { font-size: 14px; }

/* ===== TRASH VIEW ===== */
.trash-banner {
  display: flex; align-items: center; gap: 12px;
  background: #FEF3C7; border: 1px solid #FDE68A; border-radius: 8px;
  padding: 14px 16px; margin-bottom: 12px;
}
.trash-banner > i {
  font-size: 22px; color: #92400E; flex-shrink: 0;
}
.trash-banner > div { flex: 1; font-size: 13.5px; color: #78350F; }
.trash-banner strong { color: #78350F; font-weight: 600; }

.purge-pill {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 8px; border-radius: 10px;
  font-size: 11.5px; font-weight: 500;
  background: #F3F4F6; color: #4B5563;
}
.purge-pill i { font-size: 12px; }
.purge-pill.urgent { background: #FEE2E2; color: #991B1B; }

.btn-icon-danger {
  width: 28px; height: 28px; border-radius: 6px;
  border: 1px solid #FCA5A5; background: #fff;
  color: #8F1018; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 14px; transition: background 0.12s, color 0.12s;
}
.btn-icon-danger:hover { background: #D4212C; color: #fff; border-color: #D4212C; }

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

/* Wiersz tabeli z aktywnym jobem - badge "Pracuje" obok nazwy */
.firma-cell {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.working-pill {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 8px 2px 7px;
  background: #FDECED;
  border: 1px solid #FCA5A5;
  border-radius: 11px;
  font-size: 10.5px; font-weight: 600;
  color: #8F1018;
  font-family: 'JetBrains Mono', monospace;
  cursor: help;
  animation: working-pulse 2s ease-in-out infinite;
}
.wp-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #D4212C;
  animation: dot-pulse 1.4s ease-in-out infinite;
  flex-shrink: 0;
}
@keyframes working-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(212,33,44,0.0); }
  50%      { box-shadow: 0 0 0 3px rgba(212,33,44,0.15); }
}
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

.page-head-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* Modal "Dodaj lead recznie" - center modal, klikalny backdrop */
.modal-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(17, 17, 17, 0.55);
  backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center;
  padding: 24px;
  animation: ml-fade 0.12s ease-out;
}
@keyframes ml-fade { from { opacity: 0; } to { opacity: 1; } }
.modal {
  background: #fff; border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0,0,0,0.25), 0 4px 12px rgba(0,0,0,0.1);
  width: 100%; max-width: 560px;
  max-height: calc(100vh - 48px);
  display: flex; flex-direction: column;
  animation: ml-pop 0.16s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes ml-pop {
  from { opacity: 0; transform: scale(0.94) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
.modal-head {
  padding: 16px 20px; border-bottom: 1px solid #E5E7EB;
  display: flex; align-items: center; justify-content: space-between;
  flex-shrink: 0;
}
.modal-head h2 {
  font-size: 16px; font-weight: 600; margin: 0;
  display: flex; align-items: center; gap: 8px; letter-spacing: -0.2px;
}
.modal-head h2 i { color: #D4212C; font-size: 18px; }
.modal-close {
  background: none; border: none; cursor: pointer; padding: 4px;
  color: #6B7280; border-radius: 6px; display: flex;
}
.modal-close:hover:not(:disabled) { background: #F3F4F6; color: #111; }
.modal-close:disabled { opacity: 0.5; cursor: not-allowed; }
.modal-body {
  padding: 20px; overflow-y: auto;
  display: flex; flex-direction: column; gap: 14px;
}
.add-lead-hint {
  font-size: 12.5px; color: #6B7280; margin: 0 0 4px;
  line-height: 1.5; padding: 10px 12px;
  background: #FAFAF7; border-left: 3px solid #D4212C; border-radius: 4px;
}
.add-lead-form label {
  display: flex; flex-direction: column; gap: 4px;
  font-size: 12px; color: #4B5563; font-weight: 500;
}
.add-lead-form .req { color: #D4212C; }
.add-lead-form input,
.add-lead-form select,
.add-lead-form textarea {
  padding: 8px 10px; border: 1px solid #E5E7EB; border-radius: 6px;
  font-size: 13.5px; font-family: inherit; color: #111;
  background: #fff; transition: border-color 0.12s, box-shadow 0.12s;
}
.add-lead-form input:focus,
.add-lead-form select:focus,
.add-lead-form textarea:focus {
  outline: none; border-color: #D4212C;
  box-shadow: 0 0 0 3px rgba(212, 33, 44, 0.12);
}
.add-lead-form textarea { resize: vertical; min-height: 60px; font-family: inherit; }
.add-lead-form .field-hint {
  font-size: 11.5px; color: #9CA3AF; font-weight: 400; margin-top: 2px;
}
.add-lead-form .form-row {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
}
@media (max-width: 520px) {
  .add-lead-form .form-row { grid-template-columns: 1fr; }
}
.modal-actions {
  display: flex; gap: 8px; justify-content: flex-end;
  margin-top: 8px; padding-top: 14px; border-top: 1px solid #F3F4F6;
}
.modal-actions .btn { min-width: 100px; justify-content: center; }
.modal-actions .ti-loader { animation: spin 1.2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

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

/* Manualna edycja leadu (w drawer'ze) */
.btn-icon-mini {
  background: none; border: 1px solid #E5E7EB;
  width: 32px; height: 32px; border-radius: 6px;
  cursor: pointer; color: #6B7280;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
}
.btn-icon-mini:hover { color: #D4212C; border-color: #D4212C; background: #FDECED; }

.edit-banner {
  display: flex; gap: 10px; align-items: flex-start;
  padding: 12px 14px;
  background: #EFF6FF; border: 1px solid #BFDBFE;
  border-radius: 8px; margin-bottom: 16px;
  font-size: 13px; color: #1E40AF;
}
.edit-banner i { font-size: 18px; flex-shrink: 0; margin-top: 1px; }

.edit-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  margin-bottom: 16px;
}
@media (max-width: 600px) {
  .edit-grid { grid-template-columns: 1fr; }
}
.edit-field { display: flex; flex-direction: column; gap: 4px; }
.edit-field label {
  font-size: 11px; color: #6B7280;
  text-transform: uppercase; letter-spacing: 0.6px;
  font-weight: 600;
}
.edit-field input, .edit-field select, .edit-field textarea {
  padding: 8px 12px; border: 1px solid #E5E7EB;
  border-radius: 6px; font-family: inherit;
  font-size: 13.5px; background: #fff; color: #111;
  resize: vertical;
}
.edit-field input:focus, .edit-field select:focus, .edit-field textarea:focus {
  outline: none; border-color: #D4212C;
  box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}

.edit-actions {
  display: flex; gap: 8px; padding-top: 12px;
  border-top: 1px solid #E5E7EB;
}

/* Brak emaila - box z CTA "Sprawdz ponownie" */
.missing-email-box {
  padding: 14px 16px;
  background: #FFF7ED;
  border: 1px solid #FED7AA;
  border-radius: 10px;
}
.me-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 13.5px; font-weight: 600; color: #9A3412;
  margin-bottom: 4px;
}
.me-title i { font-size: 16px; }
.me-desc {
  font-size: 12px; color: #9A3412;
  line-height: 1.4; opacity: 0.85;
}
.btn-secondary {
  background: #fff; color: #111; border: 1px solid #E5E7EB;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 500;
  cursor: pointer; font-family: inherit;
}
.btn-secondary:hover { background: #FAFAF7; border-color: #D1D5DB; }
.btn-secondary i { font-size: 14px; color: #D4212C; }

/* Destrukcyjna akcja - dyskretna, ale wyraznie czerwona przy hover */
.btn-delete-lead {
  margin-top: 16px;
  padding: 6px 10px;
  background: none; border: 1px solid #F3F4F6;
  border-radius: 6px;
  color: #9CA3AF; font-size: 11.5px;
  cursor: pointer; font-family: inherit;
  display: inline-flex; align-items: center; gap: 5px;
  align-self: flex-start;
  transition: all 0.15s;
}
.btn-delete-lead i { font-size: 13px; }
.btn-delete-lead:hover {
  background: #FEE2E2; border-color: #FCA5A5; color: #991B1B;
}

/* Block lead - mniej destrukcyjne niz delete, ale wyrazne */
.btn-block-lead {
  margin-top: 4px;
  padding: 7px 11px;
  background: none; border: 1px solid #FDE68A;
  border-radius: 6px;
  color: #92400E; font-size: 12px;
  cursor: pointer; font-family: inherit;
  display: inline-flex; align-items: center; gap: 6px;
  align-self: flex-start;
  transition: all 0.15s;
}
.btn-block-lead i { font-size: 14px; }
.btn-block-lead:hover {
  background: #FEF3C7; border-color: #FBBF24; color: #78350F;
}
`;
