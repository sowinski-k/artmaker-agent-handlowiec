/* Ecombinat API client - same-origin fetches przez Next.js proxy.
 *
 * Multi-tenant auth: rejestracja + login (email + hasło), token Bearer
 * w localStorage. Każdy request leci z Authorization header, backend
 * sprawdza token i filter'uje wszystko by workspace_id.
 */

const TOKEN_KEY = 'ecombinat_token';
const USER_KEY = 'ecombinat_user';
const WORKSPACE_KEY = 'ecombinat_workspace';

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
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  localStorage.setItem(WORKSPACE_KEY, JSON.stringify(workspace));
}

interface ApiOptions extends RequestInit {
  noAuth?: boolean;
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { noAuth, headers, ...rest } = opts;
  const token = noAuth ? null : getToken();
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
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {}
    throw new Error(detail || `HTTP ${res.status}`);
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
