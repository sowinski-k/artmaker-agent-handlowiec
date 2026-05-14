/* Moje konto - profil + zmiana hasla + workspace + API keys + sygnatura.
 *
 * Sekcje:
 *   1. Profil      - email (read-only) + name
 *   2. Hasło       - zmiana hasła (current + new + confirm)
 *   3. Workspace   - nazwa workspace + identity (do sygnatury maili)
 *   4. API keys    - per workspace override globalnego env (Anthropic, Gemini,
 *                    Apify, Google Places, Woodpecker)
 *
 * Backend endpointy:
 *   GET  /api/auth/me                  - aktualny stan
 *   PATCH /api/auth/me                 - update name
 *   POST /api/auth/change-password     - zmiana hasla
 *   PATCH /api/workspace               - update workspace name + owner identity
 *   GET  /api/workspace/api-keys       - lista keys (masked)
 *   PUT  /api/workspace/api-keys       - update keys
 */

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { api, isAuthenticated, refreshMe } from '@/lib/api';
import { AccountMenu } from '@/lib/AccountMenu';

interface MeResponse {
  user: { id: number; email: string; name: string | null; is_admin: boolean };
  workspace: {
    id: number; name: string; slug: string; plan: string;
    credits: number; used_credits: number;
  };
}

interface ApiKeyRow {
  name: string;
  workspace_set: boolean;
  workspace_masked: string | null;
  env_fallback_set: boolean;
  effective_source: 'workspace' | 'env' | 'none';
}

interface KeysResponse {
  keys: ApiKeyRow[];
}

interface WorkspaceUpdateResponse {
  ok: boolean;
  workspace: { id: number; name: string; slug: string; plan: string; credits: number; used_credits: number };
  owner_identity: {
    owner_name?: string; owner_title?: string;
    company_name?: string; company_website?: string;
  };
  changed: string[];
}

const KEY_LABELS: Record<string, { label: string; desc: string; placeholder: string }> = {
  ANTHROPIC_API_KEY: {
    label: 'Anthropic (Claude)',
    desc: 'Klucz API Claude\'a do researchu i pisania maili. Konto: console.anthropic.com',
    placeholder: 'sk-ant-...',
  },
  GEMINI_API_KEY: {
    label: 'Google Gemini',
    desc: 'Klucz API Gemini do filtru trafnosci. Konto: aistudio.google.com',
    placeholder: 'AIza...',
  },
  APIFY_API_TOKEN: {
    label: 'Apify',
    desc: 'Scraper Google Maps + Allegro + LinkedIn. Konto: console.apify.com',
    placeholder: 'apify_api_...',
  },
  GOOGLE_PLACES_API_KEY: {
    label: 'Google Places API',
    desc: 'Discovery firm po nazwie + miejscu. Free tier $200/mies kredytu.',
    placeholder: 'AIza...',
  },
  WOODPECKER_API_KEY: {
    label: 'Woodpecker',
    desc: 'Wysylka cold-mail i polling odpowiedzi. Konto: woodpecker.co',
    placeholder: 'wp_...',
  },
};

