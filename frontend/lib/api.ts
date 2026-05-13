/* Ecombinat API client - same-origin fetches przez Next.js proxy.
 *
 * Multi-tenant auth: rejestracja + login (email + hasło). Dwa tryby:
 *
 *   1) Bearer (default) - token w localStorage + Authorization header.
 *      Dziala cross-origin (np. Railway frontend.up.railway.app + backend.up).
 *      Wada: localStorage jest XSS-vulnerable.
 *
 *   2) Cookie-only - backend ustawia httpOnly cookie przy login (juz robi).
 *      Frontend NIE czyta tokena, NIE wysyla Authorization, polega na cookie.
 *      Browser sam dolaczy cookie do kazdego requestu (credentials: 'include').
 *      Wymaga: subdomenowy setup (COOKIE_DOMAIN .twojadomena.pl po stronie
 *      backendu) zeby SameSite=Lax dzialal cross-subdomain.
 *
 * Tryb wybierany przez NEXT_PUBLIC_AUTH_MODE: 'bearer' (default) | 'cookie'.
 * Backend zawsze akceptuje OBA - mozemy w bezpiecznie przelaczyc na produkcji
 * po wpieciu subdomenowego DNS, bez wymuszania na useraach re-login.
 */

const TOKEN_KEY = 'ecombinat_token';
const USER_KEY = 'ecombinat_user';
const WORKSPACE_KEY = 'ecombinat_workspace';

// 'bearer' albo 'cookie'. Bezpieczniejszy: 'cookie' (po subdomenowym setupie).
const AUTH_MODE: 'bearer' | 'cookie' =
  (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_AUTH_MODE === 'cookie')
    ? 'cookie'
    : 'bearer';

export interface UserInfo {
  id: number;
  email: string;
  name: string | null;
  is_admin: boolean;
}

export interface WorkspaceInfo {
  id: number;
  name: string;
  slug: string;
  plan: string;
  credits: number;
  used_credits: number;
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Czy user jest (prawdopodobnie) zalogowany?
 *
 * Bearer mode: sprawdza czy token jest w localStorage
 * Cookie mode: localStorage nie ma tokena, ale ma USER_KEY cache jak user
 *   sie zalogowal - to nie jest 100% gwarancja (cookie moglo wygasnac),
 *   ale wystarczy dla auth gate w UI. 401 z API i tak wyrzuci na login.
 */
export function isAuthenticated(): boolean {
  if (typeof window === 'undefined') return false;
  if (AUTH_MODE === 'cookie') {
    return localStorage.getItem(USER_KEY) !== null;
  }
  return localStorage.getItem(TOKEN_KEY) !== null;
}

export function getAuthMode(): 'bearer' | 'cookie' {
  return AUTH_MODE;
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(WORKSPACE_KEY);
}

export function getCachedUser(): UserInfo | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as UserInfo) : null;
}

export function getCachedWorkspace(): WorkspaceInfo | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(WORKSPACE_KEY);
  return raw ? (JSON.parse(raw) as WorkspaceInfo) : null;
}

function _saveSession(token: string, user: UserInfo, workspace: WorkspaceInfo): void {
  if (typeof window === 'undefined') return;
  // W trybie cookie-only nie chcemy DUPLIKOWAC tokena w localStorage (XSS risk).
  // Cookie httpOnly jest jedynym storem. User/workspace cache zostaje zeby UI
  // mogl renderowac bez auth/me round-trip.
  if (AUTH_MODE === 'bearer') {
    localStorage.setItem(TOKEN_KEY, token);
  }
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  localStorage.setItem(WORKSPACE_KEY, JSON.stringify(workspace));
}

interface ApiOptions extends RequestInit {
  noAuth?: boolean;
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { noAuth, headers, ...rest } = opts;
  // W trybie cookie-only NIE wysylamy Bearer headera - polegamy na httpOnly
  // cookie ustawionym przez backend przy login. credentials: 'include' nizej
  // dolacza cookie automatycznie.
  const token = (noAuth || AUTH_MODE === 'cookie') ? null : getToken();
  const url = path.startsWith('/') ? path : '/' + path;

  const res = await fetch(url, {
    ...rest,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    credentials: 'include',
  });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== 'undefined' && !path.startsWith('/api/auth/')) {
      window.location.href = '/login';
    }
    throw new Error('Brak autoryzacji');
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail: unknown = text;
    try {
      const parsed = JSON.parse(text);
      detail = parsed.detail ?? text;
    } catch {}
    // Backend moze zwrocic structured detail (obiekt) np. dla 409 z active_job_id.
    // Rzucamy Error z message = JSON.stringify(detail) jak obiekt, plain string jak string.
    // Cause umozliwia odzyskanie obiektu przez err.cause.
    const msg = typeof detail === 'string'
      ? detail
      : (typeof detail === 'object' && detail && 'msg' in detail
          ? String((detail as { msg: unknown }).msg)
          : JSON.stringify(detail));
    const err = new Error(msg || `HTTP ${res.status}`);
    (err as Error & { detail: unknown; status: number }).detail = detail;
    (err as Error & { detail: unknown; status: number }).status = res.status;
    throw err;
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

interface AuthResponse {
  token: string;
  user: UserInfo;
  workspace: WorkspaceInfo;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const data = await api<AuthResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
    noAuth: true,
  });
  _saveSession(data.token, data.user, data.workspace);
  return data;
}

export async function register(
  email: string, password: string,
  name?: string, workspaceName?: string,
): Promise<AuthResponse> {
  const data = await api<AuthResponse>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({
      email, password,
      name: name || null,
      workspace_name: workspaceName || null,
    }),
    noAuth: true,
  });
  _saveSession(data.token, data.user, data.workspace);
  return data;
}

export async function logout(): Promise<void> {
  try {
    await api('/api/auth/logout', { method: 'POST' });
  } finally {
    clearToken();
  }
}

export async function refreshMe(): Promise<{ user: UserInfo; workspace: WorkspaceInfo }> {
  const data = await api<{ user: UserInfo; workspace: WorkspaceInfo }>('/api/auth/me');
  if (typeof window !== 'undefined') {
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    localStorage.setItem(WORKSPACE_KEY, JSON.stringify(data.workspace));
  }
  return data;
}
