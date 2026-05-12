/* Ecombinat API client - direct fetches do backendu przez NEXT_PUBLIC_BACKEND_URL.
 *
 * Wszystkie auth tokeny są w localStorage. Każdy fetch dodaje Authorization
 * Bearer header. To eliminuje całą skomplikowaną kwestię cross-origin cookies.
 *
 * UWAGA: NEXT_PUBLIC_* zmienne są wbudowywane do bundle przy build-time.
 * Po zmianie wartości w Railway -> rebuild frontendu wymagany.
 */

const BACKEND = (process.env.NEXT_PUBLIC_BACKEND_URL || '').replace(/\/$/, '');

const TOKEN_KEY = 'ecombinat_token';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
}

interface ApiOptions extends RequestInit {
  noAuth?: boolean;
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { noAuth, headers, ...rest } = opts;
  const token = noAuth ? null : getToken();

  const url = `${BACKEND}${path.startsWith('/') ? path : '/' + path}`;

  const res = await fetch(url, {
    ...rest,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    credentials: 'include',  // wysyła też cookie jako fallback
  });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== 'undefined') window.location.href = '/login';
    throw new Error('Brak autoryzacji');
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {}
    throw new Error(detail || `HTTP ${res.status}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function login(password: string): Promise<{ token: string; authed: boolean }> {
  const data = await api<{ token: string; authed: boolean }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ password }),
    noAuth: true,
  });
  setToken(data.token);
  return data;
}

export async function logout(): Promise<void> {
  try {
    await api('/api/auth/logout', { method: 'POST' });
  } finally {
    clearToken();
  }
}