export default function KontoPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState<{ kind: 'success' | 'error' | 'info'; text: string } | null>(null);

  // Profile
  const [profileName, setProfileName] = useState('');
  const [profileSaving, setProfileSaving] = useState(false);

  // Password
  const [currentPwd, setCurrentPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [newPwd2, setNewPwd2] = useState('');
  const [pwdSaving, setPwdSaving] = useState(false);

  // Workspace
  const [wsName, setWsName] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [ownerTitle, setOwnerTitle] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [companyWebsite, setCompanyWebsite] = useState('');
  const [wsSaving, setWsSaving] = useState(false);

  // API keys - per-key new value buffer (puste = nie zmieniaj)
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [keysSaving, setKeysSaving] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' && !isAuthenticated()) {
      router.push('/login');
      return;
    }
    void loadAll();
    /* eslint-disable-next-line */
  }, []);

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

  async function loadAll() {
    setLoading(true);
    try {
      const [meRes, keysRes, wsRes] = await Promise.all([
        api<MeResponse>('/api/auth/me'),
        api<KeysResponse>('/api/workspace/api-keys'),
        // Pobranie owner_identity (workspace patch zwraca strukture - dla GET
        // uzywamy /api/auth/me ktore daje workspace bez identity; identity
        // bierzemy z patcha-by-no-op albo skip - dla pierwszego load uzywamy
        // pustych pol z formularzy. Po zapisie odpowiedz patch zaktualizuje state).
        Promise.resolve(null),
      ]);
      setMe(meRes);
      setKeys(keysRes.keys);
      setProfileName(meRes.user.name || '');
      setWsName(meRes.workspace.name || '');
      void wsRes;
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Błąd ładowania konta',
      });
    } finally {
      setLoading(false);
    }
  }

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    setProfileSaving(true);
    try {
      await api('/api/auth/me', {
        method: 'PATCH',
        body: JSON.stringify({ name: profileName.trim() || null }),
      });
      // Update LS cache zeby AccountMenu pokazal aktualne dane od razu
      await refreshMe();
      setFlash({ kind: 'success', text: 'Profil zaktualizowany.' });
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Błąd zapisu',
      });
    } finally {
      setProfileSaving(false);
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    if (newPwd !== newPwd2) {
      setFlash({ kind: 'error', text: 'Nowe hasła nie są takie same.' });
      return;
    }
    if (newPwd.length < 8) {
      setFlash({ kind: 'error', text: 'Nowe hasło musi mieć min. 8 znaków.' });
      return;
    }
    setPwdSaving(true);
    try {
      await api('/api/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPwd, new_password: newPwd }),
      });
      setCurrentPwd(''); setNewPwd(''); setNewPwd2('');
      setFlash({ kind: 'success', text: 'Hasło zmienione. Następne logowanie z nowym hasłem.' });
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Błąd zmiany hasła',
      });
    } finally {
      setPwdSaving(false);
    }
  }

  async function saveWorkspace(e: React.FormEvent) {
    e.preventDefault();
    setWsSaving(true);
    try {
      const res = await api<WorkspaceUpdateResponse>('/api/workspace', {
        method: 'PATCH',
        body: JSON.stringify({
          name: wsName.trim() || null,
          owner_name: ownerName,
          owner_title: ownerTitle,
          company_name: companyName,
          company_website: companyWebsite,
        }),
      });
      if (res.owner_identity) {
        setOwnerName(res.owner_identity.owner_name || '');
        setOwnerTitle(res.owner_identity.owner_title || '');
        setCompanyName(res.owner_identity.company_name || '');
        setCompanyWebsite(res.owner_identity.company_website || '');
      }
      await refreshMe();
      setFlash({
        kind: 'success',
        text: res.changed.length ? `Workspace zaktualizowany (${res.changed.join(', ')}).` : 'Nic do zmiany.',
      });
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Błąd zapisu',
      });
    } finally {
      setWsSaving(false);
    }
  }

  async function saveKeys(e: React.FormEvent) {
    e.preventDefault();
    // Bierzemy tylko klucze ktore user TKNAL - puste pole bez tknięcia = nie wysyłamy
    // (PATCH semantyka). Jezeli user wpisal cos i potem wyczyścił, wysylamy "" = usun.
    const payload: Record<string, string> = {};
    for (const [name, value] of Object.entries(keyInputs)) {
      payload[name] = value;
    }
    if (Object.keys(payload).length === 0) {
      setFlash({ kind: 'info', text: 'Nic nie zmieniono - wpisz nowy klucz albo wyczyść istniejący.' });
      return;
    }
    setKeysSaving(true);
    try {
      const res = await api<{ ok: boolean; changed: string[] }>(
        '/api/workspace/api-keys',
        { method: 'PUT', body: JSON.stringify({ keys: payload }) },
      );
      setKeyInputs({}); // wyczysc bufory po sukcesie
      // Refresh stan kluczy
      const fresh = await api<KeysResponse>('/api/workspace/api-keys');
      setKeys(fresh.keys);
      setFlash({
        kind: 'success',
        text: `Klucze zaktualizowane: ${res.changed.length ? res.changed.join(', ') : 'brak zmian'}.`,
      });
    } catch (err) {
      setFlash({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Błąd zapisu kluczy',
      });
    } finally {
      setKeysSaving(false);
    }
  }

  if (loading) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center', color: '#6B7280' }}>
        Ładowanie konta...
      </div>
    );
  }

  if (!me) {
    return (
      <div style={{ padding: '60px 24px', textAlign: 'center', color: '#8F1018' }}>
        Brak danych konta.
      </div>
    );
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: KONTO_CSS }} />

      {flash && (
        <div className={`konto-flash flash-${flash.kind}`}>
          {flash.kind === 'success' && <i className="ti ti-check" />}
          {flash.kind === 'error' && <i className="ti ti-alert-circle" />}
          {flash.kind === 'info' && <i className="ti ti-info-circle" />}
          <span style={{ flex: 1 }}>{flash.text}</span>
          <button className="flash-close" onClick={() => setFlash(null)}>
            <i className="ti ti-x" />
          </button>
        </div>
      )}

      <div className="topbar">
        <div className="crumb">
          <strong>Konto</strong>
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <AccountMenu />
        </div>
      </div>

      <div className="content">
        <div className="page-head">
          <h1>Moje konto</h1>
          <p>Profil, hasło, ustawienia workspace, klucze API, sygnatura agenta.</p>
        </div>

        <div className="konto-grid">
          {/* === PROFIL === */}
          <section className="konto-card">
            <div className="kc-head">
              <i className="ti ti-user" />
              <h2>Profil</h2>
            </div>
            <form onSubmit={saveProfile}>
              <div className="kc-field">
                <label>Email</label>
                <input type="email" value={me.user.email} disabled />
                <span className="kc-hint">Email nie można zmienić tutaj. Skontaktuj się z supportem.</span>
              </div>
              <div className="kc-field">
                <label>Imię / nazwa do wyświetlenia</label>
                <input
                  type="text"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  placeholder="np. Krzysztof Sowiński"
                  maxLength={255}
                />
                <span className="kc-hint">Widoczne w avatarze i w menu konta.</span>
              </div>
              <div className="kc-actions">
                <button type="submit" className="btn-save" disabled={profileSaving}>
                  {profileSaving ? 'Zapisuję...' : 'Zapisz profil'}
                </button>
              </div>
            </form>
          </section>

          {/* === ZMIANA HASLA === */}
          <section className="konto-card">
            <div className="kc-head">
              <i className="ti ti-lock" />
              <h2>Hasło</h2>
            </div>
            <form onSubmit={savePassword} autoComplete="off">
              <div className="kc-field">
                <label>Aktualne hasło</label>
                <input
                  type="password"
                  value={currentPwd}
                  onChange={(e) => setCurrentPwd(e.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>
              <div className="kc-field">
                <label>Nowe hasło</label>
                <input
                  type="password"
                  value={newPwd}
                  onChange={(e) => setNewPwd(e.target.value)}
                  autoComplete="new-password"
                  required
                  minLength={8}
                />
                <span className="kc-hint">Min. 8 znaków, w tym mała + wielka litera + cyfra.</span>
              </div>
              <div className="kc-field">
                <label>Powtórz nowe hasło</label>
                <input
                  type="password"
                  value={newPwd2}
                  onChange={(e) => setNewPwd2(e.target.value)}
                  autoComplete="new-password"
                  required
                  minLength={8}
                />
                {newPwd && newPwd2 && newPwd !== newPwd2 && (
                  <span className="kc-hint kc-hint-error">Hasła się różnią.</span>
                )}
              </div>
              <div className="kc-actions">
                <button
                  type="submit"
                  className="btn-save"
                  disabled={pwdSaving || !currentPwd || !newPwd || newPwd !== newPwd2}
                >
                  {pwdSaving ? 'Zmieniam...' : 'Zmień hasło'}
                </button>
              </div>
            </form>
          </section>

          {/* === WORKSPACE + SYGNATURA === */}
          <section className="konto-card konto-card-wide">
            <div className="kc-head">
              <i className="ti ti-building" />
              <h2>Workspace</h2>
              <span className="kc-plan-pill">
                <i className="ti ti-shield-check" />
                Plan: {me.workspace.plan}
              </span>
            </div>
            <form onSubmit={saveWorkspace}>
              <div className="kc-grid-2">
                <div className="kc-field">
                  <label>Nazwa workspace</label>
                  <input
                    type="text"
                    value={wsName}
                    onChange={(e) => setWsName(e.target.value)}
                    maxLength={255}
                  />
                  <span className="kc-hint">Widoczne w sidebar i w avatar menu.</span>
                </div>
                <div className="kc-field">
                  <label>Kredyty</label>
                  <input
                    type="text"
                    value={`${me.workspace.used_credits.toLocaleString('pl-PL')} / ${me.workspace.credits.toLocaleString('pl-PL')}`}
                    disabled
                  />
                  <span className="kc-hint">Plan {me.workspace.plan}. Skontaktuj się aby zwiększyć.</span>
                </div>
              </div>

              <div className="kc-subsection">
                <div className="kc-subsection-title">
                  <i className="ti ti-signature" /> Sygnatura agenta (w mailach)
                </div>
                <div className="kc-subsection-desc">
                  Te dane agent wpisuje na końcu maili w imieniu Twoim/firmy.
                  Pozostaw puste żeby użyć defaulta z ENV.
                </div>
                <div className="kc-grid-2">
                  <div className="kc-field">
                    <label>Imię i nazwisko nadawcy</label>
                    <input
                      type="text"
                      value={ownerName}
                      onChange={(e) => setOwnerName(e.target.value)}
                      placeholder="np. Krzysztof Sowiński"
                      maxLength={255}
                    />
                  </div>
                  <div className="kc-field">
                    <label>Tytuł / stanowisko</label>
                    <input
                      type="text"
                      value={ownerTitle}
                      onChange={(e) => setOwnerTitle(e.target.value)}
                      placeholder="np. właściciel, founder"
                      maxLength={255}
                    />
                  </div>
                  <div className="kc-field">
                    <label>Nazwa firmy</label>
                    <input
                      type="text"
                      value={companyName}
                      onChange={(e) => setCompanyName(e.target.value)}
                      placeholder="np. Artmaker"
                      maxLength={255}
                    />
                  </div>
                  <div className="kc-field">
                    <label>Strona firmy</label>
                    <input
                      type="url"
                      value={companyWebsite}
                      onChange={(e) => setCompanyWebsite(e.target.value)}
                      placeholder="np. https://artmaker.pl"
                      maxLength={255}
                    />
                  </div>
                </div>
              </div>

              <div className="kc-actions">
                <button type="submit" className="btn-save" disabled={wsSaving}>
                  {wsSaving ? 'Zapisuję...' : 'Zapisz workspace'}
                </button>
              </div>
            </form>
          </section>

          {/* === API KEYS === */}
          <section className="konto-card konto-card-wide">
            <div className="kc-head">
              <i className="ti ti-key" />
              <h2>Klucze API</h2>
            </div>
            <div className="kc-subsection-desc" style={{ marginTop: 0, marginBottom: 16 }}>
              Klucze workspace nadpisują globalne klucze platformy. Bez wpisania klucza
              workspace - używamy globalnego fallback'u. Pokazujemy tylko ostatnie 4 znaki -
              nie da się odczytać pełnego klucza po zapisaniu.
            </div>
            <form onSubmit={saveKeys}>
              {keys.map((k) => {
                const meta = KEY_LABELS[k.name] || { label: k.name, desc: '', placeholder: '' };
                const buf = keyInputs[k.name];
                const hasInput = buf !== undefined;
                return (
                  <div className="kc-field kc-key-field" key={k.name}>
                    <label>
                      {meta.label}
                      <span className={`kc-key-source kc-key-${k.effective_source}`}>
                        {k.effective_source === 'workspace' && <>
                          <i className="ti ti-circle-filled" /> klucz workspace · {k.workspace_masked}
                        </>}
                        {k.effective_source === 'env' && <>
                          <i className="ti ti-server-bolt" /> globalny (env)
                        </>}
                        {k.effective_source === 'none' && <>
                          <i className="ti ti-alert-triangle" /> brak klucza
                        </>}
                      </span>
                    </label>
                    <input
                      type="password"
                      value={hasInput ? buf : ''}
                      onChange={(e) =>
                        setKeyInputs({ ...keyInputs, [k.name]: e.target.value })
                      }
                      placeholder={k.workspace_set ? '••••••••••• (pusty = usuń)' : meta.placeholder}
                    />
                    {meta.desc && <span className="kc-hint">{meta.desc}</span>}
                  </div>
                );
              })}
              <div className="kc-actions">
                <button type="submit" className="btn-save" disabled={keysSaving}>
                  {keysSaving ? 'Zapisuję...' : 'Zapisz klucze'}
                </button>
                <span className="kc-hint" style={{ marginLeft: 12 }}>
                  Tylko pola które wypełnisz zostaną zaktualizowane.
                </span>
              </div>
            </form>
          </section>
        </div>
      </div>
    </>
  );
}

