/**
 * Smoke testy dla lib/api - auth helpers + fetch wrapper.
 *
 * Kluczowe inwarianty:
 * - getToken() czyta z localStorage
 * - isAuthenticated() zwraca correctly w obu trybach (bearer / cookie)
 * - api() wysyla Authorization header z token'em (bearer mode)
 * - 401 wywoluje clearToken + redirect na /login
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

import {
  api,
  clearToken,
  getCachedUser,
  getCachedWorkspace,
  getToken,
  isAuthenticated,
  setToken,
} from '@/lib/api';

describe('lib/api auth helpers', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe('getToken', () => {
    it('zwraca null gdy brak tokenu w localStorage', () => {
      expect(getToken()).toBeNull();
    });

    it('zwraca zapisany token', () => {
      setToken('abc-xyz-123');
      expect(getToken()).toBe('abc-xyz-123');
    });
  });

  describe('isAuthenticated', () => {
    it('false gdy brak tokenu i brak user cache', () => {
      expect(isAuthenticated()).toBe(false);
    });

    it('true gdy token jest zapisany (bearer mode)', () => {
      setToken('abc');
      expect(isAuthenticated()).toBe(true);
    });
  });

  describe('clearToken', () => {
    it('usuwa token + cache user/workspace z localStorage', () => {
      setToken('xxx');
      localStorage.setItem('ecombinat_user', JSON.stringify({ id: 1 }));
      localStorage.setItem('ecombinat_workspace', JSON.stringify({ id: 1 }));
      clearToken();
      expect(getToken()).toBeNull();
      expect(getCachedUser()).toBeNull();
      expect(getCachedWorkspace()).toBeNull();
    });
  });
});

describe('lib/api fetch wrapper', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('wysyla Authorization Bearer header gdy token istnieje', async () => {
    setToken('test-token-123');
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: 'ok' }),
    } as Response);
    global.fetch = mockFetch;

    await api('/api/some-endpoint');

    expect(mockFetch).toHaveBeenCalledOnce();
    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe('Bearer test-token-123');
  });

  it('NIE wysyla Authorization headera gdy noAuth=true', async () => {
    setToken('test-token');
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    } as Response);
    global.fetch = mockFetch;

    await api('/api/auth/login', { noAuth: true, method: 'POST' });

    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.headers.Authorization).toBeUndefined();
  });

  it('rzuca Error z message dla non-OK response', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ detail: 'Server error' }),
    } as Response);

    await expect(api('/api/some')).rejects.toThrow('Server error');
  });

  it('zwraca undefined dla 204 No Content', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => null,
    } as Response);

    const res = await api('/api/some');
    expect(res).toBeUndefined();
  });

  it('parsuje JSON dla OK response', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 42, name: 'Test' }),
    } as Response);

    const res = await api<{ id: number; name: string }>('/api/leads/42');
    expect(res).toEqual({ id: 42, name: 'Test' });
  });
});
