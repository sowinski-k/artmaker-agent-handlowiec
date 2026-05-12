/* Ecombinat API client - same-origin fetches.
 *
 * Wszystkie /api/* przechodza przez Next.js catch-all proxy
 * (app/api/[...path]/route.ts), ktory server-side robi forward do
 * backendu uzywajac process.env.BACKEND_URL (runtime).
 *
 * Korzysci:
 *  - zero CORS (same domena dla frontu i /api)
 *  - cookies dzialaja natywnie (same-origin)
 *  - zmiana BACKEND_URL w Railway = dziala po RESTART frontu
 *
 * Auth token w localStorage jako fallback - przekazywany przez
 * Authorization: Bearer header. Cookies tez sa wysylane (zero overhead).
 */

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

  // Same-origin URL - Next.js api proxy obsluguje
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
    if (typeof window !== 'undefined') window.location.href = '/login';
    throw new Error('Brak autoryzacji');
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {
      // body nie jest JSON-em (np. HTML 404 z proxy) - zostaw raw
    }
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