const KONTO_CSS = `
.topbar { background: #fff; border-bottom: 1px solid #E5E7EB; padding: 0 24px; display: flex; align-items: center; height: 52px; gap: 16px; position: sticky; top: 0; z-index: 10; }
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #6B7280; }
.crumb strong { color: #111; font-weight: 500; }

.content { padding: 24px; max-width: 1080px; margin: 0 auto; }
.page-head { margin-bottom: 20px; }
.page-head h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.4px; margin: 0 0 4px; }
.page-head p { color: #6B7280; font-size: 13.5px; margin: 0; }

.konto-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.konto-card {
  background: #fff;
  border: 1px solid #E5E7EB;
  border-radius: 10px;
  padding: 20px;
}
.konto-card-wide { grid-column: 1 / -1; }
@media (max-width: 760px) {
  .konto-grid { grid-template-columns: 1fr; }
  .konto-card-wide { grid-column: auto; }
}

.kc-head {
  display: flex; align-items: center; gap: 10px;
  padding-bottom: 14px; margin-bottom: 16px;
  border-bottom: 1px solid #F3F4F6;
}
.kc-head i { font-size: 18px; color: #D4212C; }
.kc-head h2 {
  font-size: 15.5px; font-weight: 600; color: #111;
  margin: 0; letter-spacing: -0.2px; flex: 1;
}
.kc-plan-pill {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; font-weight: 600;
  color: #166534; background: #DCFCE7;
  padding: 4px 9px; border-radius: 10px;
  text-transform: capitalize;
}
.kc-plan-pill i { font-size: 12px; color: #166534; }

.kc-field {
  display: flex; flex-direction: column; gap: 4px;
  margin-bottom: 14px;
}
.kc-field label {
  display: flex; align-items: center; gap: 6px;
  font-size: 12.5px; font-weight: 500; color: #374151;
}
.kc-field input {
  padding: 9px 12px;
  border: 1px solid #E5E7EB; border-radius: 7px;
  font-family: inherit; font-size: 13px; color: #111;
  background: #FAFAF7;
  transition: border-color 0.12s, background 0.12s, box-shadow 0.12s;
}
.kc-field input:focus {
  outline: none; border-color: #D4212C; background: #fff;
  box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}
.kc-field input:disabled {
  background: #F3F4F6; color: #6B7280; cursor: not-allowed;
}
.kc-hint {
  font-size: 11.5px; color: #6B7280; margin-top: 2px;
}
.kc-hint-error { color: #8F1018; }

.kc-grid-2 {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
}
@media (max-width: 600px) {
  .kc-grid-2 { grid-template-columns: 1fr; }
}

.kc-subsection {
  margin-top: 18px; padding-top: 16px;
  border-top: 1px dashed #E5E7EB;
}
.kc-subsection-title {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 600; color: #111;
  margin-bottom: 4px;
}
.kc-subsection-title i { font-size: 14px; color: #D4212C; }
.kc-subsection-desc {
  font-size: 11.5px; color: #6B7280;
  margin-bottom: 12px;
  line-height: 1.5;
}

/* API keys */
.kc-key-field { margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #F3F4F6; }
.kc-key-field:last-of-type { border-bottom: none; padding-bottom: 0; margin-bottom: 12px; }
.kc-key-field label {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  margin-bottom: 4px;
}
.kc-key-source {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; font-weight: 500;
  padding: 3px 9px; border-radius: 10px;
  font-family: 'JetBrains Mono', monospace;
}
.kc-key-source i { font-size: 11px; }
.kc-key-workspace {
  color: #166534; background: #DCFCE7; border: 1px solid #86EFAC;
}
.kc-key-workspace i { color: #16A34A; }
.kc-key-env {
  color: #1E40AF; background: #EFF6FF; border: 1px solid #BFDBFE;
}
.kc-key-env i { color: #2563EB; }
.kc-key-none {
  color: #92400E; background: #FEF3C7; border: 1px solid #FDE68A;
}
.kc-key-none i { color: #B45309; }

/* Akcje + zapisz */
.kc-actions {
  display: flex; align-items: center; gap: 8px;
  margin-top: 14px;
}
.btn-save {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 9px 18px; border-radius: 8px;
  background: #D4212C; color: #fff;
  border: 1px solid #D4212C;
  font-family: inherit; font-size: 13px; font-weight: 500;
  cursor: pointer;
  transition: background 0.12s;
}
.btn-save:hover:not(:disabled) { background: #8F1018; border-color: #8F1018; }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

/* Flash banner */
.konto-flash {
  position: fixed; top: 64px; left: 50%; transform: translateX(-50%);
  z-index: 200; min-width: 320px; max-width: 600px;
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; border-radius: 8px;
  font-size: 13.5px; font-weight: 500;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  animation: kontoFlashIn 0.2s ease-out;
}
.konto-flash i { font-size: 18px; flex-shrink: 0; }
.konto-flash.flash-success { background: #DCFCE7; color: #166534; border: 1px solid #86EFAC; }
.konto-flash.flash-error { background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5; }
.konto-flash.flash-info { background: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE; }
.konto-flash .flash-close {
  background: none; border: none; cursor: pointer; color: inherit;
  opacity: 0.7; padding: 4px; display: flex; font-size: 16px;
}
.konto-flash .flash-close:hover { opacity: 1; }
@keyframes kontoFlashIn {
  from { transform: translate(-50%, -6px); opacity: 0; }
  to { transform: translate(-50%, 0); opacity: 1; }
}
`;
