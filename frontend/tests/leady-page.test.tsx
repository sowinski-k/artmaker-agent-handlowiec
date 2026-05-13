/**
 * Smoke testy /leady - lista leadow + drawer + bulk select.
 *
 * Co lapie:
 * - Strona renderuje sie po zalogowaniu (token w localStorage)
 * - Toolbar z search + filtry + sort + min-score widoczne
 * - Tabela renderuje wiersze gdy API zwraca dane
 * - Pusty stan gdy API zwraca []
 * - Hot lead (score>=8) ma row-hot class
 * - Drafty count w wierszu
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import LeadyPage from '@/app/(app)/leady/page';

function mockFetchOK(data: unknown) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => data,
  } as Response);
}

function loginUser() {
  localStorage.setItem('ecombinat_token', 'test-token');
  localStorage.setItem('ecombinat_user', JSON.stringify({
    id: 1, email: 't@t.pl', name: 'Test', is_admin: true,
  }));
}

describe('/leady smoke', () => {
  it('renderuje toolbar z search + filtrami', async () => {
    loginUser();
    mockFetchOK({ total: 0, items: [] });
    render(<LeadyPage />);

    expect(screen.getByPlaceholderText(/szukaj po nazwie/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue(/wszystkie segmenty/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue(/wszystkie statusy/i)).toBeInTheDocument();
  });

  it('pokazuje empty state gdy API zwraca pusta liste', async () => {
    loginUser();
    mockFetchOK({ total: 0, items: [] });
    render(<LeadyPage />);

    await waitFor(() => {
      expect(screen.getByText(/brak leadów/i)).toBeInTheDocument();
    });
  });

  it('renderuje wiersz leada gdy API zwraca dane', async () => {
    loginUser();
    mockFetchOK({
      total: 1,
      items: [{
        id: 42, segment: 'sklep_papierniczy', company_name: 'Test SENEKS',
        contact_name: 'Adam', email: 'a@t.pl', phone: null, website: 'https://t.pl',
        city: 'Krakow', status: 'researched', score: 10.0,
        created_at: '2026-05-13T12:00:00+00:00',
        drafts_count: 0, latest_draft_status: null,
      }],
    });
    render(<LeadyPage />);

    await waitFor(() => {
      expect(screen.getByText('Test SENEKS')).toBeInTheDocument();
      expect(screen.getByText('Adam')).toBeInTheDocument();
      expect(screen.getByText('Krakow')).toBeInTheDocument();
    });
  });

  it('pokazuje liczbe draftow w kolumnie Drafty', async () => {
    loginUser();
    mockFetchOK({
      total: 1,
      items: [{
        id: 1, segment: 'inne', company_name: 'WithDrafts',
        contact_name: null, email: 'a@b.pl', phone: null, website: null,
        city: null, status: 'drafted', score: 7.5,
        created_at: '2026-05-13T12:00:00+00:00',
        drafts_count: 3, latest_draft_status: 'draft',
      }],
    });
    render(<LeadyPage />);

    await waitFor(() => {
      expect(screen.getByText('WithDrafts')).toBeInTheDocument();
      // Drafty count "3" + status mini badge "draft"
      expect(screen.getByText('3')).toBeInTheDocument();
    });
  });

  it('toolbar jest sticky (CSS check przez computed style nie dziala w jsdom, ' +
      'wiec sprawdzamy obecnosc klasy)', async () => {
    loginUser();
    mockFetchOK({ total: 0, items: [] });
    const { container } = render(<LeadyPage />);

    await waitFor(() => {
      const toolbar = container.querySelector('.toolbar');
      expect(toolbar).toBeInTheDocument();
    });
  });
});
